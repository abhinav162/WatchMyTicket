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


# Explore pages link movies as /movies/<slug>/ET... (no city segment); other
# pages use /movies/<city>/<slug>/ET... — accept both.
MOVIE_LINK_RE = re.compile(r"/movies/(?:[a-z0-9-]+/)?([a-z0-9-]+)/(ET\d+)")


def match_events(html: str, movie: str, threshold: float = 0.75) -> list[tuple[str, str]]:
    """Find every (slug, event_code) on an explore page matching the movie name.

    Matching is fuzzy on the compressed strings so user input survives
    punctuation, hyphenation and spacing differences from the BMS slug.
    A movie can have several events (e.g. separate 2D and 3D listings), so
    all candidates above the threshold are returned, best match first.
    """
    # URLs can appear both as plain hrefs and inside embedded JSON with escaped slashes.
    html = html.replace("\\/", "/")
    candidates = set(MOVIE_LINK_RE.findall(html))
    target = _compress(movie)
    if not candidates:
        logger.warning(
            "BMS: explore page contained no /movies/.../ET... links at all "
            "(JS-rendered or challenge page?) — run `python -m app.debug_scrape` to inspect"
        )
        return []
    if not target:
        return []

    scored: dict[str, tuple[float, str]] = {}  # event_code -> (score, slug)
    for slug, code in candidates:
        compressed = _compress(slug)
        score = difflib.SequenceMatcher(None, target, compressed).ratio()
        if target in compressed or compressed in target:
            score = max(score, 0.95)
        if code not in scored or score > scored[code][0]:
            scored[code] = (score, slug)

    matches = sorted(
        ((score, slug, code) for code, (score, slug) in scored.items() if score >= threshold),
        reverse=True,
    )
    if matches:
        logger.debug("BMS: {!r} matched {} event(s): {}", movie, len(matches), matches)
        return [(slug, code) for _, slug, code in matches]

    best_code, (best_score, best_slug) = max(scored.items(), key=lambda kv: kv[1][0])
    logger.info(
        "BMS: best candidate for {!r} was slug={} (score {:.2f} < {:.2f}) — no match",
        movie,
        best_slug,
        best_score,
        threshold,
    )
    return []


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
            events = await self._find_events(session, watch.movie, city_slug)
            if not events:
                logger.info(
                    "BMS: no event found for movie={!r} city={!r} (not listed yet?)",
                    watch.movie,
                    watch.city,
                )
                return []

            shows: list[Show] = []
            # A movie can be listed as several events (2D / 3D / re-release).
            for movie_slug, event_code in events[:5]:
                payload = await self._fetch_showtimes(session, event_code, region, watch.date)
                booking_url = (
                    f"{BASE_URL}/movies/{city_slug}/{movie_slug}/buytickets/"
                    f"{event_code}/{watch.date.strftime('%Y%m%d')}"
                )
                shows.extend(self._parse_showtimes(payload, watch, booking_url))
        return shows

    async def _find_events(
        self, session: AsyncSession, movie: str, city_slug: str
    ) -> list[tuple[str, str]]:
        """Scan the city's explore-movies page for the movie's (slug, event code) pairs."""
        url = f"{BASE_URL}/explore/movies-{city_slug}"
        response = self._checked(await session.get(url), url)
        return match_events(response.text, movie)

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

    @staticmethod
    def _child_meta(child: dict) -> tuple[str | None, str]:
        """Extract (format, language) from a ChildEvents entry, tolerating both
        explicit fields and the '(Dolby Cinema 2D)' suffix embedded in titles."""
        fmt = child.get("EventDimension") or child.get("EventDimensionType")
        if not fmt:
            title = child.get("EventTitle") or child.get("EventName") or ""
            match = re.search(r"\(([^)]+)\)\s*$", title)
            fmt = match.group(1) if match else None
        language = child.get("EventLanguage") or child.get("EventLang") or ""
        return fmt, language

    def _parse_showtimes(self, payload: dict, watch: Watch, booking_url: str) -> list[Show]:
        """Walk the showtimes payload without assuming a fixed nesting.

        BMS has shipped (at least) two shapes: venues nested inside each
        ChildEvents entry ('VenueList'), and venues as a sibling list with
        each ShowTime carrying the child's EventCode. We recursively find
        every dict with a VenueName + ShowTimes and resolve format/language
        from the showtime's EventCode or the enclosing ChildEvents entry.
        """
        # EventCode -> (format, language) from every ChildEvents entry anywhere.
        code_meta: dict[str, tuple[str | None, str]] = {}

        def collect_children(node) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "ChildEvents" and isinstance(value, list):
                        for child in value:
                            if isinstance(child, dict) and child.get("EventCode"):
                                code_meta[child["EventCode"]] = self._child_meta(child)
                    collect_children(value)
            elif isinstance(node, list):
                for item in node:
                    collect_children(item)

        collect_children(payload)

        shows: list[Show] = []

        def walk(node, ctx: tuple[str | None, str]) -> None:
            if isinstance(node, dict):
                if node.get("EventCode") in code_meta:
                    ctx = code_meta[node["EventCode"]]
                elif "EventLang" in node or "EventLanguage" in node or "EventDimension" in node:
                    ctx = self._child_meta(node)

                theatre = node.get("VenueName")
                showtimes = node.get("ShowTimes")
                if theatre and isinstance(showtimes, list):
                    for st in showtimes:
                        if not isinstance(st, dict):
                            continue
                        time_str = st.get("ShowTime") or st.get("ShowTimeDisplay") or ""
                        if not time_str:
                            continue
                        fmt, language = code_meta.get(st.get("EventCode", ""), ctx)
                        shows.append(
                            Show(
                                movie=watch.movie,
                                city=watch.city,
                                theatre=theatre,
                                format=fmt or "2D",
                                language=language,
                                date=watch.date,
                                time=time_str,
                                booking_url=booking_url,
                            )
                        )
                for value in node.values():
                    walk(value, ctx)
            elif isinstance(node, list):
                for item in node:
                    walk(item, ctx)

        walk(payload, (None, ""))
        return shows
