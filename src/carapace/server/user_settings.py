from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..auth import AuthStore, UserIdentity, normalize_username
from ..credentials.registry import file_credential_backend_allowed_from_env
from ..models.credentials import (
    BitwardenCredentialBackendConfig,
    CredentialsConfig,
    FileCredentialBackendConfig,
)
from ..models.matrix import MatrixChannelConfig
from ..models.session import SessionBudget
from ..models.user import UserConfig, UserDefaultModelsConfig, UserGitConfig
from .auth import verify_token
from .state import server_module

server = server_module()
router = APIRouter()


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CredentialSettingsCapabilities(SettingsModel):
    bitwarden: bool = True
    file: bool = False


class UserSettingsCapabilities(SettingsModel):
    credentials: CredentialSettingsCapabilities


class ServerDefaultModels(SettingsModel):
    agent: str
    sentinel: str
    title: str


class ServerDefaults(SettingsModel):
    models: ServerDefaultModels
    budget: SessionBudget


class PublicBasicAuth(SettingsModel):
    username: str
    password_set: bool = False


class PublicFileCredentialBackend(SettingsModel):
    type: str = "file"
    path: str = ""
    expose: list[str] = []
    hide: list[str] = []


class PublicBitwardenCredentialBackend(SettingsModel):
    type: str = "bitwarden"
    url: str
    basic_auth: PublicBasicAuth | None = None
    expose: list[str] = []
    hide: list[str] = []


class PublicCredentialsSettings(SettingsModel):
    backends: dict[str, PublicFileCredentialBackend | PublicBitwardenCredentialBackend] = {}


class PublicMatrixSettings(SettingsModel):
    enabled: bool
    homeserver: str
    user_id: str
    device_name: str
    password_set: bool = False
    token_set: bool = False
    allowed_rooms: list[str] = []
    allowed_users: list[str] = []


class PublicGitSettings(SettingsModel):
    remote: str
    branch: str
    author: str
    token_set: bool = False


class PublicUserSettings(SettingsModel):
    default_models: UserDefaultModelsConfig
    default_budget: SessionBudget
    matrix: PublicMatrixSettings
    credentials: PublicCredentialsSettings
    git: PublicGitSettings


class UserSettingsResponse(SettingsModel):
    capabilities: UserSettingsCapabilities
    server_defaults: ServerDefaults
    available_models: list[dict[str, Any]]
    settings: PublicUserSettings
    restart_required: list[str] = []


class MatrixSettingsPatch(SettingsModel):
    enabled: bool | None = None
    homeserver: str | None = None
    user_id: str | None = None
    device_name: str | None = None
    password: str | None = None
    clear_password: bool = False
    token: str | None = None
    clear_token: bool = False
    allowed_rooms: list[str] | None = None
    allowed_users: list[str] | None = None

    @field_validator("homeserver", "user_id", "device_name", "password", "token", mode="before")
    @classmethod
    def _normalize_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("allowed_rooms", "allowed_users", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item.strip()]


class GitSettingsPatch(SettingsModel):
    remote: str | None = None
    branch: str | None = None
    author: str | None = None
    token: str | None = None
    clear_token: bool = False

    @field_validator("remote", "branch", "author", "token", mode="before")
    @classmethod
    def _normalize_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UserSettingsPatch(SettingsModel):
    default_models: UserDefaultModelsConfig | None = None
    default_budget: SessionBudget | None = None
    matrix: MatrixSettingsPatch | None = None
    credentials: CredentialsConfig | None = None
    git: GitSettingsPatch | None = None

    @model_validator(mode="after")
    def _validate_nonempty_patch(self) -> UserSettingsPatch:
        if not self.model_fields_set:
            raise ValueError("settings patch must not be empty")
        return self


def _auth_store() -> AuthStore:
    store = getattr(server, "_auth_store", None)
    if isinstance(store, AuthStore):
        return store
    raise HTTPException(status_code=503, detail="Auth store is not initialized")


def _file_backend_allowed() -> bool:
    try:
        return file_credential_backend_allowed_from_env()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _capabilities() -> UserSettingsCapabilities:
    return UserSettingsCapabilities(
        credentials=CredentialSettingsCapabilities(file=_file_backend_allowed()),
    )


