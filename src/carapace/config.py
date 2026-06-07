from __future__ import annotations

import os
from pathlib import Path

from .models.config import Config
from .usernames import normalize_username


def build_config(data_dir: Path | None = None) -> Config:
    """Build the in-memory ``Config`` from env vars (no config file).

    ``data_dir`` is the absolute data root; when not given it comes from
    ``CARAPACE_DATA_DIR`` (default ``./data``). Knowledge repos always live at
    ``<data_dir>/knowledges``. The env-backed subsections (database, server, …) read
    their own ``CARAPACE_*`` prefixes during validation.
    """
    if data_dir is None:
        data_dir = Path(os.environ.get("CARAPACE_DATA_DIR", "./data")).resolve()
    return Config.model_validate({"data_dir": str(data_dir)})


def resolve_knowledge_repos_dir(data_dir: Path, knowledge_repos_dir: Path | None = None) -> Path:
    """Return the parent directory containing all per-user knowledge repos."""
    if knowledge_repos_dir is not None:
        return knowledge_repos_dir.resolve()
    return (data_dir / "knowledges").resolve()


def resolve_user_knowledge_dir(
    data_dir: Path,
    username: str,
    *,
    knowledge_repos_dir: Path | None = None,
) -> Path:
    """Return the canonical knowledge repo path for a specific user."""
    return (resolve_knowledge_repos_dir(data_dir, knowledge_repos_dir) / normalize_username(username)).resolve()


def load_workspace_file(base_dir: Path, name: str) -> str:
    path = base_dir / name
    if path.exists():
        return path.read_text()
    return ""
