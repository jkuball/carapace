from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import Any, Self

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, ValidationError, field_validator, model_validator
from pydantic_ai.messages import ModelMessage

from ..models.session import SessionAttributes, SessionJobRunContext, SessionState
from ..sandbox.state import SessionSandboxSnapshot
from .auth import verify_token
from .history import _history_from_messages
from .state import server_module

server = server_module()

router = APIRouter()


class SessionCreateRequest(BaseModel):
    channel_type: str = "cli"
    channel_ref: str = ""
    private: bool | None = None
    unattended: bool | None = None
    ask_mode: bool | None = None
    yolo_mode: bool | None = None

    @model_validator(mode="after")
    def _validate_modes(self) -> Self:
        if self.ask_mode and self.yolo_mode:
            raise ValueError("ask_mode and yolo_mode are mutually exclusive")
        return self


class SessionAttributesPatch(BaseModel):
    private: bool | None = None
    archived: bool | None = None
    pinned: bool | None = None
    favorite: bool | None = None
    unattended: bool | None = None
    ask_mode: bool | None = None
    yolo_mode: bool | None = None

    @model_validator(mode="after")
    def _validate_modes(self) -> Self:
        if self.ask_mode and self.yolo_mode:
            raise ValueError("ask_mode and yolo_mode are mutually exclusive")
        return self


