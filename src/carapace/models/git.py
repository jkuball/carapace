from __future__ import annotations

from pydantic import BaseModel


class SandboxGitStatus(BaseModel):
    """Ahead/behind of the sandbox ``/workspace`` clone vs the backend repo (B1)."""

    running: bool = True
    branch: str | None = None
    upstream: bool = False
    ahead: int | None = None
    behind: int | None = None
    fetched: bool = False


class GlobalGitStatus(BaseModel):
    """Ahead/behind of the backend per-user repo vs the external remote (B2)."""

    remote_configured: bool = False
    ahead: int = 0
    behind: int = 0
    # Short hash and subject of the local HEAD; None while the repo has no commits.
    head: str | None = None
    head_subject: str | None = None


class GitActionResult(BaseModel):
    """Result of a pull/push action."""

    ok: bool
    message: str
    denied: bool = False
