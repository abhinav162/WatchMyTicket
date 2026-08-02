"""Telegram bot: home menu, new-watch conversation, watch management.

Flow (PRD §8): /start → Home → New Watch → Movie → City → Date → Format
→ Language → Theatre → Confirmation → Monitoring.
"""

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.database import session_scope
from app.models import Watch, WatchStatus
from app.repositories import user_repo, watch_repo
from app.schemas import WatchCreate, WatchUpdate
from app.utils.text import parse_list, parse_user_date

MOVIE, CITY, DATE, FORMAT, LANGUAGE, THEATRE, CONFIRM = range(7)

FORMAT_OPTIONS = ["2D", "3D", "IMAX", "ScreenX", "4DX", "Dolby"]

HELP_TEXT = (
    "🎬 <b>Ticket Watcher</b>\n\n"
    "I watch BookMyShow for you and ping you the moment matching shows appear.\n\n"
    "<b>Commands</b>\n"
    "/start — home menu\n"
    "/new — create a new watch\n"
    "/watches — list your watches\n"
    "/cancel — cancel the current action\n\n"
    "Create a watch with a movie, city and date. Format, language and theatre "
    "are optional filters — leave them as <i>Any</i> to be notified about everything."
)


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ New Watch", callback_data="menu:new")],
            [InlineKeyboardButton("📋 My Watches", callback_data="menu:watches")],
            [
                InlineKeyboardButton("⚙ Settings", callback_data="menu:settings"),
                InlineKeyboardButton("❓ Help", callback_data="menu:help"),
            ],
        ]
    )


def watch_summary(watch: Watch) -> str:
    fmt = ", ".join(watch.formats) if watch.formats else "Any format"
    lang = ", ".join(watch.languages) if watch.languages else "Any language"
    theatre = ", ".join(watch.theatres) if watch.theatres else "Any theatre"
    status = "▶️ active" if watch.status == WatchStatus.ACTIVE else "⏸ paused"
    return (
        f"🎬 <b>{watch.movie}</b>\n"
        f"📍 {watch.city} · 📅 {watch.date.strftime('%a, %d %b %Y')}\n"
        f"🎞 {fmt} · 🗣 {lang}\n"
        f"🏢 {theatre}\n"
        f"{status}"
    )


def watch_buttons(watch: Watch) -> InlineKeyboardMarkup:
    toggle = (
        InlineKeyboardButton("⏸ Pause", callback_data=f"watch:pause:{watch.id}")
        if watch.status == WatchStatus.ACTIVE
        else InlineKeyboardButton("▶️ Resume", callback_data=f"watch:resume:{watch.id}")
    )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✏️ Edit", callback_data=f"watch:edit:{watch.id}"),
                toggle,
                InlineKeyboardButton("🗑 Delete", callback_data=f"watch:delete:{watch.id}"),
            ]
        ]
    )


# ---------------------------------------------------------------- home menu


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    async with session_scope() as session:
        await user_repo.get_or_create(session, telegram_id=user.id, chat_id=chat.id)
        await session.commit()
    await update.effective_message.reply_text(
        f"Welcome, {user.first_name}! 👋\n\nWhat would you like to do?",
        reply_markup=home_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]

    if action == "watches":
        await send_watch_list(update, context)
    elif action == "help":
        await query.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)
    elif action == "settings":
        await query.message.reply_text(
            "⚙ Settings\n\nNothing to configure yet — checks run every minute automatically."
        )


# ------------------------------------------------------------ watch listing


async def send_watch_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    async with session_scope() as session:
        user = await user_repo.get_by_telegram_id(session, update.effective_user.id)
        watches = await watch_repo.list_for_user(session, user.id) if user else []

    if not watches:
        await message.reply_text(
            "You have no watches yet. Create one!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("➕ New Watch", callback_data="menu:new")]]
            ),
        )
        return

    await message.reply_text(f"📋 Your watches ({len(watches)}):")
    for watch in watches:
        await message.reply_text(
            watch_summary(watch),
            parse_mode=ParseMode.HTML,
            reply_markup=watch_buttons(watch),
        )


