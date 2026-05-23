from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SessionCommandSource = Literal["websocket", "matrix", "job", "api", "system", "recovery"]
SessionCommandType = Literal[
    "submit_turn",
    "cancel_turn",
    "resolve_tool_approval",
    "resolve_escalation",
    "retry_latest_turn",
    "reset_to_turn",
    "apply_session_command",
    "recover_session",
]


def _command_id() -> str:
    return secrets.token_hex(12)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class SessionCommandBase(BaseModel):
    session_id: str
    command_id: str = Field(default_factory=_command_id)
    source: SessionCommandSource = "api"
    created_at: datetime = Field(default_factory=_utc_now)
    idempotency_key: str | None = None
    turn_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionCommand(SessionCommandBase):
    type: SessionCommandType


class SubmitTurnCommand(SessionCommandBase):
    type: Literal["submit_turn"] = "submit_turn"
    source: SessionCommandSource = "websocket"
    message: str


class CancelTurnCommand(SessionCommandBase):
    type: Literal["cancel_turn"] = "cancel_turn"


class ResolveToolApprovalCommand(SessionCommandBase):
    type: Literal["resolve_tool_approval"] = "resolve_tool_approval"
    request_id: str
    decisions: dict[str, bool]


class ResolveEscalationCommand(SessionCommandBase):
    type: Literal["resolve_escalation"] = "resolve_escalation"
    request_id: str
    decision: Literal["allow", "deny"]
    message: str | None = None


class RetryLatestTurnCommand(SessionCommandBase):
    type: Literal["retry_latest_turn"] = "retry_latest_turn"


class ResetToTurnCommand(SessionCommandBase):
    type: Literal["reset_to_turn"] = "reset_to_turn"
    turn_index: int


class ApplySessionCommandCommand(SessionCommandBase):
    type: Literal["apply_session_command"] = "apply_session_command"
    command: str


class RecoverSessionCommand(SessionCommandBase):
    type: Literal["recover_session"] = "recover_session"
    policy: Literal["repair_as_cancelled", "mark_failed", "retry_from_checkpoint"] = "repair_as_cancelled"
