"""Tests for OAuth MCP auth (refresh + vault write-back) and MCP prewarm/degradation."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from carapace.agent.tools import _prewarm_skill_mcp, _VaultOAuth
from carapace.credentials.protocol import CredentialBackendError
from carapace.models.skills import ContextGrant, SkillCarapaceConfig, SkillMcpDecl, SkillMcpOAuthAuth

# ── Model ───────────────────────────────────────────────────────────


class TestOAuthDecl:
    def test_oauth_http_valid(self):
        cfg = SkillCarapaceConfig.model_validate(
            {
                "mcp": [
                    {"name": "idealo", "url": "https://mcp.example/mcp", "auth": {"type": "oauth", "vault_path": "v/o"}}
                ]
            }
        )
        assert isinstance(cfg.mcp[0].auth, SkillMcpOAuthAuth)

    def test_oauth_on_stdio_rejected(self):
        with pytest.raises(ValidationError):
            SkillMcpDecl(name="x", command="run", auth=SkillMcpOAuthAuth(vault_path="v/o"))


# ── _VaultOAuth ─────────────────────────────────────────────────────


class _FakeCred:
    def __init__(self, blob: dict):
        self._value = json.dumps(blob)
        self.written: str | None = None

    async def fetch(self, vault_path: str) -> str:
        return self._value

    async def write(self, vault_path: str, value: str) -> None:
        self.written = value


def _patch_token_endpoint(*, status: int = 200, payload: dict | None = None):
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload or {})
    resp.text = json.dumps(payload or {})
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return patch("carapace.agent.tools.httpx.AsyncClient", MagicMock(return_value=cm)), client


_BASE_BLOB = {"token_url": "https://issuer/token", "client_id": "cid", "refresh_token": "rt"}


class TestVaultOAuth:
    async def test_refresh_when_no_access_token(self):
        cred = _FakeCred(dict(_BASE_BLOB))
        auth = _VaultOAuth(cred, "v/o")
        p, client = _patch_token_endpoint(payload={"access_token": "AT", "expires_in": 3600})
        with p:
            token = await auth._token()
        assert token == "AT"
        client.post.assert_awaited_once()
        # rotated blob written back with new access token + derived expiry
        written = json.loads(cred.written)
        assert written["access_token"] == "AT"
        assert written["expires_at"] > time.time()

    async def test_no_refresh_when_fresh(self):
        blob = {**_BASE_BLOB, "access_token": "cached", "expires_at": time.time() + 9999}
        auth = _VaultOAuth(_FakeCred(blob), "v/o")
        p, client = _patch_token_endpoint(payload={"access_token": "NEW"})
        with p:
            token = await auth._token()
        assert token == "cached"
        client.post.assert_not_awaited()

    async def test_refresh_when_expired(self):
        blob = {**_BASE_BLOB, "access_token": "old", "expires_at": time.time() - 1}
        auth = _VaultOAuth(_FakeCred(blob), "v/o")
        p, client = _patch_token_endpoint(payload={"access_token": "fresh", "expires_in": 3600})
        with p:
            token = await auth._token()
        assert token == "fresh"
        client.post.assert_awaited_once()

    async def test_rotated_refresh_token_persisted(self):
        cred = _FakeCred(dict(_BASE_BLOB))
        auth = _VaultOAuth(cred, "v/o")
        p, _ = _patch_token_endpoint(payload={"access_token": "AT", "refresh_token": "rt2", "expires_in": 60})
        with p:
            await auth._token()
        assert json.loads(cred.written)["refresh_token"] == "rt2"

    async def test_refresh_http_error_raises(self):
        auth = _VaultOAuth(_FakeCred(dict(_BASE_BLOB)), "v/o")
        p, _ = _patch_token_endpoint(status=400, payload={"error": "invalid_grant"})
        with p, pytest.raises(CredentialBackendError, match="refresh"):
            await auth._token()

    async def test_missing_required_field_raises(self):
        auth = _VaultOAuth(_FakeCred({"client_id": "cid", "refresh_token": "rt"}), "v/o")  # no token_url
        with pytest.raises(CredentialBackendError, match="token_url"):
            await auth._token()

    async def test_prewarm_triggers_refresh(self):
        cred = _FakeCred(dict(_BASE_BLOB))
        auth = _VaultOAuth(cred, "v/o")
        p, client = _patch_token_endpoint(payload={"access_token": "AT", "expires_in": 60})
        with p:
            await auth.prewarm()
        client.post.assert_awaited_once()


# ── Prewarm / graceful degradation ──────────────────────────────────


class TestPrewarm:
    async def test_success_caches_and_reports_ready(self):
        decl = SkillMcpDecl(name="srv", url="https://e.example/mcp")
        ctx = MagicMock()
        ctx.deps.mcp_toolsets = {}
        grant = ContextGrant(skill_name="s", mcp_servers=[decl])
        with patch("carapace.agent.tools._build_one_mcp_toolset", AsyncMock(return_value=MagicMock())):
            lines = await _prewarm_skill_mcp(ctx, "s", grant)
        assert "s:srv" in ctx.deps.mcp_toolsets
        assert any("ready" in ln and "srv_*" in ln for ln in lines)

    async def test_failure_reports_unavailable_without_raising(self):
        decl = SkillMcpDecl(name="srv", url="https://e.example/mcp")
        ctx = MagicMock()
        ctx.deps.mcp_toolsets = {}
        grant = ContextGrant(skill_name="s", mcp_servers=[decl])
        with patch(
            "carapace.agent.tools._build_one_mcp_toolset",
            AsyncMock(side_effect=CredentialBackendError("token expired")),
        ):
            lines = await _prewarm_skill_mcp(ctx, "s", grant)
        assert "s:srv" not in ctx.deps.mcp_toolsets
        assert any("UNAVAILABLE" in ln and "token expired" in ln for ln in lines)
