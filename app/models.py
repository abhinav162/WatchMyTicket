"""Database models: User, Watch, NotificationHistory."""

from datetime import date, datetime, timezone

from sqlalchemy import JSON, BigInteger, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WatchStatus:
    ACTIVE = "active"
    PAUSED = "paused"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    watches: Mapped[list["Watch"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    movie: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(120))
    date: Mapped[date] = mapped_column(Date)
    formats: Mapped[list] = mapped_column(JSON, default=list)     # empty list = any format
    languages: Mapped[list] = mapped_column(JSON, default=list)   # empty list = any language
    theatres: Mapped[list] = mapped_column(JSON, default=list)    # empty list = any theatre
    status: Mapped[str] = mapped_column(String(16), default=WatchStatus.ACTIVE, index=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="watches")
    notifications: Mapped[list["NotificationHistory"]] = relationship(
        back_populates="watch", cascade="all, delete-orphan"
    )


class NotificationHistory(Base):
    __tablename__ = "notification_history"
    __table_args__ = (UniqueConstraint("watch_id", "show_hash", name="uq_watch_show_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    show_hash: Mapped[str] = mapped_column(String(64))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    watch: Mapped[Watch] = relationship(back_populates="notifications")
