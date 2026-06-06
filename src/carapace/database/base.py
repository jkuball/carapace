from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, TypeDecorator
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# JSON column type that maps to JSONB on PostgreSQL and JSON/TEXT elsewhere (SQLite).
JsonType = JSON().with_variant(postgresql.JSONB(), "postgresql")


class UtcDateTime(TypeDecorator):
    """Timezone-aware datetime stored as UTC.

    PostgreSQL keeps tz info; SQLite drops it. This decorator normalizes every
    value to UTC on the way in and re-attaches UTC on the way out so callers
    always receive tz-aware datetimes regardless of backend.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
