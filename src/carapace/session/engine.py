"""Public session engine and cross-cutting session orchestration.

This module owns the long-lived SessionEngine that wires together session
state, security, sandbox integration, subscriber broadcasting, slash-command
handling, and model selection. Turn execution itself lives in session.turns;
 this file remains the integration point that provides the concrete host
 behavior for that turn runner.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic_ai.messages import (
    ModelMessage,
    ToolCallPart,
)
from pydantic_ai.models import Model

from ..agent.deps import Deps
from ..agent.loop import run_agent_turn as _run_agent_turn
from ..credentials import SessionCredentialRegistry
from ..git.store import GitStore
from ..knowledge import KnowledgeRepoHandle, KnowledgeRepoResolver
from ..models.config import Config
from ..models.credentials import CredentialRegistryProtocol
from ..models.session import SessionAttributes, SessionState
from ..models.skills import SkillInfo
from ..models.tooling import ToolCallCallback, ToolResult
from ..notifications.router import NotificationRouter
from ..sandbox.manager import SandboxManager
from ..sandbox.runtime import SkillActivationInputs, SkillFileCredential
from ..security.context import SessionSecurity
from ..security.sentinel import Sentinel
from ..skills import SkillRegistry
from ..usage import (
    LlmRequestLog,
    LlmRequestState,
    last_record_for_source,
)
from ..usage import (
    note_llm_request_text as _note_llm_request_text,
)
from ..usage import (
    note_llm_request_thinking as _note_llm_request_thinking,
)
from ..ws_models import (
    ApprovalResponse,
    Attachment,
    EscalationResponse,
)
from .approvals import SessionApprovalMixin
from .commands import SessionCommandMixin
from .compaction_engine import SessionCompactionMixin
from .manager import SessionManager
from .model_selection import SessionModelMixin
from .titler import generate_title
from .transcript import (
    CompletedEventTurn,
    completed_event_turns,
    completed_model_turn_end_indexes,
    history_for_completed_turn_count,
    is_terminal_history_message,
    normalize_unattended_output_history,
    task_output_text,
)
from .turns import SessionTurnMixin
from .types import ActiveSession, SessionSubscriber
from .usage_budget import SessionUsageBudgetMixin


# Compatibility shims for tests that patch helpers on carapace.session.engine.
def run_agent_turn(*args: Any, **kwargs: Any) -> Any:
    return _run_agent_turn(*args, **kwargs)


def note_llm_request_text() -> LlmRequestState | None:
    return _note_llm_request_text()


def note_llm_request_thinking() -> LlmRequestState | None:
    return _note_llm_request_thinking()


class SessionEngine(
    SessionCommandMixin,
    SessionModelMixin,
    SessionUsageBudgetMixin,
    SessionApprovalMixin,
    SessionTurnMixin,
    SessionCompactionMixin,
):
    """Central session lifecycle manager.

    Owns all in-memory session state, security sessions, and agent execution.
    Channels (WebSocket, Matrix, …) subscribe to events and submit messages
        through this class. Agent turns survive transport disconnects, and LLM
        concurrency is bounded by a shared semaphore.

        Responsibility split:
        - session.types: shared session datatypes and subscriber protocol
        - session.turns: turn execution flow and failure/finalization helpers
        - this module: dependency wiring, lifecycle, approvals, broadcasts, and
            public session APIs
    """

    def __init__(
        self,
        *,
        config: Config,
        data_dir: Path,
        session_mgr: SessionManager,
        agent_model: Model | None,
        sandbox_mgr: SandboxManager,
        credential_registry_for_session: Callable[[str], Awaitable[CredentialRegistryProtocol]],
        knowledge_repo_for_session: KnowledgeRepoResolver,
        model_factory: Callable[[str], Model] | None = None,
        notification_router: NotificationRouter | None = None,
    ) -> None:
        self._config = config
        self._data_dir = data_dir
        self._session_mgr = session_mgr
        self._agent_model = agent_model
        self._sandbox_mgr = sandbox_mgr
        self._model_factory = model_factory
        self._credential_registry_for_session = credential_registry_for_session
        self._knowledge_repo_for_session = knowledge_repo_for_session
        self._notification_router = notification_router
        self._active: dict[str, ActiveSession] = {}
        self._llm_semaphore = asyncio.Semaphore(config.agent.max_parallel_llm)

        # Let SandboxManager retrieve activated skills so automatic setup can rerun on recreation
        sandbox_mgr.set_activated_skills_callback(self._get_activated_skills)
        sandbox_mgr.set_skill_activation_inputs_callback(self._skill_activation_inputs)
        sandbox_mgr.set_skill_command_aliases_callback(self._skill_command_aliases)

    async def _resolve_credential_registry(self, session_id: str) -> CredentialRegistryProtocol:
        return await self._credential_registry_for_session(session_id)

    def _session_credential_registry(self, session_id: str) -> CredentialRegistryProtocol:
        return SessionCredentialRegistry(
            session_id=session_id,
            resolve_registry=self._resolve_credential_registry,
        )

    # -- public access to file I/O manager --

    @property
    def session_mgr(self) -> SessionManager:
        return self._session_mgr

    @property
    def config(self) -> Config:
        return self._config

    async def clear_pending_notifications(self, session_id: str) -> None:
        active = self._active.get(session_id)
        if active is None or self._notification_router is None or not active.pending_notifications:
            return
        for notif_id in sorted(active.pending_notifications):
            await self._clear_pending_notification(active, session_id, notif_id)

    async def _clear_pending_notification(self, active: ActiveSession, session_id: str, notif_id: str) -> None:
        if self._notification_router is None:
            return
        pending_subscription_ids = active.pending_notifications.get(notif_id)
        if not pending_subscription_ids:
            return
        cleared = await self._notification_router.clear_notifications(
            session_id=session_id,
            notif_id=notif_id,
            subscription_ids=set(pending_subscription_ids),
        )
        remaining_subscription_ids = pending_subscription_ids - cleared.delivered_subscription_ids
        if remaining_subscription_ids:
            active.pending_notifications[notif_id] = remaining_subscription_ids
            return
        active.pending_notifications.pop(notif_id, None)

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def _repo_handle_for_session(self, session_id: str) -> KnowledgeRepoHandle:
        return self._knowledge_repo_for_session(session_id)

    def _knowledge_dir_for_session(self, session_id: str) -> Path:
        return self._repo_handle_for_session(session_id).knowledge_dir

    def _git_store_for_session(self, session_id: str) -> GitStore:
        return self._repo_handle_for_session(session_id).git_store

    def _skill_registry_for_session(self, session_id: str) -> SkillRegistry:
        return self._repo_handle_for_session(session_id).skill_registry

    def _skill_catalog_for_session(self, session_id: str) -> list[SkillInfo]:
        return self._repo_handle_for_session(session_id).skill_registry.scan()

    @property
    def sandbox_mgr(self) -> SandboxManager:
        return self._sandbox_mgr

    @property
    def agent_model(self) -> Model | None:
        return self._agent_model

    # -- session lifecycle --

    def _ensure_active(self, session_id: str) -> ActiveSession:
        """Return or create the in-memory ``ActiveSession`` for *session_id*."""
        if session_id in self._active:
            return self._active[session_id]

        state = self._session_mgr.resume_session(session_id)
        if state is None:
            raise KeyError(f"Session {session_id} not found on disk")

        security = SessionSecurity(
            session_id,
            session_factory=self._session_mgr.session_factory,
            max_sentinel_calls_per_tool_call=self._config.agent.max_sentinel_calls_per_tool_call,
            sentinel_domain_batch_window_ms=self._config.agent.sentinel_domain_batch_window_ms,
            unattended=state.attributes.unattended,
            ask_mode=state.attributes.ask_mode,
            yolo_mode=state.attributes.yolo_mode,
        )
        knowledge_dir = self._knowledge_dir_for_session(session_id)
        sentinel = Sentinel(
            model=self._config.agent.sentinel_model,
            knowledge_dir=knowledge_dir,
            skills_dir=knowledge_dir / "skills",
            unattended=state.attributes.unattended,
            ask_mode=state.attributes.ask_mode,
            timeout=timedelta(seconds=self._config.agent.sentinel_timeout_seconds),
            model_factory=self._model_factory,
            model_settings_resolver=self._resolve_model_settings,
        )
        usage_tracker = self._session_mgr.load_usage(session_id)
        llm_log = self._session_mgr.load_llm_request_log(session_id)
        stale_llm_state = self._session_mgr.load_llm_request_state(session_id)
        if stale_llm_state is not None:
            logger.warning(f"Clearing stale in-flight LLM activity for session {session_id}")
            self._session_mgr.clear_llm_request_state(session_id)

        active = ActiveSession(
            state=state,
            security=security,
            sentinel=sentinel,
            usage_tracker=usage_tracker,
            llm_request_log=llm_log,
            agent_model_name=state.agent_model_name,
            sentinel_model_name=state.sentinel_model_name,
            title_model_name=state.title_model_name,
            compaction_model_name=state.compaction_model_name,
        )
        self._restore_persisted_model_overrides(active)
        self._active[session_id] = active

        # Wire security callbacks so domain escalation / info works
        # even outside an agent turn (e.g. during sandbox setup).
        security.set_user_escalation_callback(self._make_escalation_cb(active))
        security.set_domain_info_callback(self._make_domain_info_cb(active))
        security.set_push_info_callback(self._make_push_info_cb(active))
        security.set_credential_info_callback(self._make_credential_info_cb(active))
        security.set_credential_notify_suppress(
            lambda vp: self._sandbox_mgr.mark_credential_notified(state.session_id, vp),
        )

        # Register a domain-approval callback so the sandbox proxy can
        # evaluate domain requests through the per-session sentinel.
        self._sandbox_mgr.set_domain_approval_callback(
            session_id,
            self._make_domain_eval_cb(security, sentinel, active),
        )
        # Register a domain-notify callback so skill-granted and bypass
        # domain accesses also emit UI events.
        self._sandbox_mgr.set_domain_notify_callback(
            session_id,
            self._make_domain_info_cb(active),
        )

        return active

    def _get_activated_skills(self, session_id: str) -> list[str]:
        """Return activated skills for a session (from in-memory state or disk)."""
        active = self._active.get(session_id)
        if active:
            return list(active.state.activated_skills)
        state = self._session_mgr.load_state(session_id)
        if state:
            return list(state.activated_skills)
        return []

    async def _skill_activation_inputs(self, session_id: str, skill_name: str) -> SkillActivationInputs:
        """Return approved env/file inputs for automatic skill activation providers."""
        registry = self._skill_registry_for_session(session_id)
        carapace_cfg = registry.get_carapace_config(skill_name)
        if not carapace_cfg or not carapace_cfg.credentials:
            return SkillActivationInputs()

        approved_paths = self._credential_vault_paths_for_skill(session_id, skill_name)
        env: dict[str, str] = {}
        file_credentials: list[SkillFileCredential] = []
        for decl in carapace_cfg.credentials:
            if decl.vault_path not in approved_paths or not (decl.env_var or decl.file):
                continue

            value = self._sandbox_mgr.get_cached_credential(session_id, decl.vault_path)
            if not isinstance(value, str):
                value = None
            try:
                if value is None:
                    value = await self._session_credential_registry(session_id).fetch(decl.vault_path)
                    self._sandbox_mgr.cache_credential(session_id, decl.vault_path, value)
            except KeyError:
                logger.warning(f"Credential {decl.vault_path} not found in vault during re-injection")
                continue
            if decl.base64:
                value = base64.b64decode(value).decode()
            if decl.env_var:
                env[decl.env_var] = value
            if decl.file:
                file_credentials.append(SkillFileCredential(path=decl.file, value=value))
        return SkillActivationInputs(environment=env, file_credentials=file_credentials)

    def _skill_command_aliases(self, session_id: str, skill_name: str) -> list[tuple[str, str]]:
        """Return validated command aliases declared by a skill."""
        registry = self._skill_registry_for_session(session_id)
        carapace_cfg = registry.get_carapace_config(skill_name)
        if not carapace_cfg:
            return []
        return [(command.name, command.command) for command in carapace_cfg.commands]

    def _credential_vault_paths_for_skill(self, session_id: str, skill_name: str) -> set[str]:
        """Vault paths allowed for file re-injection: that skill's context grant (from ``use_skill``)."""
        active = self._active.get(session_id)
        state = active.state if active else self._session_mgr.load_state(session_id)
        if not state:
            return set()
        grant = state.context_grants.get(skill_name)
        return grant.vault_paths if grant else set()

    def get_active(self, session_id: str) -> ActiveSession | None:
        """Return the ``ActiveSession`` if loaded, else ``None``."""
        return self._active.get(session_id)

    def _sync_active_session_policy(self, active: ActiveSession) -> None:
        if active.security is not None:
            active.security.set_policy(
                unattended=active.state.attributes.unattended,
                ask_mode=active.state.attributes.ask_mode,
                yolo_mode=active.state.attributes.yolo_mode,
            )
        if active.sentinel is not None:
            active.sentinel.set_policy(
                ask_mode=active.state.attributes.ask_mode,
                unattended=active.state.attributes.unattended,
            )

    def update_active_state(self, session_id: str, **changes: Any) -> None:
        """Apply explicit field updates to the in-memory state for a loaded session."""
        active = self._active.get(session_id)
        if active is not None:
            for field_name, value in changes.items():
                if field_name not in SessionState.model_fields:
                    raise AttributeError(f"Unknown SessionState field: {field_name}")
                if hasattr(value, "model_copy"):
                    value = value.model_copy(deep=True)
                setattr(active.state, field_name, value)
            if "attributes" in changes:
                self._sync_active_session_policy(active)

    def is_agent_running(self, session_id: str) -> bool:
        active = self._active.get(session_id)
        return active is not None and active.agent_task is not None and not active.agent_task.done()

    def get_or_activate(self, session_id: str) -> ActiveSession:
        """Return (or load) the ``ActiveSession``."""
        return self._ensure_active(session_id)

    def deactivate(self, session_id: str) -> None:
        """Remove in-memory state when a session is no longer needed."""
        active = self._active.pop(session_id, None)
        if active and active.agent_task and not active.agent_task.done():
            active.agent_task.cancel()
        self._sandbox_mgr.set_domain_approval_callback(session_id, None)
        self._sandbox_mgr.set_domain_notify_callback(session_id, None)

    # -- subscribers --

    def subscribe(self, session_id: str, sub: SessionSubscriber) -> ActiveSession:
        """Attach a subscriber and return the ``ActiveSession``."""
        active = self._ensure_active(session_id)
        if sub not in active.subscribers:
            active.subscribers.append(sub)
        return active

    def unsubscribe(self, session_id: str, sub: SessionSubscriber) -> None:
        """Detach a subscriber.  Does NOT cancel agent work or destroy security."""
        active = self._active.get(session_id)
        if active:
            with contextlib.suppress(ValueError):
                active.subscribers.remove(sub)
            # When all subscribers disconnect and no task is running we can
            # flush usage to disk, but keep the active session alive.
            if not active.subscribers and (active.agent_task is None or active.agent_task.done()):
                self._session_mgr.save_usage(session_id, active.usage_tracker)
                self._session_mgr.save_llm_request_log(session_id, active.llm_request_log)
                if active.llm_request_state is not None:
                    self._session_mgr.save_llm_request_state(session_id, active.llm_request_state)

    # -- broadcasting helpers --

    async def _broadcast(
        self,
        active: ActiveSession,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        for sub in list(active.subscribers):
            try:
                await getattr(sub, method)(*args, **kwargs)
            except Exception as exc:
                logger.warning(f"Subscriber broadcast {method} failed: {exc}")

    # -- agent execution --

    def _build_deps(
        self,
        active: ActiveSession,
        *,
        tool_call_callback: ToolCallCallback | None = None,
        tool_result_callback: Callable[[ToolResult], None] | None = None,
    ) -> Deps:
        assert active.security is not None and active.sentinel is not None
        session_id = active.state.session_id
        agent_model_id = active.agent_model_name or self._config.agent.model
        agent_model = active.agent_model
        if agent_model is None:
            if active.agent_model_name is None:
                agent_model = self._agent_model or self._resolve_model(self._config.agent.model)
            else:
                agent_model = self._resolve_model(active.agent_model_name)
                active.agent_model = agent_model

        def _append_session_events(events: list[dict[str, Any]]) -> None:
            self._session_mgr.append_events(session_id, events)

        knowledge_dir = self._knowledge_dir_for_session(session_id)

        return Deps(
            config=self._config,
            data_dir=self._data_dir,
            knowledge_dir=knowledge_dir,
            session_state=active.state,
            security=active.security,
            sentinel=active.sentinel,
            git_store=self._git_store_for_session(session_id),
            skill_catalog=self._skill_catalog_for_session(session_id),
            agent_model=agent_model,
            agent_model_id=agent_model_id,
            tool_call_callback=tool_call_callback,
            tool_result_callback=tool_result_callback,
            append_session_events=_append_session_events,
            usage_tracker=active.usage_tracker,
            assert_llm_budget_available=lambda: self._assert_llm_budget_available(active),
            llm_usage_limits=lambda: self._remaining_aux_usage_limits(active),
            sandbox=self._sandbox_mgr,
            activated_skills=[],
            credential_registry=self._session_credential_registry(session_id),
        )

    async def submit_message(
        self,
        session_id: str,
        content: str,
        *,
        origin: SessionSubscriber | None = None,
        attachments: list[Attachment] | None = None,
    ) -> None:
        """Start an agent turn.  Safe to call from any channel."""
        active = self._ensure_active(session_id)

        if active.agent_task and not active.agent_task.done():
            await self._broadcast(active, "on_error", "Agent is busy — cancel first")
            return

        # Drain leftover approval responses
        while not active.tool_approval_queue.empty():
            active.tool_approval_queue.get_nowait()
        while not active.escalation_queue.empty():
            active.escalation_queue.get_nowait()

        await self.clear_pending_notifications(session_id)

        active.agent_task = asyncio.create_task(
            self._run_turn(active, content, origin=origin, attachments=attachments or []),
            name=f"agent-turn-{session_id}",
        )

    async def retry_latest_turn(
        self,
        session_id: str,
        *,
        origin: SessionSubscriber | None = None,
    ) -> None:
        active = self._ensure_active(session_id)
        if active.agent_task and not active.agent_task.done():
            await self._broadcast(active, "on_error", "Agent is busy — cancel first")
            return

        events = self._truncate_incomplete_events(self._session_mgr.load_events(session_id))
        turns = self._completed_event_turns(events)
        if not turns:
            await self._broadcast(active, "on_error", "No completed turn available to retry")
            return

        target = turns[-1]
        user_event = events[target.start_event_index]
        attachments = [Attachment.model_validate(a) for a in user_event.get("attachments", [])]
        self._rewrite_session_transcript(session_id, events[: target.start_event_index])
        await self.submit_message(session_id, target.user_content, origin=origin, attachments=attachments)

    async def reset_to_turn(self, session_id: str, event_index: int) -> bool:
        active = self._ensure_active(session_id)
        if active.agent_task and not active.agent_task.done():
            await self._broadcast(active, "on_error", "Agent is busy — cancel first")
            return False

        events = self._truncate_incomplete_events(self._session_mgr.load_events(session_id))
        turns = self._completed_event_turns(events)
        target = next((turn for turn in turns if turn.end_event_index == event_index), None)
        if target is None:
            await self._broadcast(active, "on_error", "Unknown reset target")
            return False

        self._rewrite_session_transcript(session_id, events[: target.end_event_index + 1])
        return True

    def fork_session(
        self,
        session_id: str,
        *,
        event_index: int,
        channel_type: str,
        channel_ref: str = "",
        unattended: bool | None = None,
        ask_mode: bool | None = None,
        yolo_mode: bool | None = None,
    ) -> SessionState:
        active = self._ensure_active(session_id)
        if active.agent_task and not active.agent_task.done():
            msg = "Agent is busy — cancel first"
            raise RuntimeError(msg)

        source_meta = self._session_mgr.load_meta(session_id)
        source_state = active.state.model_copy(deep=True)
        events = self._truncate_incomplete_events(self._session_mgr.load_events(session_id))
        turns = self._completed_event_turns(events)
        target = next((turn for turn in turns if turn.end_event_index == event_index), None)
        if target is None:
            msg = "Unknown fork target"
            raise ValueError(msg)

        forked_events = events[: target.end_event_index + 1]
        turn_count = len(self._completed_event_turns(forked_events))
        history = self._truncate_incomplete_model_history(self._session_mgr.load_history(session_id))
        forked_history = self._history_for_completed_turn_count(history, turn_count)
        target_unattended = source_state.attributes.unattended if unattended is None else unattended
        target_ask_mode = source_state.attributes.ask_mode if ask_mode is None else ask_mode
        target_yolo_mode = source_state.attributes.yolo_mode if yolo_mode is None else yolo_mode
        if source_state.attributes.unattended and not target_unattended:
            forked_history = self._normalize_unattended_output_history(forked_history)

        now = datetime.now(tz=UTC)
        forked_session_id = f"{now:%Y-%m-%d-%H-%M}-{secrets.token_hex(4)}"
        forked_state = source_state.model_copy(
            deep=True,
            update={
                "session_id": forked_session_id,
                "channel_type": channel_type,
                "channel_ref": channel_ref or None,
                "title": f"{source_state.title} (Copy)" if source_state.title else None,
                "created_at": now,
                "last_active": now,
                "attributes": SessionAttributes(
                    private=source_state.attributes.private,
                    unattended=target_unattended,
                    ask_mode=target_ask_mode,
                    yolo_mode=target_yolo_mode,
                ),
                "knowledge_last_committed_at": None,
                "knowledge_last_archive_path": None,
                "knowledge_last_export_hash": None,
                "knowledge_last_commit_trigger": None,
            },
        )

        self._session_mgr.save_state(forked_state)
        self._session_mgr.save_meta(forked_session_id, source_meta.model_copy(deep=True))
        self._session_mgr.save_events(forked_session_id, forked_events)
        self._session_mgr.save_history(forked_session_id, forked_history)
        self._session_mgr.clear_llm_request_state(forked_session_id)
        self._session_mgr.clear_sandbox_snapshot(forked_session_id)

        # Seed the context-distribution gauge from the source's last agent request, but only when
        # forking at the tip: for an earlier turn the source's shape reflects more context than the
        # fork actually holds. Cost/usage still start empty — no billing is carried over.
        if target is turns[-1]:
            source_rec = last_record_for_source(self._session_mgr.load_llm_request_log(session_id), "agent")
            if source_rec is not None:
                self._session_mgr.save_llm_request_log(forked_session_id, LlmRequestLog(records=[source_rec]))

        return forked_state

    async def submit_cancel(self, session_id: str) -> None:
        """Cancel the running agent turn for *session_id*."""
        active = self._active.get(session_id)
        if not active:
            return
        if active.agent_task and not active.agent_task.done():
            active.agent_task.cancel()
            active.tool_approval_queue.put_nowait(None)
            active.escalation_queue.put_nowait(None)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await active.agent_task
            active.agent_task = None

    async def submit_approval(
        self,
        session_id: str,
        response: ApprovalResponse | EscalationResponse,
    ) -> None:
        """Forward an approval / escalation response to the running turn."""
        active = self._active.get(session_id)
        if active:
            if isinstance(response, ApprovalResponse):
                active.tool_approval_queue.put_nowait(response)
            else:
                active.escalation_queue.put_nowait(response)

    def _completed_event_turns(self, events: list[dict[str, Any]]) -> list[CompletedEventTurn]:
        return completed_event_turns(events)

    def _completed_model_turn_end_indexes(self, messages: list[ModelMessage]) -> list[int]:
        return completed_model_turn_end_indexes(messages)

    def _is_terminal_history_message(self, message: ModelMessage) -> bool:
        return is_terminal_history_message(message)

    def _history_for_completed_turn_count(self, messages: list[ModelMessage], turn_count: int) -> list[ModelMessage]:
        return history_for_completed_turn_count(messages, turn_count)

    def _normalize_unattended_output_history(self, messages: list[ModelMessage]) -> list[ModelMessage]:
        return normalize_unattended_output_history(messages)

    def _task_output_text(self, part: ToolCallPart) -> str | None:
        return task_output_text(part)

    def _rewrite_session_transcript(self, session_id: str, events: list[dict[str, Any]]) -> None:
        truncated_events = self._truncate_incomplete_events(events)
        turn_count = len(self._completed_event_turns(truncated_events))
        history = self._truncate_incomplete_model_history(self._session_mgr.load_history(session_id))
        truncated_history = self._history_for_completed_turn_count(history, turn_count)

        self._session_mgr.save_events(session_id, truncated_events)
        self._session_mgr.save_history(session_id, truncated_history)
        self._session_mgr.clear_llm_request_state(session_id)

        active = self._active.get(session_id)
        if active is not None:
            active.llm_request_state = None
            active.llm_request_thinking.clear()

    async def _generate_title(
        self, active: ActiveSession, events: list[dict[str, Any]], *, track_activity: bool = True
    ) -> str:
        session_id = active.state.session_id
        try:
            async with self._llm_semaphore:
                with self.llm_request_recording(active, track_activity=track_activity):
                    self._assert_llm_budget_available(active)
                    title = await generate_title(
                        events,
                        model=active.title_model_name or self._config.agent.title_model,
                        usage_tracker=active.usage_tracker,
                        before_llm_call=lambda: self._assert_llm_budget_available(active),
                        model_factory=self._model_factory,
                        model_settings=self._resolve_model_settings(
                            active.title_model_name or self._config.agent.title_model
                        ),
                        usage_limits=self._remaining_aux_usage_limits(active),
                    )
            if title:
                active.state.title = title
                self._session_mgr.save_state(active.state)
                self._session_mgr.save_usage(session_id, active.usage_tracker)
                await self._broadcast(active, "on_title_update", title, self._turn_usage_payload(active))
                return title
        except Exception as exc:
            logger.warning(f"Title generation failed for {session_id}: {exc}")
        return ""
