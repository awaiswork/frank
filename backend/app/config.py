from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://frank:frank@localhost:5432/frank"
    secret_key: str = "dev-secret-change-me"
    frontend_origin: str = "http://localhost:5173"
    anthropic_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
