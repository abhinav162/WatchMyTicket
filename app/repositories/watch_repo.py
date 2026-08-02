"""Watch persistence."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Watch, WatchStatus
from app.schemas import WatchCreate, WatchUpdate


async def create(session: AsyncSession, user_id: int, data: WatchCreate) -> Watch:
    watch = Watch(
        user_id=user_id,
        movie=data.movie,
        city=data.city,
        date=data.date,
        formats=data.formats,
        languages=data.languages,
        theatres=data.theatres,
        status=WatchStatus.ACTIVE,
    )
    session.add(watch)
    await session.flush()
    return watch


async def get(session: AsyncSession, watch_id: int) -> Watch | None:
    result = await session.execute(
        select(Watch).where(Watch.id == watch_id).options(selectinload(Watch.user))
    )
    return result.scalar_one_or_none()


async def list_for_user(session: AsyncSession, user_id: int) -> list[Watch]:
    result = await session.execute(
        select(Watch).where(Watch.user_id == user_id).order_by(Watch.created_at)
    )
    return list(result.scalars().all())


async def list_active(session: AsyncSession) -> list[Watch]:
    result = await session.execute(
        select(Watch)
        .where(Watch.status == WatchStatus.ACTIVE)
        .options(selectinload(Watch.user))
        .order_by(Watch.id)
    )
    return list(result.scalars().all())


async def update(session: AsyncSession, watch: Watch, data: WatchUpdate) -> Watch:
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(watch, field, value)
    await session.flush()
    return watch


async def set_status(session: AsyncSession, watch: Watch, status: str) -> Watch:
    watch.status = status
    await session.flush()
    return watch


async def touch_last_checked(session: AsyncSession, watch: Watch) -> None:
    watch.last_checked = datetime.now(timezone.utc)
    await session.flush()


async def delete(session: AsyncSession, watch: Watch) -> None:
    await session.delete(watch)
    await session.flush()