async def watches_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_watch_list(update, context)


async def watch_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, action, raw_id = query.data.split(":")
    watch_id = int(raw_id)

    async with session_scope() as session:
        watch = await watch_repo.get(session, watch_id)
        if watch is None or watch.user.telegram_id != update.effective_user.id:
            await query.edit_message_text("This watch no longer exists.")
            return

        if action == "delete":
            await watch_repo.delete(session, watch)
            await session.commit()
            await query.edit_message_text("🗑 Watch deleted. You won't receive further notifications.")
            return

        status = WatchStatus.PAUSED if action == "pause" else WatchStatus.ACTIVE
        await watch_repo.set_status(session, watch, status)
        await session.commit()
        await query.edit_message_text(
            watch_summary(watch), parse_mode=ParseMode.HTML, reply_markup=watch_buttons(watch)
        )


# ------------------------------------------------- new-watch conversation


async def new_watch_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text(
        "🎬 Which movie (or event) should I watch?\n\nSend /cancel anytime to abort."
    )
    return MOVIE


async def edit_watch_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    watch_id = int(query.data.split(":")[2])

    async with session_scope() as session:
        watch = await watch_repo.get(session, watch_id)
        if watch is None or watch.user.telegram_id != update.effective_user.id:
            await query.message.reply_text("This watch no longer exists.")
            return ConversationHandler.END

    context.user_data.clear()
    context.user_data["edit_watch_id"] = watch_id
    await query.message.reply_text(
        f"✏️ Editing <b>{watch.movie}</b> — I'll re-ask each step.\n\n"
        "🎬 Which movie (or event) should I watch?",
        parse_mode=ParseMode.HTML,
    )
    return MOVIE


async def movie_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["movie"] = update.message.text.strip()
    await update.message.reply_text("📍 Which city? (e.g. Bengaluru, Mumbai, Delhi)")
    return CITY


async def city_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["city"] = update.message.text.strip()
    await update.message.reply_text("📅 Which date? (e.g. 16 Aug or 2026-08-16)")
    return DATE


async def date_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["date"] = parse_user_date(update.message.text)
    except (ValueError, OverflowError):
        await update.message.reply_text(
            "I couldn't understand that date (or it's in the past). "
            "Try something like <b>16 Aug</b> or <b>2026-08-16</b>.",
            parse_mode=ParseMode.HTML,
        )
        return DATE
    context.user_data["formats"] = set()
    await update.message.reply_text(
        "🎞 Pick the formats you care about, then hit Done:",
        reply_markup=format_keyboard(set()),
    )
    return FORMAT


def format_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(FORMAT_OPTIONS), 3):
        rows.append(
            [
                InlineKeyboardButton(
                    ("✅ " if fmt in selected else "") + fmt, callback_data=f"fmt:{fmt}"
                )
                for fmt in FORMAT_OPTIONS[i : i + 3]
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("🌐 Any format", callback_data="fmt:any"),
            InlineKeyboardButton("✔️ Done", callback_data="fmt:done"),
        ]
    )
    return InlineKeyboardMarkup(rows)


async def format_toggled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    selected: set[str] = context.user_data.setdefault("formats", set())

    if choice == "any":
        selected.clear()
        choice = "done"
    if choice == "done":
        label = ", ".join(sorted(selected)) if selected else "Any format"
        await query.edit_message_text(f"🎞 Format: {label}")
        await query.message.reply_text(
            "🗣 Which language(s)? Comma-separated (e.g. English, Hindi) — or 'any'.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🌐 Any language", callback_data="lang:any")]]
            ),
        )
        return LANGUAGE

    if choice in selected:
        selected.discard(choice)
    else:
        selected.add(choice)
    await query.edit_message_reply_markup(reply_markup=format_keyboard(selected))
    return FORMAT


