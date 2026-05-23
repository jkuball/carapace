from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from carapace.session.state import SessionRuntimePhase

SessionEventType = Literal[
    "turn_submitted",
    "turn_queued",
    "turn_lease_acquired",
    "turn_started",
    "turn_phase_changed",
    "user_message_recorded",
    "token_emitted",
    "thinking_emitted",
    "llm_request_started",
    "llm_request_finished",
    "tool_approval_requested",
    "tool_approval_resolved",
    "escalation_requested",
    "escalation_resolved",
    "tool_call_started",
    "tool_call_completed",
    "tool_call_failed",
    "tool_call_cancelled",
    "turn_finalized",
    "turn_failed",
    "turn_cancelled",
    "turn_interrupted",
    "turn_recovered",
    "session_command_applied",
    "session_command_rejected",
]


def _event_id() -> str:
    return secrets.token_hex(12)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class SessionRuntimeEvent(BaseModel):
    type: SessionEventType
    session_id: str
    event_id: str = Field(default_factory=_event_id)
    occurred_at: datetime = Field(default_factory=_utc_now)
    turn_id: str | None = None
    command_id: str | None = None
    from_phase: SessionRuntimePhase | None = None
    to_phase: SessionRuntimePhase | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
