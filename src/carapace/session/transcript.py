from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

TURN_CANCELLED_TOOL_MESSAGE = "Tool call was canceled because the turn ended before it completed."


@dataclass(frozen=True, slots=True)
class CompletedEventTurn:
    start_event_index: int
    end_event_index: int
    user_content: str


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


def truncate_incomplete_model_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    pending_tool_calls: set[str] = set()
    safe_prefix_end = 0

    for index, message in enumerate(messages):
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ToolCallPart | NativeToolCallPart):
                    tool_call_id = getattr(part, "tool_call_id", None)
                    if isinstance(tool_call_id, str) and tool_call_id:
                        pending_tool_calls.add(tool_call_id)
        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart | NativeToolReturnPart):
                    tool_call_id = getattr(part, "tool_call_id", None)
                    if isinstance(tool_call_id, str) and tool_call_id in pending_tool_calls:
                        pending_tool_calls.remove(tool_call_id)

        if not pending_tool_calls:
            safe_prefix_end = index + 1

    return messages[:safe_prefix_end]


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


def truncate_incomplete_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools_with_results = {
        event.get("tool")
        for event in events
        if event.get("role") == "tool_result" and isinstance(event.get("tool"), str)
    }
    pending_by_tool: dict[str, int] = {}
    safe_prefix_end = 0

    for index, event in enumerate(events):
        role = event.get("role")
        tool = event.get("tool")
        if not isinstance(tool, str):
            tool = ""

        if role == "tool_call" and tool in tools_with_results:
            pending_by_tool[tool] = pending_by_tool.get(tool, 0) + 1
        elif role == "tool_result" and tool in tools_with_results:
            outstanding = pending_by_tool.get(tool, 0)
            if outstanding > 0:
                if outstanding == 1:
                    pending_by_tool.pop(tool, None)
                else:
                    pending_by_tool[tool] = outstanding - 1

        if not pending_by_tool:
            safe_prefix_end = index + 1

    return events[:safe_prefix_end]


def completed_event_turns(events: list[dict[str, Any]]) -> list[CompletedEventTurn]:
    turns: list[CompletedEventTurn] = []
    start_event_index: int | None = None
    user_content: str | None = None

    for index, event in enumerate(events):
        role = event.get("role")
        if role == "user" and isinstance(content := event.get("content"), str) and not content.startswith("/"):
            start_event_index = index
            user_content = content
        elif role == "assistant" and start_event_index is not None and user_content is not None:
            turns.append(
                CompletedEventTurn(
                    start_event_index=start_event_index,
                    end_event_index=index,
                    user_content=user_content,
                )
            )
            start_event_index = None
            user_content = None

    return turns


def completed_model_turn_end_indexes(messages: list[ModelMessage]) -> list[int]:
    turn_end_indexes: list[int] = []
    current_turn_start: int | None = None

    for index, message in enumerate(messages):
        has_user_prompt = isinstance(message, ModelRequest) and any(
            isinstance(part, UserPromptPart) and isinstance(part.content, str) for part in message.parts
        )
        if not has_user_prompt:
            continue
        if (
            current_turn_start is not None
            and index - 1 > current_turn_start
            and is_terminal_history_message(messages[index - 1])
        ):
            turn_end_indexes.append(index - 1)
        current_turn_start = index

    if (
        current_turn_start is not None
        and len(messages) - 1 > current_turn_start
        and is_terminal_history_message(messages[-1])
    ):
        turn_end_indexes.append(len(messages) - 1)

    return turn_end_indexes


def is_terminal_history_message(message: ModelMessage) -> bool:
    if isinstance(message, ModelResponse):
        return True
    if not isinstance(message, ModelRequest):
        return False
    return any(
        isinstance(part, ToolReturnPart) and part.tool_name in {"task_done", "task_failed"} for part in message.parts
    )


def history_for_completed_turn_count(messages: list[ModelMessage], turn_count: int) -> list[ModelMessage]:
    if turn_count <= 0:
        return []

    turn_end_indexes = completed_model_turn_end_indexes(messages)
    if not turn_end_indexes:
        return []

    capped_turn_count = min(turn_count, len(turn_end_indexes))
    return messages[: turn_end_indexes[capped_turn_count - 1] + 1]


def normalize_unattended_output_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Rewrite unattended task output tools into plain assistant text for attended forks."""
    normalized: list[ModelMessage] = []
    index = 0

    while index < len(messages):
        current = messages[index]
        next_message = messages[index + 1] if index + 1 < len(messages) else None

        if isinstance(current, ModelResponse):
            tool_call_parts = [part for part in current.parts if isinstance(part, ToolCallPart)]
            other_parts = [part for part in current.parts if not isinstance(part, ToolCallPart | ThinkingPart)]
            if (
                len(tool_call_parts) == 1
                and not other_parts
                and tool_call_parts[0].tool_name in {"task_done", "task_failed"}
                and isinstance(next_message, ModelRequest)
                and any(
                    isinstance(part, ToolReturnPart)
                    and part.tool_name == tool_call_parts[0].tool_name
                    and part.tool_call_id == tool_call_parts[0].tool_call_id
                    for part in next_message.parts
                )
            ):
                content = task_output_text(tool_call_parts[0])
                if content is not None:
                    normalized.append(replace(current, parts=[TextPart(content=content)]))
                    index += 2
                    continue

        normalized.append(current)
        index += 1

    return normalized


def task_output_text(part: ToolCallPart) -> str | None:
    args = part.args if isinstance(part.args, dict) else None
    if args is None:
        return None
    if part.tool_name == "task_done":
        value = args.get("result")
    elif part.tool_name == "task_failed":
        value = args.get("problem")
    else:
        return None
    return value if isinstance(value, str) and value else None
