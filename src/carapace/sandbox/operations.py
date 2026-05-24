from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

SandboxOperationPhase = Literal[
    "queued",
    "claiming_lock",
    "ensuring_sandbox",
    "running_skill_setup",
    "preparing_context",
    "injecting_credentials",
    "preparing_tunnels",
    "running_command",
    "recovering_container",
    "collecting_notifications",
    "cleaning_up",
    "completed",
    "failed",
    "interrupted",
]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class SandboxOperation(BaseModel):
    operation_id: str
    session_id: str
    phase: SandboxOperationPhase = "queued"
    version: int = 0
    tool_call_id: str | None = None
    parent_tool_id: str | None = None
    command: str
    cwd: str | None = None
    contexts: list[str] = Field(default_factory=list)
    temporary_domains: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    exit_code: int | None = None
    output: str | None = None
    last_error: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.phase in {"completed", "failed", "interrupted"}
