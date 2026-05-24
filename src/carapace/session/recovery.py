from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from loguru import logger
from pydantic_ai.messages import ModelResponse, TextPart

from carapace.session.manager import SessionManager
from carapace.session.state import SessionRuntime
from carapace.session.store import SessionStore
from carapace.session.transcript import complete_cancelled_events, complete_cancelled_model_history


class SessionRuntimeRecovery:
    def __init__(
        self,
        session_mgr: SessionManager,
        session_store: SessionStore,
        active_task_running: Callable[[str], bool],
    ) -> None:
        self._session_mgr = session_mgr
        self._session_store = session_store
        self._active_task_running = active_task_running

    def recover_stale_session_runtimes(self) -> list[SessionRuntime]:
        """Conservatively close active durable runtime phases that have no live task."""
        recovered: list[SessionRuntime] = []
        for session_id in self._session_mgr.list_sessions():
            runtime = self._session_mgr.load_session_runtime(session_id)
            if runtime is None or not runtime.is_active:
                continue
            if self._active_task_running(session_id):
                continue
            try:
                recovered.append(self._recover_stale_session_runtime(runtime))
            except Exception as exc:
                logger.warning(f"Failed to recover stale runtime for session {session_id}: {exc}")
        return recovered

    def _recover_stale_session_runtime(self, runtime: SessionRuntime) -> SessionRuntime:
        session_id = runtime.session_id
        original_phase = runtime.phase
        terminal_message = "The previous turn was interrupted before completion."
        logger.warning(f"Recovering stale session runtime session={session_id} phase={original_phase}")
        self._repair_interrupted_turn_transcript(session_id, terminal_message)
        interrupted = self._session_store.transition(
            session_id,
            to_phase="interrupted",
            event_type="turn_interrupted",
            turn_id=runtime.current_turn_id,
            updates={"last_error": f"Recovered stale runtime phase: {original_phase}"},
            payload={"recovered_from_phase": original_phase},
        )
        return self._session_store.transition(
            session_id,
            to_phase="cancelled",
            event_type="turn_cancelled",
            turn_id=interrupted.current_turn_id,
            updates={
                "current_turn_id": None,
                "pending_approval_ids": [],
                "pending_escalation_ids": [],
                "last_error": f"Recovered stale runtime phase: {original_phase}",
            },
            payload={"recovered_from_phase": original_phase},
        )

    def _repair_interrupted_turn_transcript(self, session_id: str, terminal_message: str) -> None:
        events = self._session_mgr.load_events(session_id)
        if events:
            repaired_events = complete_cancelled_events(events)
            if repaired_events and repaired_events[-1].get("role") != "assistant":
                repaired_events.append(
                    {
                        "role": "assistant",
                        "content": terminal_message,
                        "timestamp": datetime.now(tz=UTC).isoformat(),
                    }
                )
            self._session_mgr.save_events(session_id, repaired_events)

        history = self._session_mgr.load_history(session_id)
        if not history:
            return
        repaired_history = complete_cancelled_model_history(history)
        if not isinstance(repaired_history[-1], ModelResponse):
            repaired_history.append(ModelResponse(parts=[TextPart(content=terminal_message)]))
        self._session_mgr.save_history(session_id, repaired_history)
