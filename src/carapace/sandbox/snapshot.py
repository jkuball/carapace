from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

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
