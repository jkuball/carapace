from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import yaml

from carapace.sandbox.events import SandboxEventType, SandboxRuntimeEvent
from carapace.sandbox.operations import SandboxOperation, SandboxOperationPhase, utc_now
from carapace.sandbox.state import SandboxRuntimePhase, SandboxRuntimeState


class SandboxPersistence(Protocol):
    def load_sandbox_runtime(self, session_id: str) -> SandboxRuntimeState | None: ...

    def save_sandbox_runtime(self, runtime: SandboxRuntimeState) -> None: ...

    def load_sandbox_runtime_events(self, session_id: str) -> list[SandboxRuntimeEvent]: ...

    def append_sandbox_runtime_events(self, session_id: str, events: list[SandboxRuntimeEvent]) -> None: ...

    def load_sandbox_operation(self, session_id: str, operation_id: str) -> SandboxOperation | None: ...

    def save_sandbox_operation(self, operation: SandboxOperation) -> None: ...


class FileSandboxPersistence:
    def __init__(self, data_dir: Path) -> None:
        self._sessions_dir = data_dir / "sessions"

    def _sandbox_runtime_path(self, session_id: str) -> Path:
        return self._sessions_dir / session_id / "sandbox_runtime.yaml"

    def load_sandbox_runtime(self, session_id: str) -> SandboxRuntimeState | None:
        path = self._sandbox_runtime_path(session_id)
        if not path.exists():
            return None
        with open(path) as f:
            raw = yaml.safe_load(f)
        if not raw:
            return None
        return SandboxRuntimeState.model_validate(raw)

    def save_sandbox_runtime(self, runtime: SandboxRuntimeState) -> None:
        session_dir = self._sessions_dir / runtime.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(self._sandbox_runtime_path(runtime.session_id), "w") as f:
            yaml.dump(runtime.model_dump(mode="json"), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _sandbox_runtime_events_path(self, session_id: str) -> Path:
        return self._sessions_dir / session_id / "sandbox_events.yaml"

    def load_sandbox_runtime_events(self, session_id: str) -> list[SandboxRuntimeEvent]:
        path = self._sandbox_runtime_events_path(session_id)
        if not path.exists():
            return []
        events: list[SandboxRuntimeEvent] = []
        with open(path) as f:
            for doc in yaml.safe_load_all(f):
                if doc:
                    events.append(SandboxRuntimeEvent.model_validate(doc))
        return events

    def append_sandbox_runtime_events(self, session_id: str, events: list[SandboxRuntimeEvent]) -> None:
        session_dir = self._sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        path = self._sandbox_runtime_events_path(session_id)
        with open(path, "a") as f:
            for event in events:
                f.write("---\n")
                yaml.dump(
                    event.model_dump(mode="json"),
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

    def _sandbox_operation_dir(self, session_id: str) -> Path:
        return self._sessions_dir / session_id / "sandbox_operations"

    def _sandbox_operation_path(self, session_id: str, operation_id: str) -> Path:
        return self._sandbox_operation_dir(session_id) / f"{operation_id}.yaml"

    def load_sandbox_operation(self, session_id: str, operation_id: str) -> SandboxOperation | None:
        path = self._sandbox_operation_path(session_id, operation_id)
        if not path.exists():
            return None
        with open(path) as f:
            raw = yaml.safe_load(f)
        if not raw:
            return None
        return SandboxOperation.model_validate(raw)

    def save_sandbox_operation(self, operation: SandboxOperation) -> None:
        operation_dir = self._sandbox_operation_dir(operation.session_id)
        operation_dir.mkdir(parents=True, exist_ok=True)
        with open(self._sandbox_operation_path(operation.session_id, operation.operation_id), "w") as f:
            yaml.dump(
                operation.model_dump(mode="json"),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )


class SandboxTransitionError(RuntimeError):
    pass


class SandboxVersionConflictError(SandboxTransitionError):
    pass


class SandboxStore:
    def __init__(self, manager: SandboxPersistence):
        self._manager = manager

    def load_runtime(self, session_id: str) -> SandboxRuntimeState:
        runtime = self._manager.load_sandbox_runtime(session_id)
        if runtime is not None:
            return runtime
        return SandboxRuntimeState(session_id=session_id)

    def load_events(self, session_id: str) -> list[SandboxRuntimeEvent]:
        return self._manager.load_sandbox_runtime_events(session_id)

    def create_operation(
        self,
        operation: SandboxOperation,
        *,
        event_type: SandboxEventType = "sandbox_operation_queued",
        payload: Mapping[str, Any] | None = None,
    ) -> SandboxOperation:
        self._manager.save_sandbox_operation(operation)
        event = SandboxRuntimeEvent(
            type=event_type,
            session_id=operation.session_id,
            operation_id=operation.operation_id,
            to_operation_phase=operation.phase,
            payload=dict(payload or {}),
        )
        self._manager.append_sandbox_runtime_events(operation.session_id, [event])
        return operation

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
