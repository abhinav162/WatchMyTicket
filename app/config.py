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
    # curl_cffi browser impersonation profile ("chrome", "chrome124", "safari", ...)
    bms_impersonate: str = "chrome"
    # A movie's format/language variants (ScreenX, Dolby, 4DX, IMAX, dubs, ...)
    # are each a separately-queryable event; cap how many a single watch check
    # will fetch per tick (anchor event included) to bound worst-case latency.
    bms_max_events_per_watch: int = 20
    # Optional proxy for BookMyShow requests, e.g. "http://user:pass@host:port".
    # Datacenter IPs (cloud VMs) get 403'd by BMS's bot-protection far more
    # than residential/ISP IPs; empty means no proxy (direct connection).
    bms_proxy_url: str = ""
    # Pause between each sibling format/language event fetch within one
    # scrape — firing ~15 requests back-to-back in under 2 seconds looks
    # automated regardless of IP reputation. 0 disables pacing.
    bms_request_delay_seconds: float = 0.5

    log_level: str = "INFO"


settings = Settings()
