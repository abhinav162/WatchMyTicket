"""Application entrypoint: FastAPI + Telegram bot polling + background scheduler."""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.config import settings
from app.database import init_db
from app.routers import watch as watch_router
from app.routers.telegram import build_application
from app.scheduler import create_scheduler
from app.scrapers import get_scraper
from app.services.monitor import MonitorService
from app.services.notifier import LogNotifier, TelegramNotifier

logger.remove()
logger.add(sys.stderr, level=settings.log_level.upper(), backtrace=False, diagnose=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    application = None
    if settings.telegram_bot_token:
        application = build_application(settings.telegram_bot_token)
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        notifier = TelegramNotifier(application.bot)
        logger.info("Telegram bot polling started")
    else:
        notifier = LogNotifier()
        logger.warning("TELEGRAM_BOT_TOKEN not set — running without the bot; notifications are logged only")

    monitor = MonitorService(scraper=get_scraper(), notifier=notifier)
    scheduler = create_scheduler(monitor)
    scheduler.start()
    logger.info("Scheduler started (every {}s, scraper={})", settings.check_interval_seconds, settings.scraper)

    app.state.monitor = monitor

    yield

    scheduler.shutdown(wait=False)
    if application is not None:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
    logger.info("Shutdown complete")


app = FastAPI(title="Ticket Watcher", version="1.0.0", lifespan=lifespan)
app.include_router(watch_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
