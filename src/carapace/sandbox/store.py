from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from carapace.sandbox.events import SandboxEventType, SandboxRuntimeEvent
from carapace.sandbox.operations import SandboxOperation, SandboxOperationPhase, utc_now
from carapace.sandbox.state import SandboxRuntimePhase, SandboxRuntimeState
from carapace.session.manager import SessionManager


class SandboxTransitionError(RuntimeError):
    pass


class SandboxVersionConflictError(SandboxTransitionError):
    pass


class SandboxStore:
    def __init__(self, manager: SessionManager):
        self._manager = manager

    def load_runtime(self, session_id: str) -> SandboxRuntimeState:
        runtime = self._manager.load_sandbox_runtime(session_id)
        if runtime is not None:
            return runtime
        return SandboxRuntimeState(session_id=session_id)

    def load_events(self, session_id: str) -> list[SandboxRuntimeEvent]:
        return self._manager.load_sandbox_runtime_events(session_id)

    def transition_runtime(
        self,
        session_id: str,
        *,
        to_phase: SandboxRuntimePhase,
        event_type: SandboxEventType,
        expected_phase: SandboxRuntimePhase | None = None,
        expected_version: int | None = None,
        operation_id: str | None = None,
        updates: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> SandboxRuntimeState:
        current = self.load_runtime(session_id)
        if expected_phase is not None and current.phase != expected_phase:
            raise SandboxTransitionError(
                f"Cannot transition sandbox {session_id} from {current.phase!r}; expected {expected_phase!r}"
            )
        if expected_version is not None and current.version != expected_version:
            raise SandboxVersionConflictError(
                f"Cannot transition sandbox {session_id} at version {current.version}; expected {expected_version}"
            )

        next_values: dict[str, Any] = {
            "phase": to_phase,
            "version": current.version + 1,
            "updated_at": utc_now(),
        }
        if operation_id is not None:
            next_values["active_operation_id"] = operation_id
        if updates:
            next_values.update(updates)
        runtime = SandboxRuntimeState.model_validate(current.model_copy(update=next_values).model_dump())
        event = SandboxRuntimeEvent(
            type=event_type,
            session_id=session_id,
            operation_id=operation_id or runtime.active_operation_id,
            from_runtime_phase=current.phase,
            to_runtime_phase=runtime.phase,
            payload=dict(payload or {}),
        )
        self._manager.save_sandbox_runtime(runtime)
        self._manager.append_sandbox_runtime_events(session_id, [event])
        return runtime

    def transition_operation(
        self,
        session_id: str,
        operation_id: str,
        *,
        to_phase: SandboxOperationPhase,
        event_type: SandboxEventType,
        expected_phase: SandboxOperationPhase | None = None,
        expected_version: int | None = None,
        updates: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> SandboxOperation:
        current = self._manager.load_sandbox_operation(session_id, operation_id)
        if current is None:
            raise SandboxTransitionError(f"Sandbox operation {operation_id!r} does not exist for session {session_id}")
        if expected_phase is not None and current.phase != expected_phase:
            raise SandboxTransitionError(
                f"Cannot transition sandbox operation {operation_id} from {current.phase!r}; "
                f"expected {expected_phase!r}"
            )
        if expected_version is not None and current.version != expected_version:
            raise SandboxVersionConflictError(
                f"Cannot transition sandbox operation {operation_id} at version {current.version}; "
                f"expected {expected_version}"
            )

        next_values: dict[str, Any] = {
            "phase": to_phase,
            "version": current.version + 1,
            "updated_at": utc_now(),
        }
        if updates:
            next_values.update(updates)
        operation = SandboxOperation.model_validate(current.model_copy(update=next_values).model_dump())
        event = SandboxRuntimeEvent(
            type=event_type,
            session_id=session_id,
            operation_id=operation_id,
            from_operation_phase=current.phase,
            to_operation_phase=operation.phase,
            payload=dict(payload or {}),
        )
        self._manager.save_sandbox_operation(operation)
        self._manager.append_sandbox_runtime_events(session_id, [event])
        return operation
