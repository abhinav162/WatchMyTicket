from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User, Watch


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_watch(session_factory):
    """A user with one active watch for Spider-Man / Bengaluru / 2026-08-16, ScreenX only."""
    async with session_factory() as session:
        user = User(telegram_id=111, chat_id=222)
        session.add(user)
        await session.flush()
        watch = Watch(
            user_id=user.id,
            movie="Spider-Man",
            city="Bengaluru",
            date=date(2026, 8, 16),
            formats=["ScreenX"],
            languages=[],
            theatres=[],
        )
        session.add(watch)
        await session.commit()
        watch_id = watch.id
    return watch_id
