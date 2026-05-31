from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketException, status
from pydantic import BaseModel

from ..auth import AuthStore, UserIdentity, has_admin_role, normalize_username
from ..models.credentials import BitwardenCredentialBackendConfig
from ..models.user import UserConfig
from .runtime import KnowledgeGitConfig
from .state import server_module

server = server_module()

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class PublicUserIdentity(BaseModel):
    username: str
    display_name: str = ""
    email: str | None = None
    roles: list[str] = []
    config: dict[str, Any] = {}


class LoginResponse(BaseModel):
    user: PublicUserIdentity


class WebSocketTicketResponse(BaseModel):
    ticket: str


class AdminUserCreateRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    email: str | None = None
    roles: list[str] = []
    config: UserConfig = UserConfig()


class AdminUserUpdateRequest(BaseModel):
    display_name: str | None = None
    email: str | None = None
    roles: list[str] | None = None
    enabled: bool | None = None
    password: str | None = None
    config: UserConfig | None = None


class AdminUserResponse(BaseModel):
    username: str
    enabled: bool
    token_version: int
    display_name: str
    email: str | None = None
    roles: list[str] = []
    created_at: str
    updated_at: str
    password_changed_at: str
    last_login_at: str | None = None
    config: dict[str, Any]


def _redact_user_config(config: UserConfig) -> dict[str, Any]:
    payload = config.model_dump(mode="json", exclude_none=True)
    matrix = payload.get("channels", {}).get("matrix", {})
    if isinstance(matrix, dict):
        matrix.pop("password", None)
        matrix.pop("token", None)
    git = payload.get("git", {})
    if isinstance(git, dict):
        git.pop("token", None)
    backends = payload.get("credentials", {}).get("backends", {})
    if isinstance(backends, dict):
        for backend in backends.values():
            if not isinstance(backend, dict):
                continue
            basic_auth = backend.get("basic_auth")
            if isinstance(basic_auth, dict):
                basic_auth.pop("password", None)
    return payload


def _public_identity(user: UserIdentity) -> PublicUserIdentity:
    return PublicUserIdentity(
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        roles=user.roles,
        config=_redact_user_config(user.config),
    )


def _config_with_preserved_backend_passwords(username: str | None, config: UserConfig) -> UserConfig:
    merged = config.model_copy(deep=True)
    existing_user = _auth_store().get_user(username) if username is not None else None
    existing_config = existing_user.config if existing_user is not None else None

    for backend_name, backend in merged.credentials.backends.items():
        if not isinstance(backend, BitwardenCredentialBackendConfig) or backend.basic_auth is None:
            continue
        if backend.basic_auth.password is not None:
            continue
        existing_backend = None
        if existing_config is not None:
            existing_backend = existing_config.credentials.backends.get(backend_name)
        if isinstance(existing_backend, BitwardenCredentialBackendConfig) and existing_backend.basic_auth is not None:
            backend.basic_auth.password = existing_backend.basic_auth.password
        if backend.basic_auth.password is None:
            raise ValueError(f"basic_auth.password is required for credential backend {backend_name!r}")
    return merged


def _auth_store() -> AuthStore:
    store = getattr(server, "_auth_store", None)
    if isinstance(store, AuthStore):
        return store
    data_dir = getattr(server, "_data_dir", None)
    config = getattr(server, "_config", None)
    if data_dir is None or config is None:
        raise HTTPException(status_code=503, detail="Auth store is not initialized")
    store = AuthStore(data_dir, config.auth)
    server._auth_store = store  # type: ignore[attr-defined]
    return store


