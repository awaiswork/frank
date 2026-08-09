"""Transactional email, behind one small interface.

Call sites build an :class:`EmailMessage` and hand it to a sender. They never
learn which provider is configured, or whether one is configured at all — which
is what lets the whole app, and the whole test suite, run with no key and no
network.

Nothing in here logs a recipient address, a subject, or a body. Failures are
logged by event name and user id only.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import get_settings

log = logging.getLogger("frankly")

# Split rather than one number, because the two failures are not alike. Refusing
# to wait more than five seconds for a *connection* is right — an unreachable
# provider should fail fast. Refusing to wait more than five seconds for the
# *response* is not: this runs in a background task where nobody is waiting, and
# a free-tier instance is CPU-throttled for its first seconds after a cold start,
# which is exactly when a whole handshake-plus-round-trip most often overran the
# old flat 5s budget and dropped the mail on the floor.
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 15.0

# Bounded on purpose. Each retry pins a threadpool worker for the backoff, and
# the free instance can be culled mid-flight anyway, so this buys resilience
# against a blip and nothing more. Worst case is ~4s of sleeping.
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.0, 3.0)

# Retried because they say "not now". Everything else 4xx says "not ever" — a
# bad key, an unverified sender, a recipient the account isn't allowed to mail —
# and repeating those just burns quota and hides the real answer.
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


class SendFailed(Exception):
    """A provider rejection, reduced at the boundary to what is safe to log.

    Resend's error bodies quote the payload back — the 403 for an unverified
    domain names the recipient address in its ``message``. So only the status and
    the machine-readable ``name`` survive this far; the prose never does.
    """

    def __init__(self, status_code: int, error_name: str) -> None:
        super().__init__(f"{status_code} {error_name}")
        self.status_code = status_code
        self.error_name = error_name


# One pooled client for the process, built on first use rather than at import.
# `httpx.post` opens a fresh TCP connection and negotiates TLS on every single
# call; on a sleepy free instance that handshake was a large share of the budget
# it then blew. Keep-alive makes the second email of a session dramatically
# cheaper than the first. No settings are read here, so this is not the
# import-time freeze CLAUDE.md warns about — it is the same deliberate exception
# as the engine in app/db.py.
_client_lock = threading.Lock()
_client: httpx.Client | None = None


def _http_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
        return _client


class EmailSender(Protocol):
    """Swap the provider by writing one of these. Call sites don't change."""

    def send(self, message: EmailMessage) -> None: ...


class ConsoleSender:
    """Writes the email to the log and sends nothing.

    The default, and the one you develop against. It is also the only way to see
    a verification link when the provider can't reach your address — with Resend
    and no verified domain, that is every address except your own account's.

    The link is printed in full, which is exactly what we refuse to do in
    production logging. That is the trade for a usable dev loop, and it is why
    this sender is selected by configuration rather than by a debug flag that
    could plausibly survive into prod.
    """

    def send(self, message: EmailMessage) -> None:
        print(
            f"\n{'─' * 72}\n"
            f"  email → {message.to}\n"
            f"  subject: {message.subject}\n"
            f"{'─' * 72}\n"
            f"{message.text}\n"
            f"{'─' * 72}\n",
            flush=True,
        )


class ResendSender:
    """https://resend.com/docs/api-reference/emails/send-email

    Sends only the fields the message needs: recipient, subject, and the two
    bodies. No tags, no metadata, no tracking — partly because none of it is
    useful here, and partly because every field added is more personal data
    sitting in a US datacentre.

    **Region is not set here, because it cannot be.** Resend picks the sending
    region per *domain*, chosen in the dashboard when the domain is added; there
    is no per-request header or field. Until a custom domain is verified, mail
    goes out from the shared `resend.dev` domain in Resend's default region.
    So EU dispatch is something you buy with a domain, not something this code
    can ask for.

    **Sending is restricted until then, too**: with no verified domain, Resend
    accepts only `onboarding@resend.dev` as the sender and only your own Resend
    account address as the recipient. Anything else is rejected outright.
    """

    _URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str, sender: str) -> None:
        self._api_key = api_key
        self._sender = sender

    def send(self, message: EmailMessage) -> None:
        """Deliver, retrying only what is worth retrying.

        A retry can duplicate an email — the request may have succeeded server
        side and lost the response — and that is deliberately harmless here: the
        code is minted once per *send*, not per attempt, so both copies carry the
        same digits and either one works. A missing email is the failure that
        matters; a duplicate is not.
        """
        payload = json.dumps(
            {
                "from": self._sender,
                "to": [message.to],
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
            }
        )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = _http_client().post(self._URL, headers=headers, content=payload)
            except httpx.TransportError as exc:
                # Timeouts, resets, DNS — all transient by nature, all worth
                # another go. TransportError covers TimeoutException too.
                last = exc
            else:
                if response.status_code < 400:
                    return
                failure = SendFailed(response.status_code, _error_name(response))
                if response.status_code not in _RETRYABLE_STATUS:
                    raise failure
                last = failure

            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])

        assert last is not None  # the loop cannot exit without setting it
        raise last


def _error_name(response: httpx.Response) -> str:
    """The provider's machine-readable error label, and nothing else.

    Never returns the ``message`` field. Resend puts the recipient address in it
    ("You can only send testing emails to your own email address"), and an
    address in the log is the one thing this module refuses to write.
    """
    try:
        body = response.json()
    except ValueError:
        return "unparseable"
    if isinstance(body, dict):
        name = body.get("name")
        if isinstance(name, str) and name:
            return name
    return "unknown"


def get_sender() -> EmailSender:
    """Read configuration at call time, never at import.

    A module-level binding would freeze the provider at first import, which is
    the same failure that once made COOKIE_SAMESITE silently inert (see
    CLAUDE.md) and would make every test that swaps the sender a coin toss.
    """
    settings = get_settings()
    # A provider named without a key cannot send. Falling back to the console
    # keeps the app serving and turns the misconfiguration into a log line
    # rather than an exception on every registration.
    if settings.email_provider == "resend" and settings.email_api_key:
        return ResendSender(api_key=settings.email_api_key, sender=settings.email_from)
    return ConsoleSender()
