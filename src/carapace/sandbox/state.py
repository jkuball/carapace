from __future__ import annotations

from datetime import datetime

from loguru import logger
from pydantic import BaseModel

from ..database.engine import SessionFactory
from ..database.models import SessionRow
from .runtime import SandboxRuntimeKind, SandboxStatus


class SessionSandboxSnapshot(BaseModel):
    exists: bool = False
    runtime: SandboxRuntimeKind | None = None
    status: SandboxStatus = "missing"
    sandbox_id: str | None = None
    resource_id: str | None = None
    resource_kind: str | None = None
    storage_present: bool = False
    provisioned_bytes: int | None = None
    last_measured_used_bytes: int | None = None
    last_measured_at: datetime | None = None
    updated_at: datetime | None = None
    last_error: str | None = None


def load_sandbox_snapshot(session_factory: SessionFactory, session_id: str) -> SessionSandboxSnapshot | None:
    with session_factory() as db:
        row = db.get(SessionRow, session_id)
        if row is None or not row.sandbox_snapshot:
            return None
        return SessionSandboxSnapshot.model_validate(row.sandbox_snapshot)


def save_sandbox_snapshot(session_factory: SessionFactory, session_id: str, snapshot: SessionSandboxSnapshot) -> None:
    data = snapshot.model_dump(mode="json")
    with session_factory.begin() as db:
        row = db.get(SessionRow, session_id)
        if row is None:
            logger.warning(f"Cannot persist sandbox snapshot: session {session_id} not found")
            return
        row.sandbox_snapshot = data


def clear_sandbox_snapshot(session_factory: SessionFactory, session_id: str) -> None:
    with session_factory.begin() as db:
        row = db.get(SessionRow, session_id)
        if row is not None:
            row.sandbox_snapshot = None
