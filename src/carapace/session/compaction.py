"""Pure compaction strategies over pydantic-ai model history.

No I/O and no LLM calls live here: planning functions locate compaction *candidates* and
return the text to summarize; apply functions take already-produced summaries and rewrite
history + the compaction tree. The engine (see ``session/turns`` wiring) injects the real
compaction model. This keeps every strategy deterministically unit-testable.

Regions:
- Recent turns (kept verbatim): only tool-return compaction shrinks large outputs in place.
- Old turns (beyond the keep-window K): message-fold collapses whole turns into a summary.

Representations in the model history:
- A folded block is a synthetic ``ModelRequest`` with a single ``UserPromptPart`` whose text
  starts with ``FOLD_MARKER`` — provider-safe (starts a turn with a user message) and trivially
  detectable so we never re-fold it.
- A compacted tool return keeps its ``ToolReturnPart`` (same ``tool_call_id`` → pairing intact);
  only ``content`` shrinks and ``metadata`` is stamped so it is never compacted twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolReturnPart,
    UserPromptPart,
)

from ..models.compaction import FOLD_MARKER, CompactionMethod
from ..usage import count_message_tokens, count_text_tokens
from .transcript import completed_model_turn_end_indexes

# Namespaced key stashed in ``ToolReturnPart.metadata`` to mark + describe a compacted output.
_META_KEY = "carapace_compaction"


# --------------------------------------------------------------------------- thinking-drop


def apply_thinking_drop(messages: list[ModelMessage]) -> tuple[list[ModelMessage], int]:
    """Drop ``ThinkingPart``s from every response except the newest turn's.

    Old thinking is dead weight in history (providers do not need it back) yet it is cheap to
    keep the most recent turn's reasoning for continuity.
    """
    # Keep thinking only inside the most recent completed turn (it starts after the
    # second-to-last turn boundary). With ≤1 completed turn, keep everything.
    turn_ends = completed_model_turn_end_indexes(messages)
    last_boundary = turn_ends[-2] if len(turn_ends) >= 2 else -1
    out: list[ModelMessage] = []
    dropped = 0
    for index, msg in enumerate(messages):
        if index > last_boundary or not isinstance(msg, ModelResponse):
            out.append(msg)
            continue
        kept_parts = [p for p in msg.parts if not isinstance(p, ThinkingPart)]
        dropped += len(msg.parts) - len(kept_parts)
        if not kept_parts:
            # A response that was nothing but thinking — drop the whole message.
            continue
        out.append(msg if len(kept_parts) == len(msg.parts) else replace(msg, parts=kept_parts))
    return out, dropped


# ---------------------------------------------------------------------- tool-return compaction


@dataclass(frozen=True, slots=True)
class ToolReturnCandidate:
    message_index: int
    part_index: int
    tool_name: str
    tool_call_id: str | None
    content: Any
    tokens: int


@dataclass(frozen=True, slots=True)
class AppliedToolReturn:
    """A produced replacement for one tool return (summary text + bookkeeping)."""

    new_content: str
    method: CompactionMethod
    orig_tokens: int
    summary_tokens: int


def tool_return_compaction_info(part: ToolReturnPart) -> dict[str, Any] | None:
    """The stamped compaction record on a tool return, or None if not compacted."""
    meta = part.metadata
    if isinstance(meta, dict) and isinstance(info := meta.get(_META_KEY), dict):
        return info
    return None


def tool_return_is_compacted(part: ToolReturnPart) -> bool:
    return tool_return_compaction_info(part) is not None


def find_tool_return_candidates(
    messages: list[ModelMessage],
    *,
    floor_tokens: int,
    model_name: str | None = None,
    within_indexes: set[int] | None = None,
) -> list[ToolReturnCandidate]:
    """Large, not-yet-compacted tool returns, largest first.

    ``within_indexes`` restricts to message indexes in the kept (verbatim) region so we never
    touch outputs that a fold is about to absorb.
    """
    candidates: list[ToolReturnCandidate] = []
    for mi, msg in enumerate(messages):
        if within_indexes is not None and mi not in within_indexes:
            continue
        if not isinstance(msg, ModelRequest):
            continue
        for pi, part in enumerate(msg.parts):
            if not isinstance(part, ToolReturnPart) or tool_return_is_compacted(part):
                continue
            tokens = count_text_tokens(_tool_content_text(part.content), model_name=model_name)
            if tokens < floor_tokens:
                continue
            candidates.append(
                ToolReturnCandidate(
                    message_index=mi,
                    part_index=pi,
                    tool_name=part.tool_name,
                    tool_call_id=part.tool_call_id,
                    content=part.content,
                    tokens=tokens,
                )
            )
    candidates.sort(key=lambda c: c.tokens, reverse=True)
    return candidates


def apply_tool_return_compaction(
    messages: list[ModelMessage],
    applied: dict[str, AppliedToolReturn],
) -> list[ModelMessage]:
    """Replace tool-return content with summaries, keyed by ``tool_call_id``; stamp metadata."""
    if not applied:
        return messages
    out: list[ModelMessage] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            out.append(msg)
            continue
        changed = False
        new_parts: list[Any] = []
        for part in msg.parts:
            if isinstance(part, ToolReturnPart) and part.tool_call_id in applied and not tool_return_is_compacted(part):
                rep = applied[part.tool_call_id]
                meta = dict(part.metadata) if isinstance(part.metadata, dict) else {}
                meta[_META_KEY] = {
                    "compacted": True,
                    "method": rep.method,
                    "orig_tokens": rep.orig_tokens,
                    "summary_tokens": rep.summary_tokens,
                }
                new_parts.append(replace(part, content=_tool_marker(rep.method) + rep.new_content, metadata=meta))
                changed = True
            else:
                new_parts.append(part)
        out.append(replace(msg, parts=new_parts) if changed else msg)
    return out


def truncate_tool_output(content: Any, *, head_lines: int = 12, tail_lines: int = 12) -> str:
    """Deterministic (no-LLM) compaction: keep head + tail lines, elide the middle."""
    text = _tool_content_text(content)
    lines = text.splitlines()
    if len(lines) <= head_lines + tail_lines:
        return text
    elided = len(lines) - head_lines - tail_lines
    return "\n".join([*lines[:head_lines], f"… [{elided} lines elided] …", *lines[-tail_lines:]])


# -------------------------------------------------------------------------------- message-fold


@dataclass(slots=True)
class FoldPlan:
    lead_folds: list[ModelMessage]
    foldable: list[ModelMessage]
    kept: list[ModelMessage]
    source_turn_start: int
    source_turn_end: int
    orig_tokens: int = field(default=0)

    @property
    def is_empty(self) -> bool:
        return not self.foldable


def is_fold_message(msg: ModelMessage) -> bool:
    return (
        isinstance(msg, ModelRequest)
        and len(msg.parts) == 1
        and isinstance(msg.parts[0], UserPromptPart)
        and isinstance(msg.parts[0].content, str)
        and msg.parts[0].content.startswith(FOLD_MARKER)
    )


def split_lead_folds(messages: list[ModelMessage]) -> tuple[list[ModelMessage], list[ModelMessage]]:
    i = 0
    while i < len(messages) and is_fold_message(messages[i]):
        i += 1
    return messages[:i], messages[i:]


def make_fold_message(summary: str) -> ModelRequest:
    body = f"{FOLD_MARKER} Summary of earlier conversation, compacted to save context:\n\n{summary}"
    return ModelRequest(parts=[UserPromptPart(content=body)])


def plan_fold(messages: list[ModelMessage], *, keep_turns: int, model_name: str | None = None) -> FoldPlan | None:
    """Plan folding everything older than the last ``keep_turns`` completed turns.

    Returns ``None`` when there is nothing to fold (too few completed turns).
    """
    if keep_turns < 1:
        keep_turns = 1
    lead_folds, rest = split_lead_folds(messages)
    turn_ends = completed_model_turn_end_indexes(rest)
    if len(turn_ends) <= keep_turns:
        return None
    cut = turn_ends[len(turn_ends) - keep_turns - 1] + 1  # first index of the kept region
    foldable = rest[:cut]
    kept = rest[cut:]
    if not foldable:
        return None
    return FoldPlan(
        lead_folds=lead_folds,
        foldable=foldable,
        kept=kept,
        source_turn_start=0,
        source_turn_end=len(turn_ends) - keep_turns - 1,
        orig_tokens=count_message_tokens(foldable, model_name=model_name),
    )


def apply_fold(plan: FoldPlan, summary: str) -> list[ModelMessage]:
    """Build the new history: existing folds + a new fold summary + the kept verbatim region."""
    return [*plan.lead_folds, make_fold_message(summary), *plan.kept]


def fold_render_text(messages: list[ModelMessage]) -> str:
    """Flatten a foldable region to plain text for the summarizer prompt."""
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    lines.append(f"User: {part.content}")
                elif isinstance(part, ToolReturnPart):
                    lines.append(f"Tool[{part.tool_name}] result: {_tool_content_text(part.content)}")
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    lines.append(f"Assistant: {part.content}")
                elif part.__class__.__name__ == "ToolCallPart":
                    lines.append(f"Assistant called {getattr(part, 'tool_name', '?')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------- consolidate


def plan_consolidate(messages: list[ModelMessage]) -> tuple[list[ModelMessage], list[ModelMessage]] | None:
    """Return ``(lead_folds, rest)`` when ≥2 lead fold messages exist and can be merged."""
    lead_folds, rest = split_lead_folds(messages)
    if len(lead_folds) < 2:
        return None
    return lead_folds, rest


def consolidate_render_text(lead_folds: list[ModelMessage]) -> str:
    parts: list[str] = []
    for msg in lead_folds:
        if isinstance(msg, ModelRequest) and msg.parts and isinstance(msg.parts[0], UserPromptPart):
            content = msg.parts[0].content
            if isinstance(content, str):
                parts.append(content.removeprefix(FOLD_MARKER).strip())
    return "\n\n".join(parts)


def apply_consolidate(rest: list[ModelMessage], summary: str) -> list[ModelMessage]:
    return [make_fold_message(summary), *rest]


# ---------------------------------------------------------------------------------------- utils


def _tool_marker(method: CompactionMethod) -> str:
    verb = {"truncate": "truncated", "summarize": "summarized", "drop": "dropped"}[method]
    return f"[tool output {verb} to save context; re-run the tool for the full result]\n"


def _tool_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "\n".join(_tool_content_text(item) for item in content)
    return str(content)
