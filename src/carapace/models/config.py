from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_serializer, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..notifications.models import NotificationsConfig
from .credentials import CredentialsConfig
from .session import SessionBudget


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Secret(ConfigModel):
    """Flexible secret source: raw value, environment variable, or file.

    Accepts a plain string as shorthand for ``Secret(raw="...")``.
    Resolution priority: raw > env > file.
    """

    raw: str | None = None
    env: str | None = None
    file: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"raw": data}
        return data

    def resolve(self) -> SecretStr:
        """Return the resolved secret value.

        Raises ``ValueError`` when no source is configured or the
        configured source (env var / file) does not exist.
        """
        if self.raw is not None:
            return SecretStr(self.raw)
        if self.env is not None:
            val = os.environ.get(self.env)
            if val is None:
                raise ValueError(f"Environment variable {self.env!r} is not set")
            return SecretStr(val)
        if self.file is not None:
            path = Path(self.file)
            if not path.exists():
                raise ValueError(f"Secret file {self.file!r} does not exist")
            return SecretStr(path.read_text().strip())
        raise ValueError("Secret has no source configured (set raw, env, or file)")


class JwtCookieConfig(ConfigModel):
    name: str = "carapace_session"
    issuer: str = "carapace"
    audience: str = "carapace-web"
    ttl_seconds: int = Field(default=60 * 60 * 24 * 14, ge=60)
    secure: bool = False
    same_site: Literal["lax", "strict", "none"] = "lax"


class AuthConfig(ConfigModel):
    cookie: JwtCookieConfig = JwtCookieConfig()


class AvailableModelEntry(ConfigModel):
    """One row in ``agent.available_models``: shorthand ``provider:name`` string or a mapping."""

    provider: str = Field(
        description="API kind used to access the model, such as anthropic, openai, or openai-chat.",
    )
    name: str = Field(
        description="Provider-specific model name sent to that API.",
    )
    id: str | None = Field(
        default=None,
        description="Stable id for this row (slash commands, API). Defaults to provider:name.",
    )
    max_input_tokens: int | None = None
    thinking: bool | Literal["minimal", "low", "medium", "high", "xhigh"] | None = Field(
        default=None,
        description="Enable model thinking/reasoning. true/false to toggle, or an effort level.",
    )
    thinking_budget_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Optional llama.cpp reasoning budget for OpenAI-compatible rows.",
    )
    base_url: str | None = Field(
        default=None,
        description="OpenAI-compatible API base URL (openai / openai-chat rows only).",
    )
    api_key: Secret | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand_string(cls, data: Any) -> Any:
        if isinstance(data, str):
            if ":" not in data:
                msg = f"model string must be 'provider:name', got {data!r}"
                raise ValueError(msg)
            provider, name = data.split(":", 1)
            return {"provider": provider, "name": name}
        return data

    @model_validator(mode="after")
    def _validate_openai_compatible_fields(self) -> AvailableModelEntry:
        if self.base_url is None and self.api_key is None and self.thinking_budget_tokens is None:
            return self
        if self.provider not in ("openai", "openai-chat"):
            raise ValueError(
                "base_url/api_key/thinking_budget_tokens are only supported for provider 'openai' or 'openai-chat'"
            )
        return self

    @property
    def model_id(self) -> str:
        return self.id if self.id is not None else f"{self.provider}:{self.name}"

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Callable[..., Any]) -> dict[str, Any]:
        data = handler(self)
        data["id"] = self.model_id
        return data


def _default_agent_available_models() -> list[AvailableModelEntry]:
    return [
        AvailableModelEntry.model_validate("anthropic:claude-sonnet-4-6"),
        AvailableModelEntry.model_validate("anthropic:claude-haiku-4-5"),
    ]


class AgentConfig(ConfigModel):
    model: str = "anthropic:claude-sonnet-4-6"
    sentinel_model: str = "anthropic:claude-haiku-4-5"
    title_model: str = "anthropic:claude-haiku-4-5"
    default_session_budget: SessionBudget = Field(default_factory=SessionBudget)

    available_models: list[AvailableModelEntry] = Field(default_factory=_default_agent_available_models)

    max_parallel_llm: int = 2

    # Maximum number of sentinel-backed proxy domain review batches one tool call can trigger.
    # 0 disables the cap.
    max_sentinel_calls_per_tool_call: int = 10

    # Debounce window for coalescing proxy domain requests within a tool call.
    sentinel_domain_batch_window_ms: int = 100

    # Max wall-clock time for one sentinel LLM review.
    sentinel_timeout_seconds: int = Field(default=600, ge=1)

    # Cap string length returned to the model (and mirrored to tool_result_callback). 0 = no limit.
    tool_output_max_chars: int = 16_000

    @model_validator(mode="after")
    def _defaults_listed_in_available_models(self) -> AgentConfig:
        if self.max_sentinel_calls_per_tool_call < 0:
            raise ValueError("agent.max_sentinel_calls_per_tool_call must be >= 0")
        if self.sentinel_domain_batch_window_ms < 0:
            raise ValueError("agent.sentinel_domain_batch_window_ms must be >= 0")
        catalog_ids = {e.model_id for e in self.available_models}
        for field_name in ("model", "sentinel_model", "title_model"):
            mid = getattr(self, field_name)
            if mid not in catalog_ids:
                raise ValueError(
                    f"agent.{field_name}={mid!r} must match an entry in agent.available_models (as id or provider:name)"
                )
        return self


