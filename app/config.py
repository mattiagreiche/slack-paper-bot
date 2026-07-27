from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./paper_archive.db"
    app_secret_key: str = Field(default="dev-secret", min_length=1)
    shared_password: str = Field(default="papers", min_length=1)

    slack_signing_secret: str | None = None
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    slack_oauth_redirect_uri: str | None = None
    slack_oauth_migration_mode: bool = False
    slack_legacy_team_id: str | None = None
    slack_bot_token: str | None = None
    slack_request_tolerance_seconds: int = 60 * 5
    credential_encryption_key: str | None = None

    worker_interval_seconds: int = 60
    backfill_limit_per_channel: int = 200
    arxiv_request_delay_seconds: float = 3.0

    zotero_api_base_url: str = "https://api.zotero.org"
    zotero_sync_limit: int = 20

    related_papers_enabled: bool = False
    related_papers_limit: int = 5
    related_papers_retry_limit: int | None = None
    semantic_scholar_api_key: str | None = None
    semantic_scholar_api_base_url: str = "https://api.semanticscholar.org"
    semantic_scholar_recommendation_pool: str = "recent"


@lru_cache
def get_settings() -> Settings:
    return Settings()
