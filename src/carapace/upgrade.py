from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .auth import AuthStore, AuthUser, normalize_username
from .config import load_config
from .models.config import UserConfig
from .session.manager import SessionMeta


class UpgradeSummary(dict[str, list[str]]):
    def add(self, key: str, value: str) -> None:
        self.setdefault(key, []).append(value)


def upgrade_data_dir(data_dir: Path, username: str) -> UpgradeSummary:
    user = normalize_username(username)
    if not user:
        raise ValueError("username must not be empty")
    data_dir = data_dir.resolve()
    summary = UpgradeSummary()

    config = load_config(data_dir)
    _upsert_user_config(data_dir, user, _user_config_from_global_config(config), summary)
    _upgrade_sessions(data_dir, user, summary)
    _upgrade_knowledge(data_dir, user, summary)
    _upgrade_jobs(data_dir, user, summary)
    _upgrade_notifications(data_dir, user, summary)
    _upgrade_matrix_token(data_dir, user, summary)
    _upgrade_sandbox_tokens(data_dir, user, summary)
    return summary


def _user_config_from_global_config(config: Any) -> UserConfig:
    return UserConfig(
        credentials=config.credentials.model_dump(mode="json", exclude_none=True),
        channels=config.channels.model_copy(deep=True),
        git=config.git.model_dump(mode="json", exclude_none=True),
        default_models={
            "agent": config.agent.model,
            "sentinel": config.agent.sentinel_model,
            "title": config.agent.title_model,
        },
        budgets=config.agent.default_session_budget.model_dump(mode="json", exclude_none=True),
    )


def _upsert_user_config(data_dir: Path, user: str, user_config: UserConfig, summary: UpgradeSummary) -> None:
    store = AuthStore(data_dir, load_config(data_dir).auth)
    users_file = store.load_users()
    now = datetime.now(tz=UTC)
    existing = users_file.users.get(user)
    if existing is None:
        users_file.users[user] = AuthUser(
            password_hash="",
            enabled=False,
            display_name=user,
            created_at=now,
            updated_at=now,
            password_changed_at=now,
            config=user_config,
        )
        summary.add("users", f"created disabled placeholder user {user!r}")
    else:
        users_file.users[user] = existing.model_copy(update={"config": user_config, "updated_at": now})
        summary.add("users", f"updated config for user {user!r}")
    store.save_users(users_file)


def _upgrade_sessions(data_dir: Path, user: str, summary: UpgradeSummary) -> None:
    sessions_dir = data_dir / "sessions"
    if not sessions_dir.exists():
        return
    for session_dir in sorted(path for path in sessions_dir.iterdir() if path.is_dir()):
        meta_path = session_dir / "meta.yaml"
        if meta_path.exists():
            raw = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            meta = SessionMeta.model_validate(raw)
            if meta.user is not None:
                continue
        _write_yaml(meta_path, SessionMeta(user=user).model_dump(mode="json", exclude_none=True))
        summary.add("sessions", f"set owner for {session_dir.name}")


def _upgrade_knowledge(data_dir: Path, user: str, summary: UpgradeSummary) -> None:
    source = data_dir / "knowledge"
    target = data_dir / "knowledges" / user
    if not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    if target.exists():
        summary.add("knowledge", f"left existing {source} in place because {target} already exists")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    summary.add("knowledge", f"moved knowledge to {target}")


def _upgrade_jobs(data_dir: Path, user: str, summary: UpgradeSummary) -> None:
    path = data_dir / "jobs.yaml"
    if not path.exists():
        return
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    jobs = raw.get("jobs")
    if not isinstance(jobs, list):
        return
    changed = False
    for job in jobs:
        if isinstance(job, dict) and not job.get("user"):
            job["user"] = user
            changed = True
    if changed:
        _write_yaml(path, raw)
        summary.add("jobs", "added user to unowned jobs")


def _upgrade_notifications(data_dir: Path, user: str, summary: UpgradeSummary) -> None:
    subscriptions_dir = data_dir / "notifications" / "subscriptions"
    if not subscriptions_dir.exists():
        return
    for path in sorted(subscriptions_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict) or raw.get("user"):
            continue
        raw["user"] = user
        _write_yaml(path, raw)
        summary.add("notifications", f"added user to {path.name}")


def _upgrade_matrix_token(data_dir: Path, user: str, summary: UpgradeSummary) -> None:
    json_path = data_dir / "matrix_token.json"
    yaml_path = data_dir / "matrix_token.yaml"
    if not json_path.exists() and yaml_path.exists():
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        tokens = raw.get("tokens") if isinstance(raw, dict) else None
        if isinstance(tokens, list):
            changed = False
            for token in tokens:
                if isinstance(token, dict) and not token.get("user"):
                    token["user"] = user
                    changed = True
            if changed:
                _write_yaml(yaml_path, raw)
                summary.add("matrix", "added user to existing matrix_token.yaml")
        return
    if not json_path.exists():
        return
    raw_json = json.loads(json_path.read_text(encoding="utf-8"))
    token_record = dict(raw_json) if isinstance(raw_json, dict) else {}
    token_record["user"] = user
    payload = {"version": 1, "tokens": [token_record]}
    _write_yaml(yaml_path, payload)
    _backup_or_remove(json_path)
    summary.add("matrix", "converted matrix_token.json to matrix_token.yaml")


def _upgrade_sandbox_tokens(data_dir: Path, user: str, summary: UpgradeSummary) -> None:
    json_path = data_dir / "sandbox_tokens.json"
    yaml_path = data_dir / "sandbox_tokens.yaml"
    if not json_path.exists() and yaml_path.exists():
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        _add_user_to_token_mapping(raw, user)
        _write_yaml(yaml_path, raw)
        summary.add("sandbox", "ensured user in existing sandbox_tokens.yaml")
        return
    if not json_path.exists():
        return
    raw_json = json.loads(json_path.read_text(encoding="utf-8"))
    payload: dict[str, Any] = (
        {"version": 1, "tokens": raw_json} if isinstance(raw_json, dict) else {"version": 1, "tokens": []}
    )
    _add_user_to_token_mapping(payload, user)
    _write_yaml(yaml_path, payload)
    _backup_or_remove(json_path)
    summary.add("sandbox", "converted sandbox_tokens.json to sandbox_tokens.yaml")


def _add_user_to_token_mapping(raw: Any, user: str) -> None:
    if not isinstance(raw, dict):
        return
    tokens = raw.get("tokens")
    if isinstance(tokens, dict):
        for session_id, token_value in list(tokens.items()):
            if isinstance(token_value, dict):
                token_value.setdefault("user", user)
                continue
            tokens[session_id] = {"token": token_value, "user": user}
    elif isinstance(tokens, list):
        for token_record in tokens:
            if isinstance(token_record, dict):
                token_record.setdefault("user", user)


def _write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    tmp_path.replace(path)


def _backup_or_remove(path: Path) -> None:
    backup = path.with_suffix(f"{path.suffix}.bak")
    if backup.exists():
        path.unlink()
    else:
        path.replace(backup)
