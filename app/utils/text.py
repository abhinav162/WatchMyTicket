"""Small text helpers: slugs and user-input parsing."""

import re
from datetime import date

from dateutil import parser as date_parser


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def parse_user_date(text: str, today: date | None = None) -> date:
    """Parse a human-entered date like '16 Aug', 'tomorrow-ish formats', '2026-08-16'.

    Raises ValueError when the text can't be parsed or is in the past.
    """
    today = today or date.today()
    parsed = date_parser.parse(text, dayfirst=True, default=date_parser.parse(today.isoformat())).date()
    if parsed < today:
        # A month/day without a year that already passed likely means next year.
        if parsed.replace(year=parsed.year + 1) >= today:
            parsed = parsed.replace(year=parsed.year + 1)
        else:
            raise ValueError("date is in the past")
    return parsed


def parse_list(text: str) -> list[str]:
    """Parse a comma-separated user answer. 'any'/'all'/'skip' mean no filter."""
    cleaned = text.strip()
    if cleaned.lower() in {"any", "all", "skip", "-", "none", ""}:
        return []
    return [item.strip() for item in cleaned.split(",") if item.strip()]
