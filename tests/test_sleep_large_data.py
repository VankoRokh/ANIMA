import json
import os
import tracemalloc
from uuid import uuid4

import pytest

from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.execution import SleepChunkExecutor
from anima.sleep.large_data import (
    GIB,
    MIB,
    SyntheticLargeAssetProcessor,
    SyntheticLargeSource,
)
from anima.sleep.processors import ProcessorRegistry
from anima.sleep.store import SleepStore


LOGICAL_SIZE = 10 * GIB
CHUNK_SIZE = 5 * MIB
EXPECTED_CHUNKS = 2048


def _fixture(tmp_path, *, source_ref=None):
    source_ref = source_ref or SourceRef("asset", f"asset_{uuid4()}")
    source_registry = SourceRegistry().register(
        "asset",
        lambda source_id: source_id == source_ref.source_id,
    )
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    item = WorkItem.create(
        job_id=job["id"],
        source_ref=source_ref,
        processor="synthetic-large-asset",
        processor_version="1",
        cost_hint="expensive",
    )
    item = store.create_work_item(item, source_registry=source_registry)
    processor_registry = ProcessorRegistry().register(
        SyntheticLargeAssetProcessor()
    )
    executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=processor_registry,
        source_registry=source_registry,
    )
    return store, item, source_registry, executor


def _source(source_ref, *, logical_size=LOGICAL_SIZE, sample_bytes=4096):
    return SyntheticLargeSource(
        source_ref=source_ref,
        logical_size_bytes=logical_size,
        chunk_size_bytes=CHUNK_SIZE,
        sample_bytes=sample_bytes,
    )


def _storage_bytes(database_file):
    total = 0
    for suffix in ("", "-wal", "-shm"):
        path = str(database_file) + suffix
        if os.path.exists(path):
            total += os.path.getsize(path)
    return total


def _peak_for_prefix(source_ref, logical_size):
    source = _source(source_ref, logical_size=logical_size)
    tracemalloc.start()
    iterator = source.iter_from(0)
    last = None
    for _ in range(128):
        last = next(iterator)
        assert len(last.sample) == 4096
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert last is not None
    return peak


def test_synthetic_large_source_represents_ten_gib_without_materializing_payload():
    source_ref = SourceRef("asset", f"asset_{uuid4()}")
    source = _source(source_ref)

    assert source.logical_size_bytes == 10 * GIB
    assert source.chunk_count == EXPECTED_CHUNKS
    assert source.materialized_payload_limit_bytes == 4096
    assert not hasattr(source, "payload")

    first = next(source.iter_from(0))
    assert first.sequence == 0
    assert first.offset_bytes == 0
    assert first.logical_size_bytes == CHUNK_SIZE
    assert len(first.sample) == 4096


def test_large_source_can_begin_directly_at_arbitrary_chunk():
    source_ref = SourceRef("asset", f"asset_{uuid4()}")
    source = _source(source_ref)

    iterator = source.iter_from(1337)
    chunk = next(iterator)

    assert source.iter_starts == (1337,)
    assert source.yielded_sequences == (1337,)
    assert chunk.sequence == 1337
    assert chunk.offset_bytes == 1337 * CHUNK_SIZE
    assert chunk.logical_size_bytes == CHUNK_SIZE


def test_large_source_memory_is_bounded_by_materialized_chunk_not_logical_size():
    source_ref = SourceRef("asset", f"asset_{uuid4()}")

    peak_10_gib = _peak_for_prefix(source_ref, 10 * GIB)
    peak_100_gib = _peak_for_prefix(source_ref, 100 * GIB)

    assert peak_10_gib < 4 * MIB
    assert peak_100_gib < 4 * MIB
    assert abs(peak_100_gib - peak_10_gib) < 1 * MIB


