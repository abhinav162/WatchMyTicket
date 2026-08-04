"""Deterministic fake scraper for local development and demos.

Run with SCRAPER=mock to exercise the full pipeline (filtering, hashing,
duplicate prevention, Telegram notifications) without hitting BookMyShow.
"""

from app.models import Watch
from app.schemas import Show
from app.scrapers.base import BaseScraper


class MockScraper(BaseScraper):
    name = "mock"

    async def scrape(self, watch: Watch, wanted_formats: set[str] | None = None) -> list[Show]:
        base = dict(movie=watch.movie, city=watch.city, date=watch.date)
        return [
            Show(
                **base,
                theatre="PVR Vega Mall",
                format="ScreenX",
                language="English",
                time="7:30 PM",
                booking_url="https://in.bookmyshow.com/",
            ),
            Show(
                **base,
                theatre="INOX City Centre",
                format="IMAX",
                language="English",
                time="10:00 PM",
                booking_url="https://in.bookmyshow.com/",
            ),
        ]
