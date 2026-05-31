"""Tests for config loading (no LLM tokens needed)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from carapace.config import load_config, load_workspace_file, resolve_knowledge_repos_dir, resolve_user_knowledge_dir


def test_load_config_defaults(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert cfg.carapace.log_level == "info"
    assert cfg.cache.ttl_seconds == 1800
    assert cfg.cache.redis_url == "redis://localhost:6379/0"
    assert cfg.agent.model == "anthropic:claude-sonnet-4-6"
    assert cfg.sessions.commit.enabled is True
    assert cfg.sessions.commit.autosave_inactivity_hours == 4
    assert cfg.sandbox.k8s_session_pvc_size == "1Gi"
    assert cfg.sandbox.k8s_session_pvc_storage_class == ""


def test_load_config_creates_missing_file(tmp_path: Path):
    config_path = tmp_path / "config.yaml"

    cfg = load_config(tmp_path)

    assert cfg.carapace.log_level == "info"
    assert config_path.read_text() == "{}\n"


def test_load_config_from_yaml(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "cache:\n  ttl_seconds: 120\n  redis_url: redis://redis:6379/0\n"
        "agent:\n  model: anthropic:claude-sonnet-4-6\n  sentinel_model: anthropic:claude-haiku-4-5\n"
        "  sentinel_timeout_seconds: 15\n"
        "  tool_output_max_chars: 5000\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.cache.ttl_seconds == 120
    assert cfg.cache.redis_url == "redis://redis:6379/0"
    assert cfg.agent.model == "anthropic:claude-sonnet-4-6"
    assert cfg.agent.sentinel_model == "anthropic:claude-haiku-4-5"
    assert cfg.agent.sentinel_timeout_seconds == 15
    assert cfg.agent.tool_output_max_chars == 5000


def test_load_config_rejects_global_channels_config(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "channels:\n"
        "  matrix:\n"
        "    enabled: true\n"
        "    homeserver: https://matrix.example.com\n"
        "    user_id: '@carapace:example.com'\n"
    )

    with pytest.raises(ValidationError):
        load_config(tmp_path)


def test_load_config_rejects_unknown_nested_config_key(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "agent:\n"
        "  model: anthropic:claude-sonnet-4-6\n"
        "  sentinel_model: anthropic:claude-haiku-4-5\n"
        "  title_model: anthropic:claude-haiku-4-5\n"
        "  unexpected_key: true\n"
    )

    with pytest.raises(ValidationError):
        load_config(tmp_path)


def test_load_config_rejects_global_git_config(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "git:\n  remote: https://gitea.example.com/team/knowledge.git\n  token:\n    env: CARAPACE_GIT_TOKEN\n"
    )

    with pytest.raises(ValidationError):
        load_config(tmp_path)


def test_load_config_rejects_global_credentials_config(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "credentials:\n  backends:\n    vault:\n      type: bitwarden\n      url: http://127.0.0.1:8087\n"
    )

    with pytest.raises(ValidationError):
        load_config(tmp_path)


def test_load_workspace_file_missing(tmp_path: Path):
    result = load_workspace_file(tmp_path, "SECURITY.md")
    assert result == ""


def test_load_workspace_file(tmp_path: Path):
    (tmp_path / "SECURITY.md").write_text("# Test Policy\nBe safe.")
    result = load_workspace_file(tmp_path, "SECURITY.md")
    assert "Test Policy" in result


def test_resolve_knowledge_repos_dir_uses_knowledges_under_data_dir(tmp_path: Path) -> None:
    assert resolve_knowledge_repos_dir(tmp_path) == (tmp_path / "knowledges").resolve()


def test_resolve_user_knowledge_dir_uses_normalized_username(tmp_path: Path) -> None:
    assert resolve_user_knowledge_dir(tmp_path, "thies") == (tmp_path / "knowledges" / "thies").resolve()


def test_resolve_user_knowledge_dir_rejects_noncanonical_username(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="username must be lowercase"):
        resolve_user_knowledge_dir(tmp_path, "Thies")
