import sqlite3

import pytest

from anima.sleep.store import SleepStore


def test_sleep_store_initializes_schema_and_queued_job(tmp_path):
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job(created_at="2026-10-27T12:00:00+00:00")

    assert store.schema_version() == 1
    assert job["id"].startswith("sj_")
    assert job["status"] == "queued"
    assert job["created_at"] == "2026-10-27T12:00:00+00:00"
    assert job["updated_at"] == job["created_at"]

    transitions = store.list_transitions(job["id"])
    assert len(transitions) == 1
    assert transitions[0]["from_status"] is None
    assert transitions[0]["to_status"] == "queued"


def test_sleep_store_reopens_without_losing_job_identity_or_status(tmp_path):
    database = tmp_path / "sleep.db"
    first = SleepStore(database)
    job = first.create_job()
    first.transition_job(job["id"], "running", reason="start")
    first.transition_job(job["id"], "checkpointed", reason="chunk committed")

    reopened = SleepStore(database)
    restored = reopened.get_job(job["id"])

    assert restored["id"] == job["id"]
    assert restored["status"] == "checkpointed"
    assert [item["to_status"] for item in reopened.list_transitions(job["id"])] == [
        "queued",
        "running",
        "checkpointed",
    ]


def test_sleep_job_allows_resume_and_completion(tmp_path):
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()

    for status, reason in [
        ("running", "start"),
        ("checkpointed", "checkpoint 1"),
        ("interrupted", "wake requested"),
        ("running", "resume"),
        ("completed", "finished"),
    ]:
        job = store.transition_job(job["id"], status, reason=reason)

    assert job["status"] == "completed"
    assert [item["to_status"] for item in store.list_transitions(job["id"])] == [
        "queued",
        "running",
        "checkpointed",
        "interrupted",
        "running",
        "completed",
    ]


def test_sleep_job_failed_retry_is_explicit(tmp_path):
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()

    failed = store.transition_job(job["id"], "failed", reason="preflight failed")
    retried = store.transition_job(failed["id"], "queued", reason="retry approved")
    running = store.transition_job(retried["id"], "running", reason="retry start")

    assert running["status"] == "running"


@pytest.mark.parametrize(
    ("initial_steps", "invalid_status"),
    [
        ([], "completed"),
        ([], "queued"),
        (["running", "completed"], "running"),
        (["running", "interrupted"], "completed"),
        (["failed"], "completed"),
    ],
)
def test_sleep_job_rejects_invalid_transitions(tmp_path, initial_steps, invalid_status):
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()

    for index, status in enumerate(initial_steps):
        job = store.transition_job(job["id"], status, reason=f"step {index}")

    before = store.get_job(job["id"])
    transition_count = len(store.list_transitions(job["id"]))

    with pytest.raises(ValueError, match="Invalid SleepJob transition"):
        store.transition_job(job["id"], invalid_status, reason="invalid")

    assert store.get_job(job["id"]) == before
    assert len(store.list_transitions(job["id"])) == transition_count


def test_sleep_store_transaction_rolls_back(tmp_path):
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()

    with pytest.raises(RuntimeError, match="rollback test"):
        with store.transaction() as connection:
            connection.execute(
                "UPDATE sleep_jobs SET status = 'running' WHERE public_id = ?",
                (job["id"],),
            )
            raise RuntimeError("rollback test")

    assert store.get_job(job["id"])["status"] == "queued"


def test_sleep_store_database_constraints_and_foreign_keys(tmp_path):
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()

    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE sleep_jobs SET status = 'unknown' WHERE public_id = ?",
                (job["id"],),
            )

    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO sleep_job_transitions(
                    public_id, job_id, timestamp, from_status, to_status, reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "sjt_missing",
                    "sj_missing",
                    "2026-10-27T12:00:00+00:00",
                    "queued",
                    "running",
                    "foreign key test",
                ),
            )


def test_sleep_store_reports_invalid_database_file(tmp_path):
    database = tmp_path / "sleep.db"
    database.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(ValueError, match="Cannot initialize Sleep database"):
        SleepStore(database)


def test_sleep_store_default_database_uses_anima_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIMA_DATA_DIR", str(tmp_path))

    store = SleepStore()

    assert store.database_file == tmp_path / "sleep.db"
    assert store.database_file.exists()


def test_sleep_job_validates_id_and_timestamps(tmp_path):
    store = SleepStore(tmp_path / "sleep.db")

    with pytest.raises(ValueError, match="sj_UUIDv4"):
        store.create_job(public_id="sleep_123")

    with pytest.raises(ValueError, match="UTC offset"):
        store.create_job(created_at="2026-10-27T12:00:00")
