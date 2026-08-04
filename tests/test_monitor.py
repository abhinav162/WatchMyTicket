from datetime import date

import pytest

from app.models import User, Watch, WatchStatus
from app.repositories import watch_repo
from app.schemas import Show
from app.scrapers.base import BaseScraper, ScraperBlockedError
from app.services.monitor import MonitorService, _scrape_key, filter_shows


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
        self.calls = []

    async def scrape(self, watch):
        self.calls.append(watch.id)
        return list(self.shows)


class SpyNotifier:
    def __init__(self):
        self.sent = []  # flattened (watch_id, show) pairs across every notify() call
        self.batches = []  # one (watch_id, [shows]) entry per notify() call

    async def notify(self, watch, shows):
        self.batches.append((watch.id, list(shows)))
        self.sent.extend((watch.id, show) for show in shows)


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


def test_format_filter_tolerates_bms_spacing_and_prefix():
    # Regression: BMS labels this format '3D SCREEN X' (space + '3D ' prefix)
    # while a watch stores the user's plain 'ScreenX' — these must match.
    watch = make_watch(formats=["ScreenX"])
    shows = [make_show(format="3D SCREEN X"), make_show(format="Dolby Cinema 2D")]
    assert [s.format for s in filter_shows(watch, shows)] == ["3D SCREEN X"]


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
async def test_same_tick_discoveries_are_batched_into_one_notification(session_factory, seeded_watch):
    shows = [
        make_show(),
        make_show(time="10:00 PM"),
        make_show(theatre="INOX Forum", time="9:00 PM"),
    ]
    notifier = SpyNotifier()
    monitor = MonitorService(FakeScraper(shows), notifier, session_factory=session_factory)

    await monitor.run_once()

    assert len(notifier.batches) == 1  # one Telegram message for the whole tick
    assert len(notifier.batches[0][1]) == 3  # containing all 3 new shows
    assert len(notifier.sent) == 3


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


# --------------------------------------------------------- scrape dedup/cache


def test_scrape_key_ignores_filters_and_case_spacing():
    a = make_watch(movie="Spider-Man: Brand New Day", city="Bengaluru", formats=["ScreenX"])
    b = make_watch(movie="spiderman brand new day", city=" bengaluru ", formats=["IMAX"], theatres=["X"])
    assert _scrape_key(a) == _scrape_key(b)


def test_scrape_key_differs_by_date():
    a = make_watch(date=date(2026, 8, 8))
    b = make_watch(date=date(2026, 8, 9))
    assert _scrape_key(a) != _scrape_key(b)


async def _seed_two_overlapping_watches(session_factory):
    """Two watches for the same movie/city/date, different filters."""
    async with session_factory() as session:
        user = User(telegram_id=333, chat_id=444)
        session.add(user)
        await session.flush()
        watch_a = Watch(
            user_id=user.id,
            movie="Spider-Man: Brand New Day",
            city="Bengaluru",
            date=date(2026, 8, 8),
            formats=["ScreenX"],
            languages=[],
            theatres=[],
        )
        watch_b = Watch(
            user_id=user.id,
            movie="spiderman brand new day",
            city="Bengaluru",
            date=date(2026, 8, 8),
            formats=["IMAX"],
            languages=[],
            theatres=[],
        )
        session.add_all([watch_a, watch_b])
        await session.commit()


@pytest.mark.asyncio
async def test_overlapping_watches_share_one_scrape_per_tick(session_factory):
    await _seed_two_overlapping_watches(session_factory)
    shows = [
        make_show(theatre="INOX Forum", format="ScreenX", date=date(2026, 8, 8)),
        make_show(theatre="PVR Vega", format="IMAX", date=date(2026, 8, 8)),
    ]
    scraper = FakeScraper(shows)
    notifier = SpyNotifier()
    monitor = MonitorService(scraper, notifier, session_factory=session_factory)

    await monitor.run_once()

    assert len(scraper.calls) == 1  # one real scrape covered both watches
    # each watch still only got notified about shows matching its own filter
    formats_notified = {s.format for _, s in notifier.sent}
    assert formats_notified == {"ScreenX", "IMAX"}


@pytest.mark.asyncio
async def test_non_overlapping_watches_each_get_their_own_scrape(session_factory):
    async with session_factory() as session:
        user = User(telegram_id=555, chat_id=666)
        session.add(user)
        await session.flush()
        session.add_all(
            [
                Watch(
                    user_id=user.id,
                    movie="Spider-Man",
                    city="Bengaluru",
                    date=date(2026, 8, 8),
                    formats=[],
                    languages=[],
                    theatres=[],
                ),
                Watch(
                    user_id=user.id,
                    movie="Spider-Man",
                    city="Bengaluru",
                    date=date(2026, 8, 9),  # different date -> different key
                    formats=[],
                    languages=[],
                    theatres=[],
                ),
            ]
        )
        await session.commit()

    scraper = FakeScraper([])
    monitor = MonitorService(scraper, SpyNotifier(), session_factory=session_factory)
    await monitor.run_once()

    assert len(scraper.calls) == 2
