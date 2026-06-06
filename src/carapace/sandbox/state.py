from __future__ import annotations

from loguru import logger

from ..database.engine import SessionFactory
from ..database.models import SessionRow
from .snapshot import SessionSandboxSnapshot

__all__ = ["SessionSandboxSnapshot", "clear_sandbox_snapshot", "load_sandbox_snapshot", "save_sandbox_snapshot"]


def load_sandbox_snapshot(session_factory: SessionFactory, session_id: str) -> SessionSandboxSnapshot | None:
    with session_factory() as db:
        row = db.get(SessionRow, session_id)
        return row.sandbox_snapshot if row is not None else None


def save_sandbox_snapshot(session_factory: SessionFactory, session_id: str, snapshot: SessionSandboxSnapshot) -> None:
    with session_factory.begin() as db:
        row = db.get(SessionRow, session_id)
        if row is None:
            logger.warning(f"Cannot persist sandbox snapshot: session {session_id} not found")
            return
        row.sandbox_snapshot = snapshot


def clear_sandbox_snapshot(session_factory: SessionFactory, session_id: str) -> None:
    with session_factory.begin() as db:
        row = db.get(SessionRow, session_id)
        if row is not None:
            row.sandbox_snapshot = None
