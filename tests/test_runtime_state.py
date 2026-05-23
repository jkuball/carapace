from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from carapace.sandbox.events import SandboxRuntimeEvent
from carapace.sandbox.operations import SandboxOperation, SandboxOperationLease
from carapace.sandbox.state import SandboxLease, SandboxRuntimeState
from carapace.sandbox.store import SandboxStore, SandboxTransitionError, SandboxVersionConflictError
from carapace.session.events import SessionRuntimeEvent
from carapace.session.manager import SessionManager
from carapace.session.state import RuntimeLease, SessionRuntime
from carapace.session.store import SessionStore, SessionTransitionError, SessionVersionConflictError


def test_session_runtime_roundtrip(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    lease = RuntimeLease(
        owner="controller-1",
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=30),
    )
    runtime = SessionRuntime(
        session_id=session.session_id,
        phase="waiting_tool_approval",
        version=3,
        current_turn_id="turn-1",
        pending_approval_ids=["approval-1"],
        lease=lease,
    )

    mgr.save_session_runtime(runtime)

    reloaded = mgr.load_session_runtime(session.session_id)
    assert reloaded is not None
    assert reloaded.phase == "waiting_tool_approval"
    assert reloaded.current_turn_id == "turn-1"
    assert reloaded.pending_approval_ids == ["approval-1"]
    assert reloaded.lease is not None
    assert reloaded.lease.owner == "controller-1"
    assert reloaded.is_active is True
    assert reloaded.is_waiting_for_user is True


