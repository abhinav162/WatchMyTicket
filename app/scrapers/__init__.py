"""Scraper factory — keeps the monitor provider-agnostic."""

from app.config import settings
from app.scrapers.base import BaseScraper


def get_scraper(name: str | None = None) -> BaseScraper:
    name = (name or settings.scraper).lower()
    if name == "mock":
        from app.scrapers.mock import MockScraper

        return MockScraper()
    if name == "bookmyshow":
        from app.scrapers.bookmyshow import BookMyShowScraper

        return BookMyShowScraper()
    raise ValueError(f"Unknown scraper: {name}")
