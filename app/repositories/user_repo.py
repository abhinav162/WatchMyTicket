"""User persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_or_create(session: AsyncSession, telegram_id: int, chat_id: int) -> User:
    user = await get_by_telegram_id(session, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id, chat_id=chat_id)
        session.add(user)
        await session.flush()
    elif user.chat_id != chat_id:
        user.chat_id = chat_id
        await session.flush()
    return user
