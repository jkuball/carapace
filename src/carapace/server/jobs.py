from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel

from ..api_keys import Access, Scope
from ..auth import UserIdentity
from ..jobs import build_job_run_message
from ..models.jobs import JobDefinition, JobDefinitionInput, JobsFile
from ..models.session import SessionJobRunContext
from ..user_defaults import apply_job_model_defaults, effective_user_budget
from .auth import require
from .sessions import SessionInfo, _session_info_from_state
from .state import server_module

server = server_module()

router = APIRouter()

_JOB_SCHEDULER_SWEEP_SECONDS = 60


class JobRunRequest(BaseModel):
    data: str | None = None


class JobRunResult(BaseModel):
    job_id: str
    session_id: str
    created_new_session: bool
    session: SessionInfo


async def _jobs_scheduler_loop() -> None:
    """Periodically enqueue due cron-triggered jobs."""
    while True:
        await asyncio.sleep(_JOB_SCHEDULER_SWEEP_SECONDS)
        try:
            await _run_due_jobs_once()
        except Exception as exc:
            logger.warning(f"Jobs scheduler loop error: {exc}")


async def _run_due_jobs_once(*, now: datetime | None = None) -> int:
    due_runs = server._jobs_scheduler.collect_due_runs(now=now)
    for due_run in due_runs:
        try:
            await _run_job_definition(
                due_run.job,
                trigger_kind="cron",
                triggered_at=due_run.scheduled_at,
                cron_expression=due_run.trigger.expression,
                trigger_timezone=due_run.trigger.timezone,
            )
        except ValueError as exc:
            logger.warning(f"Scheduled job {due_run.job.id} skipped: {exc}")
        except Exception as exc:
            logger.warning(f"Scheduled job {due_run.job.id} failed: {exc}")
    return len(due_runs)


async def _run_job_definition(
    job: JobDefinition,
    *,
    trigger_kind: Literal["api", "cron", "manual"],
    triggered_at: datetime | None = None,
    payload: str | None = None,
    cron_expression: str | None = None,
    trigger_timezone: str | None = None,
) -> JobRunResult:
    created_new_session = False
    effective_triggered_at = triggered_at or datetime.now(tz=UTC)

    def raise_job_conflict(detail: str) -> None:
        if trigger_kind == "api":
            raise HTTPException(status_code=409, detail=detail)
        raise ValueError(detail)

    if job.persistent_session_id is None:
        job_user = server._auth_store.get_user(job.user)
        if job_user is None:
            raise_job_conflict("Job owner was not found")
        state = server._engine.session_mgr.create_session(
            channel_type="job",
            channel_ref=f"job:{job.id}",
            budget=effective_user_budget(server._engine.config, job_user.config),
            user=job.user,
            private=job.private,
            unattended=job.unattended,
            ask_mode=job.ask_mode,
            yolo_mode=job.yolo_mode,
        )
        apply_job_model_defaults(
            state,
            job_user.config,
            agent_model_name=job.agent_model_name,
            sentinel_model_name=job.sentinel_model_name,
            title_model_name=job.title_model_name,
        )
        created_new_session = True
    else:
        state = server._engine.session_mgr.load_state(job.persistent_session_id)
        if state is None or not server._engine.session_mgr.is_owned_by(state.session_id, job.user):
            raise_job_conflict("Configured persistent session was not found")
        if state.attributes.unattended:
            raise_job_conflict("Configured persistent session must be attended")
        if state.attributes.archived:
            raise_job_conflict("Configured persistent session must not be archived")

    if server._engine.is_agent_running(state.session_id):
        raise_job_conflict("Target session is busy")

    job_run_context = SessionJobRunContext(
        job_id=job.id,
        trigger_kind=trigger_kind,
        triggered_at=effective_triggered_at,
        data=payload,
        cron_expression=cron_expression,
    )
    state.latest_job_run = job_run_context
    server._engine.session_mgr.save_state(state)
    server._engine.update_active_state(state.session_id, latest_job_run=job_run_context)

    resolved_trigger_timezone = trigger_timezone or (
        next(
            (t.timezone for t in job.triggers if t.expression == cron_expression and t.timezone),
            None,
        )
        if cron_expression
        else None
    )
    message = build_job_run_message(
        job,
        trigger_kind=trigger_kind,
        triggered_at=effective_triggered_at,
        payload=payload,
        cron_expression=cron_expression,
        timezone=resolved_trigger_timezone,
    )
    await server._engine.submit_message(state.session_id, message)

    refreshed = server._engine.session_mgr.load_state(state.session_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = _session_info_from_state(refreshed, include_message_count=True)
    return JobRunResult(
        job_id=job.id,
        session_id=refreshed.session_id,
        created_new_session=created_new_session,
        session=session,
    )


@router.get("/jobs", response_model=JobsFile)
async def list_jobs(user: Annotated[UserIdentity, Depends(require(Scope.jobs, Access.read))]) -> JobsFile:
    return JobsFile(jobs=server._jobs_store.list_jobs_for_user(user.username))


@router.post("/jobs", response_model=JobDefinition, status_code=201)
async def create_job(
    body: JobDefinitionInput,
    user: Annotated[UserIdentity, Depends(require(Scope.jobs, Access.write))],
) -> JobDefinition:
    job = JobDefinition.model_validate({**body.model_dump(mode="json"), "user": user.username})
    try:
        return server._jobs_store.create_job(job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=JobDefinition)
async def get_job(
    job_id: str, user: Annotated[UserIdentity, Depends(require(Scope.jobs, Access.read))]
) -> JobDefinition:
    job = server._jobs_store.get_job_for_user(job_id, user.username)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.put("/jobs/{job_id}", response_model=JobDefinition)
async def update_job(
    job_id: str,
    body: JobDefinitionInput,
    user: Annotated[UserIdentity, Depends(require(Scope.jobs, Access.write))],
) -> JobDefinition:
    if body.id != job_id:
        raise HTTPException(status_code=400, detail="Job id in path and body must match")
    existing = server._jobs_store.get_job_for_user(job_id, user.username)
    if existing is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JobDefinition.model_validate({**body.model_dump(mode="json"), "user": user.username})
    try:
        return server._jobs_store.update_job(job_id, job)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str, user: Annotated[UserIdentity, Depends(require(Scope.jobs, Access.write))]
) -> Response:
    if server._jobs_store.get_job_for_user(job_id, user.username) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    deleted = server._jobs_store.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    return Response(status_code=204)


@router.post("/jobs/{job_id}/run", response_model=JobRunResult)
async def run_job(
    job_id: str,
    user: Annotated[UserIdentity, Depends(require(Scope.jobs, Access.write))],
    body: JobRunRequest | None = None,
) -> JobRunResult:
    job = server._jobs_store.get_job_for_user(job_id, user.username)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    body = body or JobRunRequest()
    return await _run_job_definition(
        job,
        trigger_kind="api",
        payload=body.data,
    )