class SessionUpdateRequest(BaseModel):
    attributes: SessionAttributesPatch | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None

    @field_validator("agent_model_name", "sentinel_model_name", mode="before")
    @classmethod
    def _normalize_model_name_field(cls, value: str | None) -> str | None:
        return cls._normalize_optional_model_name(value)

    @staticmethod
    def _normalize_optional_model_name(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SessionForkRequest(BaseModel):
    event_index: int
    channel_type: str = "cli"
    channel_ref: str = ""
    unattended: bool | None = None
    ask_mode: bool | None = None
    yolo_mode: bool | None = None

    @model_validator(mode="after")
    def _validate_modes(self) -> Self:
        if self.ask_mode and self.yolo_mode:
            raise ValueError("ask_mode and yolo_mode are mutually exclusive")
        return self


class SessionInfo(BaseModel):
    session_id: str
    channel_type: str
    channel_ref: str | None = None
    created_at: str
    last_active: str
    title: str | None = None
    agent_model_name: str | None = None
    sentinel_model_name: str | None = None
    attributes: SessionAttributes
    latest_job_run: SessionJobRunContext | None = None
    knowledge_last_committed_at: str | None = None
    knowledge_last_archive_path: str | None = None
    knowledge_last_commit_trigger: str | None = None
    message_count: int = 0
    total_cost_usd: float | None = None
    sandbox: SessionSandboxSnapshot | None = None

    @classmethod
    def from_state(
        cls,
        state: SessionState,
        *,
        message_count: int = 0,
        total_cost_usd: Decimal | None = None,
        sandbox: SessionSandboxSnapshot | None = None,
    ) -> SessionInfo:
        return cls(
            session_id=state.session_id,
            channel_type=state.channel_type,
            channel_ref=state.channel_ref,
            created_at=state.created_at.isoformat(),
            last_active=state.last_active.isoformat(),
            title=state.title,
            agent_model_name=state.agent_model_name,
            sentinel_model_name=state.sentinel_model_name,
            attributes=state.attributes,
            latest_job_run=state.latest_job_run.model_copy(deep=True) if state.latest_job_run is not None else None,
            knowledge_last_committed_at=(
                state.knowledge_last_committed_at.isoformat() if state.knowledge_last_committed_at else None
            ),
            knowledge_last_archive_path=state.knowledge_last_archive_path,
            knowledge_last_commit_trigger=state.knowledge_last_commit_trigger,
            message_count=message_count,
            total_cost_usd=float(total_cost_usd) if total_cost_usd is not None else None,
            sandbox=sandbox,
        )


class SessionListPage(BaseModel):
    items: list[SessionInfo]
    next_cursor: str | None = None
    has_more: bool


class SessionArchiveCommitResponse(BaseModel):
    session: SessionInfo
    committed: bool
    archive_path: str | None = None
    committed_at: str | None = None
    trigger: str
    reason: str | None = None


def _session_message_count(session_id: str) -> int:
    events = server._engine.session_mgr.load_events(session_id)
    if events:
        return sum(1 for event in events if event.get("role") in {"user", "assistant"})

    history = _history_from_messages(session_id)
    return sum(1 for message in history if message.role in {"user", "assistant"})


def _compute_sorted_session_states(*, include_archived: bool) -> list[SessionState]:
    states: list[SessionState] = []
    for session_id in server._engine.session_mgr.list_sessions():
        state = server._engine.session_mgr.load_state(session_id)
        if state is None:
            continue
        if state.attributes.archived and not include_archived:
            continue
        states.append(state)

    states.sort(
        key=lambda state: (
            not state.attributes.pinned,
            -state.last_active.timestamp(),
            state.session_id,
        )
    )
    return states


def _build_session_list_items(*, include_archived: bool, include_message_count: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for state in _compute_sorted_session_states(include_archived=include_archived):
        session_info = _session_info_from_state(state, include_message_count=include_message_count)
        items.append(session_info.model_dump(mode="json"))
    return items


def _parse_session_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid session cursor") from exc
    if offset < 0:
        raise HTTPException(status_code=400, detail="Invalid session cursor")
    return offset


def _session_info_from_state(state: SessionState, *, include_message_count: bool) -> SessionInfo:
    message_count = _session_message_count(state.session_id) if include_message_count else 0
    sandbox = server._engine.session_mgr.load_sandbox_snapshot(state.session_id)
    usage = server._engine.session_mgr.load_usage(state.session_id)
    total_cost_usd = usage.estimated_cost().get("total")
    return SessionInfo.from_state(
        state,
        message_count=message_count,
        total_cost_usd=total_cost_usd,
        sandbox=sandbox,
    )


def _session_total_cost_usd(session_id: str) -> Decimal | None:
    usage = server._engine.session_mgr.load_usage(session_id)
    return usage.estimated_cost().get("total")


async def _list_session_page(
    *,
    include_message_count: bool,
    include_archived: bool,
    limit: int | None,
    cursor: str | None,
) -> SessionListPage:
    offset = _parse_session_cursor(cursor)
    cached_items = await server._session_list_cache.get_session_infos(
        include_archived=include_archived,
        include_message_count=include_message_count,
        loader=lambda: _build_session_list_items(
            include_archived=include_archived,
            include_message_count=include_message_count,
        ),
    )
    page_items = cached_items[offset:] if limit is None else cached_items[offset : offset + limit]
    next_offset = offset + len(page_items)
    has_more = next_offset < len(cached_items)
    return SessionListPage(
        items=[SessionInfo.model_validate(item) for item in page_items],
        next_cursor=str(next_offset) if has_more else None,
        has_more=has_more,
    )


@router.post("/sessions", response_model=SessionInfo)
async def create_session(
    body: SessionCreateRequest | None = None,
    _token: str = Depends(verify_token),
) -> SessionInfo:
    body = body or SessionCreateRequest()
    state = server._engine.session_mgr.create_session(
        body.channel_type,
        body.channel_ref,
        budget=server._engine.config.agent.default_session_budget,
        private=False if body.private is None else body.private,
        unattended=False if body.unattended is None else body.unattended,
        ask_mode=False if body.ask_mode is None else body.ask_mode,
        yolo_mode=False if body.yolo_mode is None else body.yolo_mode,
    )
    return SessionInfo.from_state(state)


@router.get("/sessions", response_model=SessionListPage)
async def list_sessions(
    include_message_count: bool = False,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    _token: str = Depends(verify_token),
) -> SessionListPage:
    return await _list_session_page(
        include_message_count=include_message_count,
        include_archived=include_archived,
        limit=limit,
        cursor=cursor,
    )


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str, _token: str = Depends(verify_token)) -> SessionInfo:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    sandbox = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return SessionInfo.from_state(
        state,
        message_count=_session_message_count(session_id),
        total_cost_usd=_session_total_cost_usd(session_id),
        sandbox=sandbox,
    )


@router.patch("/sessions/{session_id}", response_model=SessionInfo)
async def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    _token: str = Depends(verify_token),
) -> SessionInfo:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    next_attributes: SessionAttributes | None = None
    previous_attributes: SessionAttributes | None = None
    previous_history: list[ModelMessage] | None = None
    archive_changed = False
    archive_now = False

    if body.attributes is not None:
        previous_attributes = state.attributes.model_copy(deep=True)
        merged_attributes = state.attributes.model_dump(mode="json")
        merged_attributes.update(body.attributes.model_dump(exclude_none=True))
        try:
            next_attributes = SessionAttributes.model_validate(merged_attributes)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        unattended_changed = next_attributes.unattended != state.attributes.unattended
        if unattended_changed:
            active = server._engine._active.get(session_id)
            lock = active.lock if active else contextlib.nullcontext()
            async with lock:
                if server._engine.is_agent_running(session_id):
                    raise HTTPException(
                        status_code=409,
                        detail="Cannot toggle unattended mode while an agent turn is actively running",
                    )
                if state.attributes.unattended and not next_attributes.unattended:
                    history = server._engine.session_mgr.load_history(session_id)
                    previous_history = history
                    truncated_history = server._engine._truncate_incomplete_model_history(history)
                    normalized_history = server._engine._normalize_unattended_output_history(truncated_history)
                    server._engine.session_mgr.save_history(session_id, normalized_history)

        archive_changed = next_attributes.archived != state.attributes.archived
        archive_now = next_attributes.archived

        if archive_changed and server._engine.is_agent_running(session_id):
            raise HTTPException(status_code=409, detail="Cannot archive a session while an agent turn is running")

    model_changes: dict[str, str | None] = {}
    if "agent_model_name" in body.model_fields_set:
        model_changes["agent_model_name"] = body.agent_model_name
    if "sentinel_model_name" in body.model_fields_set:
        model_changes["sentinel_model_name"] = body.sentinel_model_name

    previous_models: dict[str, str | None] = {}
    if model_changes:
        previous_models = {
            "agent_model_name": state.agent_model_name,
            "sentinel_model_name": state.sentinel_model_name,
        }
        try:
            state = server._engine.update_session_model_overrides(session_id, **model_changes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if next_attributes is not None:
        state.attributes = next_attributes
        server._engine.session_mgr.save_state(state)
        server._engine.update_active_state(session_id, attributes=next_attributes)

        try:
            if archive_changed and archive_now and server._session_archive.enabled and not next_attributes.private:
                await server._session_archive.commit_session(
                    session_id,
                    trigger="archive",
                    is_agent_running=lambda: server._engine.is_agent_running(session_id),
                )
                refreshed = server._engine.session_mgr.load_state(session_id)
                if refreshed is None:
                    raise HTTPException(status_code=404, detail="Session not found")
                state = refreshed
        except Exception:
            if previous_attributes is not None:
                state.attributes = previous_attributes
                server._engine.session_mgr.save_state(state)
                server._engine.update_active_state(session_id, attributes=previous_attributes)
            if previous_history is not None:
                server._engine.session_mgr.save_history(session_id, previous_history)
            if model_changes:
                state = server._engine.update_session_model_overrides(session_id, **previous_models)
            raise

        if archive_changed and archive_now:
            server._engine.deactivate(session_id)
            await server._engine.sandbox_mgr.destroy_session(session_id)

    sandbox = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return SessionInfo.from_state(
        state,
        message_count=_session_message_count(session_id),
        total_cost_usd=_session_total_cost_usd(session_id),
        sandbox=sandbox,
    )


@router.post("/sessions/{session_id}/fork", response_model=SessionInfo)
async def fork_session(
    session_id: str,
    body: SessionForkRequest,
    _token: str = Depends(verify_token),
) -> SessionInfo:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        forked = server._engine.fork_session(
            session_id,
            event_index=body.event_index,
            channel_type=body.channel_type,
            channel_ref=body.channel_ref,
            unattended=body.unattended,
            ask_mode=body.ask_mode,
            yolo_mode=body.yolo_mode,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SessionInfo.from_state(
        forked,
        message_count=_session_message_count(forked.session_id),
        total_cost_usd=_session_total_cost_usd(forked.session_id),
    )


@router.post("/sessions/{session_id}/knowledge/commit", response_model=SessionArchiveCommitResponse)
async def commit_session_knowledge(
    session_id: str,
    _token: str = Depends(verify_token),
) -> SessionArchiveCommitResponse:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not server._session_archive.enabled:
        raise HTTPException(status_code=503, detail="Session archive is disabled")
    if state.attributes.private:
        raise HTTPException(status_code=409, detail="Private sessions cannot be committed to knowledge")
    if server._engine.is_agent_running(session_id):
        raise HTTPException(status_code=409, detail="Cannot archive a session while an agent turn is running")

    result = await server._session_archive.commit_session(
        session_id,
        trigger="manual",
        is_agent_running=lambda: server._engine.is_agent_running(session_id),
    )
    fresh = server._engine.session_mgr.load_state(session_id)
    if fresh is None:
        raise HTTPException(status_code=404, detail="Session not found")
    sandbox = server._engine.session_mgr.load_sandbox_snapshot(session_id)
    return SessionArchiveCommitResponse(
        session=SessionInfo.from_state(
            fresh,
            message_count=_session_message_count(session_id),
            total_cost_usd=_session_total_cost_usd(session_id),
            sandbox=sandbox,
        ),
        committed=result.committed,
        archive_path=result.archive_path,
        committed_at=result.committed_at.isoformat() if result.committed_at else None,
        trigger=result.trigger,
        reason=result.reason,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, _token: str = Depends(verify_token)) -> None:
    state = server._engine.session_mgr.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    server._engine.deactivate(session_id)
    await server._engine.sandbox_mgr.destroy_session(session_id)
    if server._session_archive.enabled and server._config.sessions.commit.delete_from_knowledge_on_session_delete:
        try:
            await server._session_archive.delete_session_archive(state)
        except Exception as exc:
            logger.warning(f"Session archive delete failed for {session_id}: {exc}")
    if not server._engine.session_mgr.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