def test_executor_resume_requests_next_uncommitted_chunk_directly(tmp_path):
    store, item, sources, executor = _fixture(tmp_path)
    first_source = _source(item.source_ref)

    interrupted = executor.run(
        item.public_id,
        first_source,
        interrupt_after_new_chunks=123,
    )

    assert interrupted.status == "checkpointed"
    assert interrupted.processed_chunks == 123
    assert interrupted.committed_chunks == 123
    assert first_source.iter_starts == (0,)
    assert first_source.yielded_sequences[0] == 0
    assert first_source.yielded_sequences[-1] == 122
    assert len(first_source.yielded_sequences) == 123

    reopened = SleepStore(tmp_path / "sleep.db")
    resumed_executor = SleepChunkExecutor(
        sleep_store=reopened,
        processor_registry=ProcessorRegistry().register(
            SyntheticLargeAssetProcessor()
        ),
        source_registry=sources,
    )
    resumed_source = _source(item.source_ref)

    completed = resumed_executor.run(item.public_id, resumed_source)

    assert completed.status == "completed"
    assert completed.resumed_from_sequence == 123
    assert completed.processed_chunks == EXPECTED_CHUNKS - 123
    assert completed.committed_chunks == EXPECTED_CHUNKS
    assert resumed_source.iter_starts == (123,)
    assert resumed_source.yielded_sequences[0] == 123
    assert min(resumed_source.yielded_sequences) == 123
    assert completed.final_result.output["chunks_processed"] == EXPECTED_CHUNKS
    assert completed.final_result.output["logical_bytes_processed"] == LOGICAL_SIZE
    assert completed.final_result.output["last_sequence"] == EXPECTED_CHUNKS - 1
    assert reopened.get_work_item(item.public_id).attempts == 2


def test_large_source_checkpoints_and_database_store_metadata_not_payload(tmp_path):
    store, item, _, executor = _fixture(tmp_path)
    source = _source(item.source_ref)

    completed = executor.run(item.public_id, source)
    checkpoints = store.list_checkpoints(item.public_id)

    assert completed.status == "completed"
    assert len(checkpoints) == EXPECTED_CHUNKS
    assert max(
        len(json.dumps(checkpoint["checkpoint"], sort_keys=True))
        for checkpoint in checkpoints
    ) < 512
    assert max(
        len(json.dumps(checkpoint["local_result"], sort_keys=True))
        for checkpoint in checkpoints
    ) < 512
    assert _storage_bytes(store.database_file) < 64 * MIB
    assert _storage_bytes(store.database_file) < LOGICAL_SIZE // 100


def test_large_source_final_chunk_handles_non_multiple_logical_size(tmp_path):
    logical_size = 10 * GIB + 12345
    store, item, _, executor = _fixture(tmp_path)
    source = _source(item.source_ref, logical_size=logical_size)

    completed = executor.run(item.public_id, source)

    assert source.chunk_count == EXPECTED_CHUNKS + 1
    assert completed.final_result.output["chunks_processed"] == EXPECTED_CHUNKS + 1
    assert completed.final_result.output["logical_bytes_processed"] == logical_size
    latest = store.get_latest_checkpoint(item.public_id)
    assert latest["sequence"] == EXPECTED_CHUNKS
    assert latest["local_result"]["logical_size_bytes"] == 12345


def test_large_source_rejects_invalid_resume_and_sample_configuration():
    source_ref = SourceRef("asset", f"asset_{uuid4()}")
    source = _source(source_ref)

    with pytest.raises(ValueError, match="outside synthetic source"):
        next(source.iter_from(EXPECTED_CHUNKS + 1))

    with pytest.raises(ValueError, match="must not exceed"):
        SyntheticLargeSource(
            source_ref=source_ref,
            logical_size_bytes=GIB,
            chunk_size_bytes=1024,
            sample_bytes=2048,
        )


def test_existing_plain_iterable_resume_contract_remains_supported(tmp_path):
    class PlainProcessor(SyntheticLargeAssetProcessor):
        pass

    source_ref = SourceRef("asset", f"asset_{uuid4()}")
    source_registry = SourceRegistry().register(
        "asset",
        lambda source_id: source_id == source_ref.source_id,
    )
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    item = WorkItem.create(
        job_id=job["id"],
        source_ref=source_ref,
        processor="synthetic-large-asset",
        processor_version="1",
    )
    item = store.create_work_item(item, source_registry=source_registry)
    executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=ProcessorRegistry().register(PlainProcessor()),
        source_registry=source_registry,
    )
    source = SyntheticLargeSource(
        source_ref=source_ref,
        logical_size_bytes=3 * CHUNK_SIZE,
        chunk_size_bytes=CHUNK_SIZE,
    )
    plain_chunks = list(source.iter_from(0))

    interrupted = executor.run(
        item.public_id,
        plain_chunks,
        interrupt_after_new_chunks=1,
    )
    assert interrupted.status == "checkpointed"

    completed = executor.run(item.public_id, plain_chunks)
    assert completed.status == "completed"
    assert completed.resumed_from_sequence == 1
    assert completed.final_result.output["chunks_processed"] == 3
