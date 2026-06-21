from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..security.context import ApprovalSource, ApprovalVerdict


class SentFileInfo(BaseModel):
    """A file the agent exposed to the user via ``send_file``, persisted server-side."""

    file_id: str
    name: str
    mime: str
    size: int


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Structured result passed through ``tool_result_callback``."""

    tool: str
    output: str
    exit_code: int = 0
    tool_id: str | None = None
    # Provider tool-call id from the model history (``ctx.tool_call_id``). Distinct from ``tool_id``
    # (a carapace UUID), it is the only reliable link back to the model's ToolReturnPart — used to
    # surface compaction annotations on the right tool row.
    model_tool_call_id: str | None = None
    files: tuple[SentFileInfo, ...] = field(default_factory=tuple)


type ToolCallCallback = Callable[
    [str, dict[str, Any], str, ApprovalSource | None, ApprovalVerdict | None, str | None], None
]


def normalize_optional_tool_label(value: Any) -> str | None:
    """Return a cleaned tool label string, or ``None`` when the value is not meaningful."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if trimmed.lower() in {"null", "none"}:
        return None
    return trimmed


def normalize_tool_call_args(tool: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize serialized tool-call args for transport and persistence."""
    normalized = dict(args)
    if tool == "exec":
        normalized["title"] = normalize_optional_tool_label(normalized.get("title"))
    return normalized
