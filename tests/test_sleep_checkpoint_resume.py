import sqlite3
from uuid import uuid4

import pytest

from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.execution import SleepChunkExecutor
from anima.sleep.processors import (
    ChunkResult,
    FinalizeResult,
    ProcessorDescriptor,
    ProcessorRegistry,
    SleepProcessor,
)
from anima.sleep.store import SleepStore
from anima.sleep.text_consolidation import DeterministicTextConsolidationProcessor


class RecordingProcessor(SleepProcessor):
    def __init__(self):
        super().__init__(
            ProcessorDescriptor(
                name="resume-test",
                version="1",
                work_kind="CONSOLIDATE",
                source_kinds=frozenset({"event"}),
            )
        )
        self.calls = []

    def _initial_checkpoint(self, work_item):
        return {"values": []}

    def _process_chunk(self, work_item, *, chunk, checkpoint):
        self.calls.append(chunk)
        values = list(checkpoint["values"])
        values.append(chunk)
        return ChunkResult(
            checkpoint={"values": values},
            local_result={"accepted": chunk},
        )

    def _finalize(self, work_item, *, checkpoint):
        return FinalizeResult.create(
            work_item=work_item,
            output={"values": checkpoint["values"]},
        )


def _fixture(path):
    source = SourceRef("event", f"ev_{uuid4()}")
    registry = SourceRegistry().register(
        "event",
        lambda source_id: source_id == source.source_id,
    )
    store = SleepStore(path / "sleep.db")
    job = store.create_job()
    item = WorkItem.create(
        job_id=job["id"],
        source_ref=source,
        processor="resume-test",
        processor_version="1",
    )
    item = store.create_work_item(item, source_registry=registry)
    return store, item


def _executor(store, processor=None):
    processor = processor or RecordingProcessor()
    registry = ProcessorRegistry().register(processor)
    return SleepChunkExecutor(
        sleep_store=store,
        processor_registry=registry,
    ), processor


def test_checkpoint_commit_persists_checkpoint_and_local_result_atomically(tmp_path):
    store, item = _fixture(tmp_path)
    store.begin_work_item(item.public_id)

    checkpoint = store.commit_work_item_chunk(
        item.public_id,
        sequence=0,
        checkpoint={"cursor": 1},
        local_result={"accepted": "alpha"},
    )

    current = store.get_work_item(item.public_id)
    assert current.status == "running"
    assert current.checkpoint_ref == checkpoint["id"]
    assert checkpoint["sequence"] == 0
    assert checkpoint["checkpoint"] == {"cursor": 1}
    assert checkpoint["local_result"] == {"accepted": "alpha"}

    reopened = SleepStore(tmp_path / "sleep.db")
    assert reopened.get_latest_checkpoint(item.public_id) == checkpoint
    assert reopened.get_work_item(item.public_id).checkpoint_ref == checkpoint["id"]


def test_invalid_checkpoint_sequence_does_not_partially_update_work_item(tmp_path):
    store, item = _fixture(tmp_path)
    store.begin_work_item(item.public_id)
    first = store.commit_work_item_chunk(
        item.public_id,
        sequence=0,
        checkpoint={"cursor": 1},
        local_result={"accepted": "alpha"},
    )

    with pytest.raises(ValueError, match="sequence must be 1"):
        store.commit_work_item_chunk(
            item.public_id,
            sequence=2,
            checkpoint={"cursor": 3},
            local_result={"accepted": "wrong"},
        )

    assert store.list_checkpoints(item.public_id) == [first]
    assert store.get_work_item(item.public_id).checkpoint_ref == first["id"]


def test_work_item_cannot_pause_before_first_committed_chunk(tmp_path):
    store, item = _fixture(tmp_path)
    store.begin_work_item(item.public_id)

    with pytest.raises(ValueError, match="before first committed chunk"):
        store.pause_work_item(item.public_id)

    assert store.get_work_item(item.public_id).status == "running"


