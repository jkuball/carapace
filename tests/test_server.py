"""Server smoke tests (no LLM tokens needed)."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

# We patch the server module globals directly for testing
import carapace.sandbox.state as sandbox_state
import carapace.server as srv
import carapace.server.jobs as server_jobs
import carapace.server.platform_settings as platform_settings
from carapace.auth import AuthStore
from carapace.bootstrap import ensure_data_dir
from carapace.config import load_config
from carapace.credentials import CredentialBackendError, CredentialRegistry
from carapace.git.store import GitStore
from carapace.jobs import JobsScheduler, JobsStore
from carapace.models.config import AgentConfig
from carapace.models.credentials import (
    BasicAuthConfig,
    BitwardenCredentialBackendConfig,
    CredentialMetadata,
    FileCredentialBackendConfig,
)
from carapace.models.jobs import JobDefinition
from carapace.models.matrix import MatrixTokenFile, MatrixTokensFile
from carapace.models.session import SessionBudget
from carapace.models.user import UserConfig
from carapace.notifications.presence import NotificationPresenceRegistry
from carapace.notifications.store import NotificationStore
from carapace.notifications.vapid import derive_vapid_public_key, ensure_vapid_config
from carapace.sandbox.manager import SandboxManager
from carapace.sandbox.state import SessionSandboxSnapshot
from carapace.security.context import CredentialAccessEntry
from carapace.server import app, sandbox_app
from carapace.session import SessionEngine, SessionManager
from carapace.session.archive import SessionArchiveResult, SessionArchiveService
from carapace.skills import SkillRegistry
from carapace.usage import LlmRequestState

_TEST_TOKEN = "test-bearer-token-for-server-tests"


class _FakeSessionListCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str | None, bool, bool], list[dict[str, object]]] = {}

    async def get_session_infos(
        self,
        *,
        user: str | None = None,
        include_archived: bool,
        include_message_count: bool,
        loader: Callable[[], list[dict[str, object]]],
    ) -> list[dict[str, object]]:
        key = (user, include_archived, include_message_count)
        cached = self._entries.get(key)
        if cached is not None:
            return cached
        loaded = loader()
        self._entries[key] = loaded
        return loaded

    def invalidate_sync(self) -> None:
        self._entries.clear()


@pytest.fixture(autouse=True)
def _setup_server(tmp_path, monkeypatch):
    """Initialise server globals with a temp data dir so tests don't need lifespan."""
    # Bogus key — the sentinel Agent validates the env var at construction
    # time, but these tests never call the LLM.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-for-tests")
    monkeypatch.setenv("CARAPACE_TOKEN", _TEST_TOKEN)
    monkeypatch.setenv("CARAPACE_CONFIG", str(tmp_path / "config.yaml"))
    ensure_data_dir(tmp_path)
    config = load_config(tmp_path)
    srv._session_list_cache = _FakeSessionListCache()
    session_mgr = SessionManager(tmp_path, on_change=srv._session_list_cache.invalidate_sync)
    registry = SkillRegistry(tmp_path / "skills")
    skill_catalog = registry.scan()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.get_domain_info.return_value = []
    sandbox_mgr.reset_session = AsyncMock()
    sandbox_mgr.destroy_session = AsyncMock()

    cred_reg = CredentialRegistry()

    async def credential_registry_for_session(_session_id: str) -> CredentialRegistry:
        return cred_reg

    git_store = MagicMock(spec=GitStore)
    git_store.commit = AsyncMock(return_value=True)
    srv._data_dir = tmp_path
    srv._config_path = tmp_path / "config.yaml"
    srv._config = config
    srv._user_credential_registries = {}
    srv._engine = SessionEngine(
        config=config,
        data_dir=tmp_path,
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=session_mgr,
        skill_catalog=skill_catalog,
        agent_model=None,
        sandbox_mgr=sandbox_mgr,
        credential_registry_for_session=credential_registry_for_session,
    )
    srv._session_archive = SessionArchiveService(
        knowledge_dir=tmp_path,
        git_store=git_store,
        session_mgr=session_mgr,
        config=config.sessions.commit,
    )
    srv._jobs_store = JobsStore(tmp_path)
    srv._jobs_scheduler = JobsScheduler(srv._jobs_store)
    srv._auth_store = AuthStore(tmp_path, config.auth)
    srv._auth_store.create_user(username="admin", password="admin-secret", display_name="Admin", roles=["admin"])
    srv._auth_store.create_user(username="thies", password="secret", display_name="Thies")
    srv._notification_store = NotificationStore(tmp_path)
    srv._notification_presence = NotificationPresenceRegistry(
        ttl=timedelta(seconds=config.notifications.presence_ttl_seconds)
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_select_knowledge_git_config_uses_single_enabled_user(tmp_path) -> None:
    store = AuthStore(tmp_path / "git-owner", srv._config.auth)
    store.create_user(
        username="Thies",
        password="secret",
        config=UserConfig.model_validate(
            {
                "git": {
                    "remote": " https://gitea.example.com/team/knowledge.git ",
                    "branch": " dev ",
                    "author": " Thies <thies@example.com> ",
                    "token": " token-value ",
                }
            }
        ),
    )

    selected = srv._select_knowledge_git_config(store)

    assert selected.owner == "thies"
    assert selected.remote == "https://gitea.example.com/team/knowledge.git"
    assert selected.branch == "dev"
    assert selected.author == "Thies <thies@example.com>"
    assert selected.token == "token-value"


def test_select_knowledge_git_config_rejects_multiple_enabled_user_remotes(tmp_path) -> None:
    store = AuthStore(tmp_path / "git-owners", srv._config.auth)
    for username in ("alice", "bob"):
        store.create_user(
            username=username,
            password="secret",
            config=UserConfig.model_validate({"git": {"remote": f"https://gitea.example.com/{username}.git"}}),
        )

    with pytest.raises(RuntimeError, match="multiple enabled users"):
        srv._select_knowledge_git_config(store)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    auth_session = srv._auth_store.create_session(username="thies")
    token = srv._auth_store.issue_session_token(auth_session)
    return {"Cookie": f"{srv._config.auth.cookie.name}={token}"}


@pytest.fixture()
def admin_auth_headers() -> dict[str, str]:
    auth_session = srv._auth_store.create_session(username="admin")
    token = srv._auth_store.issue_session_token(auth_session)
    return {"Cookie": f"{srv._config.auth.cookie.name}={token}"}


# --- Auth ---


def test_no_auth_returns_401(client):
    resp = client.get("/api/sessions")
    assert resp.status_code in (401, 403)


def test_bad_token_returns_401(client):
    resp = client.get("/api/sessions", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_login_sets_session_cookie(client):
    resp = client.post("/api/auth/login", json={"username": "thies", "password": "secret"})

    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "thies"
    assert resp.json()["user"]["roles"] == []
    assert srv._config.auth.cookie.name in resp.cookies

    meta_resp = client.get("/api/meta")

    assert meta_resp.status_code == 200


def test_logout_revokes_session_cookie(client):
    login_resp = client.post("/api/auth/login", json={"username": "thies", "password": "secret"})
    assert login_resp.status_code == 200

    logout_resp = client.post("/api/auth/logout")

    assert logout_resp.status_code == 204
    assert srv._config.auth.cookie.name not in client.cookies

    meta_resp = client.get("/api/meta")

    assert meta_resp.status_code == 401


def test_admin_user_management_requires_admin_role(client, auth_headers, admin_auth_headers):
    unauthenticated_resp = client.get("/api/admin/users")
    assert unauthenticated_resp.status_code == 401

    non_admin_resp = client.get("/api/admin/users", headers=auth_headers)
    assert non_admin_resp.status_code == 403

    token_resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {_TEST_TOKEN}"})
    assert token_resp.status_code == 401

    create_resp = client.post(
        "/api/admin/users",
        headers=admin_auth_headers,
        json={"username": "Ada", "password": "correct-horse-battery", "display_name": "Ada"},
    )

    assert create_resp.status_code == 201
    assert create_resp.json()["username"] == "ada"

    login_resp = client.post("/api/auth/login", json={"username": "ada", "password": "correct-horse-battery"})

    assert login_resp.status_code == 200


def test_admin_platform_settings_requires_admin_role(client, auth_headers, admin_auth_headers):
    unauthenticated_resp = client.get("/api/admin/platform/settings")
    assert unauthenticated_resp.status_code == 401

    non_admin_resp = client.get("/api/admin/platform/settings", headers=auth_headers)
    assert non_admin_resp.status_code == 403

    admin_resp = client.get("/api/admin/platform/settings", headers=admin_auth_headers)
    assert admin_resp.status_code == 200
    assert admin_resp.json()["settings"]["default_models"]["agent"] == srv._config.agent.model


def test_admin_platform_settings_reports_unwritable_config(
    client,
    admin_auth_headers,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(platform_settings.os, "access", lambda _path, _mode: False)

    resp = client.get("/api/admin/platform/settings", headers=admin_auth_headers)

    assert resp.status_code == 200
    assert resp.json()["config_writable"] is False


def test_admin_platform_settings_rejects_patch_when_config_unwritable(
    client,
    admin_auth_headers,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(platform_settings.os, "access", lambda _path, _mode: False)

    resp = client.patch(
        "/api/admin/platform/settings",
        headers=admin_auth_headers,
        json={
            "default_models": {
                "agent": "anthropic:claude-haiku-4-5",
                "sentinel": "anthropic:claude-haiku-4-5",
                "title": "anthropic:claude-haiku-4-5",
            },
            "default_budget": {},
            "available_models": [{"provider": "anthropic", "name": "claude-haiku-4-5"}],
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Config file is not writable"


def test_admin_platform_settings_updates_config_and_runtime(client, admin_auth_headers):
    resp = client.patch(
        "/api/admin/platform/settings",
        headers=admin_auth_headers,
        json={
            "default_models": {
                "agent": "local:test",
                "sentinel": "local:test",
                "title": "local:test",
            },
            "default_budget": {"cost_usd": "2.50", "tool_calls": 8},
            "available_models": [
                {"provider": "anthropic", "name": "claude-haiku-4-5"},
                {
                    "provider": "openai",
                    "name": "gpt-4o-mini",
                    "id": "local:test",
                    "base_url": "http://127.0.0.1:1234/v1",
                    "api_key": {"source": "env", "value": "ANTHROPIC_API_KEY"},
                    "max_input_tokens": 1234,
                    "thinking_budget_tokens": 0,
                },
            ],
        },
    )

    assert resp.status_code == 200
    body = resp.json()["settings"]
    assert body["default_models"] == {"agent": "local:test", "sentinel": "local:test", "title": "local:test"}
    assert srv._config.agent.model == "local:test"
    assert srv._engine.config.agent.model == "local:test"
    raw = yaml.safe_load((srv._config_path).read_text())
    assert raw["agent"]["model"] == "local:test"
    assert raw["agent"]["available_models"][1]["api_key"] == {"env": "ANTHROPIC_API_KEY"}


def test_admin_platform_settings_preserves_on_disk_agent_fields(client, admin_auth_headers):
    srv._config.agent = AgentConfig()
    srv._config_path.write_text(
        yaml.safe_dump(
            {
                "agent": {
                    "model": "anthropic:claude-haiku-4-5",
                    "sentinel_model": "anthropic:claude-haiku-4-5",
                    "title_model": "anthropic:claude-haiku-4-5",
                    "available_models": [
                        {"provider": "anthropic", "name": "claude-haiku-4-5"},
                        {
                            "provider": "openai",
                            "name": "gpt-4o-mini",
                            "id": "local:test",
                            "base_url": "http://127.0.0.1:1234/v1",
                            "api_key": {"env": "ANTHROPIC_API_KEY"},
                        },
                    ],
                    "max_parallel_llm": 7,
                    "max_sentinel_calls_per_tool_call": 3,
                    "sentinel_domain_batch_window_ms": 250,
                    "sentinel_timeout_seconds": 42,
                    "tool_output_max_chars": 12345,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    resp = client.patch(
        "/api/admin/platform/settings",
        headers=admin_auth_headers,
        json={
            "default_models": {
                "agent": "local:test",
                "sentinel": "local:test",
                "title": "local:test",
            },
            "default_budget": {},
            "available_models": [
                {"provider": "anthropic", "name": "claude-haiku-4-5"},
                {
                    "provider": "openai",
                    "name": "gpt-4o-mini",
                    "id": "local:test",
                    "base_url": "http://127.0.0.1:1234/v1",
                    "api_key": {"source": "env", "value": "ANTHROPIC_API_KEY"},
                },
            ],
        },
    )

    assert resp.status_code == 200
    raw = yaml.safe_load((srv._config_path).read_text())
    assert raw["agent"]["max_parallel_llm"] == 7
    assert raw["agent"]["max_sentinel_calls_per_tool_call"] == 3
    assert raw["agent"]["sentinel_domain_batch_window_ms"] == 250
    assert raw["agent"]["sentinel_timeout_seconds"] == 42
    assert raw["agent"]["tool_output_max_chars"] == 12345


def test_admin_platform_settings_preserves_raw_secret_when_value_omitted(client, admin_auth_headers):
    srv._config_path.write_text(
        yaml.safe_dump(
            {
                "agent": {
                    "model": "local:test",
                    "sentinel_model": "local:test",
                    "title_model": "local:test",
                    "available_models": [
                        {
                            "provider": "openai",
                            "name": "gpt-4o-mini",
                            "id": "local:test",
                            "base_url": "http://127.0.0.1:1234/v1",
                            "api_key": {"raw": "existing-secret"},
                        }
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    resp = client.patch(
        "/api/admin/platform/settings",
        headers=admin_auth_headers,
        json={
            "default_models": {
                "agent": "local:test",
                "sentinel": "local:test",
                "title": "local:test",
            },
            "default_budget": {},
            "available_models": [
                {
                    "provider": "openai",
                    "name": "gpt-4o-mini",
                    "id": "local:test",
                    "base_url": "http://127.0.0.1:1234/v1",
                    "api_key": {"source": "raw"},
                }
            ],
        },
    )

    assert resp.status_code == 200
    raw = yaml.safe_load((srv._config_path).read_text())
    assert raw["agent"]["available_models"][0]["api_key"] == {"raw": "existing-secret"}
    returned_model = resp.json()["settings"]["available_models"][0]
    assert returned_model["api_key"] == {"source": "raw", "value": None, "configured": True}


def test_admin_platform_settings_drops_openai_secret_when_provider_changes(client, admin_auth_headers):
    srv._config_path.write_text(
        yaml.safe_dump(
            {
                "agent": {
                    "model": "local:test",
                    "sentinel_model": "local:test",
                    "title_model": "local:test",
                    "available_models": [
                        {
                            "provider": "openai",
                            "name": "gpt-4o-mini",
                            "id": "local:test",
                            "base_url": "http://127.0.0.1:1234/v1",
                            "api_key": {"raw": "existing-secret"},
                            "thinking_budget_tokens": 128,
                        }
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    resp = client.patch(
        "/api/admin/platform/settings",
        headers=admin_auth_headers,
        json={
            "default_models": {
                "agent": "local:test",
                "sentinel": "local:test",
                "title": "local:test",
            },
            "default_budget": {},
            "available_models": [
                {
                    "provider": "anthropic",
                    "name": "claude-haiku-4-5",
                    "id": "local:test",
                }
            ],
        },
    )

    assert resp.status_code == 200
    raw_model = yaml.safe_load((srv._config_path).read_text())["agent"]["available_models"][0]
    assert raw_model["provider"] == "anthropic"
    assert "api_key" not in raw_model
    assert "base_url" not in raw_model
    assert "thinking_budget_tokens" not in raw_model


def test_admin_platform_settings_validates_runtime_before_writing_config(
    admin_auth_headers,
    monkeypatch: pytest.MonkeyPatch,
):
    original_document = {
        "agent": {
            "model": "anthropic:claude-haiku-4-5",
            "sentinel_model": "anthropic:claude-haiku-4-5",
            "title_model": "anthropic:claude-haiku-4-5",
            "available_models": [{"provider": "anthropic", "name": "claude-haiku-4-5"}],
        }
    }
    srv._config_path.write_text(yaml.safe_dump(original_document, sort_keys=False), encoding="utf-8")

    def _failing_model_factory(_config):
        def _factory(_name: str):
            raise ValueError("runtime model validation failed")

        return _factory

    monkeypatch.setattr(platform_settings, "make_model_factory", _failing_model_factory)

    local_client = TestClient(app, raise_server_exceptions=False)
    resp = local_client.patch(
        "/api/admin/platform/settings",
        headers=admin_auth_headers,
        json={
            "default_models": {
                "agent": "local:test",
                "sentinel": "local:test",
                "title": "local:test",
            },
            "default_budget": {},
            "available_models": [
                {
                    "provider": "openai",
                    "name": "gpt-4o-mini",
                    "id": "local:test",
                    "base_url": "http://127.0.0.1:1234/v1",
                    "api_key": {"source": "env", "value": "ANTHROPIC_API_KEY"},
                }
            ],
        },
    )

    assert resp.status_code == 500
    assert yaml.safe_load(srv._config_path.read_text(encoding="utf-8")) == original_document
    assert srv._config.agent.model == "anthropic:claude-sonnet-4-6"


def test_admin_user_update_can_clear_email(client, admin_auth_headers):
    create_resp = client.post(
        "/api/admin/users",
        headers=admin_auth_headers,
        json={
            "username": "Ada",
            "password": "correct-horse-battery",
            "display_name": "Ada",
            "email": "ada@example.test",
        },
    )
    assert create_resp.status_code == 201

    update_resp = client.patch("/api/admin/users/ada", headers=admin_auth_headers, json={"email": None})

    assert update_resp.status_code == 200
    assert update_resp.json()["email"] is None


def test_admin_user_config_redacts_and_preserves_backend_password(client, admin_auth_headers):
    create_resp = client.post(
        "/api/admin/users",
        headers=admin_auth_headers,
        json={
            "username": "Ada",
            "password": "correct-horse-battery",
            "display_name": "Ada",
            "config": {
                "credentials": {
                    "backends": {
                        "vault": {
                            "type": "bitwarden",
                            "url": "http://carapace-bitwarden:8087",
                            "basic_auth": {"username": "ada", "password": "proxy-password"},
                        }
                    }
                }
            },
        },
    )

    assert create_resp.status_code == 201
    backend = create_resp.json()["config"]["credentials"]["backends"]["vault"]
    assert backend["basic_auth"] == {"username": "ada"}

    update_resp = client.patch(
        "/api/admin/users/ada",
        headers=admin_auth_headers,
        json={
            "config": {
                "credentials": {
                    "backends": {
                        "vault": {
                            "type": "bitwarden",
                            "url": "http://carapace-bitwarden:8087",
                            "basic_auth": {"username": "ada"},
                        }
                    }
                }
            }
        },
    )

    assert update_resp.status_code == 200
    user = srv._auth_store.get_user("ada")
    assert user is not None
    stored_backend = user.config.credentials.backends["vault"]
    assert isinstance(stored_backend, BitwardenCredentialBackendConfig)
    assert stored_backend.basic_auth == BasicAuthConfig(username="ada", password="proxy-password")


def test_user_settings_redacts_write_only_fields(client, auth_headers):
    srv._auth_store.update_user(
        "thies",
        {
            "config": UserConfig.model_validate(
                {
                    "credentials": {
                        "backends": {
                            "vault": {
                                "type": "bitwarden",
                                "url": "http://carapace-bitwarden:8087",
                                "basic_auth": {"username": "thies", "password": "proxy-password"},
                            }
                        }
                    },
                    "channels": {
                        "matrix": {
                            "enabled": True,
                            "homeserver": "https://matrix.example.test",
                            "user_id": "@carapace:example.test",
                            "password": "matrix-password",
                            "token": "matrix-token",
                        }
                    },
                    "git": {
                        "remote": "https://gitea.example.test/thies/knowledge.git",
                        "token": "git-token",
                    },
                }
            )
        },
    )

    resp = client.get("/api/user/settings", headers=auth_headers)

    assert resp.status_code == 200
    settings = resp.json()["settings"]
    assert settings["matrix"]["password_set"] is True
    assert settings["matrix"]["token_set"] is True
    assert "password" not in settings["matrix"]
    assert "token" not in settings["matrix"]
    assert settings["git"]["token_set"] is True
    assert "token" not in settings["git"]
    basic_auth = settings["credentials"]["backends"]["vault"]["basic_auth"]
    assert basic_auth == {"username": "thies", "password_set": True}


def test_user_settings_apply_defaults_to_new_sessions(client, auth_headers):
    patch_resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={
            "default_models": {"agent": srv._config.agent.model},
            "default_budget": {"tool_calls": 3, "cost_usd": "1.50"},
        },
    )
    assert patch_resp.status_code == 200

    create_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})

    assert create_resp.status_code == 200
    state = srv._engine.session_mgr.load_state(create_resp.json()["session_id"])
    assert state is not None
    assert state.agent_model_name == srv._config.agent.model
    assert state.budget.tool_calls == 3
    assert state.budget.cost_usd == Decimal("1.50")


def test_user_settings_full_unchanged_patch_does_not_reload_runtimes(client, auth_headers):
    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={
            "default_models": {},
            "default_budget": {},
            "matrix": {
                "enabled": False,
                "homeserver": "",
                "user_id": "",
                "device_name": "carapace",
                "allowed_rooms": [],
                "allowed_users": [],
            },
            "credentials": {"backends": {}},
            "git": {
                "remote": "",
                "branch": "main",
                "author": "carapace <carapace@%h>",
            },
        },
    )

    assert resp.status_code == 200


def test_user_settings_default_changes_reload_enabled_matrix(client, auth_headers, monkeypatch):
    srv._auth_store.update_user(
        "thies",
        {"config": UserConfig.model_validate({"channels": {"matrix": {"enabled": True}}})},
    )
    manager = MagicMock()
    manager.reload_user = AsyncMock()
    monkeypatch.setattr(srv, "_matrix_channel_manager", manager, raising=False)

    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={"default_budget": {"tool_calls": 5}},
    )

    assert resp.status_code == 200
    manager.reload_user.assert_awaited_once()


def test_user_settings_attempts_git_reload_when_matrix_reload_fails(client, auth_headers, monkeypatch):
    manager = MagicMock()
    manager.reload_user = AsyncMock(side_effect=[HTTPException(status_code=500, detail="matrix failed"), None])
    runtime = MagicMock()
    runtime.apply_config = AsyncMock()
    monkeypatch.setattr(srv, "_matrix_channel_manager", manager, raising=False)
    monkeypatch.setattr(srv, "_knowledge_git_runtime", runtime, raising=False)

    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={
            "matrix": {"enabled": True},
            "git": {"remote": "https://git.example.test/thies/knowledge.git"},
        },
    )

    assert resp.status_code == 500
    assert "matrix failed" in resp.json()["detail"]
    assert manager.reload_user.await_count == 2
    assert runtime.apply_config.await_count == 2


def test_user_settings_does_not_persist_git_when_reload_fails(client, auth_headers, monkeypatch):
    runtime = MagicMock()
    runtime.apply_config = AsyncMock(side_effect=HTTPException(status_code=500, detail="git failed"))
    monkeypatch.setattr(srv, "_knowledge_git_runtime", runtime, raising=False)

    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={"git": {"remote": "https://git.example.test/thies/knowledge.git"}},
    )

    assert resp.status_code == 500
    assert "git failed" in resp.json()["detail"]
    user = srv._auth_store.get_user("thies")
    assert user is not None
    assert user.config.git.remote == ""


def test_user_settings_does_not_persist_matrix_when_reload_fails(client, auth_headers, monkeypatch):
    manager = MagicMock()
    manager.reload_user = AsyncMock(side_effect=[HTTPException(status_code=500, detail="matrix failed"), None])
    monkeypatch.setattr(srv, "_matrix_channel_manager", manager, raising=False)

    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={"matrix": {"enabled": True}},
    )

    assert resp.status_code == 500
    assert "matrix failed" in resp.json()["detail"]
    user = srv._auth_store.get_user("thies")
    assert user is not None
    assert user.config.channels.matrix.enabled is False


def test_user_settings_matrix_password_clears_persisted_token_before_reload(client, auth_headers, monkeypatch):
    token_file = srv._engine.session_mgr.sessions_dir.parent / "matrix_token.yaml"
    token_file.write_text(
        yaml.safe_dump(
            MatrixTokensFile(
                tokens=[
                    MatrixTokenFile(
                        access_token="old-token",
                        device_id="OLD",
                        user_id="@carapace:example.test",
                        user="thies",
                    )
                ]
            ).model_dump(mode="json")
        ),
        encoding="utf-8",
    )
    srv._auth_store.update_user(
        "thies",
        {
            "config": UserConfig.model_validate(
                {
                    "channels": {
                        "matrix": {
                            "enabled": True,
                            "homeserver": "https://matrix.example.test",
                            "user_id": "@carapace:example.test",
                            "password": "old-password",
                        }
                    }
                }
            )
        },
    )

    async def reload_user(_username: str, _config: UserConfig) -> None:
        assert not token_file.exists()

    manager = MagicMock()
    manager.reload_user = AsyncMock(side_effect=reload_user)
    monkeypatch.setattr(srv, "_matrix_channel_manager", manager, raising=False)

    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={"matrix": {"password": "new-password", "clear_token": True}},
    )

    assert resp.status_code == 200
    assert not token_file.exists()
    manager.reload_user.assert_awaited_once()


def test_user_settings_matrix_password_restores_persisted_token_on_reload_failure(
    client,
    auth_headers,
    monkeypatch,
):
    token_file = srv._engine.session_mgr.sessions_dir.parent / "matrix_token.yaml"
    token_content = yaml.safe_dump(
        MatrixTokensFile(
            tokens=[
                MatrixTokenFile(
                    access_token="old-token",
                    device_id="OLD",
                    user_id="@carapace:example.test",
                    user="thies",
                )
            ]
        ).model_dump(mode="json")
    )
    token_file.write_text(token_content, encoding="utf-8")
    srv._auth_store.update_user(
        "thies",
        {
            "config": UserConfig.model_validate(
                {
                    "channels": {
                        "matrix": {
                            "enabled": True,
                            "homeserver": "https://matrix.example.test",
                            "user_id": "@carapace:example.test",
                            "password": "old-password",
                        }
                    }
                }
            )
        },
    )
    manager = MagicMock()
    manager.reload_user = AsyncMock(side_effect=[HTTPException(status_code=500, detail="matrix failed"), None])
    monkeypatch.setattr(srv, "_matrix_channel_manager", manager, raising=False)

    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={"matrix": {"password": "new-password", "clear_token": True}},
    )

    assert resp.status_code == 500
    assert token_file.read_text(encoding="utf-8") == token_content
    manager.reload_user.assert_awaited()


def test_user_settings_rejects_file_credentials_when_disabled(client, auth_headers, monkeypatch):
    monkeypatch.delenv("CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND", raising=False)

    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={"credentials": {"backends": {"dev": {"type": "file", "path": "secrets.env"}}}},
    )

    assert resp.status_code == 400
    assert "disabled" in resp.json()["detail"]


def test_user_settings_preserves_unchanged_file_credentials_when_disabled(client, auth_headers, monkeypatch):
    monkeypatch.delenv("CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND", raising=False)
    srv._auth_store.update_user(
        "thies",
        {
            "config": UserConfig(
                credentials={
                    "backends": {
                        "dev": FileCredentialBackendConfig(path="secrets.env", expose=["API_TOKEN"]),
                    }
                }
            )
        },
    )

    resp = client.patch(
        "/api/user/settings",
        headers=auth_headers,
        json={
            "default_budget": {"tool_calls": 4},
            "credentials": {
                "backends": {
                    "dev": {"type": "file", "path": "secrets.env", "expose": ["API_TOKEN"], "hide": []},
                }
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json()["settings"]["credentials"]["backends"]["dev"] == {
        "type": "file",
        "path": "secrets.env",
        "expose": ["API_TOKEN"],
        "hide": [],
    }


def test_admin_user_update_cannot_remove_last_enabled_admin(client, admin_auth_headers):
    disable_resp = client.patch("/api/admin/users/admin", headers=admin_auth_headers, json={"enabled": False})
    demote_resp = client.patch("/api/admin/users/admin", headers=admin_auth_headers, json={"roles": []})

    assert disable_resp.status_code == 400
    assert disable_resp.json() == {"detail": "Cannot remove the last enabled admin"}
    assert demote_resp.status_code == 400
    assert demote_resp.json() == {"detail": "Cannot remove the last enabled admin"}


def test_admin_user_delete_removes_other_user_and_revokes_sessions(client, admin_auth_headers):
    user_session = srv._auth_store.create_session(username="thies")
    user_token = srv._auth_store.issue_session_token(user_session)

    delete_resp = client.delete("/api/admin/users/thies", headers=admin_auth_headers)

    assert delete_resp.status_code == 204
    assert srv._auth_store.get_user("thies") is None
    assert srv._auth_store.validate_session_token(user_token) is None

    login_resp = client.post("/api/auth/login", json={"username": "thies", "password": "secret"})
    assert login_resp.status_code == 401


def test_admin_user_delete_cannot_delete_current_user(client, admin_auth_headers):
    delete_resp = client.delete("/api/admin/users/admin", headers=admin_auth_headers)

    assert delete_resp.status_code == 400
    assert delete_resp.json() == {"detail": "Cannot delete your own user"}
    assert srv._auth_store.get_user("admin") is not None


def test_meta_requires_auth(client):
    resp = client.get("/api/meta")
    assert resp.status_code in (401, 403)


def test_meta_returns_version(client, auth_headers, monkeypatch):
    monkeypatch.setattr(srv, "_APP_VERSION", "test-version")

    resp = client.get("/api/meta", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"version": "test-version"}


def test_vapid_public_key_is_public_when_configured(client):
    configured = ensure_vapid_config(srv._config.notifications, srv._data_dir)
    assert configured.vapid_private_key is not None
    srv._config.notifications = configured

    resp = client.get("/api/config/vapid-public-key")

    assert resp.status_code == 200
    assert resp.json() == {"vapid_public_key": derive_vapid_public_key(configured.vapid_private_key)}


def test_vapid_public_key_is_public_when_generated(client):
    generated = ensure_vapid_config(srv._config.notifications, srv._data_dir)
    assert generated.vapid_private_key is not None
    srv._config.notifications = generated

    resp = client.get("/api/config/vapid-public-key")

    assert resp.status_code == 200
    assert resp.json() == {"vapid_public_key": derive_vapid_public_key(generated.vapid_private_key)}


def test_notification_subscription_roundtrip(client, auth_headers):
    resp = client.post(
        "/api/notifications/subscriptions",
        headers=auth_headers,
        json={
            "endpoint": "https://push.example.test/sub-1",
            "p256dh": "key-1",
            "auth": "auth-1",
            "device_name": "Phone",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["device_name"] == "Phone"
    assert data["endpoint"] == "https://push.example.test/sub-1"
    assert data["subscribed_at"]
    assert data["preferences"]["escalation_pending"] is True

    list_resp = client.get("/api/notifications/subscriptions", headers=auth_headers)

    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["subscription_id"] == data["subscription_id"]
    assert list_resp.json()[0]["endpoint"] == data["endpoint"]
    assert list_resp.json()[0]["subscribed_at"] == data["subscribed_at"]


def test_notification_preferences_patch_persists(client, auth_headers):
    create_resp = client.post(
        "/api/notifications/subscriptions",
        headers=auth_headers,
        json={
            "endpoint": "https://push.example.test/sub-1",
            "p256dh": "key-1",
            "auth": "auth-1",
            "device_name": "Desktop",
        },
    )
    subscription_id = create_resp.json()["subscription_id"]

    patch_resp = client.patch(
        f"/api/notifications/subscriptions/{subscription_id}/preferences",
        headers=auth_headers,
        json={"attended_turn_completed": False},
    )

    assert patch_resp.status_code == 200
    assert patch_resp.json()["preferences"]["attended_turn_completed"] is False

    stored = srv._notification_store.list_subscriptions(user="thies")
    assert stored[0].notification_prefs.attended_turn_completed is False


def test_notification_test_endpoint_dispatches_owned_subscription(client, auth_headers):
    create_resp = client.post(
        "/api/notifications/subscriptions",
        headers=auth_headers,
        json={
            "endpoint": "https://push.example.test/sub-1",
            "p256dh": "key-1",
            "auth": "auth-1",
            "device_name": "Desktop",
        },
    )
    subscription_id = create_resp.json()["subscription_id"]
    srv._notification_router = AsyncMock()
    srv._notification_router.dispatch_test = AsyncMock(return_value=True)

    resp = client.post(
        f"/api/notifications/subscriptions/{subscription_id}/test",
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"delivered": True}
    dispatched = srv._notification_router.dispatch_test.await_args.kwargs["subscription"]
    assert dispatched.id == subscription_id


def test_notification_test_endpoint_returns_502_when_delivery_fails(client, auth_headers):
    create_resp = client.post(
        "/api/notifications/subscriptions",
        headers=auth_headers,
        json={
            "endpoint": "https://push.example.test/sub-1",
            "p256dh": "key-1",
            "auth": "auth-1",
            "device_name": "Desktop",
        },
    )
    subscription_id = create_resp.json()["subscription_id"]
    srv._notification_router = AsyncMock()
    srv._notification_router.dispatch_test = AsyncMock(return_value=False)

    resp = client.post(
        f"/api/notifications/subscriptions/{subscription_id}/test",
        headers=auth_headers,
    )

    assert resp.status_code == 502
    assert resp.json()["detail"] == "Failed to deliver test notification"


def test_notification_presence_updates_registry(client, auth_headers):
    session_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    session_id = session_resp.json()["session_id"]
    create_resp = client.post(
        "/api/notifications/subscriptions",
        headers=auth_headers,
        json={
            "endpoint": "https://push.example.test/sub-1",
            "p256dh": "key-1",
            "auth": "auth-1",
            "device_name": "Laptop",
        },
    )
    subscription_id = create_resp.json()["subscription_id"]

    presence_resp = client.post(
        f"/api/notifications/subscriptions/{subscription_id}/presence",
        headers=auth_headers,
        json={
            "session_id": session_id,
            "client_type": "web",
            "focus_state": "visible",
        },
    )

    assert presence_resp.status_code == 200
    assert presence_resp.json() == {"heartbeat_received": True}
    assert srv._notification_presence.is_session_actively_handled(session_id) is True


def test_interactive_presence_endpoint_updates_registry(client, auth_headers):
    session_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    session_id = session_resp.json()["session_id"]
    resp = client.post(
        "/api/notifications/presence",
        headers=auth_headers,
        json={
            "session_id": session_id,
            "source_id": "web-tab-1",
            "client_type": "web",
            "focus_state": "visible",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"heartbeat_received": True}
    assert srv._notification_presence.is_session_actively_handled(session_id) is True


def test_interactive_presence_inactive_removes_registry_entry(client, auth_headers):
    session_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    session_id = session_resp.json()["session_id"]
    client.post(
        "/api/notifications/presence",
        headers=auth_headers,
        json={
            "session_id": session_id,
            "source_id": "web-tab-1",
            "client_type": "web",
            "focus_state": "visible",
        },
    )

    resp = client.post(
        "/api/notifications/presence",
        headers=auth_headers,
        json={
            "session_id": session_id,
            "source_id": "web-tab-1",
            "client_type": "web",
            "focus_state": "inactive",
        },
    )

    assert resp.status_code == 200
    assert srv._notification_presence.is_session_actively_handled(session_id) is False


def test_interactive_presence_clears_pending_notifications(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.pending_notifications = {f"done:{sid}:1:attended_turn_completed": {"sub-1"}}
    srv._engine._notification_router = AsyncMock()
    srv._engine._notification_router.clear_notifications = AsyncMock(
        return_value=type("Delivery", (), {"delivered_subscription_ids": {"sub-1"}})()
    )

    resp = client.post(
        "/api/notifications/presence",
        headers=auth_headers,
        json={
            "session_id": sid,
            "source_id": "web-tab-1",
            "client_type": "web",
            "focus_state": "visible",
        },
    )

    assert resp.status_code == 200
    srv._engine._notification_router.clear_notifications.assert_awaited_once_with(
        session_id=sid,
        notif_id=f"done:{sid}:1:attended_turn_completed",
        subscription_ids={"sub-1"},
    )
    assert active.pending_notifications == {}


# --- Sessions REST ---


def test_create_session(client, auth_headers):
    resp = client.post("/api/sessions", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["channel_type"] == "cli"
    assert data["attributes"]["private"] is False
    assert data["attributes"]["archived"] is False


def test_create_session_accepts_ask_mode(client, auth_headers):
    resp = client.post("/api/sessions", headers=auth_headers, json={"ask_mode": True})

    assert resp.status_code == 200
    data = resp.json()
    assert data["attributes"]["ask_mode"] is True
    assert data["attributes"]["yolo_mode"] is False


def test_create_session_rejects_conflicting_modes(client, auth_headers):
    resp = client.post(
        "/api/sessions",
        headers=auth_headers,
        json={"ask_mode": True, "yolo_mode": True},
    )

    assert resp.status_code == 422


def test_create_session_defaults_to_public(client, auth_headers):
    resp = client.post("/api/sessions", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["attributes"]["private"] is False


def test_list_sessions(client, auth_headers):
    client.post("/api/sessions", headers=auth_headers)
    client.post("/api/sessions", headers=auth_headers)
    resp = client.get("/api/sessions", headers=auth_headers)
    assert resp.status_code == 200
    sessions = resp.json()["items"]
    assert len(sessions) >= 2


def test_list_sessions_skips_message_count_by_default(client, auth_headers, monkeypatch):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    load_events = MagicMock(side_effect=AssertionError("load_events should not be called"))
    monkeypatch.setattr(srv._engine.session_mgr, "load_events", load_events)

    resp = client.get("/api/sessions", headers=auth_headers)

    assert resp.status_code == 200
    session = next(item for item in resp.json()["items"] if item["session_id"] == sid)
    assert session["message_count"] == 0


def test_list_sessions_can_include_message_count(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ],
    )

    resp = client.get("/api/sessions?include_message_count=true", headers=auth_headers)

    assert resp.status_code == 200
    session = next(item for item in resp.json()["items"] if item["session_id"] == sid)
    assert session["message_count"] == 3


def test_list_sessions_can_include_message_count_from_history_fallback(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_history(
        sid,
        [
            ModelRequest(parts=[UserPromptPart(content="first")]),
            ModelResponse(parts=[TextPart(content="reply")]),
            ModelRequest(parts=[UserPromptPart(content="second")]),
        ],
    )

    resp = client.get("/api/sessions?include_message_count=true", headers=auth_headers)

    assert resp.status_code == 200
    session = next(item for item in resp.json()["items"] if item["session_id"] == sid)
    assert session["message_count"] == 3


def test_get_session(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    resp = client.get(f"/api/sessions/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["session_id"] == sid


def test_get_session_includes_total_cost_usd(client, auth_headers, monkeypatch):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    class _FakeUsage:
        def estimated_cost(self) -> dict[str, Decimal]:
            return {"total": Decimal("0.0123")}

    monkeypatch.setattr(srv._engine.session_mgr, "load_usage", lambda session_id: _FakeUsage())

    resp = client.get(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["total_cost_usd"] == pytest.approx(0.0123)


def test_jobs_crud_roundtrip(client, auth_headers):
    create_resp = client.post(
        "/api/jobs",
        headers=auth_headers,
        json={
            "id": "daily-briefing",
            "name": "Daily Briefing",
            "prompt": "Summarize the day.",
            "unattended": True,
            "triggers": [{"expression": "0 9 * * *", "timezone": "UTC"}],
        },
    )

    assert create_resp.status_code == 201
    assert create_resp.json()["id"] == "daily-briefing"

    list_resp = client.get("/api/jobs", headers=auth_headers)
    assert list_resp.status_code == 200
    assert [job["id"] for job in list_resp.json()["jobs"]] == ["daily-briefing"]

    get_resp = client.get("/api/jobs/daily-briefing", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Daily Briefing"

    update_resp = client.put(
        "/api/jobs/daily-briefing",
        headers=auth_headers,
        json={
            "id": "daily-briefing",
            "name": "Updated Briefing",
            "prompt": "Summarize the updates.",
            "unattended": True,
            "triggers": [],
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Briefing"

    delete_resp = client.delete("/api/jobs/daily-briefing", headers=auth_headers)
    assert delete_resp.status_code == 204

    missing_resp = client.get("/api/jobs/daily-briefing", headers=auth_headers)
    assert missing_resp.status_code == 404


def test_run_job_creates_fresh_session_and_submits_message(client, auth_headers, monkeypatch):
    submit_message = AsyncMock()
    monkeypatch.setattr(srv._engine, "submit_message", submit_message)

    client.post(
        "/api/jobs",
        headers=auth_headers,
        json={
            "id": "daily-briefing",
            "name": "Daily Briefing",
            "prompt": "Summarize the day.",
            "private": True,
            "unattended": True,
            "ask_mode": True,
            "agent_model_name": "openai:gpt-5.4",
            "sentinel_model_name": "openai:gpt-5.4-mini",
            "title_model_name": "openai:gpt-5.4-nano",
            "triggers": [],
        },
    )

    run_resp = client.post(
        "/api/jobs/daily-briefing/run",
        headers=auth_headers,
        json={"data": '{"source":"calendar","items":3}'},
    )

    assert run_resp.status_code == 200
    payload = run_resp.json()
    assert payload["job_id"] == "daily-briefing"
    assert payload["created_new_session"] is True
    assert payload["session"]["channel_type"] == "job"
    assert payload["session"]["latest_job_run"]["job_id"] == "daily-briefing"
    assert payload["session"]["latest_job_run"]["data"] == '{"source":"calendar","items":3}'

    session_resp = client.get(f"/api/sessions/{payload['session_id']}", headers=auth_headers)
    assert session_resp.status_code == 200
    assert session_resp.json()["latest_job_run"]["job_id"] == "daily-briefing"
    assert session_resp.json()["latest_job_run"]["data"] == '{"source":"calendar","items":3}'

    state = srv._engine.session_mgr.load_state(payload["session_id"])
    assert state is not None
    assert state.attributes.private is True
    assert state.attributes.ask_mode is True
    assert state.attributes.yolo_mode is False
    assert state.agent_model_name == "openai:gpt-5.4"
    assert state.sentinel_model_name == "openai:gpt-5.4-mini"
    assert state.title_model_name == "openai:gpt-5.4-nano"

    (session_id, message), kwargs = submit_message.await_args
    assert session_id == payload["session_id"]
    assert kwargs == {}
    assert "Summarize the day." in message
    assert "triggered via the API" in message
    assert '{"source":"calendar","items":3}' in message


def test_run_job_uses_existing_persistent_session(client, auth_headers, monkeypatch):
    submit_message = AsyncMock()
    monkeypatch.setattr(srv._engine, "submit_message", submit_message)

    state = srv._engine.session_mgr.create_session(user="thies", unattended=False)
    create_resp = client.post(
        "/api/jobs",
        headers=auth_headers,
        json={
            "id": "team-planning",
            "name": "Team Planning",
            "prompt": "Continue planning.",
            "unattended": False,
            "persistent_session_id": state.session_id,
            "triggers": [],
        },
    )
    assert create_resp.status_code == 201

    run_resp = client.post("/api/jobs/team-planning/run", headers=auth_headers)

    assert run_resp.status_code == 200
    payload = run_resp.json()
    assert payload["created_new_session"] is False
    assert payload["session_id"] == state.session_id

    (session_id, message), kwargs = submit_message.await_args
    assert session_id == state.session_id
    assert kwargs == {}
    assert "Continue planning." in message


def test_run_job_rejects_missing_persistent_session(client, auth_headers, monkeypatch):
    monkeypatch.setattr(srv._engine, "submit_message", AsyncMock())

    create_resp = client.post(
        "/api/jobs",
        headers=auth_headers,
        json={
            "id": "team-planning",
            "name": "Team Planning",
            "prompt": "Continue planning.",
            "unattended": False,
            "persistent_session_id": "missing-session",
            "triggers": [],
        },
    )
    assert create_resp.status_code == 201

    run_resp = client.post("/api/jobs/team-planning/run", headers=auth_headers)
    assert run_resp.status_code == 409
    assert "persistent session" in run_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_due_jobs_once_dispatches_cron_jobs(monkeypatch) -> None:
    submit_message = AsyncMock()
    monkeypatch.setattr(srv._engine, "submit_message", submit_message)

    srv._jobs_store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily-briefing",
                "user": "thies",
                "name": "Daily Briefing",
                "prompt": "Summarize the day.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert srv._jobs_scheduler.collect_due_runs(now=start) == []

    dispatched = await server_jobs._run_due_jobs_once(now=start + timedelta(minutes=1, seconds=5))

    assert dispatched == 1
    (session_id, message), kwargs = submit_message.await_args
    assert kwargs == {}
    assert session_id
    assert "triggered automatically" in message
    assert "* * * * *" in message


@pytest.mark.asyncio
async def test_run_due_jobs_once_uses_fired_trigger_timezone(monkeypatch) -> None:
    submit_message = AsyncMock()
    monkeypatch.setattr(srv._engine, "submit_message", submit_message)

    srv._jobs_store.create_job(
        JobDefinition.model_validate(
            {
                "id": "timezone-ambiguous",
                "user": "thies",
                "name": "Timezone Ambiguous",
                "prompt": "Summarize the day.",
                "triggers": [
                    {"expression": "* * * * *", "timezone": "UTC"},
                    {"expression": "* * * * *", "timezone": "Europe/Berlin"},
                ],
            }
        )
    )

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert srv._jobs_scheduler.collect_due_runs(now=start) == []

    dispatched = await server_jobs._run_job_definition(
        srv._jobs_store.get_job("timezone-ambiguous"),
        trigger_kind="cron",
        triggered_at=datetime(2026, 5, 9, 10, 1, tzinfo=UTC),
        cron_expression="* * * * *",
        trigger_timezone="Europe/Berlin",
    )

    assert dispatched.job_id == "timezone-ambiguous"
    (_session_id, message), kwargs = submit_message.await_args
    assert kwargs == {}
    assert "2026-05-09T12:01:00+02:00" in message


def test_update_session_privacy(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"private": True}},
    )

    assert resp.status_code == 200
    assert resp.json()["attributes"]["private"] is True
    assert resp.json()["message_count"] == 2
    assert srv._engine.session_mgr.load_state(sid).attributes.private is True


def test_update_session_privacy_updates_active_session_state(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    original_state = active.state
    active.state.activated_skills.append("demo-skill")
    assert active.state.attributes.private is False

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"private": True}},
    )

    assert resp.status_code == 200
    assert active.state is original_state
    assert active.state.attributes.private is True
    assert active.state.activated_skills == ["demo-skill"]


def test_update_session_allows_unattended_mode_change(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"unattended": True}},
    )

    assert resp.status_code == 200
    assert resp.json()["attributes"]["unattended"] is True

    # Toggle back to False
    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"unattended": False}},
    )
    assert resp.status_code == 200
    assert resp.json()["attributes"]["unattended"] is False


def test_update_session_models_updates_active_session_state(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    original_state = active.state
    agent_model_name = srv._config.agent.model
    sentinel_model_name = srv._config.agent.sentinel_model

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={
            "agent_model_name": agent_model_name,
            "sentinel_model_name": sentinel_model_name,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["agent_model_name"] == agent_model_name
    assert resp.json()["sentinel_model_name"] == sentinel_model_name
    assert active.state is original_state
    assert active.state.agent_model_name == agent_model_name
    assert active.state.sentinel_model_name == sentinel_model_name
    persisted = srv._engine.session_mgr.load_state(sid)
    assert persisted is not None
    assert persisted.agent_model_name == agent_model_name
    assert persisted.sentinel_model_name == sentinel_model_name

    reset_resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"agent_model_name": None, "sentinel_model_name": None},
    )

    assert reset_resp.status_code == 200
    assert reset_resp.json()["agent_model_name"] is None
    assert reset_resp.json()["sentinel_model_name"] is None
    assert active.state.agent_model_name is None
    assert active.state.sentinel_model_name is None


def test_update_session_single_model_preserves_other_override(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)

    first_resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"sentinel_model_name": srv._config.agent.sentinel_model},
    )

    assert first_resp.status_code == 200
    assert first_resp.json()["agent_model_name"] is None
    assert first_resp.json()["sentinel_model_name"] == srv._config.agent.sentinel_model

    second_resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"agent_model_name": srv._config.agent.model},
    )

    assert second_resp.status_code == 200
    assert second_resp.json()["agent_model_name"] == srv._config.agent.model
    assert second_resp.json()["sentinel_model_name"] == srv._config.agent.sentinel_model
    assert active.state.agent_model_name == srv._config.agent.model
    assert active.state.sentinel_model_name == srv._config.agent.sentinel_model


def test_list_sessions_excludes_archived_by_default(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    archive_resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"archived": True}},
    )

    assert archive_resp.status_code == 200
    resp = client.get("/api/sessions", headers=auth_headers)

    assert resp.status_code == 200
    assert sid not in {session["session_id"] for session in resp.json()["items"]}


def test_list_sessions_can_include_archived(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"archived": True}},
    )

    resp = client.get("/api/sessions?include_archived=true", headers=auth_headers)

    assert resp.status_code == 200
    archived_session = next(item for item in resp.json()["items"] if item["session_id"] == sid)
    assert archived_session["attributes"]["archived"] is True


def test_list_sessions_page_can_paginate(client, auth_headers):
    created_ids = [client.post("/api/sessions", headers=auth_headers).json()["session_id"] for _ in range(3)]

    first_page = client.get(
        "/api/sessions?limit=2&include_archived=true",
        headers=auth_headers,
    )

    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert len(first_payload["items"]) == 2
    assert first_payload["has_more"] is True
    assert first_payload["next_cursor"] == "2"

    second_page = client.get(
        f"/api/sessions?limit=2&include_archived=true&cursor={first_payload['next_cursor']}",
        headers=auth_headers,
    )

    assert second_page.status_code == 200
    second_payload = second_page.json()
    returned_ids = [item["session_id"] for item in first_payload["items"] + second_payload["items"]]
    assert len(set(returned_ids)) >= 3
    assert set(created_ids).issubset(set(returned_ids))
    assert second_payload["has_more"] is False
    assert second_payload["next_cursor"] is None


def test_list_sessions_page_can_include_message_count(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
        ],
    )

    resp = client.get(
        "/api/sessions?include_message_count=true&include_archived=true",
        headers=auth_headers,
    )

    assert resp.status_code == 200
    session = next(item for item in resp.json()["items"] if item["session_id"] == sid)
    assert session["message_count"] == 2


def test_list_sessions_uses_cached_summaries_on_subsequent_requests(client, auth_headers, monkeypatch):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
        ],
    )

    first_resp = client.get("/api/sessions?include_message_count=true", headers=auth_headers)
    assert first_resp.status_code == 200

    monkeypatch.setattr(
        srv._engine.session_mgr,
        "load_state",
        MagicMock(side_effect=AssertionError("load_state should not be called after summaries are cached")),
    )
    monkeypatch.setattr(
        srv._engine.session_mgr,
        "load_events",
        MagicMock(side_effect=AssertionError("load_events should not be called after summaries are cached")),
    )
    monkeypatch.setattr(
        srv._engine.session_mgr,
        "load_sandbox_snapshot",
        MagicMock(side_effect=AssertionError("load_sandbox_snapshot should not be called after summaries are cached")),
    )

    second_resp = client.get("/api/sessions?include_message_count=true", headers=auth_headers)
    assert second_resp.status_code == 200
    session = next(item for item in second_resp.json()["items"] if item["session_id"] == sid)
    assert session["message_count"] == 2


def test_list_sessions_cache_miss_loads_state_once_per_session(client, auth_headers, monkeypatch):
    created_ids = [client.post("/api/sessions", headers=auth_headers).json()["session_id"] for _ in range(3)]
    original_load_state = srv._engine.session_mgr.load_state
    load_calls: list[str] = []

    def counting_load_state(session_id: str):
        load_calls.append(session_id)
        return original_load_state(session_id)

    monkeypatch.setattr(srv._engine.session_mgr, "load_state", counting_load_state)

    resp = client.get("/api/sessions?include_archived=true", headers=auth_headers)

    assert resp.status_code == 200
    assert sorted(load_calls) == sorted(created_ids)


def test_list_sessions_page_uses_stable_tiebreaker(client, auth_headers):
    created_ids = [client.post("/api/sessions", headers=auth_headers).json()["session_id"] for _ in range(3)]
    shared_last_active = datetime(2024, 1, 1, tzinfo=UTC)

    for session_id in created_ids:
        state = srv._engine.session_mgr.load_state(session_id)
        assert state is not None
        state.last_active = shared_last_active
        state.attributes.pinned = False
        srv._engine.session_mgr.save_state(state)

    first_page = client.get(
        "/api/sessions?limit=2&include_archived=true",
        headers=auth_headers,
    )
    assert first_page.status_code == 200
    second_page = client.get(
        f"/api/sessions?limit=2&include_archived=true&cursor={first_page.json()['next_cursor']}",
        headers=auth_headers,
    )

    ordered_ids = [item["session_id"] for item in first_page.json()["items"] + second_page.json()["items"]]
    assert ordered_ids[: len(created_ids)] == sorted(created_ids)


def test_list_sessions_page_rejects_invalid_cursor(client, auth_headers):
    resp = client.get("/api/sessions?cursor=abc", headers=auth_headers)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid session cursor"


def test_update_session_archives_and_destroys_sandbox(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"archived": True}},
    )

    assert resp.status_code == 200
    assert resp.json()["attributes"]["archived"] is True
    assert srv._engine.session_mgr.load_state(sid).attributes.archived is True
    srv._engine.sandbox_mgr.destroy_session.assert_awaited_with(sid)


def test_update_session_archives_non_private_session_into_knowledge_repo(client, auth_headers, tmp_path):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"archived": True}},
    )

    assert resp.status_code == 200
    assert resp.json()["attributes"]["archived"] is True
    archive_path = resp.json()["knowledge_last_archive_path"]
    assert archive_path is not None
    archive_file = tmp_path / archive_path
    assert archive_file.exists()
    payload = archive_file.read_text()
    assert '"archived": true' in payload
    assert srv._engine.session_mgr.load_state(sid).knowledge_last_commit_trigger == "archive"