def test_session_runtime_can_be_cleared(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    mgr.save_session_runtime(SessionRuntime(session_id=session.session_id))

    mgr.clear_session_runtime(session.session_id)

    assert mgr.load_session_runtime(session.session_id) is None


def test_sandbox_runtime_roundtrip(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    lease = SandboxLease(
        owner="sandbox-controller-1",
        acquired_at=datetime.now(tz=UTC),
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=30),
    )
    runtime = SandboxRuntimeState(
        session_id=session.session_id,
        phase="ready",
        runtime="kubernetes",
        resource_id="carapace-sandbox-abc",
        resource_kind="statefulset",
        needs_runtime_setup=True,
        lease=lease,
    )

    mgr.save_sandbox_runtime(runtime)

    reloaded = mgr.load_sandbox_runtime(session.session_id)
    assert reloaded is not None
    assert reloaded.phase == "ready"
    assert reloaded.runtime == "kubernetes"
    assert reloaded.resource_kind == "statefulset"
    assert reloaded.needs_runtime_setup is True
    assert reloaded.lease is not None
    assert reloaded.lease.owner == "sandbox-controller-1"


def test_sandbox_operation_roundtrip_and_listing(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    operation = SandboxOperation(
        operation_id="op-1",
        session_id=session.session_id,
        phase="running_command",
        tool_call_id="tool-1",
        command="echo hello",
        contexts=["skill:example"],
        temporary_domains=["example.com"],
        lease=SandboxOperationLease(
            owner="operation-runner-1",
            expires_at=datetime.now(tz=UTC) + timedelta(seconds=30),
        ),
    )

    mgr.save_sandbox_operation(operation)

    reloaded = mgr.load_sandbox_operation(session.session_id, "op-1")
    assert reloaded is not None
    assert reloaded.phase == "running_command"
    assert reloaded.command == "echo hello"
    assert reloaded.contexts == ["skill:example"]
    assert reloaded.temporary_domains == ["example.com"]
    assert reloaded.is_terminal is False

    operations = mgr.list_sandbox_operations(session.session_id)
    assert [item.operation_id for item in operations] == ["op-1"]

    mgr.clear_sandbox_operation(session.session_id, "op-1")
    assert mgr.load_sandbox_operation(session.session_id, "op-1") is None


def test_runtime_events_carry_phase_changes() -> None:
    session_event = SessionRuntimeEvent(
        type="turn_phase_changed",
        session_id="session-1",
        turn_id="turn-1",
        from_phase="queued",
        to_phase="running_llm",
    )
    sandbox_event = SandboxRuntimeEvent(
        type="sandbox_operation_phase_changed",
        session_id="session-1",
        operation_id="op-1",
        from_operation_phase="queued",
        to_operation_phase="ensuring_sandbox",
    )

    assert session_event.to_phase == "running_llm"
    assert sandbox_event.to_operation_phase == "ensuring_sandbox"


def test_session_store_transition_persists_runtime_and_event(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    store = SessionStore(mgr)

    runtime = store.transition(
        session.session_id,
        expected_phase="idle",
        to_phase="queued",
        event_type="turn_queued",
        turn_id="turn-1",
        command_id="command-1",
        payload={"source": "websocket"},
    )

    assert runtime.phase == "queued"
    assert runtime.previous_phase == "idle"
    assert runtime.version == 1
    assert mgr.load_session_runtime(session.session_id) == runtime
    events = store.load_events(session.session_id)
    assert len(events) == 1
    assert events[0].type == "turn_queued"
    assert events[0].from_phase == "idle"
    assert events[0].to_phase == "queued"
    assert events[0].payload == {"source": "websocket"}


def test_session_store_rejects_unexpected_phase_and_version(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    store = SessionStore(mgr)

    try:
        store.transition(
            session.session_id,
            expected_phase="running_llm",
            to_phase="finalizing",
            event_type="turn_finalized",
        )
    except SessionTransitionError:
        pass
    else:
        raise AssertionError("expected phase mismatch")

    try:
        store.transition(
            session.session_id,
            expected_phase="idle",
            expected_version=7,
            to_phase="queued",
            event_type="turn_queued",
        )
    except SessionVersionConflictError:
        pass
    else:
        raise AssertionError("expected version mismatch")


def test_sandbox_store_runtime_transition_persists_event(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    store = SandboxStore(mgr)

    runtime = store.transition_runtime(
        session.session_id,
        expected_phase="missing",
        to_phase="starting",
        event_type="sandbox_starting",
        operation_id="op-1",
    )

    assert runtime.phase == "starting"
    assert runtime.active_operation_id == "op-1"
    assert runtime.version == 1
    events = store.load_events(session.session_id)
    assert len(events) == 1
    assert events[0].type == "sandbox_starting"
    assert events[0].from_runtime_phase == "missing"
    assert events[0].to_runtime_phase == "starting"


def test_sandbox_store_operation_transition_persists_event(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    store = SandboxStore(mgr)
    mgr.save_sandbox_operation(
        SandboxOperation(
            operation_id="op-1",
            session_id=session.session_id,
            command="echo hi",
        )
    )

    operation = store.transition_operation(
        session.session_id,
        "op-1",
        expected_phase="queued",
        to_phase="ensuring_sandbox",
        event_type="sandbox_operation_phase_changed",
        payload={"reason": "command"},
    )

    assert operation.phase == "ensuring_sandbox"
    assert operation.version == 1
    events = store.load_events(session.session_id)
    assert len(events) == 1
    assert events[0].from_operation_phase == "queued"
    assert events[0].to_operation_phase == "ensuring_sandbox"
    assert events[0].payload == {"reason": "command"}


def test_sandbox_store_rejects_unexpected_phase_and_version(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.create_session()
    store = SandboxStore(mgr)

    try:
        store.transition_runtime(
            session.session_id,
            expected_phase="ready",
            to_phase="suspending",
            event_type="sandbox_suspending",
        )
    except SandboxTransitionError:
        pass
    else:
        raise AssertionError("expected sandbox phase mismatch")

    try:
        store.transition_runtime(
            session.session_id,
            expected_phase="missing",
            expected_version=4,
            to_phase="starting",
            event_type="sandbox_starting",
        )
    except SandboxVersionConflictError:
        pass
    else:
        raise AssertionError("expected sandbox version mismatch")