@pytest.mark.parametrize("interrupt_after", [1, 2, 3])
def test_interrupted_resume_matches_uninterrupted_and_skips_committed_chunks(
    tmp_path,
    interrupt_after,
):
    chunks = ["alpha", "beta", "gamma"]

    baseline_store, baseline_item = _fixture(tmp_path / "baseline")
    baseline_executor, baseline_processor = _executor(baseline_store)
    baseline = baseline_executor.run(baseline_item.public_id, chunks)

    assert baseline.status == "completed"
    assert baseline_processor.calls == chunks
    assert baseline.final_result.output == {"values": chunks}

    resumed_dir = tmp_path / "resumed"
    first_store, resumed_item = _fixture(resumed_dir)
    first_executor, first_processor = _executor(first_store)
    interrupted = first_executor.run(
        resumed_item.public_id,
        chunks,
        interrupt_after_new_chunks=interrupt_after,
    )

    assert interrupted.status == "checkpointed"
    assert interrupted.interrupted is True
    assert interrupted.processed_chunks == interrupt_after
    assert first_processor.calls == chunks[:interrupt_after]
    assert first_store.get_work_item(resumed_item.public_id).attempts == 1

    reopened = SleepStore(resumed_dir / "sleep.db")
    second_executor, second_processor = _executor(reopened)
    completed = second_executor.run(resumed_item.public_id, chunks)

    assert completed.status == "completed"
    assert completed.interrupted is False
    assert completed.resumed_from_sequence == interrupt_after
    assert completed.processed_chunks == len(chunks) - interrupt_after
    assert second_processor.calls == chunks[interrupt_after:]
    assert completed.final_result.output == baseline.final_result.output
    assert reopened.get_work_item(resumed_item.public_id).attempts == 2
    assert [
        checkpoint["sequence"]
        for checkpoint in reopened.list_checkpoints(resumed_item.public_id)
    ] == [0, 1, 2]
    assert [
        checkpoint["local_result"]
        for checkpoint in reopened.list_checkpoints(resumed_item.public_id)
    ] == [
        {"accepted": "alpha"},
        {"accepted": "beta"},
        {"accepted": "gamma"},
    ]


def test_resume_after_last_chunk_finalizes_without_reprocessing(tmp_path):
    chunks = ["alpha"]
    store, item = _fixture(tmp_path)
    executor, first_processor = _executor(store)

    interrupted = executor.run(
        item.public_id,
        chunks,
        interrupt_after_new_chunks=1,
    )
    assert interrupted.status == "checkpointed"
    assert first_processor.calls == ["alpha"]

    reopened = SleepStore(tmp_path / "sleep.db")
    resumed_executor, resumed_processor = _executor(reopened)
    completed = resumed_executor.run(item.public_id, chunks)

    assert resumed_processor.calls == []
    assert completed.processed_chunks == 0
    assert completed.final_result.output == {"values": ["alpha"]}


def test_executor_rejects_invalid_interrupt_limit_and_terminal_work(tmp_path):
    store, item = _fixture(tmp_path)
    executor, _ = _executor(store)

    with pytest.raises(ValueError, match="positive integer"):
        executor.run(
            item.public_id,
            ["alpha"],
            interrupt_after_new_chunks=0,
        )

    completed = executor.run(item.public_id, ["alpha"])
    assert completed.status == "completed"

    with pytest.raises(ValueError, match="Cannot begin WorkItem from status: completed"):
        executor.run(item.public_id, ["alpha"])


def test_executor_rejects_checkpoint_metadata_without_persisted_checkpoint(tmp_path):
    store, item = _fixture(tmp_path)
    fake_checkpoint_id = f"wcp_{uuid4()}"
    with store.transaction() as connection:
        connection.execute(
            """
            UPDATE work_items
            SET status = 'checkpointed', checkpoint_ref = ?
            WHERE public_id = ?
            """,
            (fake_checkpoint_id, item.public_id),
        )

    executor, _ = _executor(store)
    with pytest.raises(ValueError, match="without a persisted checkpoint"):
        executor.run(item.public_id, ["alpha"])


def test_executor_rejects_checkpoint_ref_that_is_not_latest(tmp_path):
    store, item = _fixture(tmp_path)
    store.begin_work_item(item.public_id)
    checkpoint = store.commit_work_item_chunk(
        item.public_id,
        sequence=0,
        checkpoint={"values": ["alpha"]},
        local_result={"accepted": "alpha"},
    )
    store.pause_work_item(item.public_id)

    with store.transaction() as connection:
        connection.execute(
            "UPDATE work_items SET checkpoint_ref = ? WHERE public_id = ?",
            (f"wcp_{uuid4()}", item.public_id),
        )

    assert store.get_checkpoint(checkpoint["id"]) == checkpoint
    executor, _ = _executor(store)
    with pytest.raises(ValueError, match="does not match latest"):
        executor.run(item.public_id, ["alpha", "beta"])


