import os
from uuid import uuid4

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.memory_store import MemoryStore
from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.derived import DerivedResultRepository
from anima.sleep.execution import SleepChunkExecutor
from anima.sleep.large_data import GIB, MIB, SyntheticLargeAssetProcessor, SyntheticLargeSource
from anima.sleep.processors import ProcessorRegistry
from anima.sleep.runtime_integration import SleepRuntimeIntegration
from anima.sleep.selection import SelectionBudget, SelectionCandidate, SleepSelector
from anima.sleep.store import SleepStore
from anima.sleep.text_consolidation import (
    DeterministicTextConsolidationProcessor,
    TextSourceReader,
)


def _text_fixture(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    event = Event(
        "conversation.user",
        {
            "text": "Alpha beta",
            "note": "Gamma",
            "nested": {"value": "Delta"},
        },
        source="stage3-validation",
        timestamp="2026-10-27T18:00:00+00:00",
    )
    event_log.write(event)

    memory_store = MemoryStore(tmp_path / "memory.db")
    closed_memory = memory_store.create_memory(
        memory_type="episodic",
        domain="project",
        status="closed",
        content="Closed memory for Stage 3 validation",
        importance=2,
        created_at="2026-10-27T18:01:00+00:00",
        source_event_id=event.event_id,
    )
    open_memory = memory_store.create_memory(
        memory_type="episodic",
        domain="project",
        status="open",
        content="Open memory must remain ineligible",
        importance=1,
        created_at="2026-10-27T18:01:30+00:00",
        source_event_id=event.event_id,
    )

    knowledge = KnowledgeLayer(memory_store=memory_store)
    confirmed = knowledge.create_candidate(
        domain="project",
        statement="Confirmed knowledge for Stage 3 validation",
        source_memory_id=closed_memory["id"],
        created_at="2026-10-27T18:02:00+00:00",
    )
    confirmed = knowledge.confirm(
        confirmed["knowledge"]["id"],
        confirmed_at="2026-10-27T18:03:00+00:00",
    )["knowledge"]
    provisional = knowledge.create_candidate(
        domain="project",
        statement="Provisional knowledge must remain ineligible",
        source_memory_id=closed_memory["id"],
        created_at="2026-10-27T18:04:00+00:00",
    )["knowledge"]

    refs = {
        "event": SourceRef("event", event.event_id),
        "closed_memory": SourceRef("memory", closed_memory["id"]),
        "open_memory": SourceRef("memory", open_memory["id"]),
        "confirmed": SourceRef("knowledge", confirmed["id"]),
        "provisional": SourceRef("knowledge", provisional["id"]),
    }
    sources = (
        SourceRegistry()
        .register("event", lambda source_id: source_id == event.event_id)
        .register(
            "memory",
            lambda source_id: source_id in {closed_memory["id"], open_memory["id"]},
        )
        .register(
            "knowledge",
            lambda source_id: source_id in {confirmed["id"], provisional["id"]},
        )
    )
    reader = TextSourceReader(
        event_log=event_log,
        memory_store=memory_store,
        knowledge_layer=knowledge,
    )
    return {
        "event_log": event_log,
        "event": event,
        "memory_store": memory_store,
        "closed_memory": closed_memory,
        "open_memory": open_memory,
        "knowledge": knowledge,
        "confirmed": confirmed,
        "provisional": provisional,
        "refs": refs,
        "sources": sources,
        "reader": reader,
    }


def _text_executor(store, sources):
    results = DerivedResultRepository(store)
    executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=ProcessorRegistry().register(
            DeterministicTextConsolidationProcessor(max_items=16, max_chars=2048)
        ),
        source_registry=sources,
        derived_results=results,
    )
    return executor, results


def _split_event_chunks(reader, source_ref):
    chunk = reader.read(source_ref).to_chunk()
    fragments = chunk["fragments"]
    assert len(fragments) >= 2
    return [
        {"source": chunk["source"], "fragments": fragments[:1]},
        {"source": chunk["source"], "fragments": fragments[1:]},
    ]