def _user_response(username: str) -> AdminUserResponse:
    try:
        normalized_username = normalize_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user = _auth_store().get_user(normalized_username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return AdminUserResponse(
        username=normalized_username,
        enabled=user.enabled,
        token_version=user.token_version,
        display_name=user.display_name,
        email=user.email,
        roles=user.roles,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
        password_changed_at=user.password_changed_at.isoformat(),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at is not None else None,
        config=_redact_user_config(user.config),
    )


async def current_user(request: Request) -> UserIdentity:
    session_cookie = request.cookies.get(server._config.auth.cookie.name)
    if not session_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    identity = _auth_store().validate_session_token(session_cookie)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return identity


async def current_ws_user(websocket: WebSocket) -> UserIdentity:
    cookie_name = server._config.auth.cookie.name
    token = websocket.cookies.get(cookie_name)
    ticket = websocket.query_params.get("ticket")
    if token:
        identity = _auth_store().validate_session_token(token)
    elif ticket:
        identity = _auth_store().validate_websocket_token(ticket)
    else:
        identity = None
    if identity is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    return identity


async def verify_token(user: Annotated[UserIdentity, Depends(current_user)]) -> UserIdentity:
    return user


async def verify_ws_token(websocket: WebSocket) -> UserIdentity:
    return await current_ws_user(websocket)


async def verify_admin_user(user: Annotated[UserIdentity, Depends(current_user)]) -> UserIdentity:
    if not has_admin_role(user.roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def _enabled_admin_usernames() -> set[str]:
    return {
        username
        for username, user in _auth_store().load_users().users.items()
        if user.enabled and has_admin_role(user.roles)
    }


def _assert_not_removing_last_admin(username: str, updates: dict[str, object]) -> None:
    normalized_username = normalize_username(username)
    enabled_admins = _enabled_admin_usernames()
    if normalized_username not in enabled_admins or len(enabled_admins) > 1:
        return

    existing = _auth_store().get_user(normalized_username)
    if existing is None:
        return

    next_enabled = updates.get("enabled", existing.enabled)
    next_roles = updates.get("roles", existing.roles)
    if next_enabled is False or not (isinstance(next_roles, list) and has_admin_role(next_roles)):
        raise HTTPException(status_code=400, detail="Cannot remove the last enabled admin")


def _assert_user_can_be_deleted(username: str, admin_user: UserIdentity) -> None:
    normalized_username = normalize_username(username)
    if normalized_username == normalize_username(admin_user.username):
        raise HTTPException(status_code=400, detail="Cannot delete your own user")

    existing = _auth_store().get_user(normalized_username)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found")

    if existing.enabled and has_admin_role(existing.roles) and len(_enabled_admin_usernames()) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last enabled admin")


async def _bootstrap_user_knowledge_repo_if_enabled(username: str) -> None:
    normalized_username = normalize_username(username)
    user = _auth_store().get_user(normalized_username)
    if user is None or not user.enabled:
        return

    repo_registry = getattr(server, "_knowledge_repo_registry", None)
    bootstrap_user_knowledge_repo = getattr(server, "_bootstrap_user_knowledge_repo", None)
    if repo_registry is None or not callable(bootstrap_user_knowledge_repo):
        return

    await bootstrap_user_knowledge_repo(
        repo_registry,
        normalized_username,
        KnowledgeGitConfig(
            owner=normalized_username,
            remote=user.config.git.remote,
            branch=user.config.git.branch,
            author=user.config.git.author,
            token=user.config.git.token,
        ),
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: Request, response: Response, body: LoginRequest) -> LoginResponse:
    store = _auth_store()
    try:
        username = normalize_username(body.username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    user = store.verify_password(username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    auth_session = store.create_session(username=username, user_agent=request.headers.get("user-agent", ""))
    token = store.issue_session_token(auth_session)
    cookie = server._config.auth.cookie
    response.set_cookie(
        key=cookie.name,
        value=token,
        max_age=cookie.ttl_seconds,
        expires=cookie.ttl_seconds,
        httponly=True,
        secure=cookie.secure,
        samesite=cookie.same_site,
        path="/",
    )
    return LoginResponse(user=_public_identity(user.identity(username)))


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
) -> Response:
    session_cookie = request.cookies.get(server._config.auth.cookie.name)
    if session_cookie:
        _auth_store().revoke_token(session_cookie)
    cookie = server._config.auth.cookie
    response.delete_cookie(key=cookie.name, path="/")
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=PublicUserIdentity)
async def me(user: Annotated[UserIdentity, Depends(current_user)]) -> PublicUserIdentity:
    return _public_identity(user)


@router.post("/auth/ws-ticket", response_model=WebSocketTicketResponse)
async def create_websocket_ticket(
    request: Request,
    _user: Annotated[UserIdentity, Depends(current_user)],
) -> WebSocketTicketResponse:
    session_cookie = request.cookies.get(server._config.auth.cookie.name)
    if not session_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    ticket = _auth_store().issue_websocket_token(session_cookie)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return WebSocketTicketResponse(ticket=ticket)


@router.get("/admin/users", response_model=list[AdminUserResponse])
async def list_admin_users(_admin_user: Annotated[UserIdentity, Depends(verify_admin_user)]) -> list[AdminUserResponse]:
    users = _auth_store().load_users().users
    return [_user_response(username) for username in sorted(users)]


@router.post("/admin/users", response_model=AdminUserResponse, status_code=201)
async def create_admin_user(
    body: AdminUserCreateRequest,
    _admin_user: Annotated[UserIdentity, Depends(verify_admin_user)],
) -> AdminUserResponse:
    try:
        _auth_store().create_user(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            email=body.email,
            roles=body.roles,
            config=_config_with_preserved_backend_passwords(None, body.config),
        )
        await _bootstrap_user_knowledge_repo_if_enabled(body.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _user_response(body.username)


@router.patch("/admin/users/{username}", response_model=AdminUserResponse)
async def update_admin_user(
    username: str,
    body: AdminUserUpdateRequest,
    _admin_user: Annotated[UserIdentity, Depends(verify_admin_user)],
) -> AdminUserResponse:
    updates = body.model_dump(exclude_unset=True, exclude={"config", "password"})
    password = body.password if "password" in body.model_fields_set else None
    if "config" in body.model_fields_set and body.config is not None:
        updates["config"] = _config_with_preserved_backend_passwords(username, body.config)
    try:
        if updates:
            _assert_not_removing_last_admin(username, updates)
        if updates:
            _auth_store().update_user(username, updates)
        if password is not None:
            _auth_store().set_password(username, password)
        if ("enabled" in body.model_fields_set and body.enabled is True) or "config" in body.model_fields_set:
            await _bootstrap_user_knowledge_repo_if_enabled(username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _user_response(username)


@router.delete("/admin/users/{username}", status_code=204)
async def delete_admin_user(
    username: str,
    admin_user: Annotated[UserIdentity, Depends(verify_admin_user)],
) -> Response:
    try:
        normalized_username = normalize_username(username)
        _assert_user_can_be_deleted(normalized_username, admin_user)
        _auth_store().delete_user(normalized_username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    return Response(status_code=204)
