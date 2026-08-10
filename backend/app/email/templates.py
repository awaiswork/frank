"""The emails this app sends.

Two carry a six-digit code; the third is the weekly digest.

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
# The lead line carries the week's one number, so it gets the weight the supporting
# lines don't — the same order of reading the app uses everywhere else.
_LEAD = (
    f"margin:0 0 12px;font-size:17px;line-height:1.45;font-weight:600;"
    f"color:{_INK};letter-spacing:-0.01em;"
)
# Solid ink on paper, because docs/design/design-system.md says there is no
# brand-color button and the primary one is exactly this. Padding puts it at ~46px
# tall, inside the 44–50 the same doc asks for. `display:inline-block` is what makes
# the padding apply at all in the clients that strip nothing else.
_BUTTON = (
    f"display:inline-block;padding:14px 22px;background:{_INK};color:{_PAPER};"
    f"text-decoration:none;border-radius:12px;font-size:15px;font-weight:600;"
    f"letter-spacing:-0.01em;"
)
_RULE = f"border:none;border-top:1px solid {_LINE};margin:24px 0 0;"
_FOOT = f"margin:16px 0 0;font-size:13px;line-height:1.6;color:{_MUTED};"
_SIGN = f"margin:16px 0 0;font-size:13px;font-weight:700;color:{_MUTED};"


def _layout(heading: str, body_html: str, code: str | None, footer: str) -> str:
    # `code` is optional: the digest has no code to lead with, and an empty box would
    # read as a message that failed to render rather than one that never had one.
    code_html = f'<div style="{_CODE}">{escape(code)}</div>' if code else ""
    return f"""\
<div style="{_WRAP}">
  <div style="{_CARD}">
    <div style="{_MARK}">frankly</div>
    <h1 style="{_H1}">{escape(heading)}</h1>
    <div style="{_BODY}">{body_html}</div>
    {code_html}
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


def _money(cents: int) -> str:
    """Comma decimal, trailing euro — the same shape the app writes on screen."""
    sign = "\u2212" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole:,}".replace(",", "\u202f") + f",{part:02d}\u00a0\u20ac"


def weekly_digest_email(
    *,
    spent_cents: int,
    previous_spent_cents: int,
    top_categories: list[tuple[str, int]],
    upcoming_cents: int,
    upcoming_count: int,
    safe_to_spend_cents: int | None,
    streak: int,
    app_url: str,
    unsubscribe_url: str,
) -> EmailMessage:
    """A week in one screenful.

    Every number here is one a screen already shows. Nothing is computed for the email
    alone, because an email is the one surface nobody is looking at while it is written
    — the easiest place in the app to assert something that turns out not to be true.

    `safe_to_spend_cents` is None when there is no income on file, and the line is then
    absent rather than zero. Same rule as the daily note: no income, no verdict.

    `app_url` is where the button goes, and it comes from configuration rather than
    from anything a request said — see `Settings.app_base_url`. A summary is only worth
    reading if you can act on it, and the app root is the honest destination: there is
    no weekly screen to deep-link to, and Home is the glance this is a copy of.
    """
    delta = spent_cents - previous_spent_cents
    if previous_spent_cents == 0 and spent_cents == 0:
        headline = "A quiet week — nothing logged either week."
    elif delta == 0:
        headline = f"You spent {_money(spent_cents)}, the same as the week before."
    else:
        direction = "more" if delta > 0 else "less"
        headline = (
            f"You spent {_money(spent_cents)} last week — "
            f"{_money(abs(delta))} {direction} than the week before."
        )

    lines = [headline]
    if top_categories:
        joined = ", ".join(f"{name} {_money(cents)}" for name, cents in top_categories)
        lines.append(f"Most of it: {joined}.")
    if upcoming_count:
        thing = "thing" if upcoming_count == 1 else "things"
        lines.append(f"{_money(upcoming_cents)} of repeating {thing} lands in the next seven days.")
    if safe_to_spend_cents is not None:
        lines.append(f"That leaves {_money(safe_to_spend_cents)} safe to spend this month.")
    if streak >= 2:
        lines.append(f"You've checked in {streak} days running.")

    footer = (
        "You're getting this because weekly summaries are on. "
        "Turn them off any time — nothing else about your account changes."
    )
    # The URL goes in the plain part too. A button is invisible to a text-first client
    # and to a screen reader, and "open the app" with no way to open it is not a link.
    text = "\n\n".join(
        ["Your week"]
        + lines
        + [
            f"Open Frankly: {app_url}",
            f"Turn these off: {unsubscribe_url}",
            "— frankly",
        ]
    )
    head, *rest = lines
    body_html = (
        f'<p style="{_LEAD}">{escape(head)}</p>'
        + "".join(f'<p style="margin:0 0 12px">{escape(line)}</p>' for line in rest)
        + f'<p style="margin:24px 0 0"><a href="{escape(app_url)}" '
        f'style="{_BUTTON}">Open Frankly</a></p>'
        + f'<p style="margin:16px 0 0"><a href="{escape(unsubscribe_url)}" '
        f'style="color:{_MUTED}">Turn these off</a></p>'
    )
    html = _layout(heading="Your week", body_html=body_html, code=None, footer=footer)
    return EmailMessage(to="", subject="Your week with Frankly", text=text, html=html)
