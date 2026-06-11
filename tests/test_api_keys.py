"""API key store + grant tests (no LLM tokens needed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from carapace.api_keys import Access, ApiKeyGrant, ApiKeyStore, Scope
from carapace.auth import AuthStore
from carapace.database.models import ApiKeyRow
from carapace.models.config import AuthConfig


@pytest.fixture
def stores(db_factory, tmp_path):
    auth = AuthStore(db_factory, AuthConfig(), tmp_path)
    auth.create_user(username="thies", password="secret-password", display_name="Thies")
    auth.create_user(username="admin", password="admin-password", roles=["admin"])
    return auth, ApiKeyStore(db_factory, auth)


def _read_grant(scope: Scope, access: Access) -> ApiKeyGrant:
    return ApiKeyGrant(scope=scope, access=access)


def test_create_and_validate_round_trip(stores):
    _auth, keys = stores
    info, secret = keys.create_key(user="thies", name="ci", grants=[_read_grant(Scope.sessions, Access.write)])
    assert secret.startswith("ck_")
    result = keys.validate_key(secret)
    assert result is not None
    identity, grants = result
    assert identity.username == "thies"
    assert grants == {_read_grant(Scope.sessions, Access.write)}
    assert info.scopes == ["sessions:write"]


def test_secret_is_hashed_at_rest(stores, db_factory):
    _auth, keys = stores
    _info, secret = keys.create_key(user="thies", name="ci", grants=[_read_grant(Scope.jobs, Access.read)])
    with db_factory() as db:
        rows = db.query(ApiKeyRow).all()
        assert len(rows) == 1
        assert secret not in rows[0].secret_hash
        assert rows[0].secret_hash != secret
        assert len(rows[0].secret_hash) == 64  # sha256 hex


def test_validate_rejects_unknown_and_wrong_secret(stores):
    _auth, keys = stores
    _info, secret = keys.create_key(user="thies", name="ci", grants=[_read_grant(Scope.jobs, Access.read)])
    assert keys.validate_key("ck_deadbeef.nope") is None
    assert keys.validate_key("garbage-without-dot") is None
    prefix = secret.split(".", 1)[0]
    assert keys.validate_key(f"{prefix}.wrongbody") is None


def test_validate_rejects_revoked(stores):
    _auth, keys = stores
    info, secret = keys.create_key(user="thies", name="ci", grants=[_read_grant(Scope.jobs, Access.read)])
    assert keys.revoke_key(user="thies", key_id=info.id) is True
    assert keys.validate_key(secret) is None


def test_validate_rejects_expired(stores):
    _auth, keys = stores
    past = datetime.now(tz=UTC) - timedelta(seconds=1)
    _info, secret = keys.create_key(
        user="thies", name="ci", grants=[_read_grant(Scope.jobs, Access.read)], expires_at=past
    )
    assert keys.validate_key(secret) is None


def test_key_dies_when_user_disabled_or_deleted(stores):
    auth, keys = stores
    _info, secret = keys.create_key(user="thies", name="ci", grants=[_read_grant(Scope.jobs, Access.read)])
    auth.update_user("thies", {"enabled": False})
    assert keys.validate_key(secret) is None
    auth.update_user("thies", {"enabled": True})
    assert keys.validate_key(secret) is not None
    auth.delete_user("thies")
    assert keys.validate_key(secret) is None


def test_recreated_user_does_not_inherit_old_keys(stores):
    auth, keys = stores
    _info, secret = keys.create_key(user="thies", name="ci", grants=[_read_grant(Scope.jobs, Access.read)])
    auth.delete_user("thies")
    auth.create_user(username="thies", password="a-fresh-password", display_name="Thies")
    assert keys.validate_key(secret) is None
    assert keys.list_keys("thies") == []


def test_key_survives_password_change(stores):
    auth, keys = stores
    _info, secret = keys.create_key(user="thies", name="ci", grants=[_read_grant(Scope.jobs, Access.read)])
    auth.set_password("thies", "a-brand-new-password")
    assert keys.validate_key(secret) is not None


def test_admin_grant_requires_admin_role(stores):
    _auth, keys = stores
    with pytest.raises(ValueError, match="admin"):
        keys.create_key(user="thies", name="x", grants=[_read_grant(Scope.admin, Access.write)])
    info, _secret = keys.create_key(user="admin", name="x", grants=[_read_grant(Scope.admin, Access.write)])
    assert info.scopes == ["admin:write"]


def test_admin_grant_stripped_after_demotion(stores):
    auth, keys = stores
    _info, secret = keys.create_key(user="admin", name="x", grants=[_read_grant(Scope.admin, Access.write)])
    result = keys.validate_key(secret)
    assert result is not None and result[1] == {_read_grant(Scope.admin, Access.write)}
    auth.update_user("admin", {"roles": []})
    result = keys.validate_key(secret)
    assert result is not None and result[1] == set()


def test_create_requires_at_least_one_scope(stores):
    _auth, keys = stores
    with pytest.raises(ValueError, match="scope"):
        keys.create_key(user="thies", name="x", grants=[])


def test_revoke_is_owner_scoped(stores):
    _auth, keys = stores
    info, _secret = keys.create_key(user="admin", name="x", grants=[_read_grant(Scope.jobs, Access.read)])
    assert keys.revoke_key(user="thies", key_id=info.id) is False
    assert keys.revoke_key(user="admin", key_id=info.id) is True


def test_list_keys_excludes_revoked(stores):
    _auth, keys = stores
    info, _secret = keys.create_key(user="thies", name="a", grants=[_read_grant(Scope.jobs, Access.read)])
    keys.create_key(user="thies", name="b", grants=[_read_grant(Scope.sessions, Access.read)])
    keys.revoke_key(user="thies", key_id=info.id)
    listed = keys.list_keys("thies")
    assert [k.name for k in listed] == ["b"]


def test_last_used_touched_and_coalesced(stores, db_factory):
    _auth, keys = stores
    _info, secret = keys.create_key(user="thies", name="ci", grants=[_read_grant(Scope.jobs, Access.read)])
    keys.validate_key(secret)
    with db_factory() as db:
        first = db.query(ApiKeyRow).one().last_used_at
    assert first is not None
    keys.validate_key(secret)  # within coalesce window -> no rewrite
    with db_factory() as db:
        second = db.query(ApiKeyRow).one().last_used_at
    assert second == first


def test_write_grant_implies_read_but_not_vice_versa():
    write = _read_grant(Scope.sessions, Access.write)
    read = _read_grant(Scope.sessions, Access.read)
    assert write.satisfies(Scope.sessions, Access.read)
    assert write.satisfies(Scope.sessions, Access.write)
    assert read.satisfies(Scope.sessions, Access.read)
    assert not read.satisfies(Scope.sessions, Access.write)
    assert not write.satisfies(Scope.jobs, Access.read)


def test_write_grant_collapses_redundant_read(stores):
    _auth, keys = stores
    info, _secret = keys.create_key(
        user="thies",
        name="ci",
        grants=[_read_grant(Scope.sessions, Access.read), _read_grant(Scope.sessions, Access.write)],
    )
    assert info.scopes == ["sessions:write"]


def test_grant_parse_round_trip():
    grant = ApiKeyGrant.parse("jobs:write")
    assert grant == _read_grant(Scope.jobs, Access.write)
    assert grant.to_str() == "jobs:write"
    with pytest.raises(ValueError):
        ApiKeyGrant.parse("bogus:write")
