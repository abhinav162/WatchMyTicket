"""Scraper interface. New providers (District, Insider, Paytm, ...) implement this."""

from abc import ABC, abstractmethod

from app.models import Watch
from app.schemas import Show


class ScraperBlockedError(Exception):
    """The provider rejected our request (bot protection / rate limiting).

    Expected occasionally in the wild — the monitor logs a concise warning
    and retries on the next tick instead of dumping a traceback.
    """


class BaseScraper(ABC):
    """Turns a Watch into the list of shows currently bookable on a provider."""

    name: str = "base"

    @abstractmethod
    async def scrape(self, watch: Watch, wanted_formats: set[str] | None = None) -> list[Show]:
        """Return all shows for the watch's movie/city/date.

        Implementations should return the raw list; filtering by format,
        language and theatre is handled centrally by the monitor service.
        Errors should be raised — the monitor logs and continues.

        wanted_formats is an optional hint — the union of every format
        string that matters across all watches sharing this scrape (the
        monitor dedupes scrapes by movie/city/date). None means "every
        format matters" (at least one sharing watch has no format filter);
        a provider MAY use this to skip fetching irrelevant format/language
        variants, but including extras is always safe since filtering is
        still applied centrally afterward.
        """
        raise NotImplementedError
