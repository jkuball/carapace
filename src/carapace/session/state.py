from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

SessionRuntimePhase = Literal[
    "idle",
    "queued",
    "preparing_turn",
    "running_llm",
    "waiting_tool_approval",
    "waiting_escalation",
    "running_tool",
    "cancelling",
    "finalizing",
    "finalizing_failed",
    "finalizing_cancelled",
    "interrupted",
    "failed",
    "cancelled",
]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class SessionRuntime(BaseModel):
    session_id: str
    phase: SessionRuntimePhase = "idle"
    version: int = 0
    current_turn_id: str | None = None
    previous_phase: SessionRuntimePhase | None = None
    pending_approval_ids: list[str] = Field(default_factory=list)
    pending_escalation_ids: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)
    last_error: str | None = None

    @property
    def is_active(self) -> bool:
        return self.phase not in {"idle", "failed", "cancelled"}

    @property
    def is_waiting_for_user(self) -> bool:
        return self.phase in {"waiting_tool_approval", "waiting_escalation"}
