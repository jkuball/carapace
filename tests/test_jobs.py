from __future__ import annotations

from datetime import UTC, datetime

from carapace.jobs import JobsStore, build_job_run_message
from carapace.models import JobDefinition


def test_jobs_store_roundtrip(tmp_path):
    store = JobsStore(tmp_path)
    job = JobDefinition(id="daily", name="Daily", prompt="Summarize.")

    store.create_job(job)

    loaded = store.load()
    assert [entry.id for entry in loaded.jobs] == ["daily"]
    assert store.path.exists()


def test_build_job_run_message_includes_trigger_context_and_payload():
    job = JobDefinition(id="daily", name="Daily", prompt="Summarize.")

    message = build_job_run_message(
        job,
        trigger_kind="api",
        triggered_at=datetime(2026, 5, 9, 10, 30, tzinfo=UTC),
        payload={"items": 3},
    )

    assert "Summarize." in message
    assert "reason: api" in message
    assert "2026-05-09T10:30:00+00:00" in message
    assert '"items": 3' in message
