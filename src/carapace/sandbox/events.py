from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from carapace.sandbox.operations import SandboxOperationPhase
from carapace.sandbox.state import SandboxRuntimePhase

SandboxEventType = Literal[
    "sandbox_ensure_requested",
    "sandbox_starting",
    "sandbox_created",
    "sandbox_attached",
    "sandbox_resumed",
    "sandbox_ready",
    "sandbox_suspending",
    "sandbox_suspended",
    "sandbox_resetting",
    "sandbox_reset",
    "sandbox_destroying",
    "sandbox_destroyed",
    "sandbox_snapshot_refreshed",
    "sandbox_lifecycle_failed",
    "sandbox_recovered",
    "sandbox_operation_queued",
    "sandbox_operation_lock_acquired",
    "sandbox_operation_phase_changed",
    "sandbox_operation_context_prepared",
    "credential_files_injected",
    "tunnels_prepared",
    "sandbox_command_started",
    "sandbox_command_output_observed",
    "sandbox_command_completed",
    "sandbox_command_failed",
    "sandbox_operation_cleanup_started",
    "credential_files_removed",
    "tunnels_closed",
    "sandbox_operation_completed",
    "sandbox_operation_failed",
    "sandbox_operation_interrupted",
]


def _event_id() -> str:
    return secrets.token_hex(12)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class SandboxRuntimeEvent(BaseModel):
    type: SandboxEventType
    session_id: str
    event_id: str = Field(default_factory=_event_id)
    occurred_at: datetime = Field(default_factory=_utc_now)
    operation_id: str | None = None
    from_runtime_phase: SandboxRuntimePhase | None = None
    to_runtime_phase: SandboxRuntimePhase | None = None
    from_operation_phase: SandboxOperationPhase | None = None
    to_operation_phase: SandboxOperationPhase | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
