from __future__ import annotations

import os
import secrets
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

import yaml
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from pwdlib import PasswordHash
from pydantic import BaseModel, Field, model_validator

from .models.config import AuthConfig, UserConfig

_password_hash = PasswordHash.recommended()
ADMIN_ROLE = "admin"
ADMIN_USERNAME = "admin"
BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH = 16
BOOTSTRAP_ADMIN_PASSWORD_SUGGESTED_LENGTH = 24
_BOOTSTRAP_ADMIN_PASSWORD_ALPHABET = string.ascii_letters + string.digits


class UserIdentity(BaseModel):
    username: str
    display_name: str = ""
    email: str | None = None
    roles: list[str] = []
    config: UserConfig = UserConfig()


class AuthUser(BaseModel):
    password_hash: str
    enabled: bool = True
    token_version: int = 1
    display_name: str = ""
    email: str | None = None
    roles: list[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    password_changed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    last_login_at: datetime | None = None
    config: UserConfig = UserConfig()

    @model_validator(mode="after")
    def _normalize(self) -> AuthUser:
        self.display_name = self.display_name.strip()
        self.email = self.email.strip() or None if self.email is not None else None
        self.roles = normalize_roles(self.roles)
        if self.token_version < 1:
            raise ValueError("token_version must be >= 1")
        return self

    def identity(self, username: str) -> UserIdentity:
        return UserIdentity(
            username=username,
            display_name=self.display_name or username,
            email=self.email,
            roles=list(self.roles),
            config=self.config.model_copy(deep=True),
        )


class UsersFile(BaseModel):
    version: int = 1
    users: dict[str, AuthUser] = {}

    @model_validator(mode="after")
    def _normalize(self) -> UsersFile:
        normalized: dict[str, AuthUser] = {}
        for username, user in self.users.items():
            key = normalize_username(username)
            if key in normalized:
                raise ValueError(f"duplicate username after normalization: {username!r}")
            normalized[key] = user
        self.users = normalized
        return self


class AuthSession(BaseModel):
    id: str
    user: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str = ""

    @model_validator(mode="after")
    def _normalize(self) -> AuthSession:
        self.id = self.id.strip()
        if not self.id:
            raise ValueError("session id must not be empty")
        self.user = normalize_username(self.user)
        if self.expires_at <= self.created_at:
            raise ValueError("session expires_at must be after created_at")
        return self

    def is_active(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(tz=UTC)
        return self.revoked_at is None and self.expires_at > current


class SessionsFile(BaseModel):
    version: int = 1
    sessions: dict[str, AuthSession] = {}


class SessionTokenClaims(BaseModel):
    iss: str
    aud: str
    typ: str
    sub: str
    sid: str
    iat: int
    exp: int
    ver: int


class AuthStore:
    def __init__(self, data_dir: Path, config: AuthConfig):
        self._dir = data_dir / "auth"
        self._users_path = self._dir / "users.yaml"
        self._sessions_path = self._dir / "sessions.yaml"
        self._secret_path = self._dir / "session_secret"
        self._config = config
        self._lock = RLock()
        self._cached_signing_secret: str | None = None
        self._cached_signing_key: OctKey | None = None
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def users_path(self) -> Path:
        return self._users_path

    @property
    def sessions_path(self) -> Path:
        return self._sessions_path

    def load_users(self) -> UsersFile:
        with self._lock:
            if not self._users_path.exists():
                return UsersFile()
            raw = yaml.safe_load(self._users_path.read_text(encoding="utf-8")) or {}
        return UsersFile.model_validate(raw)

    def save_users(self, users_file: UsersFile) -> UsersFile:
        payload = users_file.model_dump(mode="json", exclude_none=True)
        with self._lock:
            self._write_yaml(self._users_path, payload)
        return users_file

    def get_user(self, username: str) -> AuthUser | None:
        return self.load_users().users.get(normalize_username(username))

    def ensure_bootstrap_admin(self) -> AuthUser | None:
        now = datetime.now(tz=UTC)
        with self._lock:
            users_file = self.load_users()
            if any(user.enabled and has_admin_role(user.roles) for user in users_file.users.values()):
                return None

            password = validate_bootstrap_admin_password()
            existing = users_file.users.get(ADMIN_USERNAME)
            if existing is None:
                user = AuthUser(
                    password_hash=hash_password(password),
                    display_name="Administrator",
                    roles=[ADMIN_ROLE],
                    created_at=now,
                    updated_at=now,
                    password_changed_at=now,
                )
            else:
                payload = existing.model_dump(mode="python")
                payload.update(
                    {
                        "password_hash": hash_password(password),
                        "enabled": True,
                        "display_name": existing.display_name or "Administrator",
                        "roles": normalize_roles([*existing.roles, ADMIN_ROLE]),
                        "token_version": existing.token_version + 1,
                        "updated_at": now,
                        "password_changed_at": now,
                    }
                )
                user = AuthUser.model_validate(payload)
            users_file.users[ADMIN_USERNAME] = user
            self.save_users(users_file)
            return user

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str = "",
        email: str | None = None,
        roles: list[str] | None = None,
        config: UserConfig | None = None,
    ) -> AuthUser:
        key = normalize_username(username)
        if not key:
            raise ValueError("username must not be empty")
        now = datetime.now(tz=UTC)
        with self._lock:
            users_file = self.load_users()
            if key in users_file.users:
                raise ValueError(f"User {key!r} already exists")
            user = AuthUser(
                password_hash=hash_password(password),
                display_name=display_name or key,
                email=email,
                roles=roles or [],
                created_at=now,
                updated_at=now,
                password_changed_at=now,
                config=config or UserConfig(),
            )
            users_file.users[key] = user
            self.save_users(users_file)
            return user

    def update_user(self, username: str, updates: dict[str, Any]) -> AuthUser:
        key = normalize_username(username)
        with self._lock:
            users_file = self.load_users()
            existing = users_file.users.get(key)
            if existing is None:
                raise KeyError(key)
            payload = existing.model_dump(mode="python")
            payload.update(updates)
            payload["updated_at"] = datetime.now(tz=UTC)
            updated = AuthUser.model_validate(payload)
            users_file.users[key] = updated
            self.save_users(users_file)
            return updated

    def delete_user(self, username: str) -> None:
        key = normalize_username(username)
        with self._lock:
            users_file = self.load_users()
            if key not in users_file.users:
                raise KeyError(key)
            del users_file.users[key]
            self.save_users(users_file)
            self.revoke_user_sessions(key)

    def set_password(self, username: str, password: str) -> AuthUser:
        key = normalize_username(username)
        password_hash = hash_password(password)
        with self._lock:
            users_file = self.load_users()
            existing = users_file.users.get(key)
            if existing is None:
                raise KeyError(key)
            payload = existing.model_dump(mode="python")
            payload.update(
                {
                    "password_hash": password_hash,
                    "password_changed_at": datetime.now(tz=UTC),
                    "token_version": existing.token_version + 1,
                    "updated_at": datetime.now(tz=UTC),
                }
            )
            updated = AuthUser.model_validate(payload)
            users_file.users[key] = updated
            self.save_users(users_file)
            return updated

    def verify_password(self, username: str, password: str) -> AuthUser | None:
        user = self.get_user(username)
        if user is None or not user.enabled:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def load_sessions(self) -> SessionsFile:
        with self._lock:
            if not self._sessions_path.exists():
                return SessionsFile()
            raw = yaml.safe_load(self._sessions_path.read_text(encoding="utf-8")) or {}
        return SessionsFile.model_validate(raw)

    def save_sessions(self, sessions_file: SessionsFile) -> SessionsFile:
        payload = sessions_file.model_dump(mode="json", exclude_none=True)
        with self._lock:
            self._write_yaml(self._sessions_path, payload)
        return sessions_file

    def create_session(self, *, username: str, user_agent: str = "") -> AuthSession:
        user = self.get_user(username)
        if user is None or not user.enabled:
            raise ValueError("User not found or disabled")
        now = datetime.now(tz=UTC)
        session = AuthSession(
            id=secrets.token_urlsafe(32),
            user=normalize_username(username),
            created_at=now,
            expires_at=now + timedelta(seconds=self._config.cookie.ttl_seconds),
            user_agent=user_agent,
        )
        with self._lock:
            sessions_file = self.load_sessions()
            self._prune_sessions_file(sessions_file, now=now)
            sessions_file.sessions[session.id] = session
            self.save_sessions(sessions_file)
            self.update_user(username, {"last_login_at": now})
        return session

    def get_session(self, session_id: str) -> AuthSession | None:
        return self.load_sessions().sessions.get(session_id)

    def revoke_session(self, session_id: str) -> bool:
        with self._lock:
            sessions_file = self.load_sessions()
            session = sessions_file.sessions.get(session_id)
            if session is None:
                return False
            sessions_file.sessions[session_id] = session.model_copy(update={"revoked_at": datetime.now(tz=UTC)})
            self.save_sessions(sessions_file)
            return True

    def revoke_user_sessions(self, username: str) -> int:
        key = normalize_username(username)
        now = datetime.now(tz=UTC)
        revoked = 0
        with self._lock:
            sessions_file = self.load_sessions()
            for session_id, session in sessions_file.sessions.items():
                if session.user != key or session.revoked_at is not None:
                    continue
                sessions_file.sessions[session_id] = session.model_copy(update={"revoked_at": now})
                revoked += 1
            if revoked:
                self.save_sessions(sessions_file)
        return revoked

    def prune_sessions(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(tz=UTC)
        with self._lock:
            sessions_file = self.load_sessions()
            removed = self._prune_sessions_file(sessions_file, now=current)
            if removed:
                self.save_sessions(sessions_file)
            return removed

    def signing_secret(self) -> str:
        with self._lock:
            if self._cached_signing_secret is not None:
                return self._cached_signing_secret
            if self._secret_path.exists():
                self._cached_signing_secret = self._secret_path.read_text(encoding="utf-8").strip()
                return self._cached_signing_secret
            secret = secrets.token_urlsafe(48)
            self._secret_path.write_text(secret, encoding="utf-8")
            self._secret_path.chmod(0o600)
            self._cached_signing_secret = secret
            return secret

    def issue_session_token(self, session: AuthSession) -> str:
        user = self.get_user(session.user)
        if user is None:
            raise ValueError("User not found")
        claims = {
            "iss": self._config.cookie.issuer,
            "aud": self._config.cookie.audience,
            "typ": "session",
            "sub": session.user,
            "sid": session.id,
            "iat": int(session.created_at.timestamp()),
            "exp": int(session.expires_at.timestamp()),
            "ver": user.token_version,
        }
        return jwt.encode({"alg": "HS256"}, claims, self._signing_key())

    def issue_websocket_token(self, session_token: str) -> str | None:
        session_claims = self._decode_token_claims(session_token, expected_type="session")
        if session_claims is None:
            return None
        if self._identity_from_claims(session_claims) is None:
            return None

        now = datetime.now(tz=UTC)
        user = self.get_user(session_claims.sub)
        if user is None:
            return None
        claims = {
            "iss": self._config.cookie.issuer,
            "aud": self._config.cookie.audience,
            "typ": "websocket",
            "sub": session_claims.sub,
            "sid": session_claims.sid,
            "iat": int(now.timestamp()),
            "exp": session_claims.exp,
            "ver": user.token_version,
        }
        return jwt.encode({"alg": "HS256"}, claims, self._signing_key())

    def validate_session_token(self, token: str) -> UserIdentity | None:
        claims = self._decode_token_claims(token, expected_type="session")
        if claims is None:
            return None

        return self._identity_from_claims(claims)

    def validate_websocket_token(self, token: str) -> UserIdentity | None:
        claims = self._decode_token_claims(token, expected_type="websocket")
        if claims is None:
            return None
        return self._identity_from_claims(claims)

    def _identity_from_claims(self, claims: SessionTokenClaims) -> UserIdentity | None:
        now = datetime.now(tz=UTC)
        if datetime.fromtimestamp(claims.exp, tz=UTC) <= now:
            return None

        session = self.get_session(claims.sid)
        if session is None or not session.is_active(now=now) or session.user != normalize_username(claims.sub):
            return None
        user = self.get_user(session.user)
        if user is None or not user.enabled or user.token_version != claims.ver:
            return None
        return user.identity(session.user)

    def revoke_token(self, token: str) -> bool:
        claims = self._decode_token_claims(token, expected_type="session")
        if claims is None:
            return False
        return self.revoke_session(claims.sid)

    def _decode_token_claims(self, token: str, *, expected_type: str) -> SessionTokenClaims | None:
        try:
            token_obj = jwt.decode(token, self._signing_key(), algorithms=["HS256"])
            claims = SessionTokenClaims.model_validate(token_obj.claims)
        except (JoseError, ValueError):
            return None
        if claims.iss != self._config.cookie.issuer:
            return None
        if claims.aud != self._config.cookie.audience:
            return None
        if claims.typ != expected_type:
            return None
        return claims

    def _signing_key(self) -> OctKey:
        with self._lock:
            if self._cached_signing_key is None:
                self._cached_signing_key = OctKey.import_key(self.signing_secret())
            return self._cached_signing_key

    def _prune_sessions_file(self, sessions_file: SessionsFile, *, now: datetime) -> int:
        before = len(sessions_file.sessions)
        sessions_file.sessions = {
            session_id: session for session_id, session in sessions_file.sessions.items() if session.is_active(now=now)
        }
        return before - len(sessions_file.sessions)

    def _write_yaml(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        tmp_path.replace(path)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def normalize_roles(roles: list[str]) -> list[str]:
    return [role.strip().lower() for role in roles if role.strip()]


def has_admin_role(roles: list[str]) -> bool:
    return ADMIN_ROLE in normalize_roles(roles)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    return _password_hash.verify(password, password_hash)


def suggest_bootstrap_admin_password() -> str:
    return "".join(
        secrets.choice(_BOOTSTRAP_ADMIN_PASSWORD_ALPHABET) for _ in range(BOOTSTRAP_ADMIN_PASSWORD_SUGGESTED_LENGTH)
    )


def validate_bootstrap_admin_password(password: str | None = None) -> str:
    """Return a validated bootstrap admin password or raise with a replacement suggestion."""
    if password is None:
        password = os.environ.get("CARAPACE_TOKEN", "")
    password = password.strip()
    if not password:
        raise RuntimeError("CARAPACE_TOKEN environment variable is required but not set")
    if len(password) < BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH:
        raise RuntimeError(
            "CARAPACE_TOKEN must be at least "
            f"{BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH} characters long. "
            f"Suggested replacement: {suggest_bootstrap_admin_password()}"
        )
    return password
