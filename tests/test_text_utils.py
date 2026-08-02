from datetime import date

import pytest

from app.utils.text import parse_list, parse_user_date, slugify


def test_slugify():
    assert slugify("Spider-Man: No Way Home") == "spider-man-no-way-home"
    assert slugify("  Bengaluru ") == "bengaluru"


def test_parse_list():
    assert parse_list("English, Hindi") == ["English", "Hindi"]
    assert parse_list("any") == []
    assert parse_list("  skip ") == []
    assert parse_list("PVR Vega") == ["PVR Vega"]


def test_parse_user_date_iso():
    assert parse_user_date("2026-08-16", today=date(2026, 8, 1)) == date(2026, 8, 16)


def test_parse_user_date_day_month():
    assert parse_user_date("16 Aug", today=date(2026, 8, 1)) == date(2026, 8, 16)


def test_parse_user_date_rolls_to_next_year():
    assert parse_user_date("5 Jan", today=date(2026, 8, 1)) == date(2027, 1, 5)


def test_parse_user_date_rejects_past():
    with pytest.raises(ValueError):
        parse_user_date("2025-01-01", today=date(2026, 8, 1))


def test_parse_user_date_rejects_garbage():
    with pytest.raises((ValueError, OverflowError)):
        parse_user_date("not a date", today=date(2026, 8, 1))
