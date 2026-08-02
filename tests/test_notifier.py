from datetime import date

from app.schemas import Show
from app.services import notifier as notifier_module
from app.services.notifier import _digest_buttons, _group_shows, format_digest


def make_show(**overrides) -> Show:
    data = dict(
        movie="Spider-Man: Brand New Day",
        city="Bengaluru",
        theatre="INOX: Megaplex Mall of Asia Bangalore",
        format="3D SCREEN X",
        language="English",
        date=date(2026, 8, 4),
        time="7:00 PM",
        booking_url="https://in.bookmyshow.com/buytickets/ET00502684",
    )
    data.update(overrides)
    return Show(**data)


def test_single_show_uses_ticket_found_header():
    text = format_digest([make_show()])
    assert "Ticket Found!" in text
    assert "New Shows Found" not in text


def test_multi_show_uses_count_header():
    shows = [make_show(time="7:00 PM"), make_show(time="10:00 PM")]
    text = format_digest(shows)
    assert "2 New Shows Found!" in text


def test_same_theatre_and_format_times_are_joined_on_one_line():
    shows = [make_show(time=t) for t in ("06:50 AM", "10:00 AM", "01:00 PM")]
    text = format_digest(shows)
    assert text.count("INOX: Megaplex Mall of Asia Bangalore") == 1  # one group, not repeated
    assert "06:50 AM, 10:00 AM, 01:00 PM" in text


def test_different_theatres_produce_separate_groups():
    shows = [make_show(theatre="INOX Forum", time="9:00 PM"), make_show(theatre="PVR Vega", time="7:30 PM")]
    groups = _group_shows(shows)
    assert [g[0] for g in groups] == ["INOX Forum", "PVR Vega"]


def test_group_truncation_reports_hidden_count(monkeypatch):
    monkeypatch.setattr(notifier_module, "MAX_LISTED_GROUPS", 2)
    shows = [make_show(theatre=f"Theatre {i}", time="7:00 PM") for i in range(5)]
    text = format_digest(shows)
    assert "Theatre 0" in text and "Theatre 1" in text
    assert "Theatre 4" not in text
    assert "…and 3 more show(s) not shown here." in text


def test_digest_buttons_single_url_uses_generic_label():
    shows = [make_show(time="7:00 PM"), make_show(time="10:00 PM")]  # same booking_url
    markup = _digest_buttons(shows)
    assert len(markup.inline_keyboard) == 1
    assert markup.inline_keyboard[0][0].text == "🎟 Open BookMyShow"


def test_digest_buttons_multiple_urls_labeled_by_format():
    shows = [
        make_show(format="2D", booking_url="https://x/2d"),
        make_show(format="3D SCREEN X", booking_url="https://x/screenx"),
    ]
    markup = _digest_buttons(shows)
    labels = [row[0].text for row in markup.inline_keyboard]
    assert labels == ["🎟 2D", "🎟 3D SCREEN X"]


def test_digest_buttons_capped(monkeypatch):
    monkeypatch.setattr(notifier_module, "MAX_BUTTONS", 2)
    shows = [make_show(format=f"F{i}", booking_url=f"https://x/{i}") for i in range(5)]
    markup = _digest_buttons(shows)
    assert len(markup.inline_keyboard) == 2


def test_digest_buttons_none_when_no_booking_urls():
    shows = [make_show(booking_url="")]
    assert _digest_buttons(shows) is None