def test_real_text_processor_resume_matches_uninterrupted_output(tmp_path):
    source = SourceRef("event", f"ev_{uuid4()}")
    source_registry = SourceRegistry().register(
        "event",
        lambda source_id: source_id == source.source_id,
    )
    chunks = [
        {
            "source": source.to_dict(),
            "fragments": [
                {"group": "zeta", "text": " Zed "},
                {"group": "alpha", "text": "Alpha   beta"},
            ],
        },
        {
            "source": source.to_dict(),
            "fragments": [
                {"group": "alpha", "text": "Alpha beta"},
                {"group": "alpha", "text": "Gamma"},
            ],
        },
    ]

    def make_work(path):
        store = SleepStore(path / "sleep.db")
        job = store.create_job()
        item = WorkItem.create(
            job_id=job["id"],
            source_ref=source,
            processor="deterministic-text",
            processor_version="1",
        )
        item = store.create_work_item(item, source_registry=source_registry)
        processor = DeterministicTextConsolidationProcessor(
            max_items=10,
            max_chars=100,
        )
        executor = SleepChunkExecutor(
            sleep_store=store,
            processor_registry=ProcessorRegistry().register(processor),
        )
        return store, item, executor

    _, baseline_item, baseline_executor = make_work(tmp_path / "baseline-text")
    baseline = baseline_executor.run(baseline_item.public_id, chunks)

    resumed_dir = tmp_path / "resumed-text"
    _, resumed_item, first_executor = make_work(resumed_dir)
    interrupted = first_executor.run(
        resumed_item.public_id,
        chunks,
        interrupt_after_new_chunks=1,
    )
    assert interrupted.status == "checkpointed"

    reopened = SleepStore(resumed_dir / "sleep.db")
    resumed_processor = DeterministicTextConsolidationProcessor(
        max_items=10,
        max_chars=100,
    )
    second_executor = SleepChunkExecutor(
        sleep_store=reopened,
        processor_registry=ProcessorRegistry().register(resumed_processor),
    )
    completed = second_executor.run(resumed_item.public_id, chunks)

    assert completed.final_result.output == baseline.final_result.output
    assert completed.final_result.output["groups"] == [
        {"group": "alpha", "items": ["Alpha beta", "Gamma"]},
        {"group": "zeta", "items": ["Zed"]},
    ]
    assert [
        checkpoint["sequence"]
        for checkpoint in reopened.list_checkpoints(resumed_item.public_id)
    ] == [0, 1]


def test_sleep_store_migrates_v2_work_item_to_checkpoint_schema(tmp_path):
    database = tmp_path / "sleep.db"
    job_id = f"sj_{uuid4()}"
    work_item_id = f"wi_{uuid4()}"
    source_id = f"ev_{uuid4()}"
    timestamp = "2026-10-27T12:00:00+00:00"

    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE sleep_jobs (
                row_id INTEGER PRIMARY KEY,
                public_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE work_items (
                row_id INTEGER PRIMARY KEY,
                public_id TEXT NOT NULL UNIQUE,
                job_id TEXT NOT NULL,
                work_kind TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_id TEXT NOT NULL,
                processor TEXT NOT NULL,
                processor_version TEXT NOT NULL,
                priority INTEGER NOT NULL,
                cost_hint TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                checkpoint_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '2')"
        )
        connection.execute(
            """
            INSERT INTO sleep_jobs(public_id, status, created_at, updated_at)
            VALUES (?, 'queued', ?, ?)
            """,
            (job_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO work_items(
                public_id, job_id, work_kind, source_kind, source_id,
                processor, processor_version, priority, cost_hint,
                status, attempts, checkpoint_ref, created_at, updated_at
            ) VALUES (?, ?, 'CONSOLIDATE', 'event', ?, 'resume-test', '1',
                      0, 'normal', 'queued', 0, NULL, ?, ?)
            """,
            (work_item_id, job_id, source_id, timestamp, timestamp),
        )

    store = SleepStore(database)

    assert store.schema_version() == 3
    restored = store.get_work_item(work_item_id)
    assert restored.public_id == work_item_id
    assert restored.status == "queued"
    assert restored.source_ref == SourceRef("event", source_id)
    assert store.list_checkpoints(work_item_id) == []

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "work_item_checkpoints" in tables
