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
    access_token_expire_minutes: int = 60 * 24  # 24h
    refresh_token_expire_days: int = 30
    refresh_cookie_name: str = "frankly_refresh"
    # "lax" when the app and API share a registrable domain (frankly.app +
    # api.frankly.app). Cross-site hosts (*.vercel.app → *.up.railway.app) need
    # "none", or the browser drops the refresh cookie and every reload signs the
    # user out.
    cookie_samesite: Literal["lax", "none"] = "lax"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, value: str) -> str:
        """Pin managed-Postgres URLs to psycopg3.

        Railway/Neon/Heroku hand out a bare ``postgresql://`` (or ``postgres://``)
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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
