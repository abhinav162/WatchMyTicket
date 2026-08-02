"""Scraper interface. New providers (District, Insider, Paytm, ...) implement this."""

from abc import ABC, abstractmethod

from app.models import Watch
from app.schemas import Show


class BaseScraper(ABC):
    """Turns a Watch into the list of shows currently bookable on a provider."""

    name: str = "base"

    @abstractmethod
    async def scrape(self, watch: Watch) -> list[Show]:
        """Return all shows for the watch's movie/city/date.

        Implementations should return the raw list; filtering by format,
        language and theatre is handled centrally by the monitor service.
        Errors should be raised — the monitor logs and continues.
        """
        raise NotImplementedError
