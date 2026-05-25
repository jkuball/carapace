"""Data upgrade tests (no LLM tokens needed)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from carapace.upgrade import upgrade_data_dir


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_upgrade_data_dir_adds_user_ownership_and_moves_knowledge(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "SECURITY.md").write_text("Do no harm.\n", encoding="utf-8")
    (tmp_path / "jobs.yaml").write_text(
        yaml.safe_dump({"jobs": [{"id": "daily", "prompt": "Brief me"}]}),
        encoding="utf-8",
    )
    subscriptions_dir = tmp_path / "notifications" / "subscriptions"
    subscriptions_dir.mkdir(parents=True)
    (subscriptions_dir / "sub-1.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "sub-1",
                "owner_key": "",
                "endpoint": "https://push.example.test/sub-1",
                "p256dh": "key",
                "auth": "auth",
                "subscribed_at": "2026-05-12T00:00:00Z",
                "expires_at": "2026-06-12T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "matrix_token.json").write_text(
        json.dumps({"access_token": "matrix-token", "device_id": "DEVICE"}),
        encoding="utf-8",
    )
    (tmp_path / "sandbox_tokens.json").write_text(
        json.dumps({"session-1": "sandbox-token"}),
        encoding="utf-8",
    )

    summary = upgrade_data_dir(tmp_path, " Thies ")

    assert "sessions" in summary
    assert _read_yaml(session_dir / "meta.yaml") == {"user": "thies"}
    assert _read_yaml(tmp_path / "jobs.yaml")["jobs"][0]["user"] == "thies"
    assert _read_yaml(subscriptions_dir / "sub-1.yaml")["user"] == "thies"
    assert (tmp_path / "knowledges" / "thies" / "SECURITY.md").read_text(encoding="utf-8") == "Do no harm.\n"
    assert not (tmp_path / "knowledge").exists()

    matrix_tokens = _read_yaml(tmp_path / "matrix_token.yaml")["tokens"]
    assert matrix_tokens == [{"access_token": "matrix-token", "device_id": "DEVICE", "user": "thies"}]
    assert (tmp_path / "matrix_token.json.bak").exists()

    sandbox_tokens = _read_yaml(tmp_path / "sandbox_tokens.yaml")["tokens"]
    assert sandbox_tokens["session-1"] == {"token": "sandbox-token", "user": "thies"}
    assert (tmp_path / "sandbox_tokens.json.bak").exists()

    users = _read_yaml(tmp_path / "auth" / "users.yaml")["users"]
    assert users["thies"]["enabled"] is False
    assert users["thies"]["config"]["default_models"]["agent"] == "anthropic:claude-sonnet-4-6"
