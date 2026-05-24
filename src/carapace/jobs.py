from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from croniter import croniter

from .models.jobs import JobCronTrigger, JobDefinition, JobsFile

JobTriggerKind = Literal["api", "cron", "manual"]


@dataclass(frozen=True, slots=True)
class ScheduledJobRun:
    job: JobDefinition
    trigger: JobCronTrigger
    scheduled_at: datetime


def build_job_run_message(
    job: JobDefinition,
    *,
    trigger_kind: JobTriggerKind,
    triggered_at: datetime,
    payload: str | None = None,
    cron_expression: str | None = None,
    timezone: str | None = None,
) -> str:
    title = job.name if job.name else job.id
    tz = ZoneInfo(timezone) if timezone else UTC
    iso_time = triggered_at.astimezone(tz).isoformat()

    match trigger_kind:
        case "cron":
            trigger_sentence = (
                f"The job was triggered automatically at {iso_time} due to cron rule `{cron_expression}` on the job."
            )
        case "manual":
            trigger_sentence = f"The job was triggered manually at {iso_time}."
        case "api":
            trigger_sentence = f"The job was triggered via the API at {iso_time}."
        case _:
            trigger_sentence = f"The job was triggered at {iso_time}."

    sections = [
        f"This is an invocation of job `{job.id}` ({title}).",
        "",
        f"Job instructions: {job.prompt.rstrip()}",
        "",
        trigger_sentence,
    ]

    if payload:
        sections.append(f"\nThe following additional data was supplied for this invocation:\n\n{payload}")

    return "\n".join(sections).strip()


class JobsStore:
    def __init__(self, data_dir: Path):
        self._path = data_dir / "jobs.yaml"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> JobsFile:
        if not self._path.exists():
            return JobsFile(jobs=[])
        raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        return JobsFile.model_validate(raw)

    def save(self, jobs_file: JobsFile) -> JobsFile:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = jobs_file.model_dump(mode="json", exclude_none=True)
        self._path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return jobs_file

    def list_jobs(self) -> list[JobDefinition]:
        return self.load().jobs

    def get_job(self, job_id: str) -> JobDefinition | None:
        return next((job for job in self.load().jobs if job.id == job_id), None)

    def create_job(self, job: JobDefinition) -> JobDefinition:
        jobs_file = self.load()
        if any(existing.id == job.id for existing in jobs_file.jobs):
            raise ValueError(f"Job {job.id!r} already exists")
        jobs_file.jobs.append(job)
        self.save(jobs_file)
        return job

    def update_job(self, job_id: str, job: JobDefinition) -> JobDefinition:
        jobs_file = self.load()
        for index, existing in enumerate(jobs_file.jobs):
            if existing.id != job_id:
                continue
            jobs_file.jobs[index] = job
            self.save(jobs_file)
            return job
        raise KeyError(job_id)

    def delete_job(self, job_id: str) -> bool:
        jobs_file = self.load()
        filtered = [job for job in jobs_file.jobs if job.id != job_id]
        if len(filtered) == len(jobs_file.jobs):
            return False
        jobs_file.jobs = filtered
        self.save(jobs_file)
        return True


class JobsScheduler:
    def __init__(self, store: JobsStore, *, max_trigger_backfill: int = 100):
        self._store = store
        self._max_trigger_backfill = max_trigger_backfill
        self._last_checked_at: datetime | None = None

    @property
    def last_checked_at(self) -> datetime | None:
        return self._last_checked_at

    def collect_due_runs(self, *, now: datetime | None = None) -> list[ScheduledJobRun]:
        now = now or datetime.now(tz=UTC)
        if self._last_checked_at is None:
            self._last_checked_at = now
            return []
        if now <= self._last_checked_at:
            return []

        due_runs: list[ScheduledJobRun] = []
        for job in self._store.list_jobs():
            if not job.enabled:
                continue
            for trigger in job.triggers:
                due_runs.extend(
                    self._collect_due_runs_for_trigger(
                        job,
                        trigger,
                        since=self._last_checked_at,
                        now=now,
                    )
                )

        self._last_checked_at = now
        return sorted(due_runs, key=lambda run: run.scheduled_at)

    def _collect_due_runs_for_trigger(
        self,
        job: JobDefinition,
        trigger: JobCronTrigger,
        *,
        since: datetime,
        now: datetime,
    ) -> list[ScheduledJobRun]:
        timezone = ZoneInfo(trigger.timezone or "UTC")
        since_local = since.astimezone(timezone)
        now_local = now.astimezone(timezone)
        if now_local <= since_local:
            return []

        due_runs: list[ScheduledJobRun] = []
        if (
            now_local.microsecond == 0
            and croniter.match(trigger.expression, now_local, precision_in_seconds=1)
            and now_local > since_local
        ):
            due_runs.append(
                ScheduledJobRun(
                    job=job,
                    trigger=trigger,
                    scheduled_at=now_local.astimezone(UTC),
                )
            )

        iterator = croniter(trigger.expression, now_local)
        for _ in range(self._max_trigger_backfill):
            scheduled_local = iterator.get_prev(datetime)
            if scheduled_local <= since_local:
                break
            due_runs.append(
                ScheduledJobRun(
                    job=job,
                    trigger=trigger,
                    scheduled_at=scheduled_local.astimezone(UTC),
                )
            )

        due_runs.reverse()
        return due_runs
