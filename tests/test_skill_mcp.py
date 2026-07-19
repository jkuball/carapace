"""Tests for skill-declared MCP server connections."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from pydantic_ai import ToolDenied
from pydantic_ai.toolsets.prefixed import PrefixedToolset

from carapace.agent.tools import _mcp_process_tool_call, build_skill_mcp_toolset
from carapace.models.skills import (
    ContextGrant,
    SkillCarapaceConfig,
    SkillMcpBearerAuth,
    SkillMcpDecl,
    context_grants_session_summary,
)
from carapace.security.context import ContextGrantEntry, SecurityDeniedError
from carapace.security.sentinel import _format_entry

# ── Models ──────────────────────────────────────────────────────────


class TestSkillMcpDecl:
    def test_valid(self):
        decl = SkillMcpDecl(
            name="linear",
            url="https://mcp.linear.app/mcp",
            auth=SkillMcpBearerAuth(vault_path="dev/linear-token"),
        )
        assert decl.auth is not None and decl.auth.type == "bearer"
        assert decl.display == "linear (https://mcp.linear.app/mcp)"

    def test_auth_optional(self):
        decl = SkillMcpDecl(name="local", url="http://localhost:8000/mcp")
        assert decl.auth is None

    @pytest.mark.parametrize("name", ["1abc", "with-dash", "with.dot", "with space", ""])
    def test_invalid_name(self, name: str):
        with pytest.raises(ValidationError):
            SkillMcpDecl(name=name, url="https://example.com/mcp")

    @pytest.mark.parametrize("url", ["ftp://example.com", "example.com/mcp", "file:///tmp/x"])
    def test_invalid_url(self, url: str):
        with pytest.raises(ValidationError):
            SkillMcpDecl(name="ok", url=url)

    def test_auth_from_yaml_shape(self):
        cfg = SkillCarapaceConfig.model_validate(
            {"mcp": [{"name": "l", "url": "https://x.example/mcp", "auth": {"type": "bearer", "vault_path": "dev/t"}}]}
        )
        assert cfg.mcp[0].auth is not None and cfg.mcp[0].auth.vault_path == "dev/t"

    def test_duplicate_names_rejected(self):
        with pytest.raises(ValidationError):
            SkillCarapaceConfig.model_validate(
                {"mcp": [{"name": "a", "url": "https://x.example/mcp"}, {"name": "a", "url": "https://y.example/mcp"}]}
            )


class TestGrantIntegration:
    def test_grant_holds_mcp_servers(self):
        grant = ContextGrant(skill_name="s", mcp_servers=[SkillMcpDecl(name="m", url="https://x.example/mcp")])
        summary = context_grants_session_summary("sid", {"s": grant}, lambda _sid, _vp: None)
        assert summary["s"]["mcp_servers"] == ["m (https://x.example/mcp)"]

    def test_sentinel_formats_grant_entry(self):
        entry = ContextGrantEntry(skill_name="s", mcp_servers=["m (https://x.example/mcp)"])
        assert "mcp_servers=" in _format_entry(entry)


# ── Toolset factory ─────────────────────────────────────────────────


def _ctx_with_grants(grants: dict, *, cached_token: str | None = "tok") -> MagicMock:
    ctx = MagicMock()
    ctx.deps.session_state.session_id = "sid"
    ctx.deps.session_state.context_grants = grants
    ctx.deps.mcp_toolsets = {}
    ctx.deps.sandbox.get_cached_credential = MagicMock(return_value=cached_token)
    ctx.deps.credential_registry.fetch = AsyncMock(return_value="fetched-tok")
    ctx.deps.sandbox.cache_credential = MagicMock()
    return ctx


class TestBuildSkillMcpToolset:
    async def test_no_grants_returns_none(self):
        assert await build_skill_mcp_toolset(_ctx_with_grants({})) is None

    async def test_single_server_prefixed_and_cached(self):
        decl = SkillMcpDecl(name="linear", url="https://x.example/mcp", auth=SkillMcpBearerAuth(vault_path="dev/t"))
        ctx = _ctx_with_grants({"s": ContextGrant(skill_name="s", mcp_servers=[decl])})
        toolset = await build_skill_mcp_toolset(ctx)
        assert isinstance(toolset, PrefixedToolset)
        assert toolset.prefix == "linear"
        assert ctx.deps.mcp_toolsets["s:linear"] is toolset
        # second evaluation reuses the cached instance
        assert await build_skill_mcp_toolset(ctx) is toolset

    async def test_token_refetched_on_cache_miss(self):
        decl = SkillMcpDecl(name="m", url="https://x.example/mcp", auth=SkillMcpBearerAuth(vault_path="dev/t"))
        ctx = _ctx_with_grants({"s": ContextGrant(skill_name="s", mcp_servers=[decl])}, cached_token=None)
        assert await build_skill_mcp_toolset(ctx) is not None
        ctx.deps.credential_registry.fetch.assert_awaited_once_with("dev/t")
        ctx.deps.sandbox.cache_credential.assert_called_once_with("sid", "dev/t", "fetched-tok")

    async def test_token_fetch_failure_skips_server(self):
        decl = SkillMcpDecl(name="m", url="https://x.example/mcp", auth=SkillMcpBearerAuth(vault_path="dev/t"))
        ctx = _ctx_with_grants({"s": ContextGrant(skill_name="s", mcp_servers=[decl])}, cached_token=None)
        ctx.deps.credential_registry.fetch = AsyncMock(side_effect=KeyError("missing"))
        assert await build_skill_mcp_toolset(ctx) is None


# ── process_tool_call gating ────────────────────────────────────────


def _process_ctx(*, approved: bool = False) -> MagicMock:
    ctx = MagicMock()
    ctx.tool_call_approved = approved
    ctx.deps.config.agent.tool_output_max_chars = 16_000
    ctx.deps.tool_result_callback = None
    ctx.deps.tool_call_callback = None
    ctx.deps.assert_llm_budget_available = None
    ctx.deps.llm_usage_limits = None
    return ctx


class TestMcpProcessToolCall:
    async def test_denied_call_returns_tool_denied_without_calling_server(self):
        decl = SkillMcpDecl(name="m", url="https://x.example/mcp")
        hook = _mcp_process_tool_call("s", decl)
        ctx = _process_ctx()
        call_tool = AsyncMock()
        with patch("carapace.agent.tools.security.evaluate_with", AsyncMock(side_effect=SecurityDeniedError("no"))):
            result = await hook(ctx, call_tool, "search", {"q": "x"})
        assert isinstance(result, ToolDenied)
        call_tool.assert_not_awaited()

    async def test_allowed_call_passes_through(self):
        decl = SkillMcpDecl(name="m", url="https://x.example/mcp")
        hook = _mcp_process_tool_call("s", decl)
        ctx = _process_ctx()
        call_tool = AsyncMock(return_value={"items": [1, 2]})
        with patch("carapace.agent.tools.security.evaluate_with", AsyncMock(return_value=None)) as gate:
            result = await hook(ctx, call_tool, "search", {"q": "x"})
        assert result == {"items": [1, 2]}
        call_tool.assert_awaited_once_with("search", {"q": "x"})
        gate_args = gate.await_args.args
        assert gate_args[2] == "mcp:m:search"

    async def test_approved_call_skips_gate(self):
        decl = SkillMcpDecl(name="m", url="https://x.example/mcp")
        hook = _mcp_process_tool_call("s", decl)
        ctx = _process_ctx(approved=True)
        call_tool = AsyncMock(return_value="ok")
        with patch("carapace.agent.tools.security.evaluate_with", AsyncMock()) as gate:
            result = await hook(ctx, call_tool, "search", {})
        assert result == "ok"
        gate.assert_not_awaited()

    async def test_oversized_text_result_is_spilled(self):
        decl = SkillMcpDecl(name="m", url="https://x.example/mcp")
        hook = _mcp_process_tool_call("s", decl)
        ctx = _process_ctx()
        ctx.deps.config.agent.tool_output_max_chars = 1000
        ctx.deps.session_state.session_id = "sid"
        write_result = MagicMock(exit_code=0)
        ctx.deps.sandbox.file_write = AsyncMock(return_value=write_result)
        call_tool = AsyncMock(return_value="x" * 5000)
        with patch("carapace.agent.tools.security.evaluate_with", AsyncMock(return_value=None)):
            result = await hook(ctx, call_tool, "search", {})
        assert isinstance(result, str)
        assert "Full output saved to" in result
        ctx.deps.sandbox.file_write.assert_awaited_once()
