from datetime import date

import pytest

from app.models import Watch, WatchStatus
from app.repositories import watch_repo
from app.schemas import Show
from app.scrapers.base import BaseScraper, ScraperBlockedError
from app.services.monitor import MonitorService, filter_shows


def make_show(**overrides) -> Show:
    data = dict(
        movie="Spider-Man",
        city="Bengaluru",
        theatre="PVR Vega",
        format="ScreenX",
        language="English",
        date=date(2026, 8, 16),
        time="7:30 PM",
        booking_url="https://example.com",
    )
    data.update(overrides)
    return Show(**data)


class FakeScraper(BaseScraper):
    name = "fake"

    def __init__(self, shows):
        self.shows = shows

    async def scrape(self, watch):
        return list(self.shows)


class SpyNotifier:
    def __init__(self):
        self.sent = []

    async def notify(self, watch, show):
        self.sent.append((watch.id, show))


# ------------------------------------------------------------- filtering


def make_watch(**overrides) -> Watch:
    data = dict(
        user_id=1,
        movie="Spider-Man",
        city="Bengaluru",
        date=date(2026, 8, 16),
        formats=[],
        languages=[],
        theatres=[],
        status=WatchStatus.ACTIVE,
    )
    data.update(overrides)
    return Watch(**data)


def test_empty_filters_match_everything():
    shows = [make_show(), make_show(format="IMAX", theatre="INOX")]
    assert filter_shows(make_watch(), shows) == shows


def test_format_filter():
    watch = make_watch(formats=["ScreenX"])
    shows = [make_show(), make_show(format="IMAX")]
    assert [s.format for s in filter_shows(watch, shows)] == ["ScreenX"]


def test_theatre_filter_is_substring_and_case_insensitive():
    watch = make_watch(theatres=["pvr vega"])
    shows = [make_show(theatre="PVR Vega Mall"), make_show(theatre="INOX City")]
    assert [s.theatre for s in filter_shows(watch, shows)] == ["PVR Vega Mall"]


def test_other_dates_are_excluded():
    watch = make_watch()
    shows = [make_show(), make_show(date=date(2026, 8, 17))]
    assert len(filter_shows(watch, shows)) == 1


# ---------------------------------------------------------- monitor runs


@pytest.mark.asyncio
async def test_first_check_notifies_second_check_does_not(session_factory, seeded_watch):
    shows = [make_show(), make_show(time="10:00 PM")]
    notifier = SpyNotifier()
    monitor = MonitorService(FakeScraper(shows), notifier, session_factory=session_factory)

    await monitor.run_once()
    assert len(notifier.sent) == 2

    await monitor.run_once()
    assert len(notifier.sent) == 2  # duplicates prevented


@pytest.mark.asyncio
async def test_new_show_appearing_later_triggers_one_notification(session_factory, seeded_watch):
    scraper = FakeScraper([make_show()])
    notifier = SpyNotifier()
    monitor = MonitorService(scraper, notifier, session_factory=session_factory)

    await monitor.run_once()
    assert len(notifier.sent) == 1

    scraper.shows.append(make_show(theatre="INOX Forum", time="9:00 PM"))
    await monitor.run_once()
    assert len(notifier.sent) == 2
    assert notifier.sent[-1][1].theatre == "INOX Forum"


@pytest.mark.asyncio
async def test_format_mismatch_sends_nothing(session_factory, seeded_watch):
    notifier = SpyNotifier()
    monitor = MonitorService(FakeScraper([make_show(format="IMAX")]), notifier, session_factory=session_factory)
    await monitor.run_once()
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_paused_watch_is_skipped(session_factory, seeded_watch):
    async with session_factory() as session:
        watch = await watch_repo.get(session, seeded_watch)
        await watch_repo.set_status(session, watch, WatchStatus.PAUSED)
        await session.commit()

    notifier = SpyNotifier()
    monitor = MonitorService(FakeScraper([make_show()]), notifier, session_factory=session_factory)
    await monitor.run_once()
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_blocked_scraper_does_not_crash_the_run(session_factory, seeded_watch):
    class BlockedScraper(BaseScraper):
        name = "blocked"

        async def scrape(self, watch):
            raise ScraperBlockedError("403")

    notifier = SpyNotifier()
    monitor = MonitorService(BlockedScraper(), notifier, session_factory=session_factory)
    await monitor.run_once()  # must not raise
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_last_checked_is_updated(session_factory, seeded_watch):
    monitor = MonitorService(FakeScraper([]), SpyNotifier(), session_factory=session_factory)
    await monitor.run_once()
    async with session_factory() as session:
        watch = await watch_repo.get(session, seeded_watch)
        assert watch.last_checked is not None
