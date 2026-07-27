from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://frank:frank@localhost:5433/frank"
    secret_key: str = "dev-secret-change-me-in-production-please"  # >=32 bytes for HS256
    frontend_origin: str = "http://localhost:5173"
    anthropic_api_key: str = ""

    # The model-backed features (NL capture, Advisor, daily note) are the only
    # ones that cost API usage, so they are off unless explicitly switched on
    # *and* a key is present. See app/features.py.
    llm_enabled: bool = False

    # Auth
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24h
    refresh_token_expire_days: int = 30
    refresh_cookie_name: str = "frank_refresh"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
