"""Small text helpers: slugs and user-input parsing."""

import re
from datetime import date

from dateutil import parser as date_parser


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def compress(text: str) -> str:
    """Reduce text to bare letters+digits, e.g. 'ScreenX' and '3D SCREEN X'
    both become comparable ('screenx' is a substring of '3dscreenx').

    Used wherever user input and BMS's own labelling diverge in spacing,
    punctuation, or extra qualifiers (movie titles, formats, theatre names).
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def parse_user_date(text: str, today: date | None = None) -> date:
    """Parse a human-entered date like '16 Aug', 'tomorrow-ish formats', '2026-08-16'.

    Raises ValueError when the text can't be parsed or is in the past.
    """
    today = today or date.today()
    text = text.strip()
    try:
        # ISO 8601 (YYYY-MM-DD) is unambiguous — parse it directly rather than
        # through dateutil's dayfirst heuristic, which misreads e.g. '2026-08-04'
        # as day=08/month=04 once the year is stripped off as the first token.
        parsed = date.fromisoformat(text)
    except ValueError:
        parsed = date_parser.parse(
            text, dayfirst=True, default=date_parser.parse(today.isoformat())
        ).date()
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
