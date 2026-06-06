from __future__ import annotations

from datetime import UTC, datetime, timedelta

import yaml

from carapace.auth import AuthSession, AuthStore, AuthUser, SessionsFile, UsersFile
from carapace.database.importer import import_all
from carapace.jobs import JobsStore
from carapace.models.config import AuthConfig
from carapace.models.jobs import JobDefinition, JobsFile
from carapace.models.session import SessionState
from carapace.notifications.models import NotificationSubscription
from carapace.notifications.store import NotificationStore
from carapace.session.manager import SessionManager, SessionMeta


def _write(path, model):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False), encoding="utf-8")


def _build_yaml_tree(data_dir):
    now = datetime(2026, 5, 1, tzinfo=UTC)

    _write(
        data_dir / "auth" / "users.yaml",
        UsersFile(users={"thies": AuthUser(password_hash="x", display_name="Thies", roles=["admin"])}),
    )
    _write(
        data_dir / "auth" / "sessions.yaml",
        SessionsFile(
            sessions={"sid1": AuthSession(id="sid1", user="thies", created_at=now, expires_at=now + timedelta(days=1))}
        ),
    )
    _write(
        data_dir / "jobs.yaml",
        JobsFile(jobs=[JobDefinition(id="daily", name="Daily", prompt="go", user="thies")]),
    )
    sub = NotificationSubscription(
        id="sub1",
        user="thies",
        endpoint="https://push.example/abc",
        p256dh="key",
        auth="secret",
        subscribed_at=now,
        expires_at=now + timedelta(days=30),
    )
    _write(data_dir / "notifications" / "subscriptions" / "sub1.yaml", sub)

    # One session directory with the full set of files.
    session_id = "2026-05-01-09-00-deadbeef"
    sdir = data_dir / "sessions" / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    state = SessionState(
        session_id=session_id,
        channel_type="web",
        channel_ref="room-1",
        created_at=now,
        last_active=now,
    )
    _write(sdir / "meta.yaml", SessionMeta(user="thies"))
    _write(sdir / "state.yaml", state)
    (sdir / "history.yaml").write_text(yaml.safe_dump([]), encoding="utf-8")
    # events: append-only multi-doc
    with open(sdir / "events.yaml", "w") as f:
        for ev in ({"type": "a", "timestamp": now.isoformat()}, {"type": "b"}):
            f.write("---\n")
            yaml.safe_dump(ev, f, sort_keys=False)
    # audit: append-only multi-doc
    with open(sdir / "audit.yaml", "w") as f:
        f.write("---\n")
        yaml.safe_dump({"kind": "tool_call", "final_decision": "allowed", "timestamp": now.isoformat()}, f)
    (sdir / "token").write_text("abc123", encoding="utf-8")
    return session_id


def test_importer_roundtrip(tmp_path, db_factory):
    session_id = _build_yaml_tree(tmp_path)

    counts = import_all(db_factory, tmp_path)

    assert counts.users == 1
    assert counts.auth_sessions == 1
    assert counts.jobs == 1
    assert counts.subscriptions == 1
    assert counts.sessions == 1
    assert counts.events == 2
    assert counts.audit == 1
    assert counts.sandbox_tokens == 1

    auth = AuthStore(db_factory, AuthConfig(), tmp_path)
    assert auth.get_user("thies").display_name == "Thies"
    assert auth.get_session("sid1").user == "thies"

    jobs = JobsStore(db_factory)
    assert [j.id for j in jobs.list_jobs()] == ["daily"]

    notifications = NotificationStore(db_factory)
    assert notifications.get_subscription("sub1").endpoint == "https://push.example/abc"

    mgr = SessionManager(db_factory, tmp_path)
    assert mgr.list_sessions() == [session_id]
    assert mgr.load_meta(session_id).user == "thies"
    loaded = mgr.load_state(session_id)
    assert loaded.channel_type == "web" and loaded.channel_ref == "room-1"
    assert [e["type"] for e in mgr.load_events(session_id)] == ["a", "b"]
    assert mgr.get_sandbox_token(session_id) == "abc123"


def test_importer_idempotent(tmp_path, db_factory):
    _build_yaml_tree(tmp_path)
    first = import_all(db_factory, tmp_path)
    assert first.users == 1
    second = import_all(db_factory, tmp_path)
    # Second run inserts nothing new; everything is skipped.
    assert second.users == 0
    assert second.sessions == 0
    assert second.jobs == 0
    assert second.skipped


def test_importer_dry_run_writes_nothing(tmp_path, db_factory):
    _build_yaml_tree(tmp_path)
    counts = import_all(db_factory, tmp_path, dry_run=True)
    assert counts.users == 1  # counted
    # But nothing persisted.
    assert JobsStore(db_factory).list_jobs() == []
    assert SessionManager(db_factory, tmp_path).list_sessions() == []
