"""Notification-history persistence (duplicate prevention)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationHistory


async def known_hashes(session: AsyncSession, watch_id: int) -> set[str]:
    result = await session.execute(
        select(NotificationHistory.show_hash).where(NotificationHistory.watch_id == watch_id)
    )
    return set(result.scalars().all())


async def record(session: AsyncSession, watch_id: int, show_hash: str) -> None:
    session.add(NotificationHistory(watch_id=watch_id, show_hash=show_hash))
    await session.flush()
