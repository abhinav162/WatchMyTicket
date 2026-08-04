"""Best-effort BookMyShow scraper.

BookMyShow sits behind bot protection that fingerprints the TLS handshake,
so a vanilla HTTP client gets 403 regardless of headers. We use curl_cffi
with Chrome impersonation, which presents a real browser TLS/JA3 fingerprint.

Strategy:
1. Resolve the BMS region code for the watch's city (static map of major
   cities, falling back to the city slug uppercased).
2. Find the movie's event code (ET########) by scanning the city's "explore
   movies" page for a link whose slug matches the movie name.
3. Fetch showtimes for that anchor event, then discover every sibling event
   code (2D/3D, language dubs, premium formats like ScreenX/Dolby/4DX/IMAX)
   listed in its ChildEvents metadata and fetch each of those independently.
   BMS does NOT embed a sibling's showtimes in the anchor's response even
   though it lists the sibling as a child — each format/language variant is
   its own separately-queryable event, confirmed by comparing a movie's
   buytickets page (which deep-links straight to e.g. an EventCode for its
   ScreenX showing) against the anchor event's response, which reports zero
   shows for that same EventCode.

BMS has no official API and changes its markup regularly, so every step is
defensive: a 403 raises ScraperBlockedError (logged as a one-line warning),
anything else raises and the monitor retries on the next tick. Polling stays
conservative (one request cycle per watch per minute).
"""

import difflib
import re
import secrets
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from curl_cffi.curl import CurlError
from curl_cffi.requests import AsyncSession
from loguru import logger

from app.config import settings
from app.models import Watch
from app.schemas import Show
from app.scrapers.base import BaseScraper, ScraperBlockedError
from app.utils.text import compress, slugify

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


# Explore pages link movies as /movies/<slug>/ET... (no city segment); other
# pages use /movies/<city>/<slug>/ET... — accept both.
MOVIE_LINK_RE = re.compile(r"/movies/(?:[a-z0-9-]+/)?([a-z0-9-]+)/(ET\d+)")


