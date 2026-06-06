from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic_ai import ModelMessagesTypeAdapter

from ..auth import SessionsFile, UsersFile, _session_to_row, _user_to_row
from ..models.jobs import JobsFile
from ..models.session import SessionState
from ..notifications.models import NotificationSubscription
from ..sandbox.state import SessionSandboxSnapshot
from ..session.manager import SessionMeta, _parse_timestamp, _state_columns, _to_json_safe
from ..usage import LlmRequestLog, UsageTracker
from ..usernames import normalize_username
from .engine import SessionFactory
from .models import (
    AuthSessionRow,
    JobRow,
    NotificationSubscriptionRow,
    SandboxTokenRow,
    SessionAuditRow,
    SessionEventRow,
    SessionHistoryRow,
    SessionLlmRequestRow,
    SessionRow,
    SessionUsageRow,
    User,
)


@dataclass
class ImportCounts:
    users: int = 0
    auth_sessions: int = 0
    jobs: int = 0
    subscriptions: int = 0
    sessions: int = 0
    history: int = 0
    usage: int = 0
    llm_requests: int = 0
    events: int = 0
    audit: int = 0
    sandbox_tokens: int = 0
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"users={self.users} auth_sessions={self.auth_sessions} jobs={self.jobs} "
            f"subscriptions={self.subscriptions} sessions={self.sessions} history={self.history} "
            f"usage={self.usage} llm_requests={self.llm_requests} events={self.events} "
            f"audit={self.audit} sandbox_tokens={self.sandbox_tokens} skipped={len(self.skipped)}"
        )


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_multidoc(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    with open(path) as f:
        try:
            docs = list(yaml.safe_load_all(f))
        except yaml.YAMLError:
            f.seek(0)
            docs = []
            for raw in f.read().split("---\n"):
                if not raw.strip():
                    continue
                try:
                    docs.append(yaml.safe_load(raw))
                except yaml.YAMLError:
                    continue
    for doc in docs:
        if isinstance(doc, list):
            result.extend(item for item in doc if isinstance(item, dict))
        elif isinstance(doc, dict):
            result.append(doc)
    return result


_TRUNCATE_ORDER = [
    SessionAuditRow,
    SessionEventRow,
    SessionHistoryRow,
    SessionLlmRequestRow,
    SessionUsageRow,
    SandboxTokenRow,
    SessionRow,
    JobRow,
    NotificationSubscriptionRow,
]


def import_all(
    session_factory: SessionFactory,
    data_dir: Path,
    *,
    purge: bool = False,
    dry_run: bool = False,
) -> ImportCounts:
    """Read existing YAML/file storage under *data_dir* and load it into the database.

    Idempotent: rows whose primary key already exists are skipped. With ``purge=True``
    the target tables are emptied first. ``dry_run=True`` rolls back at the end.
    """
    counts = ImportCounts()

    with session_factory() as db:
        if purge and not dry_run:
            for model in _TRUNCATE_ORDER:
                db.query(model).delete()
            db.commit()

        # --- users.yaml ---
        users_raw = _load_yaml(data_dir / "auth" / "users.yaml")
        if users_raw:
            users_file = UsersFile.model_validate(users_raw)
            for username, user in users_file.users.items():
                if db.get(User, username):
                    counts.skipped.append(f"user:{username}")
                    continue
                db.add(_user_to_row(username, user))
                counts.users += 1

        # --- auth/sessions.yaml ---
        sessions_raw = _load_yaml(data_dir / "auth" / "sessions.yaml")
        if sessions_raw:
            auth_file = SessionsFile.model_validate(sessions_raw)
            for sid, session in auth_file.sessions.items():
                if db.get(AuthSessionRow, sid):
                    counts.skipped.append(f"auth_session:{sid}")
                    continue
                db.add(_session_to_row(session))
                counts.auth_sessions += 1

        # --- jobs.yaml ---
        jobs_raw = _load_yaml(data_dir / "jobs.yaml")
        if jobs_raw:
            jobs_file = JobsFile.model_validate(jobs_raw)
            for job in jobs_file.jobs:
                if db.get(JobRow, job.id):
                    counts.skipped.append(f"job:{job.id}")
                    continue
                db.add(
                    JobRow(
                        id=job.id,
                        user=job.user,
                        enabled=job.enabled,
                        name=job.name,
                        prompt=job.prompt,
                        data=job.model_dump(mode="json"),
                    )
                )
                counts.jobs += 1

        # --- notifications/subscriptions/*.yaml ---
        sub_dir = data_dir / "notifications" / "subscriptions"
        if sub_dir.exists():
            for path in sorted(sub_dir.glob("*.yaml")):
                raw = _load_yaml(path)
                if not raw:
                    continue
                sub = NotificationSubscription.model_validate(raw)
                if db.get(NotificationSubscriptionRow, sub.id):
                    counts.skipped.append(f"subscription:{sub.id}")
                    continue
                db.add(
                    NotificationSubscriptionRow(
                        id=sub.id,
                        user=sub.user,
                        endpoint=sub.endpoint,
                        expires_at=sub.expires_at,
                        data=sub.model_dump(mode="json"),
                    )
                )
                counts.subscriptions += 1

        # --- per-session directories ---
        sessions_dir = data_dir / "sessions"
        if sessions_dir.exists():
            for session_dir in sorted(p for p in sessions_dir.iterdir() if p.is_dir()):
                _import_session(db, session_dir, counts)

        if dry_run:
            db.rollback()
        else:
            db.commit()

    logger.info(f"YAML import complete: {counts.summary()}")
    return counts


def _import_session(db: Any, session_dir: Path, counts: ImportCounts) -> None:
    session_id = session_dir.name
    if db.get(SessionRow, session_id) is not None:
        counts.skipped.append(f"session:{session_id}")
        return

    state_raw = _load_yaml(session_dir / "state.yaml")
    meta_raw = _load_yaml(session_dir / "meta.yaml")
    user = ""
    if meta_raw:
        user = SessionMeta.model_validate(meta_raw).user

    if not state_raw:
        # Session directory without state — nothing meaningful to migrate.
        counts.skipped.append(f"session-no-state:{session_id}")
        return

    state = SessionState.model_validate(state_raw)
    snapshot_raw = _load_yaml(session_dir / "sandbox.yaml")
    sandbox_snapshot = (
        SessionSandboxSnapshot.model_validate(snapshot_raw).model_dump(mode="json") if snapshot_raw else None
    )
    db.add(
        SessionRow(
            session_id=session_id,
            user=normalize_username(user) if user else "",
            sandbox_snapshot=sandbox_snapshot,
            **_state_columns(state),
        )
    )
    db.flush()  # persist the parent row before its FK-dependent children
    counts.sessions += 1

    # history
    history_raw = _load_yaml(session_dir / "history.yaml")
    if history_raw:
        messages = ModelMessagesTypeAdapter.validate_python(history_raw)
        db.add(
            SessionHistoryRow(
                session_id=session_id,
                messages=ModelMessagesTypeAdapter.dump_python(messages, mode="json"),
            )
        )
        counts.history += 1

    # usage
    usage_raw = _load_yaml(session_dir / "usage.yaml")
    if usage_raw:
        db.add(
            SessionUsageRow(
                session_id=session_id,
                tracker=UsageTracker.model_validate(usage_raw).model_dump(mode="json"),
            )
        )
        counts.usage += 1

    # llm request log
    llm_raw = _load_yaml(session_dir / "llm_requests.yaml")
    if llm_raw:
        db.add(
            SessionLlmRequestRow(
                session_id=session_id,
                log=LlmRequestLog.model_validate(llm_raw).model_dump(mode="json"),
            )
        )
        counts.llm_requests += 1

    # events (append-only multi-doc)
    for seq, event in enumerate(_load_multidoc(session_dir / "events.yaml")):
        data = _to_json_safe(event)
        db.add(
            SessionEventRow(
                session_id=session_id,
                seq=seq,
                timestamp=_parse_timestamp(data.get("timestamp")),
                data=data,
            )
        )
        counts.events += 1

    # audit (append-only multi-doc)
    for entry in _load_multidoc(session_dir / "audit.yaml"):
        data = _to_json_safe(entry)
        db.add(
            SessionAuditRow(
                session_id=session_id,
                timestamp=_parse_timestamp(data.get("timestamp")),
                data=data,
            )
        )
        counts.audit += 1

    # sandbox token
    token_path = session_dir / "token"
    if token_path.exists():
        token = token_path.read_text().strip()
        if token:
            db.add(SandboxTokenRow(session_id=session_id, token=token))
            counts.sandbox_tokens += 1
