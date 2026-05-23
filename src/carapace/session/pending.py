from __future__ import annotations

from typing import Any

from carapace.session.state import SessionRuntime


def pending_approval_requests(runtime: SessionRuntime, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not runtime.pending_approval_ids:
        return []

    resolved_ids = {
        event.get("tool_call_id")
        for event in events
        if event.get("role") == "approval_response" and isinstance(event.get("tool_call_id"), str)
    }
    requested_ids = {item for item in runtime.pending_approval_ids if item not in resolved_ids}
    if not requested_ids:
        return []

    pending_by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("role") != "approval_request":
            continue
        tool_call_id = event.get("tool_call_id")
        if not isinstance(tool_call_id, str) or tool_call_id not in requested_ids or tool_call_id in pending_by_id:
            continue
        pending_by_id[tool_call_id] = {
            "tool_call_id": tool_call_id,
            "tool": event.get("tool", ""),
            "args": event.get("args", {}),
            "explanation": event.get("explanation", ""),
            "risk_level": event.get("risk_level", ""),
        }
    return list(pending_by_id.values())


def pending_escalations(runtime: SessionRuntime, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not runtime.pending_escalation_ids:
        return []

    resolved_ids = {
        event.get("request_id")
        for event in events
        if event.get("role") in {"domain_access_approval", "git_push_approval", "credential_approval"}
        and event.get("decision") is not None
        and isinstance(event.get("request_id"), str)
    }
    requested_ids = {item for item in runtime.pending_escalation_ids if item not in resolved_ids}
    if not requested_ids:
        return []

    pending_by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        request_id = event.get("request_id")
        if not isinstance(request_id, str) or request_id not in requested_ids or request_id in pending_by_id:
            continue
        role = event.get("role")
        if role == "git_push_approval":
            pending_by_id[request_id] = {
                "request_id": request_id,
                "kind": "git_push",
                "ref": event.get("ref", ""),
                "explanation": event.get("explanation", ""),
                "changed_files": event.get("changed_files", []),
            }
        elif role == "credential_approval":
            vault_paths = event.get("vault_paths", [])
            pending_by_id[request_id] = {
                "request_id": request_id,
                "kind": "credential_access",
                "vault_path": vault_paths[0] if vault_paths else "",
                "vault_paths": vault_paths,
                "names": event.get("names", []),
                "descriptions": event.get("descriptions", []),
                "skill_name": event.get("skill_name"),
                "explanation": event.get("explanation", ""),
            }
        elif role == "domain_access_approval":
            pending_by_id[request_id] = {
                "request_id": request_id,
                "kind": "domain_access",
                "domain": event.get("domain", ""),
                "command": event.get("command", ""),
            }
    return list(pending_by_id.values())
