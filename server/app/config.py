from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="development", alias="LABWATCH_ENV")
    secret_key: str = Field(default="dev-only-change-me-use-32-bytes-min", alias="LABWATCH_SECRET_KEY")
    api_host: str = Field(default="0.0.0.0", alias="LABWATCH_API_HOST")
    api_port: int = Field(default=8000, alias="LABWATCH_API_PORT")
    public_url: str = Field(default="http://localhost", alias="LABWATCH_PUBLIC_URL")

    database_url: str = Field(
        default="sqlite+aiosqlite:///./labwatch.db",
        alias="DATABASE_URL",
    )

    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="admin", alias="ADMIN_PASSWORD")
    admin_email: str = Field(default="admin@localhost", alias="ADMIN_EMAIL")

    access_token_minutes: int = 480
    refresh_token_days: int = 7

    heartbeat_interval_seconds: int = Field(default=30, alias="HEARTBEAT_INTERVAL_SECONDS")
    offline_after_seconds: int = Field(default=90, alias="OFFLINE_AFTER_SECONDS")
    unhealthy_after_seconds: int = Field(default=180, alias="UNHEALTHY_AFTER_SECONDS")
    require_agent_approval: bool = Field(default=False, alias="REQUIRE_AGENT_APPROVAL")

    metrics_raw_retention_days: int = Field(default=30, alias="METRICS_RAW_RETENTION_DAYS")
    metrics_hourly_retention_days: int = Field(default=365, alias="METRICS_HOURLY_RETENTION_DAYS")
    audit_log_retention_days: int = Field(default=0, alias="AUDIT_LOG_RETENTION_DAYS")
    agent_log_retention_days: int = Field(default=90, alias="AGENT_LOG_RETENTION_DAYS")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="labwatch@localhost", alias="SMTP_FROM")
    smtp_starttls: bool = Field(default=True, alias="SMTP_STARTTLS")
    smtp_enabled: bool = Field(default=False, alias="SMTP_ENABLED")

    cors_origins: str = Field(default="http://localhost,http://localhost:5173,http://127.0.0.1:5173")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sync_database_url(self) -> str:
        url = self.database_url
        return (
            url.replace("postgresql+asyncpg://", "postgresql://")
            .replace("sqlite+aiosqlite://", "sqlite://")
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
