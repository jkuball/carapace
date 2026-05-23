from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

from carapace.sandbox.events import SandboxEventType
from carapace.sandbox.operations import SandboxOperation, SandboxOperationPhase
from carapace.sandbox.runtime import ExecResult, SandboxRuntimeKind, SandboxStatus
from carapace.sandbox.state import SandboxRuntimePhase
from carapace.sandbox.store import SandboxStore


def _operation_id() -> str:
    return f"sandbox-op-{secrets.token_hex(8)}"


def _phase_for_status(status: SandboxStatus) -> SandboxRuntimePhase:
    match status:
        case "running":
            return "ready"
        case "scaled_down" | "stopped":
            return "suspended"
        case "pending":
            return "starting"
        case "error":
            return "error"
        case "missing":
            return "missing"


def _truncate_output(output: str, limit: int = 4000) -> str:
    if len(output) <= limit:
        return output
    return output[:limit] + "\n[truncated]"


class SandboxRuntimeController:
    def __init__(self, store: SandboxStore):
        self._store = store

    def starting(self, session_id: str, *, runtime: SandboxRuntimeKind) -> None:
        self._store.transition_runtime(
            session_id,
            to_phase="starting",
            event_type="sandbox_starting",
            updates={
                "runtime": runtime,
                "needs_runtime_setup": False,
                "last_error": None,
            },
        )

    def ready(
        self,
        session_id: str,
        *,
        runtime: SandboxRuntimeKind,
        resource_id: str | None,
        resource_kind: str | None = None,
        storage_present: bool = False,
        needs_runtime_setup: bool = False,
    ) -> None:
        self._store.transition_runtime(
            session_id,
            to_phase="ready",
            event_type="sandbox_ready",
            updates={
                "runtime": runtime,
                "resource_id": resource_id,
                "resource_kind": resource_kind,
                "storage_present": storage_present,
                "needs_runtime_setup": needs_runtime_setup,
                "last_error": None,
            },
        )

    def refreshed(
        self,
        session_id: str,
        *,
        runtime: SandboxRuntimeKind,
        status: SandboxStatus,
        resource_id: str | None,
        resource_kind: str | None,
        storage_present: bool,
    ) -> None:
        self._store.transition_runtime(
            session_id,
            to_phase=_phase_for_status(status),
            event_type="sandbox_snapshot_refreshed",
            updates={
                "runtime": runtime,
                "resource_id": resource_id,
                "resource_kind": resource_kind,
                "storage_present": storage_present,
                "needs_runtime_setup": False,
                "last_error": None,
            },
            payload={"status": status},
        )

    def suspending(self, session_id: str) -> None:
        self._store.transition_runtime(session_id, to_phase="suspending", event_type="sandbox_suspending")

    def resetting(self, session_id: str) -> None:
        self._store.transition_runtime(session_id, to_phase="resetting", event_type="sandbox_resetting")

    def destroying(self, session_id: str) -> None:
        self._store.transition_runtime(session_id, to_phase="destroying", event_type="sandbox_destroying")

    def destroyed(self, session_id: str) -> None:
        self._store.transition_runtime(
            session_id,
            to_phase="missing",
            event_type="sandbox_destroyed",
            updates={
                "resource_id": None,
                "resource_kind": None,
                "storage_present": False,
                "needs_runtime_setup": False,
                "active_operation_id": None,
                "last_error": None,
            },
        )

    def failed(self, session_id: str, error: str) -> None:
        self._store.transition_runtime(
            session_id,
            to_phase="error",
            event_type="sandbox_lifecycle_failed",
            updates={"last_error": error, "needs_runtime_setup": False},
            payload={"error": error},
        )

    def queue_operation(
        self,
        session_id: str,
        *,
        command: str,
        cwd: str | None,
        contexts: list[str],
        temporary_domains: set[str] | None,
    ) -> SandboxOperation:
        operation = SandboxOperation(
            operation_id=_operation_id(),
            session_id=session_id,
            command=command,
            cwd=cwd,
            contexts=contexts,
            temporary_domains=sorted(temporary_domains or set()),
        )
        self._store.create_operation(operation, payload={"cwd": cwd})
        self._store.transition_runtime(
            session_id,
            to_phase=self._store.load_runtime(session_id).phase,
            event_type="sandbox_operation_queued",
            operation_id=operation.operation_id,
            updates={"active_operation_id": operation.operation_id},
        )
        return operation

    def operation_phase(
        self,
        session_id: str,
        operation_id: str,
        phase: SandboxOperationPhase,
        event_type: SandboxEventType = "sandbox_operation_phase_changed",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self._store.transition_operation(
            session_id,
            operation_id,
            to_phase=phase,
            event_type=event_type,
            payload=payload,
        )

    def operation_finished(self, session_id: str, operation_id: str, result: ExecResult) -> None:
        if result.exit_code != 0:
            self._store.transition_operation(
                session_id,
                operation_id,
                to_phase="failed",
                event_type="sandbox_operation_failed",
                updates={
                    "exit_code": result.exit_code,
                    "stdout": _truncate_output(result.output),
                    "last_error": f"Command exited with {result.exit_code}",
                },
                payload={"exit_code": result.exit_code},
            )
            self._store.transition_runtime(
                session_id,
                to_phase=self._store.load_runtime(session_id).phase,
                event_type="sandbox_operation_failed",
                operation_id=operation_id,
                updates={"active_operation_id": None},
            )
            return

        self._store.transition_operation(
            session_id,
            operation_id,
            to_phase="completed",
            event_type="sandbox_operation_completed",
            updates={"exit_code": result.exit_code, "stdout": _truncate_output(result.output), "last_error": None},
            payload={"exit_code": result.exit_code},
        )
        self._store.transition_runtime(
            session_id,
            to_phase=self._store.load_runtime(session_id).phase,
            event_type="sandbox_operation_completed",
            operation_id=operation_id,
            updates={"active_operation_id": None},
        )

    def operation_failed(self, session_id: str, operation_id: str, error: str) -> None:
        self._store.transition_operation(
            session_id,
            operation_id,
            to_phase="failed",
            event_type="sandbox_operation_failed",
            updates={"last_error": error},
            payload={"error": error},
        )
        self._store.transition_runtime(
            session_id,
            to_phase=self._store.load_runtime(session_id).phase,
            event_type="sandbox_operation_failed",
            operation_id=operation_id,
            updates={"active_operation_id": None},
        )

    def operation_interrupted(self, session_id: str, operation_id: str, error: str) -> None:
        self._store.transition_operation(
            session_id,
            operation_id,
            to_phase="interrupted",
            event_type="sandbox_operation_interrupted",
            updates={"last_error": error},
            payload={"error": error},
        )
        self._store.transition_runtime(
            session_id,
            to_phase=self._store.load_runtime(session_id).phase,
            event_type="sandbox_operation_interrupted",
            operation_id=operation_id,
            updates={"active_operation_id": None},
        )