def test_update_session_archives_updates_active_session_state(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    original_state = active.state

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"archived": True}},
    )

    assert resp.status_code == 200
    assert original_state.attributes.archived is True
    assert srv._engine.get_active(sid) is None


def test_update_session_unarchives_without_deactivating_active_session(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    original_state = active.state
    active.state.attributes.archived = True
    srv._engine.session_mgr.save_state(active.state)

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"archived": False}},
    )

    assert resp.status_code == 200
    assert original_state.attributes.archived is False
    assert srv._engine.get_active(sid) is active
    srv._engine.sandbox_mgr.destroy_session.assert_not_awaited()


def test_update_session_syncs_active_access_mode_policy(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    active = srv._engine.get_or_activate(sid)

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"ask_mode": True}},
    )

    assert resp.status_code == 200
    assert active.state.attributes.ask_mode is True
    assert active.security.ask_mode is True
    assert active.security.yolo_mode is False
    assert active.sentinel._ask_mode is True


def test_update_session_rejects_conflicting_access_modes(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"ask_mode": True, "yolo_mode": True}},
    )

    assert resp.status_code == 422


def test_archived_session_rejects_sandbox_start(client, auth_headers):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"archived": True}},
    )

    resp = client.post(f"/api/sessions/{sid}/sandbox/up", headers=auth_headers)

    assert resp.status_code == 409


