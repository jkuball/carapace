from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..auth import UserIdentity
from ..sandbox.manager import UploadError, UploadTooLargeError
from ..sandbox.state import SessionSandboxSnapshot
from .auth import verify_token
from .state import server_module

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

server = server_module()

router = APIRouter()


def _load_owned_session(session_id: str, user: UserIdentity):
    state = server._engine.session_mgr.load_state(session_id)
    if state is None or not server._engine.session_mgr.is_owned_by(session_id, user.username):
        raise HTTPException(status_code=404, detail="Session not found")
    return state


@router.get("/sessions/{session_id}/sandbox", response_model=SessionSandboxSnapshot)
async def get_session_sandbox(
    session_id: str,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> SessionSandboxSnapshot:
    _load_owned_session(session_id, user)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


@router.post("/sessions/{session_id}/sandbox/up", response_model=SessionSandboxSnapshot)
async def start_session_sandbox(
    session_id: str,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> SessionSandboxSnapshot:
    state = _load_owned_session(session_id, user)
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot start sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.ensure_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


@router.post("/sessions/{session_id}/sandbox/down", response_model=SessionSandboxSnapshot)
async def stop_session_sandbox(
    session_id: str,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> SessionSandboxSnapshot:
    state = _load_owned_session(session_id, user)
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot scale down sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.cleanup_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


class UploadedFile(BaseModel):
    name: str
    path: str


@router.post("/sessions/{session_id}/sandbox/files", response_model=UploadedFile)
async def upload_session_sandbox_file(
    session_id: str,
    user: Annotated[UserIdentity, Depends(verify_token)],
    file: Annotated[UploadFile, File()],
) -> UploadedFile:
    _load_owned_session(session_id, user)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    if snapshot is None or snapshot.status != "running":
        raise HTTPException(status_code=409, detail="Sandbox must be running to upload files")
    filename = file.filename or "upload"
    try:
        path = await server._engine.sandbox_mgr.upload_tmp_file(
            session_id,
            filename,
            file.read,
            max_bytes=MAX_UPLOAD_BYTES,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return UploadedFile(name=filename, path=path)


@router.post("/sessions/{session_id}/sandbox/wipe", response_model=SessionSandboxSnapshot)
async def wipe_session_sandbox(
    session_id: str,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> SessionSandboxSnapshot:
    state = _load_owned_session(session_id, user)
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot wipe sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.reset_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()
