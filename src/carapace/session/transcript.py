"""Transcript and model-history helpers for session branching."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


@dataclass(frozen=True, slots=True)
class CompletedEventTurn:
    start_event_index: int
    end_event_index: int
    user_content: str


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
