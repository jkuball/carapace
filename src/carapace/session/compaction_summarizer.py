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
You compress the older part of an ongoing assistant conversation to save context, while keeping
enough that the assistant can continue seamlessly, as if it still remembered everything.

Write a chronological narrative — a story of what happened, in past tense — NOT a bullet list and
NOT just the final outcome. Walk through the conversation in order: what the user asked for, what
the assistant did (commands run, tools used, files and resources touched, searches performed), what
the results were, which decisions and trade-offs were made, errors hit and how they were handled,
and any pivots in direction. Preserve concrete specifics that may be needed later: names,
identifiers, paths, counts, key values, URLs, and unresolved threads.

Be much shorter than the original conversation, but do not over-compress to a few lines — keep the
meaningful steps. Stay strictly faithful; never invent details or outcomes. Omit only true filler
(greetings, acknowledgements, verbatim repetition).

Format: flowing prose in the third person ("the user", "the assistant"), split into a few short
paragraphs when the topic shifts.

Example of the desired style:
"Initially the user wanted research on gummy bears. The assistant searched the web and found three
sources — a history of Haribo, a sugar-content comparison, and a manufacturing overview — and
summarized the key facts from each. The user then pivoted to ask about other snacks instead, so the
assistant dropped the gummy-bear thread and began comparing licorice and dark chocolate, noting the
user cared most about sugar content and flagging that price data was still missing."

Reply with ONLY the summary.
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
