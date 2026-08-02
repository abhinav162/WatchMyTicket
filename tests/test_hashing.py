from datetime import date

from app.schemas import Show
from app.utils.hashing import show_hash


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


def test_hash_is_stable():
    assert show_hash(make_show()) == show_hash(make_show())


def test_hash_ignores_case_and_whitespace():
    assert show_hash(make_show(movie="  spider-man ")) == show_hash(make_show(movie="Spider-Man"))
    assert show_hash(make_show(theatre="PVR  Vega")) == show_hash(make_show(theatre="pvr vega"))


def test_hash_changes_with_identity_fields():
    base = show_hash(make_show())
    assert show_hash(make_show(theatre="INOX")) != base
    assert show_hash(make_show(time="10:00 PM")) != base
    assert show_hash(make_show(format="IMAX")) != base
    assert show_hash(make_show(date=date(2026, 8, 17))) != base


def test_hash_ignores_booking_url_and_city():
    base = show_hash(make_show())
    assert show_hash(make_show(booking_url="https://other.example")) == base
