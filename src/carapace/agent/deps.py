from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from carapace.git.store import GitStore
from carapace.models.config import Config
from carapace.models.credentials import CredentialRegistryProtocol
from carapace.models.session import SessionState
from carapace.models.skills import SkillInfo
from carapace.models.tooling import ToolCallCallback, ToolResult
from carapace.sandbox.manager import SandboxManager
from carapace.security.context import SessionSecurity
from carapace.security.sentinel import Sentinel
from carapace.usage import UsageTracker


class TaskDone(BaseModel):
    """Explicit unattended completion output for successful runs."""

    result: str


class TaskFailed(BaseModel):
    """Explicit unattended completion output for blocked or failed runs."""

    problem: str


class Deps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: Config
    data_dir: Path
    knowledge_dir: Path
    session_state: SessionState
    sandbox: SandboxManager
    security: SessionSecurity
    sentinel: Sentinel
    git_store: GitStore
    skill_catalog: list[SkillInfo] = []
    activated_skills: list[str] = []
    agent_model: Model
    agent_model_id: str = Field(
        description="carapace-registered model id (custom id or provider:name); usage keys, not provider wire ids.",
    )

    tool_call_callback: ToolCallCallback | None = None
    tool_result_callback: Callable[[ToolResult], None] | None = None
    append_session_events: Callable[[list[dict[str, Any]]], None] | None = None
    usage_tracker: UsageTracker
    assert_llm_budget_available: Callable[[], None] | None = None
    llm_usage_limits: Callable[[], UsageLimits | None] | None = None
    credential_registry: CredentialRegistryProtocol
