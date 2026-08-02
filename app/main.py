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
    app.state.scheduler = scheduler

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
    scheduler = getattr(app.state, "scheduler", None)
    monitor = getattr(app.state, "monitor", None)
    job = scheduler.get_job("monitor") if scheduler else None
    return {
        "status": "ok",
        "scheduler_running": bool(scheduler and scheduler.running),
        "next_check_at": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "last_tick_at": monitor.last_tick_at.isoformat() if monitor and monitor.last_tick_at else None,
        "last_tick_duration_seconds": monitor.last_tick_duration if monitor else None,
        "last_tick_notifications": monitor.last_tick_notifications if monitor else None,
    }
