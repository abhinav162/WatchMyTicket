"""Best-effort BookMyShow scraper.

Strategy:
1. Resolve the BMS region code for the watch's city (static map of major cities,
   falling back to the city slug uppercased).
2. Find the movie's event code (ET########) by scanning the city's "explore
   movies" page for a link whose slug matches the movie name.
3. Fetch showtimes from the public showtimes-by-event API and parse venues,
   formats, languages and times.

BookMyShow has no official API and actively changes its markup and applies
bot protection, so every step is defensive: any failure raises and the
monitor logs it and retries on the next tick. Polling stays conservative
(one request cycle per watch per minute).
"""

import re
from datetime import date

import httpx
from loguru import logger

from app.config import settings
from app.models import Watch
from app.schemas import Show
from app.scrapers.base import BaseScraper
from app.utils.text import slugify

BASE_URL = "https://in.bookmyshow.com"

# BMS region codes for major cities; anything unknown falls back to slug.upper().
REGION_CODES = {
    "mumbai": "MUMBAI",
    "delhi": "NCR",
    "new delhi": "NCR",
    "ncr": "NCR",
    "gurgaon": "NCR",
    "gurugram": "NCR",
    "noida": "NCR",
    "bengaluru": "BANG",
    "bangalore": "BANG",
    "chennai": "CHEN",
    "hyderabad": "HYD",
    "kolkata": "KOLK",
    "pune": "PUNE",
    "ahmedabad": "AHD",
    "chandigarh": "CHD",
    "jaipur": "JAIP",
    "kochi": "KOCH",
    "lucknow": "LUCK",
}


class BookMyShowScraper(BaseScraper):
    name = "bookmyshow"

    def _headers(self) -> dict:
        return {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }

    def _region_code(self, city: str) -> str:
        slug = slugify(city)
        return REGION_CODES.get(slug.replace("-", " "), slug.replace("-", "").upper())

    async def scrape(self, watch: Watch) -> list[Show]:
        city_slug = slugify(watch.city)
        region = self._region_code(watch.city)

        async with httpx.AsyncClient(
            headers=self._headers(),
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
        ) as client:
            event_code = await self._find_event_code(client, watch.movie, city_slug)
            if not event_code:
                logger.info(
                    "BMS: no event found for movie={!r} city={!r} (not listed yet?)",
                    watch.movie,
                    watch.city,
                )
                return []
            payload = await self._fetch_showtimes(client, event_code, region, watch.date)

        movie_slug = slugify(watch.movie)
        booking_url = (
            f"{BASE_URL}/movies/{city_slug}/{movie_slug}/buytickets/"
            f"{event_code}/{watch.date.strftime('%Y%m%d')}"
        )
        return self._parse_showtimes(payload, watch, booking_url)

    async def _find_event_code(self, client: httpx.AsyncClient, movie: str, city_slug: str) -> str | None:
        """Scan the city's explore-movies page for a /movies/.../ET... link matching the title."""
        url = f"{BASE_URL}/explore/movies-{city_slug}"
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

        movie_slug = slugify(movie)
        # Exact slug first, then a loose match on the significant words.
        patterns = [rf"/movies/[a-z0-9-]+/{re.escape(movie_slug)}/(ET\d+)"]
        words = [w for w in movie_slug.split("-") if len(w) > 2]
        if words:
            loose = "[a-z0-9-]*".join(re.escape(w) for w in words)
            patterns.append(rf"/movies/[a-z0-9-]+/[a-z0-9-]*{loose}[a-z0-9-]*/(ET\d+)")

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)

        # Fallback: embedded JSON often carries "eventCode":"ET..." next to the title.
        title_pattern = re.escape(movie.strip())
        match = re.search(
            rf'"(?:eventName|title)"\s*:\s*"{title_pattern}".{{0,500}}?"(?:eventCode|code)"\s*:\s*"(ET\d+)"',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        return match.group(1) if match else None

    async def _fetch_showtimes(
        self, client: httpx.AsyncClient, event_code: str, region: str, show_date: date
    ) -> dict:
        url = f"{BASE_URL}/api/movies-data/showtimes-by-event"
        params = {
            "appCode": "MOBAND2",
            "appVersion": "14304",
            "language": "en",
            "eventCode": event_code,
            "regionCode": region,
            "subRegion": region,
            "bmsId": "1.0",
            "token": "",
            "dateCode": show_date.strftime("%Y%m%d"),
        }
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _parse_showtimes(self, payload: dict, watch: Watch, booking_url: str) -> list[Show]:
        shows: list[Show] = []
        for detail in payload.get("ShowDetails", []) or []:
            event = detail.get("Event", {}) or {}
            for child in event.get("ChildEvents", []) or []:
                fmt = child.get("EventDimension") or child.get("EventDimensionType") or "2D"
                language = child.get("EventLanguage") or ""
                title = child.get("EventTitle") or watch.movie
                for venue in child.get("VenueList", []) or []:
                    theatre = venue.get("VenueName") or ""
                    if not theatre:
                        continue
                    for show_time in venue.get("ShowTimes", []) or []:
                        time_str = show_time.get("ShowTime") or ""
                        if not time_str:
                            continue
                        shows.append(
                            Show(
                                movie=title,
                                city=watch.city,
                                theatre=theatre,
                                format=fmt,
                                language=language,
                                date=watch.date,
                                time=time_str,
                                booking_url=booking_url,
                            )
                        )
        return shows
