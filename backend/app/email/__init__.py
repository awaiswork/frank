"""Transactional email: one interface, two providers, no worker."""

from app.email.delivery import queue_email
from app.email.sender import ConsoleSender, EmailMessage, EmailSender, ResendSender, get_sender
from app.email.templates import password_reset_email, verification_email

__all__ = [
    "ConsoleSender",
    "EmailMessage",
    "EmailSender",
    "ResendSender",
    "get_sender",
    "password_reset_email",
    "queue_email",
    "verification_email",
]
