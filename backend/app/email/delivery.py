"""Handing an email to the provider without making anyone wait for it.

There is no worker, no queue and no Redis on this stack, and there isn't going to
be — so delivery is a FastAPI background task. It runs after the response is
already on the wire, which is what guarantees that a slow provider can never turn
"reset my password" into a thirty-second hang. A send that fails is logged and
dropped; the caller has already been told, truthfully, that if the address exists
an email is on its way.

Known limitation, documented rather than hidden: Render's free instance is culled
after fifteen idle minutes. A background task still in flight when that happens
dies with it, and nothing retries. The resend button is the recovery path.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import BackgroundTasks

from app.email.sender import EmailMessage, get_sender

log = logging.getLogger("frankly")


def _deliver(message: EmailMessage, user_id: uuid.UUID, purpose: str) -> None:
    """Runs off the request path. Must never raise — nothing is listening."""
    try:
        get_sender().send(message)
        log.info('{"event":"email_sent","user_id":"%s","purpose":"%s"}', user_id, purpose)
    except Exception as exc:  # noqa: BLE001 — a failed email must not crash a worker
        # Type only. The address, subject, body and link are all off limits, and
        # provider errors have a habit of quoting the payload back at you.
        log.warning(
            '{"event":"email_send_failed","user_id":"%s","purpose":"%s","error":"%s"}',
            user_id,
            purpose,
            type(exc).__name__,
        )


def queue_email(
    background: BackgroundTasks,
    message: EmailMessage,
    *,
    to: str,
    user_id: uuid.UUID,
    purpose: str,
) -> None:
    """Schedule `message` for delivery after the response is sent."""
    background.add_task(
        _deliver,
        EmailMessage(to=to, subject=message.subject, text=message.text, html=message.html),
        user_id,
        purpose,
    )