async def language_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        context.user_data["languages"] = []
        message = update.callback_query.message
    else:
        context.user_data["languages"] = parse_list(update.message.text)
        message = update.message
    await message.reply_text(
        "🏢 Any specific theatre(s)? Comma-separated (e.g. PVR Vega) — or 'any' "
        "to search every theatre.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🌐 Any theatre", callback_data="theatre:any")]]
        ),
    )
    return THEATRE


async def theatre_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        context.user_data["theatres"] = []
        message = update.callback_query.message
    else:
        context.user_data["theatres"] = parse_list(update.message.text)
        message = update.message

    data = context.user_data
    formats = sorted(data.get("formats") or [])
    summary = (
        "Please confirm your watch:\n\n"
        f"🎬 <b>{data['movie']}</b>\n"
        f"📍 {data['city']} · 📅 {data['date'].strftime('%a, %d %b %Y')}\n"
        f"🎞 {', '.join(formats) if formats else 'Any format'}\n"
        f"🗣 {', '.join(data['languages']) if data['languages'] else 'Any language'}\n"
        f"🏢 {', '.join(data['theatres']) if data['theatres'] else 'Any theatre'}"
    )
    await message.reply_text(
        summary,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Confirm", callback_data="confirm:yes"),
                    InlineKeyboardButton("❌ Cancel", callback_data="confirm:no"),
                ]
            ]
        ),
    )
    return CONFIRM


async def confirm_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data != "confirm:yes":
        context.user_data.clear()
        await query.edit_message_text("❌ Cancelled. Nothing was saved.")
        return ConversationHandler.END

    data = context.user_data
    payload = WatchCreate(
        movie=data["movie"],
        city=data["city"],
        date=data["date"],
        formats=sorted(data.get("formats") or []),
        languages=data.get("languages") or [],
        theatres=data.get("theatres") or [],
    )

    async with session_scope() as session:
        user = await user_repo.get_or_create(
            session, telegram_id=update.effective_user.id, chat_id=update.effective_chat.id
        )
        edit_id = data.get("edit_watch_id")
        if edit_id:
            watch = await watch_repo.get(session, edit_id)
            if watch is not None and watch.user_id == user.id:
                await watch_repo.update(session, watch, WatchUpdate(**payload.model_dump()))
            else:
                watch = await watch_repo.create(session, user.id, payload)
        else:
            watch = await watch_repo.create(session, user.id, payload)
        await session.commit()
        logger.info("Watch {} saved for telegram user {}", watch.id, update.effective_user.id)

    context.user_data.clear()
    await query.edit_message_text(
        "✅ <b>Monitoring started!</b>\n\n"
        "I check every minute and will message you the moment matching shows appear. 🍿",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("❌ Cancelled.", reply_markup=home_keyboard())
    return ConversationHandler.END


# ---------------------------------------------------------------- assembly


def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()

    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("new", new_watch_start),
            CallbackQueryHandler(new_watch_start, pattern=r"^menu:new$"),
            CallbackQueryHandler(edit_watch_start, pattern=r"^watch:edit:\d+$"),
        ],
        states={
            MOVIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, movie_received)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city_received)],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date_received)],
            FORMAT: [CallbackQueryHandler(format_toggled, pattern=r"^fmt:")],
            LANGUAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, language_received),
                CallbackQueryHandler(language_received, pattern=r"^lang:any$"),
            ],
            THEATRE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, theatre_received),
                CallbackQueryHandler(theatre_received, pattern=r"^theatre:any$"),
            ],
            CONFIRM: [CallbackQueryHandler(confirm_received, pattern=r"^confirm:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("watches", watches_command))
    application.add_handler(conversation)
    application.add_handler(CallbackQueryHandler(menu_router, pattern=r"^menu:"))
    application.add_handler(
        CallbackQueryHandler(watch_action, pattern=r"^watch:(pause|resume|delete):\d+$")
    )
    return application