def test_list_sessions_sorts_pinned_first(client, auth_headers):
    first = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    second = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    client.patch(
        f"/api/sessions/{first}",
        headers=auth_headers,
        json={"attributes": {"pinned": True}},
    )

    resp = client.get("/api/sessions", headers=auth_headers)

    assert resp.status_code == 200
    session_ids = [item["session_id"] for item in resp.json()["items"] if item["session_id"] in {first, second}]
    assert session_ids[0] == first


def test_fork_session_creates_new_session_from_turn(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    state = srv._engine.session_mgr.load_state(sid)
    state.title = "Fork me"
    state.activated_skills = ["web"]
    state.channel_type = "matrix"
    state.channel_ref = "!room:example.com"
    srv._engine.session_mgr.save_state(state)
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
            {"role": "user", "content": "follow-up"},
            {"role": "assistant", "content": "next"},
        ],
    )

    resp = client.post(
        f"/api/sessions/{sid}/fork",
        headers=auth_headers,
        json={"event_index": 1, "channel_type": "web", "channel_ref": ""},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] != sid
    assert data["channel_type"] == "web"
    assert data["channel_ref"] is None
    assert data["title"] == "Fork me (Copy)"
    assert data["message_count"] == 2
    forked_sid = data["session_id"]
    forked_state = srv._engine.session_mgr.load_state(forked_sid)
    assert forked_state is not None
    assert forked_state.activated_skills == ["web"]
    assert srv._engine.session_mgr.load_events(forked_sid)[-1]["content"] == "world"
    assert srv._engine.session_mgr.load_events(sid)[-1]["content"] == "next"


