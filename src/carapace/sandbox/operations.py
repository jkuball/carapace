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


class InjectedCredentialFile(BaseModel):
    path: str
    vault_path: str
    name: str
    written_at: datetime = Field(default_factory=utc_now)
    removed_at: datetime | None = None


class PreparedTunnel(BaseModel):
    local_url: str
    remote_url: str
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None


class SandboxOperationLease(BaseModel):
    owner: str
    acquired_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


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
    injected_files: list[InjectedCredentialFile] = Field(default_factory=list)
    prepared_tunnels: list[PreparedTunnel] = Field(default_factory=list)
    temporary_domains: list[str] = Field(default_factory=list)
    lease: SandboxOperationLease | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    last_error: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.phase in {"completed", "failed", "interrupted"}
