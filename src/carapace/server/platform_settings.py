from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..config import get_config_path
from ..llm import make_model_factory
from ..models.config import AgentConfig, AvailableModelEntry, Config, Secret, agent_available_model_entries
from ..models.session import SessionBudget
from .auth import verify_admin_user
from .state import server_module

server = server_module()
router = APIRouter()


class PlatformSettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformDefaultModels(PlatformSettingsModel):
    agent: str
    sentinel: str
    title: str


class PublicModelSecret(PlatformSettingsModel):
    source: Literal["raw", "env", "file"] | None = None
    value: str | None = None
    configured: bool = False


class PublicPlatformModelEntry(PlatformSettingsModel):
    id: str
    provider: str
    name: str
    max_input_tokens: int | None = None
    thinking: bool | Literal["minimal", "low", "medium", "high", "xhigh"] | None = None
    thinking_budget_tokens: int | None = None
    base_url: str | None = None
    api_key: PublicModelSecret = PublicModelSecret()


class PlatformSettingsPayload(PlatformSettingsModel):
    default_models: PlatformDefaultModels
    default_budget: SessionBudget
    available_models: list[PublicPlatformModelEntry]


class PlatformSettingsResponse(PlatformSettingsModel):
    config_path: str
    config_writable: bool
    settings: PlatformSettingsPayload


class PlatformSecretPatch(PlatformSettingsModel):
    source: Literal["raw", "env", "file"] | None = None
    value: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _normalize_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PlatformModelEntryPatch(PlatformSettingsModel):
    provider: str
    name: str
    id: str | None = None
    max_input_tokens: int | None = Field(default=None, ge=1)
    thinking: bool | Literal["minimal", "low", "medium", "high", "xhigh"] | None = None
    thinking_budget_tokens: int | None = Field(default=None, ge=0)
    base_url: str | None = None
    api_key: PlatformSecretPatch | None = None

    @field_validator("provider", "name", "id", "base_url", mode="before")
    @classmethod
    def _normalize_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _validate_required_strings(self) -> PlatformModelEntryPatch:
        if not self.provider:
            raise ValueError("model provider is required")
        if not self.name:
            raise ValueError("model name is required")
        return self

    @property
    def model_id(self) -> str:
        return self.id if self.id is not None else f"{self.provider}:{self.name}"


class PlatformSettingsPatch(PlatformSettingsModel):
    default_models: PlatformDefaultModels
    default_budget: SessionBudget = SessionBudget()
    available_models: list[PlatformModelEntryPatch]

    @model_validator(mode="after")
    def _validate_available_models_nonempty(self) -> PlatformSettingsPatch:
        if not self.available_models:
            raise ValueError("at least one model must be configured")
        return self


def _config_path() -> Path:
    configured = getattr(server, "_config_path", None)
    if isinstance(configured, Path):
        return configured
    return get_config_path()


def _read_config_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=500, detail="Config file root must be a mapping")
    return raw