def test_fork_session_rejects_conflicting_inherited_modes(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"ask_mode": True})
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )

    resp = client.post(
        f"/api/sessions/{sid}/fork",
        headers=auth_headers,
        json={"event_index": 1, "channel_type": "web", "yolo_mode": True},
    )

    assert resp.status_code == 400
    assert "ask_mode and yolo_mode are mutually exclusive" in resp.json()["detail"]


def test_commit_session_knowledge_writes_archive(client, auth_headers, tmp_path):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )

    resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["committed"] is True
    assert data["session"]["message_count"] == 2
    archive_path = data["archive_path"]
    assert archive_path is not None
    archive_file = tmp_path / archive_path
    assert archive_file.is_file()
    payload = archive_file.read_text()
    assert sid in payload
    assert '"history"' in payload
    assert '"timestamp"' in payload


def test_commit_session_knowledge_rejects_private_sessions(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"private": True})
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "secret"}])

    resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)

    assert resp.status_code == 409


def test_commit_session_knowledge_passes_agent_guard_inside_archive_lock(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "hello"}])
    srv._session_archive.commit_session = AsyncMock(
        return_value=SessionArchiveResult(
            committed=False,
            archive_path=None,
            committed_at=None,
            trigger="manual",
            reason="Cannot archive a session while an agent turn is running",
        )
    )

    resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)

    assert resp.status_code == 200
    _, kwargs = srv._session_archive.commit_session.await_args
    assert kwargs["trigger"] == "manual"
    assert callable(kwargs["is_agent_running"])


