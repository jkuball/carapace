from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..sandbox.state import SessionSandboxSnapshot
from .auth import verify_token
from .state import server_module

server = server_module()

router = APIRouter()


@router.get("/sessions/{session_id}/sandbox", response_model=SessionSandboxSnapshot)
async def get_session_sandbox(session_id: str, _token: str = Depends(verify_token)) -> SessionSandboxSnapshot:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


@router.post("/sessions/{session_id}/sandbox/up", response_model=SessionSandboxSnapshot)
async def start_session_sandbox(session_id: str, _token: str = Depends(verify_token)) -> SessionSandboxSnapshot:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot start sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.ensure_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


@router.post("/sessions/{session_id}/sandbox/down", response_model=SessionSandboxSnapshot)
async def stop_session_sandbox(session_id: str, _token: str = Depends(verify_token)) -> SessionSandboxSnapshot:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot scale down sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.cleanup_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()


@router.post("/sessions/{session_id}/sandbox/wipe", response_model=SessionSandboxSnapshot)
async def wipe_session_sandbox(session_id: str, _token: str = Depends(verify_token)) -> SessionSandboxSnapshot:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if state.attributes.archived:
        raise HTTPException(status_code=409, detail="Archived sessions must be unarchived before use")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot wipe sandbox while an agent turn is running")
    await server._engine.sandbox_mgr.reset_session(session_id)
    snapshot = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return snapshot or SessionSandboxSnapshot()