def _storage_bytes(database_file):
    total = 0
    for suffix in ("", "-wal", "-shm"):
        path = str(database_file) + suffix
        if os.path.exists(path):
            total += os.path.getsize(path)
    return total


def test_stage3_canonical_mixed_sources_interrupt_restart_resume_and_replay(tmp_path):
    fixture = _text_fixture(tmp_path)
    refs = fixture["refs"]

    before_events = fixture["event_log"].load_events()
    before_closed_memory = fixture["memory_store"].get_memory(
        fixture["closed_memory"]["id"]
    )
    before_open_memory = fixture["memory_store"].get_memory(
        fixture["open_memory"]["id"]
    )
    before_confirmed = fixture["knowledge"].describe(fixture["confirmed"]["id"])
    before_provisional = fixture["knowledge"].describe(fixture["provisional"]["id"])

    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    selector = SleepSelector(sleep_store=store, source_registry=fixture["sources"])
    selection = selector.select(
        job_id=job["id"],
        candidates=[
            SelectionCandidate(
                refs["open_memory"], priority=10, cost_hint="cheap", eligible=False
            ),
            SelectionCandidate(refs["event"], priority=9, cost_hint="cheap"),
            SelectionCandidate(refs["closed_memory"], priority=8, cost_hint="normal"),
            SelectionCandidate(refs["confirmed"], priority=7, cost_hint="normal"),
            SelectionCandidate(
                refs["provisional"], priority=6, cost_hint="cheap", terminal=True
            ),
        ],
        processor=DeterministicTextConsolidationProcessor.NAME,
        processor_version=DeterministicTextConsolidationProcessor.VERSION,
        budget=SelectionBudget(max_items=3, max_cost_units=5),
    )

    assert [item.source_ref for item in selection.work_items] == [
        refs["event"],
        refs["closed_memory"],
        refs["confirmed"],
    ]
    assert selection.total_cost_units == 5
    assert selection.skipped_ineligible == 1
    assert selection.skipped_terminal == 1
    assert selection.skipped_budget == 0

    by_source = {item.source_ref: item for item in selection.work_items}
    event_chunks = _split_event_chunks(fixture["reader"], refs["event"])

    executor, _ = _text_executor(store, fixture["sources"])
    runtime = SleepRuntimeIntegration(sleep_store=store, executor=executor)
    runtime.activate_job(job["id"])
    runtime.enter_sleep()

    interrupted = runtime.process_work(
        by_source[refs["event"]].public_id,
        event_chunks,
        max_new_chunks=1,
    )
    assert interrupted.status == "checkpointed"
    assert interrupted.processed_chunks == 1
    assert store.get_job(job["id"])["status"] == "checkpointed"

    reopened = SleepStore(tmp_path / "sleep.db")
    resumed_executor, resumed_results = _text_executor(reopened, fixture["sources"])
    resumed_runtime = SleepRuntimeIntegration(
        sleep_store=reopened,
        executor=resumed_executor,
    )
    resumed_runtime.activate_job(job["id"])
    resumed_runtime.enter_sleep()

    resumed = resumed_runtime.process_work(
        by_source[refs["event"]].public_id,
        event_chunks,
        max_new_chunks=None,
    )
    assert resumed.status == "completed"
    assert resumed.resumed_from_sequence == 1
    assert resumed.processed_chunks == 1
    assert resumed.final_result.authority == "derived"

    for source_ref in (refs["closed_memory"], refs["confirmed"]):
        item = by_source[source_ref]
        chunk = fixture["reader"].read(source_ref).to_chunk()
        outcome = resumed_runtime.process_work(
            item.public_id,
            [chunk],
            max_new_chunks=None,
        )
        assert outcome.status == "completed"
        assert outcome.final_result.source_refs == (source_ref,)
        assert outcome.final_result.authority == "derived"

    assert reopened.get_job(job["id"])["status"] == "completed"
    job_results = resumed_results.list_results(job_id=job["id"])
    assert len(job_results) == 3
    assert {result.source_refs[0] for result in job_results} == {
        refs["event"],
        refs["closed_memory"],
        refs["confirmed"],
    }
    assert all(result.processor == "deterministic-text" for result in job_results)
    assert all(result.processor_version == "1" for result in job_results)
    assert all(result.authority == "derived" for result in job_results)

    baseline_store = SleepStore(tmp_path / "baseline" / "sleep.db")
    baseline_job = baseline_store.create_job()
    baseline_item = baseline_store.create_work_item(
        WorkItem.create(
            job_id=baseline_job["id"],
            source_ref=refs["event"],
            processor="deterministic-text",
            processor_version="1",
        ),
        source_registry=fixture["sources"],
    )
    baseline_executor, _ = _text_executor(baseline_store, fixture["sources"])
    baseline = baseline_executor.run(baseline_item.public_id, event_chunks)
    assert resumed.final_result.output == baseline.final_result.output

    with pytest.raises(RuntimeError, match="SleepJob is not running: completed"):
        resumed_runtime.process_work(
            by_source[refs["event"]].public_id,
            event_chunks,
            max_new_chunks=None,
        )
    assert len(resumed_results.list_results(job_id=job["id"])) == 3

    assert fixture["event_log"].load_events() == before_events
    assert fixture["memory_store"].get_memory(
        fixture["closed_memory"]["id"]
    ) == before_closed_memory
    assert fixture["memory_store"].get_memory(
        fixture["open_memory"]["id"]
    ) == before_open_memory
    assert fixture["knowledge"].describe(
        fixture["confirmed"]["id"]
    ) == before_confirmed
    assert fixture["knowledge"].describe(
        fixture["provisional"]["id"]
    ) == before_provisional
    assert fixture["knowledge"].get(fixture["confirmed"]["id"])["status"] == "confirmed"


