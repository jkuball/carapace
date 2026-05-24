"""Slash command processing for the Matrix channel."""

from __future__ import annotations

from carapace.agent.deps import Deps
from carapace.models.skills import context_grants_session_summary
from carapace.ws_models import CommandResult


def handle_matrix_slash_command(
    command: str,
    deps: Deps,
    security_md: str,
    slash_commands: list[dict[str, str]],
) -> CommandResult | None:
    """Process a slash command inline for the Matrix channel.

    This mirrors the logic that used to live in ``server._handle_slash_command``
    but works without depending on server-module globals.
    """
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/help":
        return CommandResult(command="help", data={"commands": slash_commands})

    if cmd == "/session":
        session_id = deps.session_state.session_id
        grants_summary = context_grants_session_summary(
            session_id,
            deps.session_state.context_grants,
            deps.sandbox.get_cached_credential,
        )
        return CommandResult(
            command="session",
            data={
                "session_id": session_id,
                "channel_type": deps.session_state.channel_type,
                "context_grants": grants_summary,
                "allowed_domains": deps.sandbox.get_domain_info(session_id),
            },
        )

    if cmd == "/skills":
        skills = [{"name": s.name, "description": s.description.strip()} for s in deps.skill_catalog]
        return CommandResult(command="skills", data=skills)

    if cmd == "/usage":
        tracker = deps.usage_tracker
        costs = tracker.estimated_cost()
        cat_costs = tracker.estimated_category_cost()
        return CommandResult(
            command="usage",
            data={
                "models": {k: v.model_dump() for k, v in tracker.models.items()},
                "categories": {k: v.model_dump() for k, v in tracker.categories.items()},
                "total_input": tracker.total_input,
                "total_output": tracker.total_output,
                "costs": {k: str(v) for k, v in costs.items()},
                "category_costs": {k: str(v) for k, v in cat_costs.items()},
            },
        )

    return None