def _write_config_document(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(f"{path.name}.{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}.bak")
    if path.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _public_secret(secret: Secret | None) -> PublicModelSecret:
    if secret is None:
        return PublicModelSecret()
    if secret.raw is not None:
        return PublicModelSecret(source="raw", configured=True)
    if secret.env is not None:
        return PublicModelSecret(source="env", value=secret.env, configured=True)
    if secret.file is not None:
        return PublicModelSecret(source="file", value=secret.file, configured=True)
    return PublicModelSecret()


def _public_model_entry(entry: AvailableModelEntry) -> PublicPlatformModelEntry:
    return PublicPlatformModelEntry(
        id=entry.model_id,
        provider=entry.provider,
        name=entry.name,
        max_input_tokens=entry.max_input_tokens,
        thinking=entry.thinking,
        thinking_budget_tokens=entry.thinking_budget_tokens,
        base_url=entry.base_url,
        api_key=_public_secret(entry.api_key),
    )


def _response() -> PlatformSettingsResponse:
    path = _config_path()
    return PlatformSettingsResponse(
        config_path=str(path),
        config_writable=path.exists() and path.is_file() and path.parent.exists(),
        settings=PlatformSettingsPayload(
            default_models=PlatformDefaultModels(
                agent=server._config.agent.model,
                sentinel=server._config.agent.sentinel_model,
                title=server._config.agent.title_model,
            ),
            default_budget=server._config.agent.default_session_budget,
            available_models=[
                _public_model_entry(entry) for entry in agent_available_model_entries(server._config.agent)
            ],
        ),
    )


def _secret_from_patch(patch: PlatformSecretPatch | None, existing: Secret | None) -> Secret | None:
    if patch is None:
        return existing.model_copy(deep=True) if existing is not None else None
    if patch.source is None:
        return None
    if patch.source == "raw":
        if patch.value is not None:
            return Secret(raw=patch.value)
        if existing is not None and existing.raw is not None:
            return existing.model_copy(deep=True)
        raise HTTPException(status_code=400, detail="Raw API key value is required for new raw secrets")
    if patch.value is None:
        raise HTTPException(status_code=400, detail=f"{patch.source} API key value is required")
    if patch.source == "env":
        return Secret(env=patch.value)
    return Secret(file=patch.value)


def _agent_config_from_patch(body: PlatformSettingsPatch) -> AgentConfig:
    existing_by_id = {entry.model_id: entry for entry in agent_available_model_entries(server._config.agent)}
    entries = []
    for patch in body.available_models:
        existing = existing_by_id.get(patch.model_id)
        entries.append(
            AvailableModelEntry(
                provider=patch.provider,
                name=patch.name,
                id=patch.id,
                max_input_tokens=patch.max_input_tokens,
                thinking=patch.thinking,
                thinking_budget_tokens=patch.thinking_budget_tokens,
                base_url=patch.base_url,
                api_key=_secret_from_patch(patch.api_key, existing.api_key if existing is not None else None),
            )
        )
    return AgentConfig(
        model=body.default_models.agent,
        sentinel_model=body.default_models.sentinel,
        title_model=body.default_models.title,
        default_session_budget=body.default_budget,
        available_models=entries,
        max_parallel_llm=server._config.agent.max_parallel_llm,
        max_sentinel_calls_per_tool_call=server._config.agent.max_sentinel_calls_per_tool_call,
        sentinel_domain_batch_window_ms=server._config.agent.sentinel_domain_batch_window_ms,
        sentinel_timeout_seconds=server._config.agent.sentinel_timeout_seconds,
        tool_output_max_chars=server._config.agent.tool_output_max_chars,
    )


def _secret_to_yaml(secret: Secret | None) -> dict[str, str] | None:
    if secret is None:
        return None
    if secret.raw is not None:
        return {"raw": secret.raw}
    if secret.env is not None:
        return {"env": secret.env}
    if secret.file is not None:
        return {"file": secret.file}
    return None


def _model_entry_to_yaml(entry: AvailableModelEntry) -> dict[str, Any]:
    data: dict[str, Any] = {
        "provider": entry.provider,
        "name": entry.name,
    }
    if entry.id is not None:
        data["id"] = entry.id
    if entry.max_input_tokens is not None:
        data["max_input_tokens"] = entry.max_input_tokens
    if entry.thinking is not None:
        data["thinking"] = entry.thinking
    if entry.thinking_budget_tokens is not None:
        data["thinking_budget_tokens"] = entry.thinking_budget_tokens
    if entry.base_url is not None:
        data["base_url"] = entry.base_url
    secret = _secret_to_yaml(entry.api_key)
    if secret is not None:
        data["api_key"] = secret
    return data


def _agent_config_to_yaml(agent: AgentConfig) -> dict[str, Any]:
    data: dict[str, Any] = {
        "model": agent.model,
        "sentinel_model": agent.sentinel_model,
        "title_model": agent.title_model,
        "default_session_budget": agent.default_session_budget.model_dump(mode="json", exclude_none=True),
        "available_models": [_model_entry_to_yaml(entry) for entry in agent.available_models],
        "max_parallel_llm": agent.max_parallel_llm,
        "max_sentinel_calls_per_tool_call": agent.max_sentinel_calls_per_tool_call,
        "sentinel_domain_batch_window_ms": agent.sentinel_domain_batch_window_ms,
        "sentinel_timeout_seconds": agent.sentinel_timeout_seconds,
        "tool_output_max_chars": agent.tool_output_max_chars,
    }
    if not data["default_session_budget"]:
        data.pop("default_session_budget")
    return data


def _validated_config_with_agent(agent: AgentConfig, document: dict[str, Any]) -> Config:
    candidate = dict(document)
    candidate["agent"] = _agent_config_to_yaml(agent)
    return Config.model_validate(candidate)


def _apply_runtime_config(config: Config) -> None:
    model_factory = make_model_factory(config)
    agent_model = model_factory(config.agent.model)
    model_factory(config.agent.sentinel_model)
    model_factory(config.agent.title_model)
    server.__dict__["_config"] = config
    server._engine.apply_platform_model_config(config, model_factory=model_factory, agent_model=agent_model)


@router.get("/admin/platform/settings", response_model=PlatformSettingsResponse)
async def get_platform_settings(
    _admin: Annotated[object, Depends(verify_admin_user)],
) -> PlatformSettingsResponse:
    return _response()


@router.patch("/admin/platform/settings", response_model=PlatformSettingsResponse)
async def update_platform_settings(
    body: PlatformSettingsPatch,
    _admin: Annotated[object, Depends(verify_admin_user)],
) -> PlatformSettingsResponse:
    path = _config_path()
    document = _read_config_document(path)
    agent = _agent_config_from_patch(body)
    config = _validated_config_with_agent(agent, document)
    document["agent"] = _agent_config_to_yaml(config.agent)
    try:
        _write_config_document(path, document)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}") from exc
    _apply_runtime_config(config)
    return _response()