def proxy_with_session(base_url: str) -> str:
    """Append a fresh sticky-session id to a residential-proxy URL's username.

    A single scrape makes ~15 requests (explore page + every format/language
    variant). Confirmed live that this provider rotates to a brand new
    residential IP on every request by default — meaning one BMS session
    would hop across a dozen different residential IPs within seconds, which
    itself is a bot-like pattern. Appending '_session-<id>' (this provider's
    sticky-session convention, confirmed empirically) pins one IP for every
    request sharing that id. A fresh id per scrape() call means different
    ticks still rotate IPs over time, spreading load across the pool.
    """
    parts = urlsplit(base_url)
    if not parts.username:
        return base_url
    session_id = secrets.token_hex(4)
    userinfo = f"{parts.username}_session-{session_id}"
    if parts.password:
        userinfo += f":{parts.password}"
    netloc = f"{userinfo}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


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
    target = compress(movie)
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
        compressed = compress(slug)
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

    @staticmethod
    async def _get(session: AsyncSession, url: str, **kwargs):
        """session.get() wrapped so a dead proxy exit node or dropped
        connection is treated the same as a 403: log a one-line warning and
        let the caller retry, instead of an unhandled traceback. Residential
        proxy pools have some percentage of unreliable peers."""
        try:
            return await session.get(url, **kwargs)
        except CurlError as exc:
            raise ScraperBlockedError(f"Connection to BookMyShow failed for {url}: {exc}") from exc

    async def scrape(self, watch: Watch) -> list[Show]:
        city_slug = slugify(watch.city)
        region = self._region_code(watch.city)

        def booking_url(anchor_slug: str, event_code: str) -> str:
            return (
                f"{BASE_URL}/movies/{city_slug}/{anchor_slug}/buytickets/"
                f"{event_code}/{watch.date.strftime('%Y%m%d')}"
            )

        proxy = proxy_with_session(settings.bms_proxy_url) if settings.bms_proxy_url else None
        async with AsyncSession(
            impersonate=settings.bms_impersonate,
            timeout=settings.http_timeout_seconds,
            headers={"Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8"},
            proxy=proxy,
        ) as session:
            events = await self._find_events(session, watch.movie, city_slug)
            if not events:
                logger.info(
                    "BMS: no event found for movie={!r} city={!r} (not listed yet?)",
                    watch.movie,
                    watch.city,
                )
                return []

            anchor_slug, anchor_code = events[0]
            anchor_payload = await self._fetch_showtimes(session, anchor_code, region, watch.date)
            shows = self._parse_showtimes(anchor_payload, watch, booking_url(anchor_slug, anchor_code))

            # Format/language variants (ScreenX, Dolby, 4DX, IMAX, dubs, ...) are
            # listed as ChildEvents of the anchor but have their own independent
            # showtimes, not embedded in the anchor's response — fetch each one.
            sibling_codes = [
                code for code in self._collect_child_codes(anchor_payload) if code != anchor_code
            ]
            max_extra = max(settings.bms_max_events_per_watch - 1, 0)
            if len(sibling_codes) > max_extra:
                logger.info(
                    "BMS: {!r} has {} format/language variants; checking the first {} "
                    "(raise BMS_MAX_EVENTS_PER_WATCH to check more)",
                    watch.movie,
                    len(sibling_codes) + 1,
                    max_extra + 1,
                )
                sibling_codes = sibling_codes[:max_extra]

            for code in sibling_codes:
                try:
                    payload = await self._fetch_showtimes(session, code, region, watch.date)
                except ScraperBlockedError as exc:
                    logger.debug("BMS: variant {} fetch failed, skipping: {}", code, exc)
                    continue
                shows.extend(self._parse_showtimes(payload, watch, booking_url(anchor_slug, code)))
        return shows

    async def _find_events(
        self, session: AsyncSession, movie: str, city_slug: str
    ) -> list[tuple[str, str]]:
        """Scan the city's explore-movies page for the movie's (slug, event code) pairs."""
        url = f"{BASE_URL}/explore/movies-{city_slug}"
        response = self._checked(await self._get(session, url), url)
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
        response = self._checked(await self._get(session, url, params=params), url)
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

    @classmethod
    def _collect_child_codes(cls, payload: dict) -> dict[str, tuple[str | None, str]]:
        """Every EventCode -> (format, language) reachable via a ChildEvents
        list anywhere in the payload (the anchor event includes itself)."""
        code_meta: dict[str, tuple[str | None, str]] = {}

        def walk(node) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "ChildEvents" and isinstance(value, list):
                        for child in value:
                            if isinstance(child, dict) and child.get("EventCode"):
                                code_meta[child["EventCode"]] = cls._child_meta(child)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return code_meta

    def _parse_showtimes(self, payload: dict, watch: Watch, booking_url: str) -> list[Show]:
        """Walk the showtimes payload without assuming a fixed nesting.

        BMS has shipped (at least) two shapes: venues nested inside each
        ChildEvents entry ('VenueList'), and venues as a sibling list with
        each ShowTime carrying the child's EventCode. We recursively find
        every dict with a VenueName + ShowTimes and resolve format/language
        from the showtime's EventCode or the enclosing ChildEvents entry.

        Each ShowDetails entry carries its own 'Date'. BMS has been observed
        to silently substitute a different date's data when asked for a
        dateCode it doesn't have cached (confirmed with an out-of-range
        date, which came back as whatever date it had default), so entries
        whose Date doesn't match the requested one are discarded rather
        than trusted — otherwise a stale/substituted response could be
        mislabeled with the watch's target date and trigger a false
        notification for a date that was never actually offered.
        """
        code_meta = self._collect_child_codes(payload)
        requested_date = watch.date.strftime("%Y%m%d")
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

        for detail in payload.get("ShowDetails", []) or []:
            if not isinstance(detail, dict):
                continue
            actual_date = detail.get("Date")
            if actual_date and actual_date != requested_date:
                logger.warning(
                    "BMS: requested date {} but a ShowDetails entry is dated {} — "
                    "discarding it (BMS may not have the requested date cached yet)",
                    requested_date,
                    actual_date,
                )
                continue
            walk(detail, (None, ""))

        return shows
