"""LLM-backed summarization for compaction (folded turns + large tool outputs).

Mirrors ``titler.generate_title``: a lightweight aux agent call logged under the
``compaction`` source so it shows up in usage without masquerading as an agent turn.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.models import Model, infer_model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from ..usage import LlmRequestLogCapability, UsageTracker, provider_cost_usd_from_messages

_FOLD_SYSTEM = """\
You compress the older part of an ongoing DevOps assistant conversation to save context.
Write a dense, factual summary that preserves: the user's goals, decisions made, commands run
and their outcomes, files and resources touched, errors hit, and any unresolved threads.
Omit small talk. Use terse notes, not prose. Do NOT invent details. Reply with ONLY the summary.
"""

_TOOL_SYSTEM = """\
You compress a single tool output to save context in an ongoing DevOps session.
Keep the parts an agent would need later: key results, identifiers, counts, errors, and notable
values. Drop repetition and boilerplate. Be faithful — never invent. Reply with ONLY the summary.
"""


async def _run_summary(
    system: str,
    text: str,
    *,
    model: str,
    usage_tracker: UsageTracker | None,
    before_llm_call: Callable[[], None] | None,
    model_factory: Callable[[str], Model] | None,
    model_settings: ModelSettings | None,
    usage_limits: UsageLimits | None,
) -> str:
    resolved = model_factory(model) if model_factory is not None else infer_model(model)
    agent: Agent[None, str] = Agent(
        resolved,
        output_type=str,
        instructions=system,
        model_settings=model_settings,
        capabilities=[LlmRequestLogCapability(source="compaction")],
        retries={"tools": 1, "output": 2},
    )
    if before_llm_call is not None:
        before_llm_call()
    result = await agent.run(text, usage_limits=usage_limits)
    if usage_tracker:
        usage_tracker.record(
            model,
            "compaction",
            result.usage,
            cost_usd=provider_cost_usd_from_messages(result.new_messages()),
        )
    return result.output.strip()


async def summarize_fold(text: str, **kwargs: Any) -> str:
    """Summarize a folded run of turns. Returns '' on failure (caller should abort the fold)."""
    try:
        return await _run_summary(_FOLD_SYSTEM, text, **kwargs)
    except Exception:
        logger.opt(exception=True).warning("Fold summarization failed")
        return ""


async def summarize_tool_output(tool_name: str, text: str, **kwargs: Any) -> str:
    try:
        return await _run_summary(_TOOL_SYSTEM, f"Tool: {tool_name}\n\n{text}", **kwargs)
    except Exception:
        logger.opt(exception=True).warning("Tool-output summarization failed")
        return ""
