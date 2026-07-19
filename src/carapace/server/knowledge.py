"""Read-only browsing of the per-user knowledge repo working tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, ValidationError

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..models.skills import SkillCarapaceConfig
from ..session.sent_files import guess_mime
from ..skills import SkillDocument, parse_skill_document
from .auth import require
from .state import server_module

server = server_module()

router = APIRouter()

# Files above this size are download-only: the browser inlines contents into the
# listing response, and huge blobs would bloat it for no benefit.
MAX_INLINE_TEXT_BYTES = 1024 * 1024


def read_text_content(target: Path, size: int) -> str | None:
    """Decode *target* as UTF-8 text, or return ``None`` if binary or too large.

    Same heuristic git uses: a NUL byte means binary. UTF-8 decoding catches the
    rest, so extensionless files (``.gitignore``, ``Dockerfile``) read as text.
    """
    if size > MAX_INLINE_TEXT_BYTES:
        return None
    data = target.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class KnowledgeEntry(BaseModel):
    name: str
    type: Literal["file", "dir"]
    size: int | None = None
    # Recognized directory conventions get a `kind` plus a human label the client
    # renders where a file would show its size. Extension point for skill dirs.
    kind: Literal["session"] | None = None
    label: str | None = None
    session_id: str | None = None


def session_archive_entry(directory: Path) -> tuple[str | None, str] | None:
    """Return ``(title, session_id)`` if *directory* is a session archive, else ``None``.

    Detection is by the ``conversation.json`` marker rather than the path layout,
    so it survives a reconfigured ``path_prefix``. Title may be None for untitled
    (or private, never-titled) sessions; the session id is always the dir name.
    """
    archive = directory / "conversation.json"
    if not archive.is_file():
        return None
    # ponytail: parses the whole archive (up to ~1 MB) for one field, since
    # "session" sorts last in the JSON. Cache by (path, mtime) if listing a month
    # of sessions ever gets slow.
    try:
        payload = json.loads(archive.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # The repo is user-writable; a hand-mangled archive must not break browsing.
        logger.debug(f"Ignoring unreadable session archive {archive}: {exc}")
        return None
    session = payload.get("session") if isinstance(payload, dict) else None
    if not isinstance(session, dict):
        return None
    title = session.get("title")
    session_id = session.get("session_id")
    return (title if isinstance(title, str) and title.strip() else None), (
        session_id if isinstance(session_id, str) and session_id else directory.name
    )


class KnowledgeSkill(BaseModel):
    """Frontmatter of a skill dir's SKILL.md, rendered as a card above its prose."""

    name: str
    description: str = ""
    # None when metadata.carapace is absent or fails validation; the prose still renders.
    carapace: SkillCarapaceConfig | None = None


class KnowledgeDirListing(BaseModel):
    type: Literal["dir"] = "dir"
    path: str
    entries: list[KnowledgeEntry]
    # Recognized directory conventions get their defining document inlined, rendered
    # below the listing (a skill dir's SKILL.md, frontmatter stripped into `skill`).
    kind: Literal["skill"] | None = None
    doc_name: str | None = None
    doc: str | None = None
    skill: KnowledgeSkill | None = None


class KnowledgeFileInfo(BaseModel):
    type: Literal["file"] = "file"
    path: str
    name: str
    size: int
    mime: str
    # Decoded contents for text files within MAX_INLINE_TEXT_BYTES; None for binary
    # or oversized files, which the client offers as a download instead.
    content: str | None = None


def resolve_target(root: Path, raw_path: str) -> Path:
    """Resolve *raw_path* inside *root*, rejecting traversal and ``.git``."""
    root = root.resolve()
    target = (root / raw_path).resolve() if raw_path else root
    if target != root and not target.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Not found")
    if ".git" in target.relative_to(root).parts:
        raise HTTPException(status_code=404, detail="Not found")
    return target


def build_entry(child: Path) -> KnowledgeEntry:
    if not child.is_dir():
        return KnowledgeEntry(name=child.name, type="file", size=child.stat().st_size)
    archive = session_archive_entry(child)
    if archive is None:
        return KnowledgeEntry(name=child.name, type="dir")
    title, session_id = archive
    return KnowledgeEntry(name=child.name, type="dir", kind="session", label=title, session_id=session_id)


SKILL_DOC = "SKILL.md"


def list_dir(root: Path, target: Path) -> KnowledgeDirListing:
    entries = [build_entry(child) for child in target.iterdir() if child.name != ".git"]
    entries.sort(key=lambda e: (e.type != "dir", e.name.casefold()))
    rel = target.relative_to(root.resolve())
    listing = KnowledgeDirListing(path="" if rel == Path() else rel.as_posix(), entries=entries)

    # A SKILL.md marks a skill dir (same marker SkillRegistry scans for); inline it so
    # the browser can render it under the listing without a second request.
    skill_doc = target / SKILL_DOC
    if skill_doc.is_file():
        raw = read_text_content(skill_doc, skill_doc.stat().st_size)
        if raw is not None:
            document = parse_skill_document(raw, fallback_name=target.name)
            listing.kind = "skill"
            listing.doc_name = SKILL_DOC
            listing.doc = document.body
            listing.skill = KnowledgeSkill(
                name=document.name,
                description=document.description,
                carapace=parse_carapace_config(document, target.name),
            )
    return listing


def parse_carapace_config(document: SkillDocument, skill_name: str) -> SkillCarapaceConfig | None:
    """Validate ``metadata.carapace``, or return None if absent or malformed."""
    raw = document.metadata.get("carapace")
    if raw is None:
        return None
    try:
        return SkillCarapaceConfig.model_validate(raw)
    except ValidationError as exc:
        # Skills are user-authored; a bad declaration must not break browsing.
        logger.warning(f"Invalid metadata.carapace in SKILL.md for skill '{skill_name}': {exc}")
        return None


@router.get("/knowledge/browse", response_model=None)
@router.get("/knowledge/browse/{path:path}", response_model=None)
async def browse_knowledge(
    user: Annotated[UserIdentity, Depends(require(Scope.knowledge, Access.read))],
    path: str = "",
    raw: Annotated[bool, Query()] = False,
    download: Annotated[bool, Query()] = False,
) -> KnowledgeDirListing | KnowledgeFileInfo | FileResponse:
    root = server._knowledge_repo_registry.get_for_user(user.username).knowledge_dir.resolve()
    if not root.is_dir():
        return KnowledgeDirListing(path="", entries=[])
    target = resolve_target(root, path)
    if target.is_dir():
        return list_dir(root, target)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    rel = target.relative_to(root).as_posix()
    if raw or download:
        return FileResponse(
            target,
            media_type=guess_mime(target.name),
            filename=target.name,
            content_disposition_type="attachment" if download else "inline",
        )
    size = target.stat().st_size
    mime = guess_mime(target.name)
    return KnowledgeFileInfo(
        path=rel,
        name=target.name,
        size=size,
        mime=mime,
        content=None if mime.startswith("image/") else read_text_content(target, size),
    )
