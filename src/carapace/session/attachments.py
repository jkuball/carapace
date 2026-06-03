"""Build the hidden preamble that tells the agent about user-uploaded files.

The user's chat bubble shows only their typed text plus attachment chips. The
preamble produced here is prepended to the prompt the LLM actually receives (and
to ``history.yaml``), so the agent knows where each uploaded file landed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class AttachmentLike(Protocol):
    name: str
    path: str


def build_attachment_preamble(attachments: Sequence[AttachmentLike]) -> str:
    """Return the preamble text for *attachments*, or ``""`` when there are none."""
    if not attachments:
        return ""
    lines = ["The user has provided the following files:"]
    for att in attachments:
        lines.append(f"- {att.name} (uploaded to {att.path} inside your sandbox)")
    return "\n".join(lines)


def augment_prompt(user_input: str, attachments: Sequence[AttachmentLike]) -> str:
    """Prepend the attachment preamble to *user_input* (no-op without attachments)."""
    preamble = build_attachment_preamble(attachments)
    if not preamble:
        return user_input
    if not user_input:
        return preamble
    return f"{preamble}\n\n{user_input}"
