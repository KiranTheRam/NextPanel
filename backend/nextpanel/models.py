import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    requests: Mapped[list["Request"]] = relationship(
        back_populates="user", foreign_keys="Request.user_id", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="sessions")


class MediaType(str, enum.Enum):
    MANGA = "manga"
    COMIC = "comic"


class RequestStatus(str, enum.Enum):
    PENDING = "pending"                          # waiting for admin decision
    DENIED = "denied"
    PROCESSING = "processing"                    # approved + added to the app, nothing on disk yet
    PARTIALLY_AVAILABLE = "partially_available"  # some chapters/issues downloaded
    AVAILABLE = "available"                      # every known chapter/issue downloaded
    FAILED = "failed"                            # approval could not be completed


class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (
        UniqueConstraint(
            "media_type", "provider", "provider_id", name="ux_requests_media_provider"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType))
    # metadata provider id the target app understands: MangaUpdates id for
    # manga, ComicVine volume id for comics
    provider: Mapped[str] = mapped_column(String)
    provider_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String)
    english_title: Mapped[str] = mapped_column(String, default="")
    alt_titles: Mapped[str] = mapped_column(Text, default="")  # newline-joined
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_url: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus), default=RequestStatus.PENDING)
    note: Mapped[str] = mapped_column(Text, default="")  # deny reason / failure detail
    # id of the series row created in mangarr/pullarr once approved
    remote_series_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downloaded_count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)

    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="requests", foreign_keys=[user_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])


class PushSubscription(Base):
    """A browser/device push endpoint belonging to a signed-in user."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String)
    auth: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
