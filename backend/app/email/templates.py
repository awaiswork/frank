"""The two emails this app sends.

Voice follows the product's own copy — first person, short sentences, plain
verbs, sentence case, no exclamation marks, no emoji, signed "— frankly". It
should read like the app talking, not like a bank.

Every message: says plainly what to do if you didn't ask for it, states how long
the link is good for, and carries the same words in both parts. The plain-text
alternative is not a formality — some clients render it, and anyone reading with
a screen reader on a text-first client gets it instead of the HTML.

The HTML deliberately does very little: inline styles, system fonts, no external
stylesheet, no web font, no image, no tracking pixel. Layout is one centred
column with a max-width rather than nested tables; that renders correctly
everywhere except the old Word-engine Outlook, where it degrades to full-width
text, which is fine.
"""

from __future__ import annotations

from html import escape

from app.email.sender import EmailMessage

# Light-theme tokens from docs/design/design-system.md. Mail clients are a
# light-background world, and a dark palette here would read as broken.
_PAPER = "#f1ede3"
_SURFACE = "#ffffff"
_INK = "#1b1a15"
_INK_2 = "#46443b"
_MUTED = "#736f65"
_LINE = "#e6e1d4"
_ACCENT = "#1f7a4d"

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

# Built once so the template below stays readable at a sane line length. Every
# rule is inline because an email client will not fetch a stylesheet.
_WRAP = f"margin:0;padding:24px 12px;background:{_PAPER};font-family:{_FONT};"
_CARD = (
    f"max-width:520px;margin:0 auto;background:{_SURFACE};"
    f"border:1px solid {_LINE};border-radius:16px;padding:32px 28px;"
)
_MARK = f"font-size:20px;font-weight:700;color:{_INK};letter-spacing:-0.01em;"
_H1 = (
    f"margin:22px 0 0;font-size:22px;line-height:1.25;font-weight:600;"
    f"color:{_INK};letter-spacing:-0.02em;"
)
_BODY = f"margin-top:14px;font-size:15px;line-height:1.6;color:{_INK_2};"
_BUTTON = (
    f"display:inline-block;background:{_INK};color:{_PAPER};text-decoration:none;"
    f"font-size:15px;font-weight:600;padding:13px 22px;border-radius:11px;"
)
_SMALL = f"margin:18px 0 0;font-size:13px;line-height:1.6;color:{_MUTED};"
_RULE = f"border:none;border-top:1px solid {_LINE};margin:24px 0 0;"
_FOOT = f"margin:16px 0 0;font-size:13px;line-height:1.6;color:{_MUTED};"
_SIGN = f"margin:16px 0 0;font-size:13px;font-weight:700;color:{_MUTED};"
_LINKC = f"color:{_ACCENT};word-break:break-all;"


def _layout(heading: str, body_html: str, button_label: str, url: str, footer: str) -> str:
    """One centred column. Everything inline, nothing fetched."""
    safe_url = escape(url, quote=True)
    return f"""\
<div style="{_WRAP}">
  <div style="{_CARD}">
    <div style="{_MARK}">frankly</div>
    <h1 style="{_H1}">{escape(heading)}</h1>
    <div style="{_BODY}">{body_html}</div>
    <div style="margin:26px 0 6px;">
      <a href="{safe_url}" style="{_BUTTON}">{escape(button_label)}</a>
    </div>
    <p style="{_SMALL}">
      If the button doesn't work, paste this into your browser:<br>
      <a href="{safe_url}" style="{_LINKC}">{escape(url)}</a>
    </p>
    <hr style="{_RULE}">
    <p style="{_FOOT}">{escape(footer)}</p>
    <p style="{_SIGN}">— frankly</p>
  </div>
</div>"""


def verification_email(url: str, ttl_hours: int) -> EmailMessage:
    window = "24 hours" if ttl_hours == 24 else f"{ttl_hours} hours"
    heading = "Confirm your email"
    footer = (
        "If you didn't sign up for Frankly, you can ignore this. "
        "Nothing happens until the link is used."
    )
    text = f"""\
Confirm your email

You're nearly set up. Use the link below and I'll know this address is yours.

{url}

This link works for the next {window}.

{footer}

— frankly
"""
    html = _layout(
        heading=heading,
        body_html=(
            "You're nearly set up. Use the button below and I'll know this "
            f"address is yours.<br><br>This link works for the next {escape(window)}."
        ),
        button_label="Confirm my email",
        url=url,
        footer=footer,
    )
    return EmailMessage(to="", subject="Confirm your email", text=text, html=html)


def password_reset_email(url: str, ttl_minutes: int) -> EmailMessage:
    window = "hour" if ttl_minutes == 60 else f"{ttl_minutes} minutes"
    window_phrase = "the next hour" if ttl_minutes == 60 else f"the next {window}"
    heading = "Set a new password"
    footer = (
        "If you didn't ask to reset your password, you can ignore this — "
        "your current one still works, and nobody can use this link without your inbox."
    )
    text = f"""\
Set a new password

Use the link below to choose a new one. Signing in again afterwards will sign you
out everywhere else, which is what you want if someone else has been in here.

{url}

This link works for {window_phrase}, and only once.

{footer}

— frankly
"""
    html = _layout(
        heading=heading,
        body_html=(
            "Use the button below to choose a new one. Signing in again afterwards "
            "will sign you out everywhere else, which is what you want if someone "
            "else has been in here.<br><br>"
            f"This link works for {escape(window_phrase)}, and only once."
        ),
        button_label="Set a new password",
        url=url,
        footer=footer,
    )
    return EmailMessage(to="", subject="Set a new password", text=text, html=html)
