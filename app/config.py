"""Application configuration loaded from environment variables / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    telegram_bot_token: str = ""

    # Database. Defaults to a local SQLite file; set a postgres URL in production,
    # e.g. postgresql+asyncpg://user:pass@host:5432/ticket_watcher
    database_url: str = "sqlite+aiosqlite:///./storage/ticket_watcher.db"

    # Monitoring
    check_interval_seconds: int = 60

    # Which scraper implementation to use: "bookmyshow" or "mock"
    scraper: str = "bookmyshow"

    # HTTP scraping
    http_timeout_seconds: float = 15.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    log_level: str = "INFO"


settings = Settings()
