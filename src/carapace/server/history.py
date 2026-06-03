from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ThinkingPart, ToolCallPart, UserPromptPart

from ..auth import UserIdentity
from ..models.tooling import normalize_tool_call_args
from ..security.context import ApprovalSource, ApprovalVerdict
from ..ws_models import Attachment, FinalStatus
from .auth import verify_token
from .state import server_module

server = server_module()

router = APIRouter()

_HistoryRole = Literal[
    "user",
    "assistant",
    "thinking",
    "tool_call",
    "tool_result",
    "command",
    "proxy_approval",
    "domain_access_approval",
    "approval_request",
    "approval_response",
    "git_push",
    "git_push_approval",
    "credential_approval",
]


class HistoryMessage(BaseModel):
    role: _HistoryRole
    content: str = ""
    final_status: FinalStatus | None = None
    event_index: int | None = None
    reasoning_duration_ms: int | None = None
    reasoning_tokens: int | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    detail: str | None = None
    contexts: list[str] | None = None
    approval_source: ApprovalSource | None = None
    approval_verdict: ApprovalVerdict | None = None
    approval_explanation: str | None = None
    result: str | None = None
    command: str | None = None
    data: Any = None
    request_id: str | None = None
    domain: str | None = None
    decision: str | None = None
    tool_call_id: str | None = None
    decision_source: ApprovalSource | None = None
    message: str | None = None
    explanation: str | None = None
    risk_level: str | None = None
    ref: str | None = None
    changed_files: list[str] | None = None
    vault_paths: list[str] | None = None
    names: list[str] | None = None
    descriptions: list[str] | None = None
    skill_name: str | None = None
    tool_id: str | None = None
    parent_tool_id: str | None = None
    exit_code: int | None = None
    attachments: list[Attachment] | None = None

    @model_validator(mode="after")
    def _contexts_from_args_when_missing(self) -> Self:
        """Legacy events only stored contexts inside ``args``; expose them top-level."""
        if self.role != "tool_call" or self.contexts is not None:
            return self
        raw = self.args.get("contexts") if self.args else None
        if isinstance(raw, list):
            return self.model_copy(update={"contexts": list(raw)})
        return self


@router.get("/sessions/{session_id}/history", response_model=list[HistoryMessage])
async def get_session_history(
    session_id: str,
    user: Annotated[UserIdentity, Depends(verify_token)],
    limit: Annotated[int, Query()] = -1,
) -> list[HistoryMessage]:
    if server._engine.session_mgr.load_state(session_id) is None or not server._engine.session_mgr.is_owned_by(
        session_id, user.username
    ):
        raise HTTPException(status_code=404, detail="Session not found")

    events = server._engine.session_mgr.load_events(session_id)
    result = (
        [
            HistoryMessage.model_validate(
                {
                    **event,
                    "args": normalize_tool_call_args(event.get("tool", ""), event["args"])
                    if isinstance(event.get("args"), dict)
                    else event.get("args"),
                    "event_index": index,
                }
            )
            for index, event in enumerate(events)
        ]
        if events
        else [
            HistoryMessage.model_validate({**message.model_dump(mode="python"), "event_index": index})
            for index, message in enumerate(_history_from_messages(session_id))
        ]
    )

    if limit > 0:
        result = result[-limit:]
    return result


def _history_from_messages(session_id: str) -> list[HistoryMessage]:
    """Fallback: build history from Pydantic AI messages for sessions without events."""
    raw_messages = server._engine.session_mgr.load_history(session_id)
    result: list[HistoryMessage] = []
    for msg in raw_messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    result.append(HistoryMessage(role="user", content=part.content))
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    args = normalize_tool_call_args(part.tool_name, part.args) if isinstance(part.args, dict) else {}
                    ctx_raw = args.get("contexts")
                    contexts = list(ctx_raw) if isinstance(ctx_raw, list) else None
                    result.append(
                        HistoryMessage(
                            role="tool_call",
                            content="",
                            tool=part.tool_name,
                            args=args,
                            contexts=contexts,
                        )
                    )
                elif isinstance(part, TextPart):
                    result.append(HistoryMessage(role="assistant", content=part.content))
                elif isinstance(part, ThinkingPart) and part.content:
                    result.append(HistoryMessage(role="thinking", content=part.content))
    return result
