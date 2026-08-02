"""REST API for watch management (useful for debugging and future dashboards)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import WatchStatus
from app.repositories import user_repo, watch_repo
from app.schemas import WatchCreate, WatchOut, WatchUpdate

router = APIRouter(prefix="/watches", tags=["watches"])


@router.get("", response_model=list[WatchOut])
async def list_watches(telegram_id: int, session: AsyncSession = Depends(get_db)):
    user = await user_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        return []
    return await watch_repo.list_for_user(session, user.id)


@router.post("", response_model=WatchOut, status_code=201)
async def create_watch(
    telegram_id: int,
    chat_id: int,
    payload: WatchCreate,
    session: AsyncSession = Depends(get_db),
):
    user = await user_repo.get_or_create(session, telegram_id=telegram_id, chat_id=chat_id)
    watch = await watch_repo.create(session, user.id, payload)
    await session.commit()
    return watch


@router.patch("/{watch_id}", response_model=WatchOut)
async def update_watch(watch_id: int, payload: WatchUpdate, session: AsyncSession = Depends(get_db)):
    watch = await watch_repo.get(session, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    if payload.status is not None and payload.status not in (WatchStatus.ACTIVE, WatchStatus.PAUSED):
        raise HTTPException(status_code=422, detail="status must be 'active' or 'paused'")
    watch = await watch_repo.update(session, watch, payload)
    await session.commit()
    return watch


@router.delete("/{watch_id}", status_code=204)
async def delete_watch(watch_id: int, session: AsyncSession = Depends(get_db)):
    watch = await watch_repo.get(session, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    await watch_repo.delete(session, watch)
    await session.commit()