def test_stage3_canonical_large_source_direct_resume_preserves_bounded_storage(tmp_path):
    logical_size = 10 * GIB
    chunk_size = 5 * MIB
    interrupt_after = 777
    source_ref = SourceRef("asset", f"asset_{uuid4()}")
    sources = SourceRegistry().register(
        "asset",
        lambda source_id: source_id == source_ref.source_id,
    )
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    item = store.create_work_item(
        WorkItem.create(
            job_id=job["id"],
            source_ref=source_ref,
            processor="synthetic-large-asset",
            processor_version="1",
            cost_hint="expensive",
        ),
        source_registry=sources,
    )
    executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=ProcessorRegistry().register(SyntheticLargeAssetProcessor()),
        source_registry=sources,
    )
    source = SyntheticLargeSource(
        source_ref=source_ref,
        logical_size_bytes=logical_size,
        chunk_size_bytes=chunk_size,
    )

    first = executor.run(
        item.public_id,
        source,
        interrupt_after_new_chunks=interrupt_after,
    )
    assert first.status == "checkpointed"
    assert first.committed_chunks == interrupt_after

    reopened = SleepStore(tmp_path / "sleep.db")
    resumed_executor = SleepChunkExecutor(
        sleep_store=reopened,
        processor_registry=ProcessorRegistry().register(SyntheticLargeAssetProcessor()),
        source_registry=sources,
    )
    resumed_source = SyntheticLargeSource(
        source_ref=source_ref,
        logical_size_bytes=logical_size,
        chunk_size_bytes=chunk_size,
    )
    completed = resumed_executor.run(item.public_id, resumed_source)

    assert completed.status == "completed"
    assert completed.resumed_from_sequence == interrupt_after
    assert resumed_source.iter_starts == (interrupt_after,)
    assert resumed_source.yielded_sequences[0] == interrupt_after
    assert completed.final_result.output["logical_bytes_processed"] == logical_size
    assert completed.final_result.output["chunks_processed"] == 2048
    assert completed.final_result.source_refs == (source_ref,)
    assert completed.final_result.authority == "derived"
    assert _storage_bytes(reopened.database_file) < 8 * MIB