def agent_available_model_entries(agent: AgentConfig) -> list[AvailableModelEntry]:
    """Catalog for API and model factory: YAML order, duplicate ``model_id`` keeps last row; sorted ids."""
    by_id: dict[str, AvailableModelEntry] = {}
    for e in agent.available_models:
        by_id[e.model_id] = e
    return sorted(by_id.values(), key=lambda e: e.model_id)


class SandboxConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_SANDBOX_", extra="forbid")

    # Container backend: "docker" for local development, "kubernetes" for cluster deployments.
    runtime: Literal["docker", "kubernetes"] = "docker"
    # Container image used for sandbox pods/containers.
    base_image: str = "carapace-sandbox:latest"
    # Minutes of inactivity before a sandbox is automatically cleaned up.
    idle_timeout_minutes: int = 60
    # Docker network to attach sandbox containers to (docker runtime only).
    network_name: str = "carapace-sandbox"
    # Port of the HTTP proxy sidecar that sandbox traffic is routed through.
    proxy_port: int = 3128
    # Kubernetes namespace where sandbox pods are created.
    k8s_namespace: str = "carapace"
    # PVC claim name for the shared data volume mounted into sandbox pods.
    k8s_pvc_claim: str = "carapace-data"
    # ServiceAccount assigned to sandbox pods (None = namespace default).
    k8s_service_account: str | None = None
    # PriorityClass for sandbox pods (None = cluster default).
    k8s_priority_class: str | None = None
    # Attach ownerReferences on sandbox StatefulSets (and legacy pod sandboxes).
    # When False, resources rely on labels + argocd.argoproj.io/tracking-id only.
    k8s_owner_ref: bool = True
    # Server Deployment name for ownerReference fallback (Helm: release name).
    k8s_server_deployment_name: str = "carapace"
    # Preferred owner for sandbox resources (namespaced Sandboxes CRD singleton).
    # Set to null or an empty string to use k8s_server_deployment_name instead.
    # When set, the named Sandboxes object must exist.
    k8s_sandboxes_name: str | None = "carapace-sandboxes"
    # ArgoCD application / Helm release name. Used for the app.kubernetes.io/instance
    # label and the argocd.argoproj.io/tracking-id annotation so that sandbox pods
    # appear in the ArgoCD resource tree even without an ownerReference.
    k8s_app_instance: str = "carapace"
    # Size of per-session PVCs created via StatefulSet volumeClaimTemplates.
    k8s_session_pvc_size: str = "1Gi"
    # StorageClass for per-session PVCs (empty = cluster default).
    k8s_session_pvc_storage_class: str = ""
    # Resource requests/limits for sandbox containers (empty = no constraint).
    k8s_resource_requests_cpu: str = ""
    k8s_resource_requests_memory: str = ""
    k8s_resource_limits_cpu: str = ""
    k8s_resource_limits_memory: str = ""
    # Remove sandbox resources for sessions that no longer exist on disk at startup.
    cleanup_orphans_on_startup: bool = True


class SessionCommitConfig(ConfigModel):
    enabled: bool = True
    path_prefix: str = "sessions"
    autosave_enabled: bool = True
    autosave_inactivity_hours: int = 4
    delete_from_knowledge_on_session_delete: bool = True

    @model_validator(mode="after")
    def _validate_commit_settings(self) -> SessionCommitConfig:
        if self.autosave_inactivity_hours <= 0:
            raise ValueError("sessions.commit.autosave_inactivity_hours must be > 0")
        prefix = Path(self.path_prefix)
        if prefix.is_absolute() or ".." in prefix.parts:
            raise ValueError("sessions.commit.path_prefix must stay inside the knowledge directory")
        normalized = str(prefix).strip("/")
        self.path_prefix = normalized or "sessions"
        return self


class SessionsConfig(ConfigModel):
    commit: SessionCommitConfig = SessionCommitConfig()


class CacheConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_CACHE_", extra="forbid")

    ttl_seconds: int = 1800
    redis_url: str = "redis://localhost:6379/0"

    @model_validator(mode="after")
    def _validate(self) -> CacheConfig:
        if self.ttl_seconds <= 0:
            raise ValueError("cache.ttl_seconds must be > 0")
        if not self.redis_url.strip():
            raise ValueError("cache.redis_url must not be empty")
        return self


class ServerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARAPACE_SERVER_", extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8321
    sandbox_port: int = 8322
    internal_port: int = 8320
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
    ]


class CarapaceConfig(ConfigModel):
    log_level: str = "info"
    logfire_token: str = ""


class Config(ConfigModel):
    carapace: CarapaceConfig = CarapaceConfig()
    cache: CacheConfig = CacheConfig()
    server: ServerConfig = ServerConfig()
    auth: AuthConfig = AuthConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    agent: AgentConfig = AgentConfig()
    sessions: SessionsConfig = SessionsConfig()
    sandbox: SandboxConfig = SandboxConfig()
    credentials: CredentialsConfig = CredentialsConfig()
    data_dir: str = "."  # resolved relative to config file location
    knowledge_dir: str = "./knowledge"  # resolved relative to config file location
