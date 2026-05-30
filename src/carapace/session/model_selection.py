"""Model catalog and per-session model override helpers."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, Literal, Protocol

from loguru import logger
from pydantic_ai.models import Model, infer_model
from pydantic_ai.settings import ModelSettings

from ..llm import model_settings_for_config
from ..models.config import AvailableModelEntry, Config, agent_available_model_entries
from ..models.session import SessionState
from .manager import SessionManager
from .types import ActiveSession


class _UnsetType:
    pass


_UNSET = _UnsetType()

ModelType = Literal["agent", "sentinel", "title"]


class SessionModelHost(Protocol):
    _active: dict[str, ActiveSession]
    _config: Config
    _session_mgr: SessionManager
    _model_factory: Callable[[str], Model] | None

    async def _generate_title(self, active: ActiveSession, events: list[dict[str, Any]]) -> str: ...


def _logger() -> Any:
    engine_module = sys.modules.get("carapace.session.engine")
    if engine_module is None:
        return logger
    return getattr(engine_module, "logger", logger)


class SessionModelMixin(SessionModelHost):
    _MODEL_TYPES: tuple[ModelType, ...] = ("agent", "sentinel", "title")

    @property
    def available_models(self) -> list[str]:
        return [e.model_id for e in self.available_model_entries]

    @property
    def available_model_entries(self) -> list[AvailableModelEntry]:
        """Deduplicated ``agent.available_models`` (last row per ``model_id``), sorted by id."""
        return agent_available_model_entries(self._config.agent)

    def _max_input_tokens_for_model_id(self, model_id: str) -> int | None:
        for entry in self.available_model_entries:
            if entry.model_id == model_id:
                return entry.max_input_tokens
        return None

    def _resolve_model(self, name: str) -> Model:
        """Create a Model from a name, using the model_factory if available."""
        return self._model_factory(name) if self._model_factory else infer_model(name)

    def _resolve_model_settings(self, name: str) -> ModelSettings | None:
        """Build per-model request settings from the configured catalog."""
        return model_settings_for_config(self._config, name, default_thinking=True)

    def apply_platform_model_config(
        self,
        config: Config,
        *,
        model_factory: Callable[[str], Model] | None,
        agent_model: Model | None,
    ) -> None:
        self._config = config
        self._model_factory = model_factory
        self._agent_model = agent_model
        for active in self._active.values():
            if active.agent_model_name is None:
                active.agent_model = None
            if active.sentinel_model_name is None and active.sentinel is not None:
                active.sentinel.set_model(config.agent.sentinel_model)

    def _restore_persisted_model_overrides(self, active: ActiveSession) -> None:
        """Validate restored overrides, falling back to defaults when they are no longer usable."""
        state_changed = False

        if active.agent_model_name is not None:
            try:
                active.agent_model = self._resolve_model(active.agent_model_name)
            except Exception as exc:
                _logger().warning(
                    f"Persisted agent model override {active.agent_model_name!r} for session "
                    + f"{active.state.session_id} is no longer valid: {exc}. Falling back to "
                    + f"{self._config.agent.model!r}."
                )
                self._apply_model_override(active, "agent", None, None)
                state_changed = True

        if active.sentinel_model_name is not None and active.sentinel is not None:
            try:
                active.sentinel.set_model(active.sentinel_model_name)
            except Exception as exc:
                _logger().warning(
                    f"Persisted sentinel model override {active.sentinel_model_name!r} for session "
                    + f"{active.state.session_id} is no longer valid: {exc}. Falling back to "
                    + f"{self._config.agent.sentinel_model!r}."
                )
                self._apply_model_override(active, "sentinel", None, None)
                state_changed = True

        if active.title_model_name is not None:
            try:
                self._resolve_model(active.title_model_name)
            except Exception as exc:
                _logger().warning(
                    f"Persisted title model override {active.title_model_name!r} for session "
                    + f"{active.state.session_id} is no longer valid: {exc}. Falling back to "
                    + f"{self._config.agent.title_model!r}."
                )
                self._apply_model_override(active, "title", None, None)
                state_changed = True

        if state_changed:
            self._session_mgr.save_state(active.state)

    def update_session_model_overrides(
        self,
        session_id: str,
        *,
        agent_model_name: str | None | _UnsetType = _UNSET,
        sentinel_model_name: str | None | _UnsetType = _UNSET,
    ) -> SessionState:
        """Persist agent and sentinel model overrides without routing through slash commands."""
        active = self._active.get(session_id)
        state = active.state if active is not None else self._session_mgr.load_state(session_id)
        if state is None:
            raise KeyError(session_id)

        if not isinstance(agent_model_name, _UnsetType):
            next_agent_model = None if agent_model_name is None else self._resolve_model(agent_model_name)
            if active is not None:
                self._apply_model_override(active, "agent", agent_model_name, next_agent_model)
            else:
                state.agent_model_name = agent_model_name

        if not isinstance(sentinel_model_name, _UnsetType):
            if sentinel_model_name is not None:
                self._resolve_model(sentinel_model_name)
            if active is not None:
                self._apply_model_override(active, "sentinel", sentinel_model_name, None)
            else:
                state.sentinel_model_name = sentinel_model_name

        self._session_mgr.save_state(state)
        return state

    def _handle_models_command(self, active: ActiveSession) -> dict[str, Any]:
        """Show the available model catalog for selection."""
        available = [e.model_dump(mode="json", by_alias=True) for e in self.available_model_entries]
        return {"command": "models", "data": {"available": available}}

    def _models_slash_view(self, active: ActiveSession) -> dict[str, dict[str, str]]:
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
        }
        overrides = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
        }
        return {t: {"current": overrides[t] or defaults[t], "default": defaults[t]} for t in self._MODEL_TYPES}

    async def _handle_model_selector_command(
        self, active: ActiveSession, arg: str, *, slash_line: str
    ) -> dict[str, Any]:
        """Process ``/model [ROLE] [MODEL | reset]`` while keeping ``/model MODEL`` as ``all``."""
        if not arg:
            return self._handle_model_all_command(active, "")

        target_aliases: dict[str, ModelType | Literal["all"]] = {
            "all": "all",
            "agent": "agent",
            "sentinel": "sentinel",
            "title": "title",
        }
        args = arg.split(maxsplit=1)
        target = target_aliases.get(args[0].lower())
        if target is None:
            return self._handle_model_all_command(active, arg)

        remainder = args[1].strip() if len(args) == 2 else ""
        if target == "all":
            return self._handle_model_all_command(active, remainder)
        return await self._handle_model_command(active, target, remainder, slash_line=slash_line)

    def _handle_model_all_command(self, active: ActiveSession, arg: str) -> dict[str, Any]:
        """Process ``/model [MODEL | reset]`` — show or set all three model roles at once."""
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
        }
        models_view = self._models_slash_view(active)

        if not arg:
            return {"command": "model", "data": {"models": models_view}}

        if arg == "reset":
            for model_type in self._MODEL_TYPES:
                self._apply_model_override(active, model_type, None, None)
            self._session_mgr.save_state(active.state)
            reset_view = {t: {"current": defaults[t], "default": defaults[t]} for t in self._MODEL_TYPES}
            return {
                "command": "model",
                "data": {"models": reset_view, "message": "Reset all models to defaults."},
            }

        try:
            new_model = self._resolve_model(arg)
        except Exception as exc:
            return {"command": "model", "data": {"models": models_view, "error": str(exc)}}

        self._apply_model_override(active, "agent", arg, new_model)
        self._apply_model_override(active, "sentinel", arg, None)
        self._apply_model_override(active, "title", arg, None)
        self._session_mgr.save_state(active.state)
        switched = {t: {"current": arg, "default": defaults[t]} for t in self._MODEL_TYPES}
        return {
            "command": "model",
            "data": {
                "models": switched,
                "message": f"Switched agent, sentinel, and title to: {arg}",
            },
        }

    async def _handle_model_command(
        self, active: ActiveSession, model_type: ModelType, arg: str, *, slash_line: str
    ) -> dict[str, Any]:
        """Process ``/model ROLE [MODEL | reset]`` for one model role."""
        cmd_name = {"agent": "model-agent", "sentinel": "model-sentinel", "title": "model-title"}[model_type]
        defaults = {
            "agent": self._config.agent.model,
            "sentinel": self._config.agent.sentinel_model,
            "title": self._config.agent.title_model,
        }
        overrides = {
            "agent": active.agent_model_name,
            "sentinel": active.sentinel_model_name,
            "title": active.title_model_name,
        }
        default = defaults[model_type]
        current = overrides[model_type] or default

        if not arg:
            return {"command": cmd_name, "data": {"current": current, "default": default}}

        if arg == "reset":
            self._apply_model_override(active, model_type, None, None)
            self._session_mgr.save_state(active.state)
            if model_type == "title":
                await self._regenerate_title(active, pending_user_line=slash_line)
            return {
                "command": cmd_name,
                "data": {"current": default, "default": default, "message": f"Reset to default: {default}"},
            }

        try:
            new_model = self._resolve_model(arg)
        except Exception as exc:
            return {"command": cmd_name, "data": {"current": current, "default": default, "error": str(exc)}}

        self._apply_model_override(active, model_type, arg, new_model if model_type == "agent" else None)
        self._session_mgr.save_state(active.state)
        if model_type == "title":
            await self._regenerate_title(active, pending_user_line=slash_line)
        return {
            "command": cmd_name,
            "data": {"current": arg, "default": default, "message": f"Switched to: {arg}"},
        }

    def _apply_model_override(
        self, active: ActiveSession, model_type: ModelType, name: str | None, model_obj: Model | None = None
    ) -> None:
        if model_type == "agent":
            active.agent_model = model_obj
            active.agent_model_name = name
            active.state.agent_model_name = name
        elif model_type == "sentinel":
            active.sentinel_model_name = name
            active.state.sentinel_model_name = name
            if active.sentinel:
                active.sentinel.set_model(name or self._config.agent.sentinel_model)
        elif model_type == "title":
            active.title_model_name = name
            active.state.title_model_name = name

    async def _regenerate_title(self, active: ActiveSession, *, pending_user_line: str | None = None) -> None:
        """Regenerate the session title using the current title model.

        *pending_user_line* is the slash command line not yet persisted to events (e.g. first
        ``/model title`` in a session).
        """
        session_id = active.state.session_id
        events = list(self._session_mgr.load_events(session_id))
        if pending_user_line:
            events.append({"role": "user", "content": pending_user_line})
        if events:
            await self._generate_title(active, events)