def test_delete_session_removes_archived_knowledge(client, auth_headers, tmp_path):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "hello"}])
    commit_resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)
    archive_path = commit_resp.json()["archive_path"]
    assert archive_path is not None
    archive_file = tmp_path / archive_path
    assert archive_file.exists()

    resp = client.delete(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 204
    assert not archive_file.exists()


def test_archiving_session_does_not_remove_knowledge_archive(client, auth_headers, tmp_path):
    sid = client.post("/api/sessions", headers=auth_headers).json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "hello"}])
    commit_resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)
    archive_path = commit_resp.json()["archive_path"]
    assert archive_path is not None
    archive_file = tmp_path / archive_path
    assert archive_file.exists()

    resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"archived": True}},
    )

    assert resp.status_code == 200
    assert archive_file.exists()
    assert srv._engine.sandbox_mgr.destroy_session.await_count == 1


def test_delete_private_session_keeps_committed_knowledge(client, auth_headers, tmp_path):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(sid, [{"role": "user", "content": "hello"}])
    commit_resp = client.post(f"/api/sessions/{sid}/knowledge/commit", headers=auth_headers)
    archive_path = commit_resp.json()["archive_path"]
    assert archive_path is not None
    archive_file = tmp_path / archive_path
    assert archive_file.exists()

    patch_resp = client.patch(
        f"/api/sessions/{sid}",
        headers=auth_headers,
        json={"attributes": {"private": True}},
    )
    assert patch_resp.status_code == 200

    resp = client.delete(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 204
    assert archive_file.exists()


def test_delete_session_still_succeeds_when_archive_cleanup_fails(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._session_archive.delete_session_archive = AsyncMock(side_effect=RuntimeError("boom"))

    resp = client.delete(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 204
    assert srv._engine.session_mgr.load_state(sid) is None


@pytest.mark.asyncio
async def test_autosave_skips_state_load_errors_and_continues(monkeypatch) -> None:
    eligible = srv._engine.session_mgr.create_session(user="thies", private=False)
    cutoff_age = datetime.now(tz=UTC) - timedelta(hours=srv._config.sessions.commit.autosave_inactivity_hours + 1)

    eligible_state = srv._engine.session_mgr.load_state(eligible.session_id)
    eligible_state.last_active = cutoff_age
    srv._engine.session_mgr.save_state(eligible_state)

    bad_session_id = "broken-session"
    monkeypatch.setattr(srv._engine.session_mgr, "list_sessions", lambda: [bad_session_id, eligible.session_id])

    original_load_state = srv._engine.session_mgr.load_state

    def flaky_load_state(session_id: str):
        if session_id == bad_session_id:
            raise FileNotFoundError("missing state")
        return original_load_state(session_id)

    monkeypatch.setattr(srv._engine.session_mgr, "load_state", flaky_load_state)
    srv._session_archive.commit_session = AsyncMock()

    await srv._autosave_inactive_sessions()

    srv._session_archive.commit_session.assert_awaited_once()
    _, kwargs = srv._session_archive.commit_session.await_args
    assert kwargs["trigger"] == "autosave"
    cutoff_delta = kwargs["autosave_cutoff"] - cutoff_age
    assert timedelta(minutes=59) < cutoff_delta < timedelta(hours=1, minutes=1)
    assert kwargs["is_agent_running"]() is False


@pytest.mark.asyncio
async def test_autosave_skips_sessions_already_committed_since_last_activity() -> None:
    stale = srv._engine.session_mgr.create_session(user="thies", private=False)
    eligible = srv._engine.session_mgr.create_session(user="thies", private=False)
    cutoff_age = datetime.now(tz=UTC) - timedelta(hours=srv._config.sessions.commit.autosave_inactivity_hours + 1)

    stale_state = srv._engine.session_mgr.load_state(stale.session_id)
    stale_state.last_active = cutoff_age
    stale_state.knowledge_last_committed_at = cutoff_age + timedelta(minutes=5)
    srv._engine.session_mgr.save_state(stale_state)

    eligible_state = srv._engine.session_mgr.load_state(eligible.session_id)
    eligible_state.last_active = cutoff_age
    eligible_state.knowledge_last_committed_at = cutoff_age - timedelta(minutes=5)
    srv._engine.session_mgr.save_state(eligible_state)

    srv._session_archive.commit_session = AsyncMock()

    await srv._autosave_inactive_sessions()

    srv._session_archive.commit_session.assert_awaited_once()
    args, kwargs = srv._session_archive.commit_session.await_args
    assert args == (eligible.session_id,)
    assert kwargs["trigger"] == "autosave"


@pytest.mark.asyncio
async def test_autosave_passes_runtime_agent_guard(monkeypatch) -> None:
    eligible = srv._engine.session_mgr.create_session(user="thies", private=False)
    cutoff_age = datetime.now(tz=UTC) - timedelta(hours=srv._config.sessions.commit.autosave_inactivity_hours + 1)

    eligible_state = srv._engine.session_mgr.load_state(eligible.session_id)
    eligible_state.last_active = cutoff_age
    srv._engine.session_mgr.save_state(eligible_state)

    monkeypatch.setattr(srv._engine, "is_agent_running", lambda session_id: session_id == eligible.session_id)
    srv._session_archive.commit_session = AsyncMock()

    await srv._autosave_inactive_sessions()

    srv._session_archive.commit_session.assert_not_awaited()


def test_get_session_includes_cached_sandbox_snapshot(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(
            runtime="kubernetes",
            status="scaled_down",
            storage_present=True,
            last_measured_used_bytes=1234,
        ),
    )

    resp = client.get(f"/api/sessions/{sid}", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["sandbox"]["status"] == "scaled_down"
    assert resp.json()["sandbox"]["last_measured_used_bytes"] == 1234


def test_get_session_uses_in_process_sandbox_snapshot_cache(client, auth_headers, monkeypatch):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(
            runtime="kubernetes",
            status="scaled_down",
            storage_present=True,
            last_measured_used_bytes=1234,
        ),
    )

    monkeypatch.setattr(
        sandbox_state.SessionSandboxSnapshot,
        "model_validate",
        MagicMock(side_effect=AssertionError("sandbox snapshot should be served from cache")),
    )

    first = client.get(f"/api/sessions/{sid}", headers=auth_headers)
    second = client.get(f"/api/sessions/{sid}", headers=auth_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["sandbox"]["status"] == "scaled_down"
    assert second.json()["sandbox"]["status"] == "scaled_down"


def test_get_session_sandbox_returns_cached_snapshot(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(
            runtime="kubernetes",
            status="running",
            storage_present=True,
            last_measured_used_bytes=4096,
        ),
    )

    resp = client.get(f"/api/sessions/{sid}/sandbox", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    assert resp.json()["last_measured_used_bytes"] == 4096


def test_get_session_sandbox_returns_default_snapshot_when_missing(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    resp = client.get(f"/api/sessions/{sid}/sandbox", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "missing"
    assert resp.json()["exists"] is False


def test_start_session_sandbox_starts_when_idle(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    async def _ensure_session(session_id: str) -> tuple[MagicMock, bool]:
        assert session_id == sid
        srv._engine.session_mgr.save_sandbox_snapshot(
            sid,
            SessionSandboxSnapshot(
                exists=True,
                runtime="kubernetes",
                status="running",
                storage_present=True,
                updated_at=datetime.now(tz=UTC),
            ),
        )
        return MagicMock(), True

    srv._engine.sandbox_mgr.ensure_session = AsyncMock(side_effect=_ensure_session)

    resp = client.post(f"/api/sessions/{sid}/sandbox/up", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    srv._engine.sandbox_mgr.ensure_session.assert_awaited_once_with(sid)


def test_start_session_sandbox_rejects_running_agent(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.agent_task = MagicMock()
    active.agent_task.done.return_value = False

    resp = client.post(f"/api/sessions/{sid}/sandbox/up", headers=auth_headers)

    assert resp.status_code == 409


def test_stop_session_sandbox_scales_down_when_idle(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(
        sid,
        SessionSandboxSnapshot(
            exists=True,
            runtime="kubernetes",
            status="running",
            storage_present=True,
            updated_at=datetime.now(tz=UTC),
        ),
    )

    async def _cleanup_session(session_id: str) -> None:
        assert session_id == sid
        srv._engine.session_mgr.save_sandbox_snapshot(
            sid,
            SessionSandboxSnapshot(
                exists=True,
                runtime="kubernetes",
                status="scaled_down",
                storage_present=True,
                updated_at=datetime.now(tz=UTC),
            ),
        )

    srv._engine.sandbox_mgr.cleanup_session = AsyncMock(side_effect=_cleanup_session)

    resp = client.post(f"/api/sessions/{sid}/sandbox/down", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "scaled_down"
    srv._engine.sandbox_mgr.cleanup_session.assert_awaited_once_with(sid)


def test_stop_session_sandbox_rejects_running_agent(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.agent_task = MagicMock()
    active.agent_task.done.return_value = False

    resp = client.post(f"/api/sessions/{sid}/sandbox/down", headers=auth_headers)

    assert resp.status_code == 409


def test_wipe_session_sandbox_resets_when_idle(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_sandbox_snapshot(sid, SessionSandboxSnapshot(runtime="docker"))

    resp = client.post(f"/api/sessions/{sid}/sandbox/wipe", headers=auth_headers)

    assert resp.status_code == 200
    srv._engine.sandbox_mgr.reset_session.assert_awaited_once_with(sid)


def test_wipe_session_sandbox_rejects_running_agent(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.agent_task = MagicMock()
    active.agent_task.done.return_value = False

    resp = client.post(f"/api/sessions/{sid}/sandbox/wipe", headers=auth_headers)

    assert resp.status_code == 409


def test_get_nonexistent_session(client, auth_headers):
    resp = client.get("/api/sessions/doesnotexist", headers=auth_headers)
    assert resp.status_code == 404


def test_sandbox_list_credentials_audit(client, auth_headers, monkeypatch):
    """GET /credentials appends CredentialAccessEntry and audit for the session."""
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    mock_reg = MagicMock()
    mock_reg.list = AsyncMock(return_value=[CredentialMetadata(vault_path="dev/key", name="key", description="test")])
    monkeypatch.setattr(srv, "_credential_registry_for_session", AsyncMock(return_value=mock_reg), raising=False)
    srv._engine.sandbox_mgr.verify_session_token.side_effect = lambda s, t: s == sid and t == "secret"
    srv._engine.sandbox_mgr.mark_credential_notified.return_value = False

    basic = base64.b64encode(b"wrong-id:secret").decode()
    sb_client = TestClient(sandbox_app)
    resp = sb_client.get("/credentials", headers={"Authorization": f"Basic {basic}"})
    assert resp.status_code == 401

    basic_ok = base64.b64encode(f"{sid}:secret".encode()).decode()
    resp = sb_client.get("/credentials?q=dev", headers={"Authorization": f"Basic {basic_ok}"})
    assert resp.status_code == 200
    assert resp.json() == [{"vault_path": "dev/key", "name": "key", "description": "test"}]

    active = srv._engine.get_or_activate(sid)
    cred_entries = [e for e in active.security.action_log if isinstance(e, CredentialAccessEntry)]
    assert len(cred_entries) == 1
    assert cred_entries[0].vault_paths == ["dev/key"]
    assert cred_entries[0].decision == "approved"
    assert "query='dev'" in cred_entries[0].explanation

    audit_path = srv._data_dir / "sessions" / sid / "audit.yaml"
    assert audit_path.is_file()
    text = audit_path.read_text()
    assert "credential_access" in text
    assert "auto_allowed" in text


def test_sandbox_list_credentials_backend_error_returns_503(client, auth_headers, monkeypatch):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    mock_reg = MagicMock()
    mock_reg.list = AsyncMock(side_effect=CredentialBackendError("Bitwarden backend unavailable"))
    monkeypatch.setattr(srv, "_credential_registry_for_session", AsyncMock(return_value=mock_reg), raising=False)
    srv._engine.sandbox_mgr.verify_session_token.side_effect = lambda s, t: s == sid and t == "secret"

    basic = base64.b64encode(f"{sid}:secret".encode()).decode()
    sb_client = TestClient(sandbox_app)
    resp = sb_client.get("/credentials", headers={"Authorization": f"Basic {basic}"})

    assert resp.status_code == 503
    assert resp.json() == {"detail": "Bitwarden backend unavailable"}


def test_sandbox_fetch_credential_backend_error_returns_503(client, auth_headers, monkeypatch):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    mock_reg = MagicMock()
    mock_reg.fetch_metadata = AsyncMock(side_effect=CredentialBackendError("Bitwarden backend unavailable"))
    monkeypatch.setattr(srv, "_credential_registry_for_session", AsyncMock(return_value=mock_reg), raising=False)
    srv._engine.sandbox_mgr.verify_session_token.side_effect = lambda s, t: s == sid and t == "secret"

    basic = base64.b64encode(f"{sid}:secret".encode()).decode()
    sb_client = TestClient(sandbox_app)
    resp = sb_client.get("/credentials/bw/id-1", headers={"Authorization": f"Basic {basic}"})

    assert resp.status_code == 503
    assert resp.text == "Bitwarden backend unavailable"


# --- WebSocket: basic slash commands ---


def test_ws_auth_required(client):
    with pytest.raises(Exception), client.websocket_connect("/api/chat/fake"):  # noqa: B017
        pass


def test_ws_session_not_found(client, auth_headers):
    with pytest.raises(Exception), client.websocket_connect("/api/chat/doesnotexist", headers=auth_headers):  # noqa: B017
        pass


def test_ws_ticket_allows_cookie_free_websocket(client, auth_headers):
    ticket_resp = client.post("/api/auth/ws-ticket", headers=auth_headers)
    assert ticket_resp.status_code == 200
    ticket = ticket_resp.json()["ticket"]
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?ticket={ticket}") as ws:
        _consume_status(ws)


def _consume_status(ws):
    """Consume the initial status message sent on connect."""
    msg = ws.receive_json()
    assert msg["type"] == "status"
    return msg


def test_ws_help_command(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}", headers=auth_headers) as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/help"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        assert echo["content"] == "/help"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "help"
        assert "commands" in msg["data"]
        commands = {entry["command"] for entry in msg["data"]["commands"]}
        assert "/skills" in commands
        assert "/session" in commands
        assert "/security" not in commands
        assert "/approve-context" not in commands
        assert "/memory" not in commands


def test_ws_connection_updates_presence_registry(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?client_id=web-tab-1", headers=auth_headers) as ws:
        _consume_status(ws)
        assert srv._notification_presence.is_session_actively_handled(sid) is True

    assert srv._notification_presence.is_session_actively_handled(sid) is False


def test_ws_blank_client_id_falls_back_to_generated_source_id(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}?client_id=%20%20%20", headers=auth_headers) as ws:
        _consume_status(ws)
        entries = srv._notification_presence.list_presence(session_id=sid)
        assert len(entries) == 1
        assert entries[0].source_id.startswith("ws:")
        assert entries[0].source_id != ""

    assert srv._notification_presence.is_session_actively_handled(sid) is False


def test_list_commands_excludes_removed_commands(client, auth_headers):
    resp = client.get("/api/commands", headers=auth_headers)

    assert resp.status_code == 200
    commands = {entry["command"] for entry in resp.json()}
    assert "/skills" in commands
    assert "/session" in commands
    assert "/security" not in commands
    assert "/approve-context" not in commands
    assert "/memory" not in commands


def test_ws_session_command_for_web(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers, json={"channel_type": "web"})
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}", headers=auth_headers) as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/session"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "session"
        assert msg["data"]["session_id"] == sid
        assert msg["data"]["channel_type"] == "web"


def test_ws_reset_to_turn_emits_ack(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.save_events(
        sid,
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "second answer"},
        ],
    )
    srv._engine.session_mgr.save_history(
        sid,
        [
            ModelRequest(parts=[UserPromptPart(content="first")]),
            ModelResponse(parts=[TextPart(content="first answer")]),
            ModelRequest(parts=[UserPromptPart(content="second")]),
            ModelResponse(parts=[TextPart(content="second answer")]),
        ],
    )

    with client.websocket_connect(f"/api/chat/{sid}", headers=auth_headers) as ws:
        _consume_status(ws)
        ws.send_json({"type": "reset_to_turn", "event_index": 1})
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "reset_to_turn"
        assert msg["data"] == {"event_index": 1}

    assert srv._engine.session_mgr.load_events(sid) == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "first answer"},
    ]


def test_ws_status_includes_budget_gauges_for_configured_defaults(client, auth_headers):
    srv._engine.config.agent.default_session_budget = SessionBudget(input_tokens=1_000)
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}", headers=auth_headers) as ws:
        status = _consume_status(ws)
        assert status["usage"]["budget_gauges"][0]["key"] == "input"
        assert status["usage"]["budget_gauges"][0]["current_value"] == "0 tokens"


def test_ws_status_includes_live_llm_activity_when_running(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    active = srv._engine.get_or_activate(sid)
    active.llm_request_state = LlmRequestState(
        request_id="req-1",
        source="agent",
        model_name="anthropic:claude-haiku-4-5",
        started_at=datetime.now(tz=UTC),
        phase="thinking",
    )
    active.agent_task = MagicMock()
    active.agent_task.done.return_value = False

    with client.websocket_connect(f"/api/chat/{sid}", headers=auth_headers) as ws:
        status = _consume_status(ws)
        assert status["llm_activity"]["request_id"] == "req-1"
        assert status["llm_activity"]["phase"] == "thinking"
        assert status["llm_activity"]["source"] == "agent"


def test_history_includes_thinking_reasoning_metadata(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {
                "role": "thinking",
                "content": "first thought",
                "reasoning_duration_ms": 1200,
                "reasoning_tokens": 42,
            },
            {"role": "assistant", "content": "done"},
        ],
    )

    resp = client.get(f"/api/sessions/{sid}/history", headers=auth_headers)

    assert resp.status_code == 200
    history = resp.json()
    assert history[0]["role"] == "thinking"
    assert history[0]["reasoning_duration_ms"] == 1200
    assert history[0]["reasoning_tokens"] == 42


def test_history_includes_assistant_final_status(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]
    srv._engine.session_mgr.append_events(
        sid,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "done", "final_status": "success"},
        ],
    )

    resp = client.get(f"/api/sessions/{sid}/history", headers=auth_headers)

    assert resp.status_code == 200
    history = resp.json()
    assert history[1]["role"] == "assistant"
    assert history[1]["final_status"] == "success"


def test_ws_budget_command_emits_status_refresh(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}", headers=auth_headers) as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/budget input 1000"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "budget"
        status = ws.receive_json()
        assert status["type"] == "status"
        assert status["usage"]["budget_gauges"][0]["key"] == "input"


def test_ws_skills_command(client, auth_headers):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    with client.websocket_connect(f"/api/chat/{sid}", headers=auth_headers) as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/skills"})
        echo = ws.receive_json()
        assert echo["type"] == "user_message"
        msg = ws.receive_json()
        assert msg["type"] == "command_result"
        assert msg["command"] == "skills"


def test_ws_unknown_command_is_agent_message(client, auth_headers, monkeypatch):
    create_resp = client.post("/api/sessions", headers=auth_headers)
    sid = create_resp.json()["session_id"]

    async def _fake_run_turn(
        user_input: str,
        _deps: object,
        message_history: list[object],
        **_kwargs: object,
    ) -> tuple[list[object], str, str, str]:
        assert user_input == "/tmp"
        return (
            [
                *message_history,
                ModelRequest(parts=[UserPromptPart(content=user_input)]),
                ModelResponse(parts=[TextPart(content="treated as text")]),
            ],
            "treated as text",
            "",
            "success",
        )

    monkeypatch.setattr(srv._engine.sandbox_mgr, "refresh_sandbox_snapshot", AsyncMock())
    monkeypatch.setattr(srv._engine, "_generate_title", AsyncMock(return_value="title"))
    monkeypatch.setattr("carapace.session.engine.run_agent_turn", _fake_run_turn)

    with client.websocket_connect(f"/api/chat/{sid}", headers=auth_headers) as ws:
        _consume_status(ws)
        ws.send_json({"type": "message", "content": "/tmp"})
        msg = ws.receive_json()
        assert msg["type"] == "user_message"
        assert msg["content"] == "/tmp"
        msg = ws.receive_json()
        assert msg["type"] == "done"
        assert msg["content"] == "treated as text"
