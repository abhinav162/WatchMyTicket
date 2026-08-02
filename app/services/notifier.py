"""Telegram notification delivery.

All shows discovered as new within a single monitor tick are sent as one
digest message per watch, not one message per show — a watch's first
successful check can easily surface a dozen matching showtimes at once.
"""

from typing import Protocol

from loguru import logger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app.models import Watch
from app.schemas import Show

MAX_LISTED_GROUPS = 20  # cap venue/format groups shown before "...and N more"
MAX_BUTTONS = 4  # cap distinct booking-link buttons on one message


class Notifier(Protocol):
    async def notify(self, watch: Watch, shows: list[Show]) -> None: ...


def _group_shows(shows: list[Show]) -> list[tuple[str, str, str, list[str], str]]:
    """Group shows by (theatre, format, language), collecting their times.

    Returns [(theatre, format, language, times, booking_url), ...] in the
    order each group first appears; booking_url is the group's first show's
    (shows sharing a format/event code share the same booking link).
    """
    times: dict[tuple[str, str, str], list[str]] = {}
    booking_urls: dict[tuple[str, str, str], str] = {}
    order: list[tuple[str, str, str]] = []
    for show in shows:
        key = (show.theatre, show.format, show.language)
        if key not in times:
            times[key] = []
            booking_urls[key] = show.booking_url
            order.append(key)
        times[key].append(show.time)

    result = []
    for theatre, fmt, language in order:
        key = (theatre, fmt, language)
        result.append((theatre, fmt, language, times[key], booking_urls[key]))
    return result


def format_digest(shows: list[Show]) -> str:
    """Render one or more newly-found shows for the same watch as one message."""
    first = shows[0]
    header = "🎬 <b>Ticket Found!</b>" if len(shows) == 1 else f"🎬 <b>{len(shows)} New Shows Found!</b>"
    lines = [header, "", f"<b>{first.movie}</b>", f"📅 {first.date.strftime('%a, %d %b %Y')}", ""]

    groups = _group_shows(shows)
    shown, hidden = groups[:MAX_LISTED_GROUPS], groups[MAX_LISTED_GROUPS:]
    for theatre, fmt, language, times, _ in shown:
        lines.append(f"🏢 <b>{theatre}</b>")
        lines.append(f"🎞 {fmt}" + (f" • 🗣 {language}" if language else ""))
        lines.append(f"🕐 {', '.join(times)}")
        lines.append("")
    if hidden:
        hidden_count = sum(len(times) for *_, times, _ in hidden)
        lines.append(f"…and {hidden_count} more show(s) not shown here.")

    return "\n".join(lines).rstrip()


def _digest_buttons(shows: list[Show]) -> InlineKeyboardMarkup | None:
    """One button per distinct booking link, capped at MAX_BUTTONS."""
    seen: dict[str, str] = {}
    for show in shows:
        if show.booking_url and show.booking_url not in seen:
            seen[show.booking_url] = show.format
    if not seen:
        return None
    entries = list(seen.items())[:MAX_BUTTONS]
    if len(entries) == 1:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🎟 Open BookMyShow", url=entries[0][0])]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"🎟 {fmt}", url=url)] for url, fmt in entries])


class TelegramNotifier:
    def __init__(self, bot: Bot):
        self._bot = bot

    async def notify(self, watch: Watch, shows: list[Show]) -> None:
        if not shows:
            return
        await self._bot.send_message(
            chat_id=watch.user.chat_id,
            text=format_digest(shows),
            parse_mode=ParseMode.HTML,
            reply_markup=_digest_buttons(shows),
        )
        logger.info(
            "Notified chat={} watch={} {} new show(s) in one digest",
            watch.user.chat_id,
            watch.id,
            len(shows),
        )


class LogNotifier:
    """Used when no bot token is configured (local development)."""

    async def notify(self, watch: Watch, shows: list[Show]) -> None:
        if not shows:
            return
        logger.info(
            "[dry-run] watch={} would notify {} new show(s): {}",
            watch.id,
            len(shows),
            [(s.theatre, s.time, s.format) for s in shows],
        )
