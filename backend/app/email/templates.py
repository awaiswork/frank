"""The two emails this app sends, both carrying a six-digit code.

Codes rather than links, deliberately. A link has to survive a mail client
rewriting it, works only on the device that opened the inbox, and quietly
becomes a second way to spend the same secret. A code is read once and typed
into whatever tab is already open.

Voice follows the product's own copy — first person, short sentences, plain
verbs, sentence case, no exclamation marks, no emoji, signed "— frankly". It
should read like the app talking, not like a bank.

Every message: leads with the code, states how long it lasts, and says plainly
what to do if you didn't ask for it. The plain-text alternative is not a
formality — some clients render it, and anyone on a text-first client or a
screen reader gets it instead of the HTML.

The HTML does very little: inline styles, system fonts, no external stylesheet,
no web font, no image, no tracking pixel. One centred column with a max-width
rather than nested tables; that renders correctly everywhere except the old
Word-engine Outlook, where it degrades to full-width text, which is fine.
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
_INSET = "#f4f1e8"

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "'SFMono-Regular',Menlo,Consolas,'Liberation Mono',monospace"

# Built once so the template stays readable at a sane line length. Every rule is
# inline because an email client will not fetch a stylesheet.
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
# Wide letter-spacing so the digits are read one at a time rather than as a
# number, which is how people transcribe them without mistakes.
_CODE = (
    f"display:inline-block;margin:22px 0 6px;padding:14px 22px;background:{_INSET};"
    f"border:1px solid {_LINE};border-radius:12px;font-family:{_MONO};"
    f"font-size:30px;font-weight:700;letter-spacing:0.28em;color:{_INK};"
)
_RULE = f"border:none;border-top:1px solid {_LINE};margin:24px 0 0;"
_FOOT = f"margin:16px 0 0;font-size:13px;line-height:1.6;color:{_MUTED};"
_SIGN = f"margin:16px 0 0;font-size:13px;font-weight:700;color:{_MUTED};"


def _layout(heading: str, body_html: str, code: str, footer: str) -> str:
    return f"""\
<div style="{_WRAP}">
  <div style="{_CARD}">
    <div style="{_MARK}">frankly</div>
    <h1 style="{_H1}">{escape(heading)}</h1>
    <div style="{_BODY}">{body_html}</div>
    <div style="{_CODE}">{escape(code)}</div>
    <hr style="{_RULE}">
    <p style="{_FOOT}">{escape(footer)}</p>
    <p style="{_SIGN}">— frankly</p>
  </div>
</div>"""


def _window(minutes: int) -> str:
    return "10 minutes" if minutes == 10 else f"{minutes} minutes"


def verification_code_email(code: str, ttl_minutes: int) -> EmailMessage:
    window = _window(ttl_minutes)
    footer = (
        "If you didn't sign up for Frankly, you can ignore this. "
        "The code expires on its own and nothing is created until it's used."
    )
    text = f"""\
Confirm your email

Here's the code to finish setting up. It works for the next {window}.

{code}

{footer}

— frankly
"""
    html = _layout(
        heading="Confirm your email",
        body_html=(
            f"Here's the code to finish setting up. It works for the next {escape(window)}."
        ),
        code=code,
        footer=footer,
    )
    return EmailMessage(to="", subject=f"{code} is your Frankly code", text=text, html=html)


def password_reset_code_email(code: str, ttl_minutes: int) -> EmailMessage:
    window = _window(ttl_minutes)
    footer = (
        "If you didn't ask to reset your password, you can ignore this — "
        "your current one still works, and this code is useless without your inbox."
    )
    text = f"""\
Reset your password

Enter this code to set a new password. It works for the next {window}, and only
once. Changing your password signs you out everywhere else, which is what you
want if someone else has been in here.

{code}

{footer}

— frankly
"""
    html = _layout(
        heading="Reset your password",
        body_html=(
            "Enter this code to set a new password. It works for the next "
            f"{escape(window)}, and only once.<br><br>Changing your password signs "
            "you out everywhere else, which is what you want if someone else has "
            "been in here."
        ),
        code=code,
        footer=footer,
    )
    return EmailMessage(to="", subject=f"{code} is your Frankly reset code", text=text, html=html)
