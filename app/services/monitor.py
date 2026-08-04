"""Monitoring pipeline (PRD §13):

load active watches → scrape → filter → hash → compare → notify → store hash.
"""

import time
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import database
from app.models import Watch
from app.repositories import notification_repo, watch_repo
from app.schemas import Show
from app.scrapers.base import BaseScraper, ScraperBlockedError
from app.services.comparator import diff
from app.services.notifier import Notifier
from app.utils.hashing import show_hash
from app.utils.text import compress


def _matches_any(value: str, wanted: list[str]) -> bool:
    """Punctuation/spacing-tolerant containment match; an empty filter matches
    everything. BMS's own labels rarely match a user's filter verbatim — e.g.
    the watch filter 'ScreenX' must match BMS's actual label '3D SCREEN X' —
    so both sides are compressed to bare letters+digits before comparing.
    """
    if not wanted:
        return True
    value_compressed = compress(value)
    return any(compress(w) in value_compressed for w in wanted)


def filter_shows(watch: Watch, shows: list[Show]) -> list[Show]:
    return [
        s
        for s in shows
        if s.date == watch.date
        and _matches_any(s.format, watch.formats or [])
        and _matches_any(s.language, watch.languages or [])
        and _matches_any(s.theatre, watch.theatres or [])
    ]


def _scrape_key(watch: Watch) -> tuple[str, str, object]:
    """Cache key for raw scrape results, shared by watches that target the
    same movie/city/date regardless of their format/theatre/language filters
    (those are applied afterward by filter_shows). Keeps each tick from
    re-scraping BookMyShow once per watch when several watches overlap —
    fewer requests per tick means less exposure to BMS's bot-protection.
    """
    return (compress(watch.movie), watch.city.strip().lower(), watch.date)


class MonitorService:
    def __init__(
        self,
        scraper: BaseScraper,
        notifier: Notifier,
        session_factory: async_sessionmaker | None = None,
    ):
        self._scraper = scraper
        self._notifier = notifier
        self._session_factory = session_factory or database.session_factory
        # Heartbeat/observability — exposed via /health.
        self.last_tick_at: datetime | None = None
        self.last_tick_duration: float | None = None
        self.last_tick_notifications: int = 0

    async def run_once(self) -> None:
        started = time.monotonic()
        async with self._session_factory() as session:
            watches = await watch_repo.list_active(session)
        sent_total = 0
        scrape_cache: dict[tuple, list[Show]] = {}
        for watch in watches:
            try:
                sent_total += await self.check_watch(watch, scrape_cache)
            except ScraperBlockedError as exc:
                logger.warning(
                    "watch={} ({!r}): {} — retrying next tick", watch.id, watch.movie, exc
                )
            except Exception:
                logger.exception("Check failed for watch={} ({!r})", watch.id, watch.movie)

        self.last_tick_at = datetime.now(timezone.utc)
        self.last_tick_duration = round(time.monotonic() - started, 2)
        self.last_tick_notifications = sent_total
        logger.info(
            "Monitor tick: {} active watch(es) checked via {} scrape(s), "
            "{} notification(s) sent, took {}s",
            len(watches),
            len(scrape_cache),
            sent_total,
            self.last_tick_duration,
        )

    async def check_watch(self, watch: Watch, scrape_cache: dict[tuple, list[Show]] | None = None) -> int:
        """Check one watch. Returns the number of new shows notified this tick.

        All shows newly discovered in this tick are sent as a single digest
        message via one notify() call, not one message per show. When called
        from run_once(), scrape_cache is shared across every watch in the
        tick so watches sharing a (movie, city, date) reuse one scrape.
        """
        cache = scrape_cache if scrape_cache is not None else {}
        key = _scrape_key(watch)
        if key in cache:
            shows = cache[key]
            logger.debug("watch={}: reusing cached scrape for {}", watch.id, key)
        else:
            shows = await self._scraper.scrape(watch)
            cache[key] = shows
        matching = filter_shows(watch, shows)

        async with self._session_factory() as session:
            known = await notification_repo.known_hashes(session, watch.id)
            result = diff(known, matching)

            if result.added:
                await self._notifier.notify(watch, result.added)
                for show in result.added:
                    await notification_repo.record(session, watch.id, show_hash(show))

            db_watch = await watch_repo.get(session, watch.id)
            if db_watch is not None:
                await watch_repo.touch_last_checked(session, db_watch)
            await session.commit()

        sent = len(result.added)
        if sent:
            logger.info("watch={} ({!r}): {} new show(s) notified", watch.id, watch.movie, sent)
        return sent
