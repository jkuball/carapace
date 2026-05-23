from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from loguru import logger

from carapace.session.events import SessionEventType
from carapace.session.state import SessionRuntimePhase
from carapace.session.store import SessionStore


class SessionRuntimeController:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def transition(
        self,
        session_id: str,
        *,
        to_phase: SessionRuntimePhase,
        event_type: SessionEventType,
        turn_id: str | None = None,
        command_id: str | None = None,
        updates: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            self._store.transition(
                session_id,
                to_phase=to_phase,
                event_type=event_type,
                turn_id=turn_id,
                command_id=command_id,
                updates=updates,
                payload=payload,
            )
        except Exception as exc:
            logger.warning(f"Failed to record session runtime transition for {session_id}: {exc}")

    def turn_queued(self, session_id: str, turn_id: str, *, source: str) -> None:
        self.transition(
            session_id,
            to_phase="queued",
            event_type="turn_queued",
            turn_id=turn_id,
            payload={"source": source},
            updates={
                "pending_approval_ids": [],
                "pending_escalation_ids": [],
                "sandbox_operation_ids": [],
                "last_error": None,
                "lease": None,
            },
        )

    def turn_started(self, session_id: str, turn_id: str | None) -> None:
        self.transition(session_id, to_phase="preparing_turn", event_type="turn_started", turn_id=turn_id)

    def running_llm(self, session_id: str, turn_id: str | None) -> None:
        self.transition(session_id, to_phase="running_llm", event_type="turn_phase_changed", turn_id=turn_id)

    def finalizing(self, session_id: str, turn_id: str | None) -> None:
        self.transition(session_id, to_phase="finalizing", event_type="turn_phase_changed", turn_id=turn_id)

    def turn_finalized(self, session_id: str, turn_id: str | None) -> None:
        self.transition(
            session_id,
            to_phase="idle",
            event_type="turn_finalized",
            turn_id=turn_id,
            updates={
                "current_turn_id": None,
                "pending_approval_ids": [],
                "pending_escalation_ids": [],
                "sandbox_operation_ids": [],
                "lease": None,
                "last_error": None,
            },
        )

    def finalizing_cancelled(self, session_id: str, turn_id: str | None) -> None:
        self.transition(
            session_id,
            to_phase="finalizing_cancelled",
            event_type="turn_phase_changed",
            turn_id=turn_id,
        )

    def turn_cancelled(self, session_id: str, turn_id: str | None) -> None:
        self.transition(
            session_id,
            to_phase="cancelled",
            event_type="turn_cancelled",
            turn_id=turn_id,
            updates={
                "pending_approval_ids": [],
                "pending_escalation_ids": [],
                "lease": None,
            },
        )

    def turn_cancelling(self, session_id: str, *, source: str) -> None:
        runtime = self._store.load_runtime(session_id)
        self.transition(
            session_id,
            to_phase="cancelling",
            event_type="turn_phase_changed",
            turn_id=runtime.current_turn_id,
            payload={"source": source},
        )

    def turn_failed(self, session_id: str, turn_id: str | None, error: str) -> None:
        self.transition(
            session_id,
            to_phase="finalizing_failed",
            event_type="turn_phase_changed",
            turn_id=turn_id,
            updates={"last_error": error},
        )
        self.transition(
            session_id,
            to_phase="failed",
            event_type="turn_failed",
            turn_id=turn_id,
            updates={
                "pending_approval_ids": [],
                "pending_escalation_ids": [],
                "lease": None,
                "last_error": error,
            },
        )

    def approval_requested(self, session_id: str, tool_call_id: str, tool: str) -> None:
        runtime = self._store.load_runtime(session_id)
        pending_ids = [item for item in runtime.pending_approval_ids if item != tool_call_id]
        pending_ids.append(tool_call_id)
        self.transition(
            session_id,
            to_phase="waiting_tool_approval",
            event_type="tool_approval_requested",
            turn_id=runtime.current_turn_id,
            updates={"pending_approval_ids": pending_ids},
            payload={"tool_call_id": tool_call_id, "tool": tool},
        )

    def approvals_resolved(self, session_id: str, tool_call_ids: set[str]) -> None:
        runtime = self._store.load_runtime(session_id)
        self.transition(
            session_id,
            to_phase="running_llm",
            event_type="tool_approval_resolved",
            turn_id=runtime.current_turn_id,
            updates={"pending_approval_ids": []},
            payload={"tool_call_ids": sorted(tool_call_ids)},
        )

    def escalation_requested(self, session_id: str, request_id: str) -> None:
        runtime = self._store.load_runtime(session_id)
        pending_ids = [item for item in runtime.pending_escalation_ids if item != request_id]
        pending_ids.append(request_id)
        self.transition(
            session_id,
            to_phase="waiting_escalation",
            event_type="escalation_requested",
            turn_id=runtime.current_turn_id,
            updates={"pending_escalation_ids": pending_ids},
            payload={"request_id": request_id},
        )

    def escalation_resolved(self, session_id: str, request_id: str, *, cancelled: bool = False) -> None:
        runtime = self._store.load_runtime(session_id)
        pending_ids = [item for item in runtime.pending_escalation_ids if item != request_id]
        next_phase = runtime.previous_phase or "running_llm"
        if next_phase == "waiting_escalation":
            next_phase = "running_llm"
        self.transition(
            session_id,
            to_phase=next_phase,
            event_type="escalation_resolved",
            turn_id=runtime.current_turn_id,
            updates={"pending_escalation_ids": pending_ids},
            payload={"request_id": request_id, "cancelled": cancelled},
        )
