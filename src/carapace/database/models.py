from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, JsonType, UtcDateTime

# SQLite only autoincrements an "INTEGER PRIMARY KEY" rowid alias; a BIGINT primary key
# does not autoincrement there. Use a 64-bit type on real databases, plain INTEGER on SQLite.
AutoBigInt = BigInteger().with_variant(Integer(), "sqlite")


class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(256), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    display_name: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    roles: Mapped[list[str]] = mapped_column(JsonType, default=list)
    config: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
    password_changed_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AuthSessionRow(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    user_agent: Mapped[str] = mapped_column(Text, default="")


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    name: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)


class NotificationSubscriptionRow(Base):
    __tablename__ = "notification_subscriptions"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)

    __table_args__ = (UniqueConstraint("user", "endpoint", name="uq_subscription_user_endpoint"),)


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), index=True)
    channel_type: Mapped[str] = mapped_column(String(64), index=True)
    channel_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_active: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    state: Mapped[dict[str, Any]] = mapped_column(JsonType)
    sandbox_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)

    __table_args__ = (Index("ix_sessions_channel", "channel_type", "channel_ref"),)


class SessionHistoryRow(Base):
    __tablename__ = "session_history"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    messages: Mapped[list[Any]] = mapped_column(JsonType, default=list)


class SessionEventRow(Base):
    __tablename__ = "session_events"

    id: Mapped[int] = mapped_column(AutoBigInt, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)

    __table_args__ = (Index("ix_session_events_session_seq", "session_id", "seq"),)


class SessionUsageRow(Base):
    __tablename__ = "session_usage"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    tracker: Mapped[dict[str, Any]] = mapped_column(JsonType)


class SessionLlmRequestRow(Base):
    __tablename__ = "session_llm_requests"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    log: Mapped[dict[str, Any]] = mapped_column(JsonType)


class SessionAuditRow(Base):
    __tablename__ = "session_audit"

    id: Mapped[int] = mapped_column(AutoBigInt, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)


class SandboxTokenRow(Base):
    __tablename__ = "sandbox_tokens"

    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
