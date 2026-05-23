from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    ToolCallPart,
    ToolReturnPart,
)

TURN_CANCELLED_TOOL_MESSAGE = "Tool call was canceled because the turn ended before it completed."


def complete_cancelled_model_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    completed = list(messages)
    pending_parts = []
    pending_index_by_id: dict[str, int] = {}

    for message in completed:
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if not isinstance(part, ToolCallPart | NativeToolCallPart):
                    continue
                tool_call_id = getattr(part, "tool_call_id", None)
                if isinstance(tool_call_id, str) and tool_call_id and tool_call_id not in pending_index_by_id:
                    pending_index_by_id[tool_call_id] = len(pending_parts)
                    pending_parts.append(part)
        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if not isinstance(part, ToolReturnPart | NativeToolReturnPart):
                    continue
                tool_call_id = getattr(part, "tool_call_id", None)
                if not isinstance(tool_call_id, str):
                    continue
                pending_index = pending_index_by_id.pop(tool_call_id, None)
                if pending_index is not None:
                    pending_parts[pending_index] = None

    synthetic_returns: list[ToolReturnPart | NativeToolReturnPart] = []
    for pending_part in pending_parts:
        if pending_part is None:
            continue
        if isinstance(pending_part, NativeToolCallPart):
            synthetic_returns.append(
                NativeToolReturnPart(
                    tool_name=pending_part.tool_name,
                    content=TURN_CANCELLED_TOOL_MESSAGE,
                    tool_call_id=pending_part.tool_call_id,
                    outcome="failed",
                    provider_name=pending_part.provider_name,
                    provider_details=pending_part.provider_details,
                )
            )
        else:
            synthetic_returns.append(
                ToolReturnPart(
                    tool_name=pending_part.tool_name,
                    content=TURN_CANCELLED_TOOL_MESSAGE,
                    tool_call_id=pending_part.tool_call_id,
                    outcome="failed",
                )
            )

    if synthetic_returns:
        completed.append(ModelRequest(parts=cast(Any, synthetic_returns)))
    return completed


def complete_cancelled_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed = list(events)
    pending_tool_calls: list[dict[str, Any] | None] = []
    pending_index_by_id: dict[str, int] = {}
    pending_indexes_by_tool: dict[str, list[int]] = {}

    for event in completed:
        role = event.get("role")
        tool = event.get("tool")
        tool_id = event.get("tool_id")

        if role == "tool_call" and isinstance(tool, str):
            pending_index = len(pending_tool_calls)
            pending_tool_calls.append(event)
            if isinstance(tool_id, str) and tool_id:
                pending_index_by_id[tool_id] = pending_index
            else:
                pending_indexes_by_tool.setdefault(tool, []).append(pending_index)
            continue

        if role != "tool_result":
            continue

        resolved_index: int | None = None
        if isinstance(tool_id, str) and tool_id:
            resolved_index = pending_index_by_id.pop(tool_id, None)
        elif isinstance(tool, str):
            queue = pending_indexes_by_tool.get(tool)
            if queue:
                resolved_index = queue.pop(0)
                if not queue:
                    pending_indexes_by_tool.pop(tool, None)

        if resolved_index is not None:
            pending_tool_calls[resolved_index] = None

    for pending_call in pending_tool_calls:
        if pending_call is None:
            continue
        synthetic_result: dict[str, Any] = {
            "role": "tool_result",
            "tool": pending_call.get("tool"),
            "result": TURN_CANCELLED_TOOL_MESSAGE,
            "exit_code": 130,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }
        tool_id = pending_call.get("tool_id")
        if isinstance(tool_id, str) and tool_id:
            synthetic_result["tool_id"] = tool_id
        completed.append(synthetic_result)

    return completed
