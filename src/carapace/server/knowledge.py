"""Read-only browsing of the per-user knowledge repo working tree."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..session.sent_files import guess_mime
from .auth import require
from .state import server_module

server = server_module()

router = APIRouter()


class KnowledgeEntry(BaseModel):
    name: str
    type: Literal["file", "dir"]
    size: int | None = None


class KnowledgeDirListing(BaseModel):
    type: Literal["dir"] = "dir"
    path: str
    entries: list[KnowledgeEntry]


class KnowledgeFileInfo(BaseModel):
    type: Literal["file"] = "file"
    path: str
    name: str
    size: int
    mime: str


def resolve_target(root: Path, raw_path: str) -> Path:
    """Resolve *raw_path* inside *root*, rejecting traversal and ``.git``."""
    root = root.resolve()
    target = (root / raw_path).resolve() if raw_path else root
    if target != root and not target.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Not found")
    if ".git" in target.relative_to(root).parts:
        raise HTTPException(status_code=404, detail="Not found")
    return target


def list_dir(root: Path, target: Path) -> KnowledgeDirListing:
    entries = [
        KnowledgeEntry(
            name=child.name,
            type="dir" if child.is_dir() else "file",
            size=None if child.is_dir() else child.stat().st_size,
        )
        for child in target.iterdir()
        if child.name != ".git"
    ]
    entries.sort(key=lambda e: (e.type != "dir", e.name.casefold()))
    rel = target.relative_to(root.resolve())
    return KnowledgeDirListing(path="" if rel == Path() else rel.as_posix(), entries=entries)


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
    return KnowledgeFileInfo(
        path=rel,
        name=target.name,
        size=target.stat().st_size,
        mime=guess_mime(target.name),
    )