def _public_credentials(config: CredentialsConfig) -> PublicCredentialsSettings:
    backends: dict[str, PublicFileCredentialBackend | PublicBitwardenCredentialBackend] = {}
    for name, backend in config.backends.items():
        if isinstance(backend, FileCredentialBackendConfig):
            backends[name] = PublicFileCredentialBackend(
                path=backend.path,
                expose=list(backend.expose),
                hide=list(backend.hide),
            )
            continue
        basic_auth = None
        if backend.basic_auth is not None:
            basic_auth = PublicBasicAuth(
                username=backend.basic_auth.username,
                password_set=backend.basic_auth.password is not None,
            )
        backends[name] = PublicBitwardenCredentialBackend(
            url=backend.url,
            basic_auth=basic_auth,
            expose=list(backend.expose),
            hide=list(backend.hide),
        )
    return PublicCredentialsSettings(backends=backends)


def _public_matrix(config: MatrixChannelConfig) -> PublicMatrixSettings:
    return PublicMatrixSettings(
        enabled=config.enabled,
        homeserver=config.homeserver,
        user_id=config.user_id,
        device_name=config.device_name,
        password_set=config.password is not None,
        token_set=config.token is not None,
        allowed_rooms=list(config.allowed_rooms),
        allowed_users=list(config.allowed_users),
    )


def _public_git(config: UserGitConfig) -> PublicGitSettings:
    return PublicGitSettings(
        remote=config.remote,
        branch=config.branch,
        author=config.author,
        token_set=config.token is not None,
    )


def _available_model_ids() -> set[str]:
    return {entry.model_id for entry in server._engine.available_model_entries}


def _validate_default_models(default_models: UserDefaultModelsConfig) -> None:
    available = _available_model_ids()
    for field_name in ("agent", "sentinel", "title"):
        model_id = getattr(default_models, field_name)
        if model_id is None:
            continue
        if model_id not in available:
            raise HTTPException(status_code=400, detail=f"Unknown {field_name} model: {model_id}")


def _assert_credentials_supported(credentials: CredentialsConfig) -> None:
    if _file_backend_allowed():
        return
    for name, backend in credentials.backends.items():
        if isinstance(backend, FileCredentialBackendConfig):
            raise HTTPException(
                status_code=400,
                detail=f"File credential backend {name!r} is disabled on this server",
            )


def _credentials_with_preserved_backend_passwords(username: str, credentials: CredentialsConfig) -> CredentialsConfig:
    merged = credentials.model_copy(deep=True)
    existing_user = _auth_store().get_user(username)
    existing_credentials = existing_user.config.credentials if existing_user is not None else CredentialsConfig()

    for backend_name, backend in merged.backends.items():
        if not isinstance(backend, BitwardenCredentialBackendConfig) or backend.basic_auth is None:
            continue
        if backend.basic_auth.password is not None:
            continue
        existing_backend = existing_credentials.backends.get(backend_name)
        if isinstance(existing_backend, BitwardenCredentialBackendConfig) and existing_backend.basic_auth is not None:
            backend.basic_auth.password = existing_backend.basic_auth.password
        if backend.basic_auth.password is None:
            raise HTTPException(
                status_code=400,
                detail=f"basic_auth.password is required for credential backend {backend_name!r}",
            )
    return merged


def _assert_git_remote_owner(username: str, next_config: UserConfig) -> None:
    if not next_config.git.remote:
        return
    normalized_username = normalize_username(username)
    for other_username, other_user in _auth_store().load_users().users.items():
        if normalize_username(other_username) == normalized_username:
            continue
        if other_user.enabled and other_user.config.git.remote:
            raise HTTPException(
                status_code=400,
                detail=f"Knowledge Git remote is already configured for user {other_username!r}",
            )


async def _invalidate_user_credential_registry(username: str) -> None:
    registries = getattr(server, "_user_credential_registries", None)
    if not isinstance(registries, dict):
        return
    cached = registries.pop(normalize_username(username), None)
    if cached is None:
        return
    _, registry = cached
    await registry.close()


