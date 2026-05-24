"""Slash-command handling for SessionEngine."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from ..git.store import GitStore
from ..models.config import Config
from ..models.skills import SkillInfo, context_grants_session_summary
from ..sandbox.manager import SandboxManager
from ..skills import SkillRegistry
from ..ws_models import SLASH_COMMANDS
from .manager import SessionManager
from .types import ActiveSession


class SessionCommandHost(Protocol):
    _active: dict[str, ActiveSession]
    _config: Config
    _git_store: GitStore
    _knowledge_dir: Path
    _sandbox_mgr: SandboxManager
    _session_mgr: SessionManager
    _skill_catalog: list[SkillInfo]

    async def _broadcast(self, active: ActiveSession, method: str, *args: Any, **kwargs: Any) -> None: ...
    async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> str: ...
    def _handle_models_command(self, active: ActiveSession) -> dict[str, Any]: ...
    async def _handle_model_selector_command(
        self, active: ActiveSession, arg: str, *, slash_line: str
    ) -> dict[str, Any]: ...
    def _budget_gauges(self, active: ActiveSession) -> list[Any]: ...
    def _usage_last_llm_payload_row(
        self, active: ActiveSession, source: Literal["agent", "sentinel"]
    ) -> dict[str, Any] | None: ...
    def _budget_command_payload(self, active: ActiveSession, *, message: str | None = None) -> dict[str, Any]: ...
    def _parse_budget_limit_value(
        self, metric: Literal["input", "output", "cost", "tool_calls"], raw: str
    ) -> int | Decimal: ...
    def _set_budget_metric(
        self,
        active: ActiveSession,
        metric: Literal["input", "output", "cost", "tool_calls"],
        value: int | Decimal,
    ) -> str: ...


class SessionCommandMixin:
    _active: dict[str, ActiveSession]
    _config: Config
    _git_store: GitStore
    _knowledge_dir: Path
    _sandbox_mgr: SandboxManager
    _session_mgr: SessionManager
    _skill_catalog: list[SkillInfo]

    if TYPE_CHECKING:

        async def _broadcast(self, active: ActiveSession, method: str, *args: Any, **kwargs: Any) -> None: ...
        async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> str: ...
        def _handle_models_command(self, active: ActiveSession) -> dict[str, Any]: ...
        async def _handle_model_selector_command(
            self, active: ActiveSession, arg: str, *, slash_line: str
        ) -> dict[str, Any]: ...
        def _budget_gauges(self, active: ActiveSession) -> list[Any]: ...
        def _usage_last_llm_payload_row(
            self, active: ActiveSession, source: Literal["agent", "sentinel"]
        ) -> dict[str, Any] | None: ...
        def _budget_command_payload(self, active: ActiveSession, *, message: str | None = None) -> dict[str, Any]: ...
        def _parse_budget_limit_value(
            self, metric: Literal["input", "output", "cost", "tool_calls"], raw: str
        ) -> int | Decimal: ...
        def _set_budget_metric(
            self,
            active: ActiveSession,
            metric: Literal["input", "output", "cost", "tool_calls"],
            value: int | Decimal,
        ) -> str: ...

    async def handle_slash_command(self, session_id: str, command: str) -> dict[str, Any] | None:
        """Process a slash command, return structured data or ``None``."""
        active = self._active.get(session_id)
        if not active:
            return None

        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd == "/help":
            return {"command": "help", "data": {"commands": SLASH_COMMANDS}}

        if cmd == "/session":
            grants_summary = context_grants_session_summary(
                session_id,
                active.state.context_grants,
                self._sandbox_mgr.get_cached_credential,
            )
            return {
                "command": "session",
                "data": {
                    "session_id": session_id,
                    "channel_type": active.state.channel_type,
                    "context_grants": grants_summary,
                    "allowed_domains": self._sandbox_mgr.get_domain_info(session_id),
                },
            }

        if cmd == "/skills":
            skills = [{"name": s.name, "description": s.description.strip()} for s in self._skill_catalog]
            return {"command": "skills", "data": skills}

        if cmd == "/retitle":
            arg = parts[1].strip() if len(parts) > 1 else ""
            if arg:
                active.state.title = arg
                self._session_mgr.save_state(active.state)
                await self._broadcast(active, "on_title_update", arg)
                return {"command": "retitle", "data": {"message": f"Title set to: {arg}"}}
            events = list(self._session_mgr.load_events(session_id))
            new_title = await self._generate_title(active, events)
            if not new_title:
                return {
                    "command": "retitle",
                    "data": {"message": "Could not generate a title (no eligible messages yet, or generation failed)."},
                }
            return {"command": "retitle", "data": {"message": f"Title: {new_title}"}}

        if cmd == "/models":
            return self._handle_models_command(active)

        if cmd == "/model":
            return await self._handle_model_selector_command(
                active,
                parts[1].strip() if len(parts) > 1 else "",
                slash_line=command.strip(),
            )

        if cmd == "/usage":
            tracker = active.usage_tracker
            costs = tracker.estimated_cost()
            cat_costs = tracker.estimated_category_cost()
            return {
                "command": "usage",
                "data": {
                    "models": {k: v.model_dump() for k, v in tracker.models.items()},
                    "categories": {k: v.model_dump() for k, v in tracker.categories.items()},
                    "total_input": tracker.total_input,
                    "total_output": tracker.total_output,
                    "total_tool_calls": tracker.tool_calls,
                    "costs": {k: str(v) for k, v in costs.items()},
                    "category_costs": {k: str(v) for k, v in cat_costs.items()},
                    "budget_gauges": [g.model_dump(mode="json") for g in self._budget_gauges(active)],
                    "last_llm_agent": self._usage_last_llm_payload_row(active, "agent"),
                    "last_llm_sentinel": self._usage_last_llm_payload_row(active, "sentinel"),
                },
            }

        if cmd == "/budget":
            return self._handle_budget_command(active, parts)

        if cmd == "/pull":
            return await self._handle_pull_command()

        if cmd == "/push":
            return await self._handle_push_command()

        if cmd == "/reload":
            return await self._handle_reload_command(session_id)

        return None

    def _handle_budget_command(self, active: ActiveSession, parts: list[str]) -> dict[str, Any]:
        if len(parts) == 1:
            return {"command": "budget", "data": self._budget_command_payload(active)}

        args = parts[1].strip().split(maxsplit=1)
        metric_aliases: dict[str, Literal["input", "output", "cost", "tool_calls"]] = {
            "input": "input",
            "output": "output",
            "cost": "cost",
            "tools": "tool_calls",
            "tool": "tool_calls",
            "tool_calls": "tool_calls",
            "tool-calls": "tool_calls",
        }
        metric = metric_aliases.get(args[0].lower()) if len(args) == 2 else None
        if len(args) != 2 or metric is None:
            return {
                "command": "budget",
                "data": {
                    **self._budget_command_payload(active),
                    "error": "Usage: /budget, /budget input N, /budget output N, /budget cost N, or /budget tools N",
                },
            }

        try:
            value = self._parse_budget_limit_value(metric, args[1].strip())
        except ValueError as exc:
            return {
                "command": "budget",
                "data": {**self._budget_command_payload(active), "error": str(exc)},
            }
        message = self._set_budget_metric(active, metric, value)
        return {
            "command": "budget",
            "data": self._budget_command_payload(active, message=message),
        }

    async def _handle_push_command(self) -> dict[str, Any]:
        """Handle the ``/push`` slash command — push to external remote."""
        if not self._config.git.remote:
            return {"command": "push", "data": {"message": "No external remote configured."}}
        try:
            await self._git_store.push_to_remote()
            return {"command": "push", "data": {"message": "Pushed to external remote."}}
        except Exception as exc:
            return {"command": "push", "data": {"message": f"Push failed: {exc}"}}

    async def _handle_pull_command(self) -> dict[str, Any]:
        """Handle the ``/pull`` slash command — pull from external remote."""
        if not self._config.git.remote:
            return {"command": "pull", "data": {"message": "No external remote configured."}}
        try:
            summary = await self._git_store.pull_from_remote()
            registry = SkillRegistry(self._knowledge_dir / "skills")
            self._skill_catalog = registry.scan()
            return {"command": "pull", "data": {"message": summary}}
        except RuntimeError as exc:
            return {"command": "pull", "data": {"message": f"Pull failed: {exc}"}}

    async def _handle_reload_command(self, session_id: str) -> dict[str, Any]:
        """Handle the ``/reload`` slash command — reset the sandbox completely."""
        try:
            await self._sandbox_mgr.reset_session(session_id)
            return {
                "command": "reload",
                "data": {
                    "message": "Sandbox reset. A fresh workspace will be created from Git on the next command.",
                },
            }
        except Exception as exc:
            return {"command": "reload", "data": {"message": f"Reload failed: {exc}"}}
