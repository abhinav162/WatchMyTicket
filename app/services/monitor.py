"""Monitoring pipeline (PRD §13):

load active watches → scrape → filter → hash → compare → notify → store hash.
"""

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


def _matches_any(value: str, wanted: list[str]) -> bool:
    """Case-insensitive containment match; an empty filter matches everything."""
    if not wanted:
        return True
    value_lower = value.lower()
    return any(w.lower() in value_lower for w in wanted)


def filter_shows(watch: Watch, shows: list[Show]) -> list[Show]:
    return [
        s
        for s in shows
        if s.date == watch.date
        and _matches_any(s.format, watch.formats or [])
        and _matches_any(s.language, watch.languages or [])
        and _matches_any(s.theatre, watch.theatres or [])
    ]


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

    async def run_once(self) -> None:
        async with self._session_factory() as session:
            watches = await watch_repo.list_active(session)
        logger.debug("Monitor tick: {} active watch(es)", len(watches))
        for watch in watches:
            try:
                await self.check_watch(watch)
            except ScraperBlockedError as exc:
                logger.warning(
                    "watch={} ({!r}): {} — retrying next tick", watch.id, watch.movie, exc
                )
            except Exception:
                logger.exception("Check failed for watch={} ({!r})", watch.id, watch.movie)

    async def check_watch(self, watch: Watch) -> int:
        """Check one watch. Returns the number of notifications sent."""
        shows = await self._scraper.scrape(watch)
        matching = filter_shows(watch, shows)

        async with self._session_factory() as session:
            known = await notification_repo.known_hashes(session, watch.id)
            result = diff(known, matching)

            sent = 0
            for show in result.added:
                await self._notifier.notify(watch, show)
                await notification_repo.record(session, watch.id, show_hash(show))
                sent += 1

            db_watch = await watch_repo.get(session, watch.id)
            if db_watch is not None:
                await watch_repo.touch_last_checked(session, db_watch)
            await session.commit()

        if sent:
            logger.info("watch={} ({!r}): {} new show(s) notified", watch.id, watch.movie, sent)
        return sent
