from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ..auth import AuthStore, UserIdentity, get_token, normalize_username
from ..models.config import UserConfig
from .state import server_module

server = server_module()

router = APIRouter()
_bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user: UserIdentity


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
    config: UserConfig


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
    user = _auth_store().get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return AdminUserResponse(
        username=normalize_username(username),
        enabled=user.enabled,
        token_version=user.token_version,
        display_name=user.display_name,
        email=user.email,
        roles=user.roles,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
        password_changed_at=user.password_changed_at.isoformat(),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at is not None else None,
        config=user.config,
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
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    identity = _auth_store().validate_session_token(token)
    if identity is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    return identity


async def verify_token(user: Annotated[UserIdentity, Depends(current_user)]) -> UserIdentity:
    return user


async def verify_ws_token(websocket: WebSocket) -> UserIdentity:
    return await current_ws_user(websocket)


async def verify_admin_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin token required")
    expected = get_token()
    if credentials.credentials != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    return credentials.credentials


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: Request, response: Response, body: LoginRequest) -> LoginResponse:
    store = _auth_store()
    username = normalize_username(body.username)
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
    return LoginResponse(user=user.identity(username))


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


@router.get("/auth/me", response_model=UserIdentity)
async def me(user: Annotated[UserIdentity, Depends(current_user)]) -> UserIdentity:
    return user


@router.get("/admin/users", response_model=list[AdminUserResponse])
async def list_admin_users(_admin_token: Annotated[str, Depends(verify_admin_token)]) -> list[AdminUserResponse]:
    users = _auth_store().load_users().users
    return [_user_response(username) for username in sorted(users)]


@router.post("/admin/users", response_model=AdminUserResponse, status_code=201)
async def create_admin_user(
    body: AdminUserCreateRequest,
    _admin_token: Annotated[str, Depends(verify_admin_token)],
) -> AdminUserResponse:
    try:
        _auth_store().create_user(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            email=body.email,
            roles=body.roles,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _user_response(body.username)


@router.patch("/admin/users/{username}", response_model=AdminUserResponse)
async def update_admin_user(
    username: str,
    body: AdminUserUpdateRequest,
    _admin_token: Annotated[str, Depends(verify_admin_token)],
) -> AdminUserResponse:
    updates = body.model_dump(exclude_none=True)
    password = updates.pop("password", None)
    try:
        if updates:
            _auth_store().update_user(username, updates)
        if password is not None:
            _auth_store().set_password(username, password)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _user_response(username)
