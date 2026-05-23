from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from carapace.session.events import SessionEventType, SessionRuntimeEvent
from carapace.session.manager import SessionManager
from carapace.session.state import SessionRuntime, SessionRuntimePhase, utc_now


class SessionTransitionError(RuntimeError):
    pass


class SessionVersionConflictError(SessionTransitionError):
    pass


class SessionStore:
    def __init__(self, manager: SessionManager):
        self._manager = manager

    def load_runtime(self, session_id: str) -> SessionRuntime:
        runtime = self._manager.load_session_runtime(session_id)
        if runtime is not None:
            return runtime
        return SessionRuntime(session_id=session_id)

    def save_runtime(self, runtime: SessionRuntime) -> None:
        self._manager.save_session_runtime(runtime)

    def load_events(self, session_id: str) -> list[SessionRuntimeEvent]:
        return self._manager.load_session_runtime_events(session_id)

    def transition(
        self,
        session_id: str,
        *,
        to_phase: SessionRuntimePhase,
        event_type: SessionEventType,
        expected_phase: SessionRuntimePhase | None = None,
        expected_version: int | None = None,
        turn_id: str | None = None,
        command_id: str | None = None,
        updates: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> SessionRuntime:
        current = self.load_runtime(session_id)
        if expected_phase is not None and current.phase != expected_phase:
            raise SessionTransitionError(
                f"Cannot transition session {session_id} from {current.phase!r}; expected {expected_phase!r}"
            )
        if expected_version is not None and current.version != expected_version:
            raise SessionVersionConflictError(
                f"Cannot transition session {session_id} at version {current.version}; expected {expected_version}"
            )

        next_values: dict[str, Any] = {
            "phase": to_phase,
            "version": current.version + 1,
            "previous_phase": current.phase,
            "updated_at": utc_now(),
        }
        if turn_id is not None:
            next_values["current_turn_id"] = turn_id
        if updates:
            next_values.update(updates)
        runtime = SessionRuntime.model_validate(current.model_copy(update=next_values).model_dump())
        event = SessionRuntimeEvent(
            type=event_type,
            session_id=session_id,
            turn_id=turn_id or runtime.current_turn_id,
            command_id=command_id,
            from_phase=current.phase,
            to_phase=runtime.phase,
            payload=dict(payload or {}),
        )
        self._manager.save_session_runtime(runtime)
        self._manager.append_session_runtime_events(session_id, [event])
        return runtime