def _settings_response(username: str, *, restart_required: list[str] | None = None) -> UserSettingsResponse:
    user = _auth_store().get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    config = user.config
    return UserSettingsResponse(
        capabilities=_capabilities(),
        server_defaults=ServerDefaults(
            models=ServerDefaultModels(
                agent=server._config.agent.model,
                sentinel=server._config.agent.sentinel_model,
                title=server._config.agent.title_model,
            ),
            budget=server._config.agent.default_session_budget,
        ),
        available_models=[
            entry.model_dump(mode="json", by_alias=True) for entry in server._engine.available_model_entries
        ],
        settings=PublicUserSettings(
            default_models=config.default_models,
            default_budget=config.budgets,
            matrix=_public_matrix(config.channels.matrix),
            credentials=_public_credentials(config.credentials),
            git=_public_git(config.git),
        ),
        restart_required=restart_required or [],
    )


def _apply_matrix_patch(config: UserConfig, patch: MatrixSettingsPatch) -> None:
    matrix = config.channels.matrix.model_copy(deep=True)
    fields = patch.model_fields_set
    if "enabled" in fields and patch.enabled is not None:
        matrix.enabled = patch.enabled
    if "homeserver" in fields:
        matrix.homeserver = patch.homeserver or ""
    if "user_id" in fields:
        matrix.user_id = patch.user_id or ""
    if "device_name" in fields:
        matrix.device_name = patch.device_name or "carapace"
    if patch.clear_password:
        matrix.password = None
    elif "password" in fields:
        matrix.password = patch.password
    if patch.clear_token:
        matrix.token = None
    elif "token" in fields:
        matrix.token = patch.token
    if "allowed_rooms" in fields:
        matrix.allowed_rooms = patch.allowed_rooms or []
    if "allowed_users" in fields:
        matrix.allowed_users = patch.allowed_users or []
    config.channels.matrix = MatrixChannelConfig.model_validate(matrix.model_dump(mode="python"))


def _apply_git_patch(config: UserConfig, patch: GitSettingsPatch) -> None:
    git = config.git.model_copy(deep=True)
    fields = patch.model_fields_set
    if "remote" in fields:
        git.remote = patch.remote or ""
    if "branch" in fields:
        git.branch = patch.branch or "main"
    if "author" in fields:
        git.author = patch.author or "carapace <carapace@%h>"
    if patch.clear_token:
        git.token = None
    elif "token" in fields:
        git.token = patch.token
    config.git = UserGitConfig.model_validate(git.model_dump(mode="python"))


@router.get("/user/settings", response_model=UserSettingsResponse)
async def get_user_settings(user: Annotated[UserIdentity, Depends(verify_token)]) -> UserSettingsResponse:
    return _settings_response(user.username)


@router.patch("/user/settings", response_model=UserSettingsResponse)
async def update_user_settings(
    body: UserSettingsPatch,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> UserSettingsResponse:
    stored_user = _auth_store().get_user(user.username)
    if stored_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    next_config = stored_user.config.model_copy(deep=True)
    restart_required: list[str] = []
    credentials_changed = False

    if "default_models" in body.model_fields_set:
        next_config.default_models = body.default_models or UserDefaultModelsConfig()
        _validate_default_models(next_config.default_models)

    if "default_budget" in body.model_fields_set:
        next_config.budgets = body.default_budget or SessionBudget()

    if body.matrix is not None:
        _apply_matrix_patch(next_config, body.matrix)
        restart_required.append("matrix")

    if "credentials" in body.model_fields_set:
        credentials = body.credentials or CredentialsConfig()
        _assert_credentials_supported(credentials)
        next_config.credentials = _credentials_with_preserved_backend_passwords(user.username, credentials)
        credentials_changed = True

    if body.git is not None:
        _apply_git_patch(next_config, body.git)
        _assert_git_remote_owner(user.username, next_config)
        restart_required.append("git")

    try:
        _auth_store().update_user(user.username, {"config": next_config})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if credentials_changed:
        await _invalidate_user_credential_registry(user.username)

    return _settings_response(user.username, restart_required=restart_required)
