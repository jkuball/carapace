from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from carapace.models import JobDefinition, JobsFile

JobTriggerKind = Literal["api", "cron", "manual"]


def build_job_run_message(
    job: JobDefinition,
    *,
    trigger_kind: JobTriggerKind,
    triggered_at: datetime,
    payload: dict[str, Any] | None = None,
    cron_expression: str | None = None,
) -> str:
    sections = [
        job.prompt.rstrip(),
        "",
        "Trigger Context",
        f"- reason: {trigger_kind}",
        f"- time: {triggered_at.astimezone(UTC).isoformat()}",
    ]
    if cron_expression:
        sections.append(f"- cron: {cron_expression}")
    if payload:
        sections.extend(
            [
                "",
                "Payload JSON",
                json.dumps(payload, indent=2, sort_keys=True),
            ]
        )
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
