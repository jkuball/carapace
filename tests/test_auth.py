"""Auth module tests (no LLM tokens needed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from carapace.auth import (
    AuthSession,
    AuthStore,
    SessionsFile,
    get_token,
    hash_password,
    normalize_username,
    verify_password,
)
from carapace.models.config import AuthConfig, JwtCookieConfig, UserConfig


def test_get_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "test-token-123")
    assert get_token() == "test-token-123"


def test_get_token_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "  my-token  ")
    assert get_token() == "my-token"


def test_get_token_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARAPACE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="CARAPACE_TOKEN"):
        get_token()


def test_get_token_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "")
    with pytest.raises(RuntimeError, match="CARAPACE_TOKEN"):
        get_token()


def test_normalize_username_strips_and_lowercases() -> None:
    assert normalize_username(" Thies ") == "thies"


def test_password_hashing_never_accepts_plaintext_hashes() -> None:
    password_hash = hash_password("correct-horse-battery")

    assert password_hash != "correct-horse-battery"
    assert verify_password("correct-horse-battery", password_hash) is True
    assert verify_password("wrong", password_hash) is False
    assert verify_password("correct-horse-battery", "") is False

    with pytest.raises(ValueError, match="password must not be empty"):
        hash_password("")


def test_create_user_normalizes_persists_and_verifies_password(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig())
    config = UserConfig(default_models={"agent": "anthropic:test"})

    user = store.create_user(
        username=" Thies ",
        password="secret",
        display_name=" Thies Gerken ",
        email=" thies@example.com ",
        roles=[" admin ", ""],
        config=config,
    )

    assert user.password_hash != "secret"
    assert store.users_path.exists()
    persisted = store.load_users().users
    assert list(persisted) == ["thies"]
    assert persisted["thies"].display_name == "Thies Gerken"
    assert persisted["thies"].email == "thies@example.com"
    assert persisted["thies"].roles == ["admin"]
    assert persisted["thies"].config.default_models == {"agent": "anthropic:test"}
    assert store.verify_password("THIES", "secret") is not None
    assert store.verify_password("thies", "wrong") is None


def test_create_user_rejects_empty_and_duplicate_normalized_usernames(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig())

    with pytest.raises(ValueError, match="username must not be empty"):
        store.create_user(username=" ", password="secret")

    store.create_user(username="Thies", password="secret")

    with pytest.raises(ValueError, match="already exists"):
        store.create_user(username=" thies ", password="secret")


def test_disabled_users_cannot_login_or_keep_existing_sessions(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig())
    store.create_user(username="thies", password="secret")
    auth_session = store.create_session(username="thies")
    token = store.issue_session_token(auth_session)

    assert store.validate_session_token(token) is not None

    store.update_user("thies", {"enabled": False})

    assert store.verify_password("thies", "secret") is None
    assert store.validate_session_token(token) is None


def test_session_token_roundtrip_persists_session_and_identity(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig(cookie=JwtCookieConfig(ttl_seconds=3600)))
    store.create_user(username="thies", password="secret", display_name="Thies")

    auth_session = store.create_session(username="THIES", user_agent="pytest")
    token = store.issue_session_token(auth_session)
    identity = store.validate_session_token(token)

    assert auth_session.user == "thies"
    assert store.sessions_path.exists()
    persisted_session = store.get_session(auth_session.id)
    assert persisted_session is not None
    assert persisted_session.user_agent == "pytest"
    persisted_user = store.get_user("thies")
    assert persisted_user is not None
    assert persisted_user.last_login_at is not None
    assert identity is not None
    assert identity.username == "thies"
    assert identity.display_name == "Thies"


def test_revoke_token_invalidates_session(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig())
    store.create_user(username="thies", password="secret")
    auth_session = store.create_session(username="thies")
    token = store.issue_session_token(auth_session)

    assert store.revoke_token(token) is True
    assert store.validate_session_token(token) is None
    revoked_session = store.get_session(auth_session.id)
    assert revoked_session is not None
    assert revoked_session.revoked_at is not None
    assert store.revoke_token("not-a-token") is False


def test_password_change_increments_token_version_and_invalidates_old_tokens(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig())
    store.create_user(username="thies", password="old-secret")
    old_session = store.create_session(username="thies")
    old_token = store.issue_session_token(old_session)

    updated = store.set_password("thies", "new-secret")
    new_session = store.create_session(username="thies")
    new_token = store.issue_session_token(new_session)

    assert updated.token_version == 2
    assert store.verify_password("thies", "old-secret") is None
    assert store.verify_password("thies", "new-secret") is not None
    assert store.validate_session_token(old_token) is None
    assert store.validate_session_token(new_token) is not None


def test_set_password_raises_for_missing_user(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig())

    with pytest.raises(KeyError):
        store.set_password("missing", "new-secret")


def test_expired_token_is_rejected(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig())
    store.create_user(username="thies", password="secret")
    now = datetime.now(tz=UTC)
    expired_session = AuthSession(
        id="expired-session",
        user="thies",
        created_at=now - timedelta(minutes=2),
        expires_at=now - timedelta(minutes=1),
    )
    store.save_sessions(SessionsFile(sessions={expired_session.id: expired_session}))
    token = store.issue_session_token(expired_session)

    assert store.validate_session_token(token) is None


def test_token_signed_for_different_auth_config_is_rejected(tmp_path) -> None:
    store = AuthStore(
        tmp_path,
        AuthConfig(cookie=JwtCookieConfig(issuer="carapace-a", audience="web-a")),
    )
    store.create_user(username="thies", password="secret")
    auth_session = store.create_session(username="thies")
    token = store.issue_session_token(auth_session)

    other_config_store = AuthStore(
        tmp_path,
        AuthConfig(cookie=JwtCookieConfig(issuer="carapace-b", audience="web-b")),
    )

    assert other_config_store.validate_session_token(token) is None


def test_signing_secret_is_reused_across_store_instances(tmp_path) -> None:
    store = AuthStore(tmp_path, AuthConfig())
    first_secret = store.signing_secret()

    reloaded_store = AuthStore(tmp_path, AuthConfig())

    assert reloaded_store.signing_secret() == first_secret
    assert (tmp_path / "auth" / "session_secret").stat().st_mode & 0o777 == 0o600
