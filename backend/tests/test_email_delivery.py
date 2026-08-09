"""Getting the mail out, and saying why when it doesn't.

Production sent from Resend's shared `onboarding@resend.dev` for a release. That
sender delivers only to the address on our own Resend account and refuses every
other recipient with 403 — so signup worked for the one person testing it and
failed for everybody else. What made it take a release to find was the logging:
the rejection surfaced as `"error":"HTTPStatusError"` and nothing more, because
the provider's own explanation quotes the recipient's address and was therefore
dropped wholesale.

So these tests pin both halves of the lesson. Transient failures must not be the
end of an email (they were: one attempt, a five-second budget, and silence), and
a refusal must reach the log named — carrying enough to diagnose itself, and
never the address.

The `outbox` fixture patches the sender lookup, so nothing here touches the
network; the fake client stands in one level lower, at the HTTP call.
"""

from __future__ import annotations

import logging
import uuid

import httpx
import pytest

from app.email import SendFailed
from app.email.delivery import _deliver
from app.email.sender import EmailMessage, ResendSender

RECIPIENT = "someone@example.com"

MESSAGE = EmailMessage(
    to=RECIPIENT,
    subject="123456 is your Frankly code",
    text="123456",
    html="<p>123456</p>",
)


def response(status: int, body: object | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=body if body is not None else {},
        request=httpx.Request("POST", ResendSender._URL),
    )


class FakeClient:
    """Hands back queued outcomes; an ``Exception`` in the queue is raised."""

    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoff is real in production and pointless in a test."""
    monkeypatch.setattr("app.email.sender.time.sleep", lambda _seconds: None)


def install(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> FakeClient:
    monkeypatch.setattr("app.email.sender._http_client", lambda: client)
    return client


def send() -> None:
    ResendSender(api_key="test-key", sender="Frankly <onboarding@resend.dev>").send(MESSAGE)


class TestRetries:
    def test_a_timeout_is_retried_rather_than_dropped(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: None
    ) -> None:
        """The exact failure that made prod emails vanish: a slow first call on a
        cold instance used to be the whole story."""
        client = install(
            monkeypatch,
            FakeClient(httpx.ReadTimeout("too slow"), response(200, {"id": "abc"})),
        )
        send()
        assert client.calls == 2

    def test_a_connection_error_is_retried(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: None
    ) -> None:
        client = install(
            monkeypatch,
            FakeClient(httpx.ConnectError("no route"), response(200, {"id": "abc"})),
        )
        send()
        assert client.calls == 2

    def test_a_rate_limit_is_retried(self, monkeypatch: pytest.MonkeyPatch, no_sleep: None) -> None:
        """Resend's free tier caps requests per second, and that is a "not now"."""
        client = install(
            monkeypatch,
            FakeClient(response(429, {"name": "rate_limit_exceeded"}), response(200, {"id": "a"})),
        )
        send()
        assert client.calls == 2

    def test_giving_up_raises_the_last_failure(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: None
    ) -> None:
        client = install(
            monkeypatch,
            FakeClient(
                response(503, {"name": "internal_server_error"}),
                response(503, {"name": "internal_server_error"}),
                response(503, {"name": "internal_server_error"}),
            ),
        )
        with pytest.raises(SendFailed) as caught:
            send()
        assert caught.value.status_code == 503
        assert client.calls == 3  # bounded — it does not retry forever

    def test_success_costs_exactly_one_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = install(monkeypatch, FakeClient(response(200, {"id": "abc"})))
        send()
        assert client.calls == 1


class TestPermanentRejections:
    def test_an_unverified_domain_is_not_retried(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: None
    ) -> None:
        """Resend's 403 for "you can only mail your own address" is forever.

        Retrying it burns quota and buys nothing — and this is the rejection that
        silently blocks every recipient but the account owner, so it has to reach
        the log named rather than as a bare exception type.
        """
        client = install(
            monkeypatch,
            FakeClient(
                response(
                    403,
                    {
                        "statusCode": 403,
                        "name": "validation_error",
                        "message": (
                            "You can only send testing emails to your own email "
                            f"address ({RECIPIENT})"
                        ),
                    },
                )
            ),
        )
        with pytest.raises(SendFailed) as caught:
            send()
        assert client.calls == 1
        assert caught.value.status_code == 403
        assert caught.value.error_name == "validation_error"

    def test_a_bad_key_is_not_retried(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: None
    ) -> None:
        client = install(monkeypatch, FakeClient(response(401, {"name": "missing_api_key"})))
        with pytest.raises(SendFailed):
            send()
        assert client.calls == 1

    def test_an_unreadable_error_body_still_names_itself(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: None
    ) -> None:
        broken = httpx.Response(
            status_code=400,
            content=b"<html>gateway</html>",
            request=httpx.Request("POST", ResendSender._URL),
        )
        install(monkeypatch, FakeClient(broken))
        with pytest.raises(SendFailed) as caught:
            send()
        assert caught.value.error_name == "unparseable"


class TestTheFailureNeverLeaksTheAddress:
    def test_send_failed_carries_no_prose(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The provider quotes the recipient back at us; it stops at this boundary."""
        install(
            monkeypatch,
            FakeClient(
                response(
                    403,
                    {"name": "validation_error", "message": f"only your own address ({RECIPIENT})"},
                )
            ),
        )
        with pytest.raises(SendFailed) as caught:
            send()
        assert RECIPIENT not in str(caught.value)

    def test_the_log_line_names_the_status_but_not_the_recipient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_deliver` must swallow the failure *and* leave a usable trace.

        Attaching a handler directly because the `frankly` logger sets
        `propagate=False`, so caplog's root handler never sees these records.
        """
        records: list[logging.LogRecord] = []

        class Collect(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        class Rejecting:
            def send(self, message: EmailMessage) -> None:
                raise SendFailed(403, "validation_error")

        monkeypatch.setattr("app.email.delivery.get_sender", Rejecting)

        log = logging.getLogger("frankly")
        handler = Collect()
        log.addHandler(handler)
        try:
            # Must not raise: nothing is listening on a background task.
            _deliver(MESSAGE, uuid.uuid4(), "email_verify_code")
        finally:
            log.removeHandler(handler)

        assert len(records) == 1
        line = records[0].getMessage()
        assert '"status":403' in line
        assert "validation_error" in line
        assert RECIPIENT not in line
        assert MESSAGE.subject not in line
