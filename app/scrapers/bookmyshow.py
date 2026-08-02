"""Best-effort BookMyShow scraper.

BookMyShow sits behind bot protection that fingerprints the TLS handshake,
so a vanilla HTTP client gets 403 regardless of headers. We use curl_cffi
with Chrome impersonation, which presents a real browser TLS/JA3 fingerprint.

Strategy:
1. Resolve the BMS region code for the watch's city (static map of major
   cities, falling back to the city slug uppercased).
2. Find the movie's event code (ET########) by scanning the city's "explore
   movies" page for a link whose slug matches the movie name.
3. Fetch showtimes from the public showtimes-by-event API and parse venues,
   formats, languages and times.

BMS has no official API and changes its markup regularly, so every step is
defensive: a 403 raises ScraperBlockedError (logged as a one-line warning),
anything else raises and the monitor retries on the next tick. Polling stays
conservative (one request cycle per watch per minute).
"""

import difflib
import re
from datetime import date

from curl_cffi.requests import AsyncSession
from loguru import logger

from app.config import settings
from app.models import Watch
from app.schemas import Show
from app.scrapers.base import BaseScraper, ScraperBlockedError
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


def _compress(text: str) -> str:
    """Reduce a title/slug to bare letters+digits: 'Spider-Man: Brand New Day'
    and 'spiderman brand new day' both become 'spidermanbrandnewday'."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def match_event(html: str, movie: str, threshold: float = 0.75) -> tuple[str, str] | None:
    """Find the (slug, event_code) on an explore page best matching the movie name.

    Matching is fuzzy on the compressed strings so user input survives
    punctuation, hyphenation and spacing differences from the BMS slug.
    """
    # URLs can appear both as plain hrefs and inside embedded JSON with escaped slashes.
    html = html.replace("\\/", "/")
    candidates = set(re.findall(r"/movies/[a-z0-9-]+/([a-z0-9-]+)/(ET\d+)", html))
    target = _compress(movie)
    if not target or not candidates:
        return None

    best: tuple[str, str] | None = None
    best_score = 0.0
    for slug, code in candidates:
        compressed = _compress(slug)
        score = difflib.SequenceMatcher(None, target, compressed).ratio()
        if target in compressed or compressed in target:
            score = max(score, 0.95)
        if score > best_score:
            best_score, best = score, (slug, code)

    if best and best_score >= threshold:
        logger.debug("BMS: matched {!r} -> slug={} score={:.2f}", movie, best[0], best_score)
        return best
    if best:
        logger.info(
            "BMS: best candidate for {!r} was slug={} (score {:.2f} < {:.2f}) — no match",
            movie,
            best[0],
            best_score,
            threshold,
        )
    return None


class BookMyShowScraper(BaseScraper):
    name = "bookmyshow"

    def _region_code(self, city: str) -> str:
        slug = slugify(city)
        return REGION_CODES.get(slug.replace("-", " "), slug.replace("-", "").upper())

    @staticmethod
    def _checked(response, url: str):
        if response.status_code == 403:
            raise ScraperBlockedError(f"BookMyShow bot protection returned 403 for {url}")
        if response.status_code >= 400:
            raise ScraperBlockedError(f"BookMyShow returned HTTP {response.status_code} for {url}")
        return response

    async def scrape(self, watch: Watch) -> list[Show]:
        city_slug = slugify(watch.city)
        region = self._region_code(watch.city)

        async with AsyncSession(
            impersonate=settings.bms_impersonate,
            timeout=settings.http_timeout_seconds,
            headers={"Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8"},
        ) as session:
            found = await self._find_event(session, watch.movie, city_slug)
            if not found:
                logger.info(
                    "BMS: no event found for movie={!r} city={!r} (not listed yet?)",
                    watch.movie,
                    watch.city,
                )
                return []
            movie_slug, event_code = found
            payload = await self._fetch_showtimes(session, event_code, region, watch.date)

        booking_url = (
            f"{BASE_URL}/movies/{city_slug}/{movie_slug}/buytickets/"
            f"{event_code}/{watch.date.strftime('%Y%m%d')}"
        )
        return self._parse_showtimes(payload, watch, booking_url)

    async def _find_event(
        self, session: AsyncSession, movie: str, city_slug: str
    ) -> tuple[str, str] | None:
        """Scan the city's explore-movies page for the movie's (slug, event code)."""
        url = f"{BASE_URL}/explore/movies-{city_slug}"
        response = self._checked(await session.get(url), url)
        return match_event(response.text, movie)

    async def _fetch_showtimes(
        self, session: AsyncSession, event_code: str, region: str, show_date: date
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
        response = self._checked(await session.get(url, params=params), url)
        try:
            return response.json()
        except ValueError as exc:
            raise ScraperBlockedError(
                "BookMyShow showtimes endpoint returned non-JSON (challenge page?)"
            ) from exc

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
