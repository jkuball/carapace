from __future__ import annotations

from datetime import UTC, datetime, timedelta

from carapace.jobs import JobsScheduler, JobsStore, build_job_run_message
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


def test_jobs_scheduler_skips_first_scan(tmp_path):
    store = JobsStore(tmp_path)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    due_runs = scheduler.collect_due_runs(now=datetime(2026, 5, 9, 10, 0, tzinfo=UTC))

    assert due_runs == []


def test_jobs_scheduler_collects_due_runs_once_per_window(tmp_path):
    store = JobsStore(tmp_path)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert scheduler.collect_due_runs(now=start) == []

    due_runs = scheduler.collect_due_runs(now=start + timedelta(minutes=1, seconds=5))

    assert len(due_runs) == 1
    assert due_runs[0].job.id == "daily"
    assert due_runs[0].scheduled_at == datetime(2026, 5, 9, 10, 1, tzinfo=UTC)

    assert scheduler.collect_due_runs(now=start + timedelta(minutes=1, seconds=30)) == []


def test_jobs_scheduler_collects_due_run_on_exact_now_boundary(tmp_path):
    store = JobsStore(tmp_path)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert scheduler.collect_due_runs(now=start) == []

    due_runs = scheduler.collect_due_runs(now=start + timedelta(minutes=1))

    assert len(due_runs) == 1
    assert due_runs[0].job.id == "daily"
    assert due_runs[0].scheduled_at == datetime(2026, 5, 9, 10, 1, tzinfo=UTC)


def test_jobs_scheduler_does_not_regress_checkpoint_when_clock_moves_backwards(tmp_path):
    store = JobsStore(tmp_path)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "daily",
                "name": "Daily",
                "prompt": "Summarize.",
                "triggers": [{"expression": "* * * * *"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    start = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    assert scheduler.collect_due_runs(now=start) == []
    due_runs = scheduler.collect_due_runs(now=start + timedelta(minutes=5))

    assert [run.scheduled_at for run in due_runs] == [
        datetime(2026, 5, 9, 10, 1, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 2, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 3, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 4, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 5, tzinfo=UTC),
    ]

    assert scheduler.collect_due_runs(now=start + timedelta(minutes=4)) == []
    assert scheduler.collect_due_runs(now=start + timedelta(minutes=6)) == [
        due_runs[0].__class__(
            job=due_runs[0].job,
            trigger=due_runs[0].trigger,
            scheduled_at=datetime(2026, 5, 9, 10, 6, tzinfo=UTC),
        )
    ]


def test_jobs_scheduler_honors_trigger_timezone(tmp_path):
    store = JobsStore(tmp_path)
    store.create_job(
        JobDefinition.model_validate(
            {
                "id": "berlin-morning",
                "name": "Berlin Morning",
                "prompt": "Summarize.",
                "triggers": [{"expression": "0 9 * * *", "timezone": "Europe/Berlin"}],
            }
        )
    )
    scheduler = JobsScheduler(store)

    assert scheduler.collect_due_runs(now=datetime(2026, 5, 9, 6, 55, tzinfo=UTC)) == []

    due_runs = scheduler.collect_due_runs(now=datetime(2026, 5, 9, 7, 5, tzinfo=UTC))

    assert len(due_runs) == 1
    assert due_runs[0].scheduled_at == datetime(2026, 5, 9, 7, 0, tzinfo=UTC)
