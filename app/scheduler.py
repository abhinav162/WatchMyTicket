"""Background scheduler: runs the monitor every CHECK_INTERVAL_SECONDS."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.services.monitor import MonitorService


def create_scheduler(monitor: MonitorService) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        monitor.run_once,
        trigger="interval",
        seconds=settings.check_interval_seconds,
        id="monitor",
        max_instances=1,   # never overlap two monitoring cycles
        coalesce=True,     # collapse missed runs into one
    )
    return scheduler
