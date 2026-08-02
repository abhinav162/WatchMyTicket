from datetime import date

from app.schemas import Show
from app.services.comparator import diff
from app.utils.hashing import show_hash


def make_show(theatre="PVR Vega", time="7:30 PM") -> Show:
    return Show(
        movie="Spider-Man",
        city="Bengaluru",
        theatre=theatre,
        format="ScreenX",
        language="English",
        date=date(2026, 8, 16),
        time=time,
        booking_url="https://example.com",
    )


def test_all_new_when_no_history():
    shows = [make_show(), make_show(time="10:00 PM")]
    result = diff(set(), shows)
    assert result.added == shows
    assert result.removed_hashes == set()


def test_known_shows_are_not_re_added():
    show = make_show()
    result = diff({show_hash(show)}, [show, make_show(time="10:00 PM")])
    assert len(result.added) == 1
    assert result.added[0].time == "10:00 PM"


def test_removed_hashes_reported():
    gone = show_hash(make_show(theatre="INOX"))
    result = diff({gone}, [make_show()])
    assert result.removed_hashes == {gone}
    assert len(result.added) == 1


def test_duplicate_shows_in_scrape_result_collapse():
    show = make_show()
    result = diff(set(), [show, show, show])
    assert len(result.added) == 1
