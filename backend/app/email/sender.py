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
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import get_settings

log = logging.getLogger("frankly")

# The provider gets one shot and a short leash. This runs in a background task,
# so a slow provider costs nobody a response — but an unbounded wait would pin a
# threadpool worker for as long as the socket stayed open.
_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


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
        response = httpx.post(
            self._URL,
            timeout=_TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(
                {
                    "from": self._sender,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.text,
                    "html": message.html,
                }
            ),
        )
        response.raise_for_status()


def get_sender() -> EmailSender:
    """Read configuration at call time, never at import.

    A module-level binding would freeze the provider at first import, which is
    the same failure that once made COOKIE_SAMESITE silently inert (see
    CLAUDE.md) and would make every test that swaps the sender a coin toss.
    """
    settings = get_settings()
    if settings.email_provider == "resend":
        return ResendSender(api_key=settings.email_api_key, sender=settings.email_from)
    return ConsoleSender()
