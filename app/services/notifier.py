"""Telegram notification delivery."""

from typing import Protocol

from loguru import logger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app.models import Watch
from app.schemas import Show


class Notifier(Protocol):
    async def notify(self, watch: Watch, show: Show) -> None: ...


def format_notification(show: Show) -> str:
    lines = [
        "🎬 <b>Ticket Found!</b>",
        "",
        f"<b>Movie:</b> {show.movie}",
        f"<b>Theatre:</b> {show.theatre}",
        f"<b>Date:</b> {show.date.strftime('%a, %d %b %Y')}",
        f"<b>Time:</b> {show.time}",
        f"<b>Format:</b> {show.format}",
    ]
    if show.language:
        lines.append(f"<b>Language:</b> {show.language}")
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, bot: Bot):
        self._bot = bot

    async def notify(self, watch: Watch, show: Show) -> None:
        keyboard = None
        if show.booking_url:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🎟 Open BookMyShow", url=show.booking_url)]]
            )
        await self._bot.send_message(
            chat_id=watch.user.chat_id,
            text=format_notification(show),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        logger.info("Notified chat={} watch={} show={} {}", watch.user.chat_id, watch.id, show.theatre, show.time)


class LogNotifier:
    """Used when no bot token is configured (local development)."""

    async def notify(self, watch: Watch, show: Show) -> None:
        logger.info("[dry-run] watch={} would notify: {} @ {} {}", watch.id, show.movie, show.theatre, show.time)
