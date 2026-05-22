from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./paper_archive.db"
    app_secret_key: str = Field(default="dev-secret", min_length=1)
    shared_password: str = Field(default="papers", min_length=1)
    demo_mode: bool = True

    slack_signing_secret: str | None = None
    slack_bot_token: str | None = None
    slack_request_tolerance_seconds: int = 60 * 5

    worker_interval_seconds: int = 60
    backfill_limit_per_channel: int = 200
    arxiv_request_delay_seconds: float = 3.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
