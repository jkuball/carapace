"""Auth module tests (no LLM tokens needed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from carapace.auth import (
    ADMIN_ROLE,
    ADMIN_USERNAME,
    BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH,
    BOOTSTRAP_ADMIN_PASSWORD_SUGGESTED_LENGTH,
    AuthSession,
    AuthStore,
    SessionsFile,
    hash_password,
    normalize_username,
    validate_bootstrap_admin_password,
    verify_password,
)
from carapace.models.config import AuthConfig, JwtCookieConfig
from carapace.models.user import UserConfig


def test_validate_bootstrap_admin_password_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "test-token-12345")
    assert validate_bootstrap_admin_password() == "test-token-12345"


def test_validate_bootstrap_admin_password_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "  my-token-is-long  ")
    assert validate_bootstrap_admin_password() == "my-token-is-long"


def test_validate_bootstrap_admin_password_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARAPACE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="CARAPACE_TOKEN"):
        validate_bootstrap_admin_password()


def test_validate_bootstrap_admin_password_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "")
    with pytest.raises(RuntimeError, match="CARAPACE_TOKEN"):
        validate_bootstrap_admin_password()


def test_validate_bootstrap_admin_password_raises_when_too_short_with_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "short")

    with pytest.raises(RuntimeError, match=rf"at least {BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH} characters") as exc_info:
        validate_bootstrap_admin_password()

    suggestion = str(exc_info.value).split("Suggested replacement: ", maxsplit=1)[1]
    assert len(suggestion) == BOOTSTRAP_ADMIN_PASSWORD_SUGGESTED_LENGTH
    assert suggestion.isalnum()


def test_normalize_username_accepts_canonical_usernames() -> None:
    assert normalize_username("thies") == "thies"
    assert normalize_username("ada-lovelace_01.test") == "ada-lovelace_01.test"


@pytest.mark.parametrize(
    ("username", "message"),
    [
        ("", "username must not be empty"),
        (" ", "username must not be empty"),
        (" thies", "username must not contain leading or trailing whitespace"),
        ("thies ", "username must not contain leading or trailing whitespace"),
        ("Thies", "username must be lowercase"),
        ("thies gerken", "username may only contain lowercase letters, digits, '_', '-', or '.'"),
        ("thies!", "username may only contain lowercase letters, digits, '_', '-', or '.'"),
    ],
)
def test_normalize_username_rejects_noncanonical_usernames(username: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_username(username)


def test_password_hashing_never_accepts_plaintext_hashes() -> None:
    password_hash = hash_password("correct-horse-battery")

    assert password_hash != "correct-horse-battery"
    assert verify_password("correct-horse-battery", password_hash) is True
    assert verify_password("wrong", password_hash) is False
    assert verify_password("correct-horse-battery", "") is False

    with pytest.raises(ValueError, match="password must not be empty"):
        hash_password("")


def test_create_user_persists_and_verifies_password(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
    config = UserConfig(default_models={"agent": "anthropic:test"})

    user = store.create_user(
        username="thies",
        password="secret",
        display_name=" Thies Gerken ",
        email=" thies@example.com ",
        roles=[" Admin ", ""],
        config=config,
    )

    assert user.password_hash != "secret"
    persisted = store.load_users().users
    assert list(persisted) == ["thies"]
    assert persisted["thies"].display_name == "Thies Gerken"
    assert persisted["thies"].email == "thies@example.com"
    assert persisted["thies"].roles == ["admin"]
    assert persisted["thies"].config.default_models.agent == "anthropic:test"
    assert store.verify_password("thies", "secret") is not None
    assert store.verify_password("thies", "wrong") is None


def test_verify_password_rejects_invalid_username_format(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
    store.create_user(username="thies", password="secret")

    with pytest.raises(ValueError, match="username must be lowercase"):
        store.verify_password("THIES", "secret")


def test_user_git_config_rejects_secret_source_objects() -> None:
    with pytest.raises(ValidationError):
        UserConfig.model_validate(
            {
                "git": {
                    "remote": "https://gitea.example.com/team/knowledge.git",
                    "token": {"env": "CARAPACE_GIT_TOKEN"},
                }
            }
        )


def test_create_user_rejects_invalid_and_duplicate_usernames(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)

    with pytest.raises(ValueError, match="username must not be empty"):
        store.create_user(username=" ", password="secret")

    with pytest.raises(ValueError, match="username must be lowercase"):
        store.create_user(username="Thies", password="secret")

    store.create_user(username="thies", password="secret")

    with pytest.raises(ValueError, match="already exists"):
        store.create_user(username="thies", password="secret")


def test_ensure_bootstrap_admin_creates_admin_from_env(db_factory, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "bootstrap-secret-123")
    store = AuthStore(db_factory, AuthConfig(), tmp_path)

    created = store.ensure_bootstrap_admin()
    repeated = store.ensure_bootstrap_admin()

    assert created is not None
    assert repeated is None
    assert store.verify_password(ADMIN_USERNAME, "bootstrap-secret-123") is not None
    admin = store.get_user(ADMIN_USERNAME)
    assert admin is not None
    assert admin.roles == [ADMIN_ROLE]


def test_ensure_bootstrap_admin_skips_when_another_admin_exists(
    db_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CARAPACE_TOKEN", raising=False)
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
    store.create_user(username="thies", password="secret", roles=[ADMIN_ROLE])

    created = store.ensure_bootstrap_admin()

    assert created is None
    assert store.get_user(ADMIN_USERNAME) is None


def test_ensure_bootstrap_admin_repairs_disabled_admin_placeholder(
    db_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARAPACE_TOKEN", "bootstrap-secret-123")
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
    store.create_user(username=ADMIN_USERNAME, password="temporary-secret")
    placeholder = store.update_user(ADMIN_USERNAME, {"enabled": False, "password_hash": ""})

    created = store.ensure_bootstrap_admin()

    assert created is not None
    assert created.enabled is True
    assert created.roles == [ADMIN_ROLE]
    assert created.token_version == placeholder.token_version + 1
    assert store.verify_password(ADMIN_USERNAME, "bootstrap-secret-123") is not None


def test_disabled_users_cannot_login_or_keep_existing_sessions(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
    store.create_user(username="thies", password="secret")
    auth_session = store.create_session(username="thies")
    token = store.issue_session_token(auth_session)

    assert store.validate_session_token(token) is not None

    store.update_user("thies", {"enabled": False})

    assert store.verify_password("thies", "secret") is None
    assert store.validate_session_token(token) is None


def test_session_token_roundtrip_persists_session_and_identity(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(cookie=JwtCookieConfig(ttl_seconds=3600)), tmp_path)
    store.create_user(username="thies", password="secret", display_name="Thies")

    auth_session = store.create_session(username="thies", user_agent="pytest")
    token = store.issue_session_token(auth_session)
    identity = store.validate_session_token(token)

    assert auth_session.user == "thies"
    persisted_session = store.get_session(auth_session.id)
    assert persisted_session is not None
    assert persisted_session.user_agent == "pytest"
    persisted_user = store.get_user("thies")
    assert persisted_user is not None
    assert persisted_user.last_login_at is not None
    assert identity is not None
    assert identity.username == "thies"
    assert identity.display_name == "Thies"


def test_revoke_token_invalidates_session(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
    store.create_user(username="thies", password="secret")
    auth_session = store.create_session(username="thies")
    token = store.issue_session_token(auth_session)

    assert store.revoke_token(token) is True
    assert store.validate_session_token(token) is None
    revoked_session = store.get_session(auth_session.id)
    assert revoked_session is not None
    assert revoked_session.revoked_at is not None
    assert store.revoke_token("not-a-token") is False


def test_create_session_prunes_expired_sessions_and_keeps_revoked_audit_trail(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(cookie=JwtCookieConfig(ttl_seconds=3600)), tmp_path)
    store.create_user(username="thies", password="secret")
    now = datetime.now(tz=UTC)
    expired_session = AuthSession(
        id="expired-session",
        user="thies",
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    revoked_session = AuthSession(
        id="revoked-session",
        user="thies",
        created_at=now - timedelta(minutes=30),
        expires_at=now + timedelta(minutes=30),
        revoked_at=now - timedelta(minutes=1),
    )
    store.save_sessions(
        SessionsFile(
            sessions={
                expired_session.id: expired_session,
                revoked_session.id: revoked_session,
            }
        )
    )

    fresh_session = store.create_session(username="thies")

    persisted_sessions = store.load_sessions().sessions
    assert list(persisted_sessions) == [revoked_session.id, fresh_session.id]
    assert persisted_sessions[revoked_session.id].revoked_at == revoked_session.revoked_at


def test_websocket_token_is_scoped_to_session_and_revocation(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(cookie=JwtCookieConfig(ttl_seconds=3600)), tmp_path)
    store.create_user(username="thies", password="secret")
    auth_session = store.create_session(username="thies")
    session_token = store.issue_session_token(auth_session)

    websocket_token = store.issue_websocket_token(session_token)

    assert websocket_token is not None
    identity = store.validate_websocket_token(websocket_token)
    assert identity is not None
    assert identity.username == "thies"
    assert store.validate_session_token(websocket_token) is None
    store.revoke_token(session_token)
    assert store.validate_websocket_token(websocket_token) is None


def test_password_change_increments_token_version_and_invalidates_old_tokens(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
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


def test_set_password_raises_for_missing_user(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)

    with pytest.raises(KeyError):
        store.set_password("missing", "new-secret")


def test_expired_token_is_rejected(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
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


def test_token_signed_for_different_auth_config_is_rejected(db_factory, tmp_path) -> None:
    store = AuthStore(
        db_factory,
        AuthConfig(cookie=JwtCookieConfig(issuer="carapace-a", audience="web-a")),
        tmp_path,
    )
    store.create_user(username="thies", password="secret")
    auth_session = store.create_session(username="thies")
    token = store.issue_session_token(auth_session)

    other_config_store = AuthStore(
        db_factory,
        AuthConfig(cookie=JwtCookieConfig(issuer="carapace-b", audience="web-b")),
        tmp_path,
    )

    assert other_config_store.validate_session_token(token) is None


def test_signing_secret_is_reused_across_store_instances(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
    first_secret = store.signing_secret()

    reloaded_store = AuthStore(db_factory, AuthConfig(), tmp_path)

    assert reloaded_store.signing_secret() == first_secret


def test_signing_secret_is_cached_per_store_instance(db_factory, tmp_path) -> None:
    store = AuthStore(db_factory, AuthConfig(), tmp_path)
    first_secret = store.signing_secret()
    store._secret_path.write_text("changed-on-disk", encoding="utf-8")

    assert store.signing_secret() == first_secret
    assert (tmp_path / "auth" / "session_secret").stat().st_mode & 0o777 == 0o600
