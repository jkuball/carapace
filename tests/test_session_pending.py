from __future__ import annotations

from typing import Any

from carapace.session.pending import pending_approval_requests, pending_escalations
from carapace.session.state import SessionRuntime


def test_pending_approval_requests_include_durable_tool_approvals() -> None:
    runtime = SessionRuntime(
        session_id="session-1",
        phase="waiting_tool_approval",
        pending_approval_ids=["tool-1"],
    )
    events: list[dict[str, Any]] = [
        {
            "role": "approval_request",
            "tool_call_id": "tool-1",
            "tool": "exec",
            "args": {"command": "date"},
            "explanation": "run date",
            "risk_level": "low",
        }
    ]

    assert pending_approval_requests(runtime, events) == [
        {
            "tool_call_id": "tool-1",
            "tool": "exec",
            "args": {"command": "date"},
            "explanation": "run date",
            "risk_level": "low",
        }
    ]


def test_pending_approval_requests_skip_resolved_tool_approvals() -> None:
    runtime = SessionRuntime(
        session_id="session-1",
        phase="waiting_tool_approval",
        pending_approval_ids=["tool-1"],
    )
    events: list[dict[str, Any]] = [
        {"role": "approval_request", "tool_call_id": "tool-1", "tool": "exec", "args": {}},
        {"role": "approval_response", "tool_call_id": "tool-1", "decision": "approved"},
    ]

    assert pending_approval_requests(runtime, events) == []


def test_pending_escalations_include_durable_credential_requests() -> None:
    runtime = SessionRuntime(
        session_id="session-1",
        phase="waiting_escalation",
        pending_escalation_ids=["req-1"],
    )
    events: list[dict[str, Any]] = [
        {
            "role": "credential_approval",
            "request_id": "req-1",
            "vault_paths": ["dev/api"],
            "names": ["api"],
            "descriptions": ["API token"],
            "explanation": "need token",
        }
    ]

    assert pending_escalations(runtime, events) == [
        {
            "request_id": "req-1",
            "kind": "credential_access",
            "vault_path": "dev/api",
            "vault_paths": ["dev/api"],
            "names": ["api"],
            "descriptions": ["API token"],
            "skill_name": None,
            "explanation": "need token",
        }
    ]


def test_pending_escalations_skip_resolved_requests() -> None:
    runtime = SessionRuntime(
        session_id="session-1",
        phase="waiting_escalation",
        pending_escalation_ids=["req-1"],
    )
    events: list[dict[str, Any]] = [
        {"role": "domain_access_approval", "request_id": "req-1", "domain": "example.com"},
        {"role": "domain_access_approval", "request_id": "req-1", "decision": "allow"},
    ]

    assert pending_escalations(runtime, events) == []
