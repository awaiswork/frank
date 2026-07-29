from functools import lru_cache
from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The local-only fallback. Booting with this in production would mean forgeable
# JWTs, so `_check_prod` below refuses to start on it.
DEV_SECRET = "dev-secret-change-me-in-production-please"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://frank:frank@localhost:5433/frank"
    secret_key: str = DEV_SECRET  # >=32 bytes for HS256
    # Comma-separated: production and Vercel preview origins have to coexist.
    frontend_origin: str = "http://localhost:5173"
    anthropic_api_key: str = ""

    # The model-backed features (NL capture, Advisor, daily note) are the only
    # ones that cost API usage, so they are off unless explicitly switched on
    # *and* a key is present. See app/features.py.
    llm_enabled: bool = False

    # Per-IP throttling on the unauthenticated auth routes. Off in the test
    # suite, which registers far more accounts per minute than a human would.
    rate_limit_enabled: bool = True

    # Auth
    jwt_algorithm: str = "HS256"
    # Short on purpose. Refresh sessions are revocable server-side, but an access
    # token is not — it is valid until it expires, whatever the session says. This
    # number is therefore the real worst-case window between "revoke everything"
    # and the attacker actually losing access.
    access_token_expire_minutes: int = 15
    # Refresh session lifetimes. "Remember me" picks between them; it does not
    # touch the cookie's security attributes, only how long the session lives.
    refresh_token_expire_days: int = 30
    refresh_session_short_hours: int = 12
    refresh_cookie_name: str = "frankly_refresh"
    # A refresh token that was rotated this recently is treated as a benign
    # replay rather than theft. Two tabs booting together both present the same
    # cookie; without this window the second one looks like a stolen token and
    # takes the whole family down with it. Real replay arrives much later.
    refresh_rotation_grace_seconds: int = 10

    # One-time token lifetimes.
    password_reset_ttl_minutes: int = 60
    email_verify_ttl_hours: int = 24
    # Client-visible cooldown between verification resends, per user.
    email_resend_cooldown_seconds: int = 60

    # Email. `console` writes the message to the log and sends nothing, which is
    # the default so the app runs — and the tests pass — with no provider, no key
    # and no network.
    email_provider: Literal["console", "resend"] = "console"
    email_api_key: str = ""
    # Until a domain is verified, Resend accepts no other sender.
    email_from: str = "Frankly <onboarding@resend.dev>"
    # The origin user-facing links are built from. `frontend_origin` is a list
    # whose order is incidental (Vercel previews), and a link is not something to
    # build out of a list by luck. Falls back to the first origin when unset.
    public_app_url: str = ""
    # "lax" when the app and API share a registrable domain (frankly.app +
    # api.frankly.app). Cross-site hosts (*.vercel.app → *.onrender.com) need
    # "none", or the browser drops the refresh cookie and every reload signs the
    # user out.
    cookie_samesite: Literal["lax", "none"] = "lax"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, value: str) -> str:
        """Pin managed-Postgres URLs to psycopg3.

        Neon/Railway/Heroku hand out a bare ``postgresql://`` (or ``postgres://``)
        URL. SQLAlchemy maps those to psycopg2, which this project doesn't
        install — it uses ``psycopg[binary]`` v3 — so the app would die at import.
        """
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origin.split(",") if origin.strip()]

    @property
    def app_base_url(self) -> str:
        """Origin for links we email people. Never user-controlled.

        Reset and verification links are the one place this app builds a URL that
        someone will click from outside it, so the host comes from configuration
        only — never from a request header, a form field or a redirect parameter.
        That is what keeps this off the open-redirect list.
        """
        origins = self.cors_origins
        if not origins:  # pragma: no cover — `_check_prod` refuses to boot first
            raise ValueError("FRONTEND_ORIGIN is empty; there is no origin to build links from")
        return (self.public_app_url or origins[0]).rstrip("/")

    @model_validator(mode="after")
    def _check_prod(self) -> Self:
        """Fail fast rather than deploy something quietly insecure."""
        if self.is_prod and self.secret_key == DEV_SECRET:
            raise ValueError("SECRET_KEY must be set to a real value when ENV=prod")
        if self.cookie_samesite == "none" and not self.is_prod:
            raise ValueError(
                "COOKIE_SAMESITE=none requires ENV=prod — SameSite=None is only "
                "valid on a Secure cookie, and Secure is driven by ENV."
            )
        # An empty origin list breaks CORS *and* every emailed link, but only at
        # the moment someone asks for one — long after the deploy looked healthy.
        # Refuse at boot instead.
        if not self.cors_origins:
            raise ValueError("FRONTEND_ORIGIN must contain at least one origin")
        if self.email_provider != "console" and not self.email_api_key:
            raise ValueError(
                f"EMAIL_PROVIDER={self.email_provider} needs EMAIL_API_KEY. "
                "Leave EMAIL_PROVIDER unset to log emails instead of sending them."
            )
        # A link built from an origin the browser will refuse is worse than no
        # link: the email looks fine and the click fails. Catch it at boot.
        if self.public_app_url and self.public_app_url.rstrip("/") not in self.cors_origins:
            raise ValueError(
                "PUBLIC_APP_URL must be one of the origins in FRONTEND_ORIGIN "
                "(exact match, scheme included, no trailing slash)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
