from uuid import uuid4

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.memory_store import MemoryStore
from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.derived import (
    DERIVED_OUTPUT_ID_PREFIX,
    DERIVED_RESULT_ID_PREFIX,
    DerivedResultRepository,
)
from anima.sleep.execution import SleepChunkExecutor
from anima.sleep.processors import (
    ChunkResult,
    FinalizeResult,
    ProcessorDescriptor,
    ProcessorRegistry,
    SleepProcessor,
)
from anima.sleep.store import SleepStore
from anima.sleep.text_consolidation import (
    DeterministicTextConsolidationProcessor,
    TextSourceReader,
)


class EchoProcessor(SleepProcessor):
    def __init__(self):
        super().__init__(
            ProcessorDescriptor(
                name="derived-echo",
                version="1",
                work_kind="CONSOLIDATE",
                source_kinds=frozenset({"event", "memory", "knowledge"}),
            )
        )

    def _initial_checkpoint(self, work_item):
        return {"values": []}

    def _process_chunk(self, work_item, *, chunk, checkpoint):
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


def _event_work(tmp_path, *, source_exists=None):
    source = SourceRef("event", f"ev_{uuid4()}")
    exists = source_exists or {source.source_id}
    registry = SourceRegistry().register(
        "event",
        lambda source_id: source_id in exists,
    )
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    item = WorkItem.create(
        job_id=job["id"],
        source_ref=source,
        processor="derived-echo",
        processor_version="1",
    )
    item = store.create_work_item(item, source_registry=registry)
    repository = DerivedResultRepository(store)
    executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=ProcessorRegistry().register(EchoProcessor()),
        source_registry=registry,
        derived_results=repository,
    )
    return store, repository, executor, item, registry, exists


def _real_sources(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    event = Event(
        "conversation.user",
        {"text": "Persistent provenance source"},
        source="test",
        session_id="stage-3-7",
        timestamp="2026-10-27T12:00:00+00:00",
    )
    event_log.write(event)

    memory_store = MemoryStore(tmp_path / "memory.db")
    memory = memory_store.create_memory(
        memory_type="episodic",
        domain="project",
        status="closed",
        content="Closed memory remains authoritative source data.",
        importance=2,
        created_at="2026-10-27T12:01:00+00:00",
        source_event_id=event.event_id,
    )

    knowledge_layer = KnowledgeLayer(memory_store=memory_store)
    knowledge = knowledge_layer.create_candidate(
        domain="project",
        statement="Derived Sleep output does not become confirmed knowledge automatically.",
        source_memory_id=memory["id"],
        created_at="2026-10-27T12:02:00+00:00",
    )
    knowledge = knowledge_layer.confirm(
        knowledge["knowledge"]["id"],
        confirmed_at="2026-10-27T12:03:00+00:00",
    )["knowledge"]

    registry = SourceRegistry()
    registry.register(
        "event",
        lambda source_id: any(
            record["id"] == source_id for record in event_log.load_events()
        ),
    )
    registry.register(
        "memory",
        lambda source_id: memory_store.get_memory(source_id) is not None,
    )
    registry.register(
        "knowledge",
        lambda source_id: knowledge_layer.get(source_id) is not None,
    )
    reader = TextSourceReader(
        event_log=event_log,
        memory_store=memory_store,
        knowledge_layer=knowledge_layer,
    )
    return {
        "event_log": event_log,
        "event": event,
        "memory_store": memory_store,
        "memory": memory,
        "knowledge_layer": knowledge_layer,
        "knowledge": knowledge,
        "registry": registry,
        "reader": reader,
    }


def test_derived_result_persists_identity_output_and_transformation_history(tmp_path):
    store, repository, executor, item, _, _ = _event_work(tmp_path)

    outcome = executor.run(item.public_id, ["alpha", "beta"])
    result = outcome.final_result

    assert outcome.status == "completed"
    assert result.public_id.startswith(DERIVED_RESULT_ID_PREFIX)
    assert result.output_ref.startswith(DERIVED_OUTPUT_ID_PREFIX)
    assert result.work_item_id == item.public_id
    assert result.job_id == item.job_id
    assert result.source_refs == (item.source_ref,)
    assert result.processor == "derived-echo"
    assert result.processor_version == "1"
    assert result.authority == "derived"
    assert result.output == {"values": ["alpha", "beta"]}
    assert [step["kind"] for step in result.transformation_history] == [
        "chunk",
        "chunk",
        "finalize",
    ]
    assert [
        step["sequence"]
        for step in result.transformation_history
        if step["kind"] == "chunk"
    ] == [0, 1]

    checkpoint_ids = {
        checkpoint["id"] for checkpoint in store.list_checkpoints(item.public_id)
    }
    history_checkpoint_ids = {
        step["checkpoint_ref"]
        for step in result.transformation_history
        if step["kind"] == "chunk"
    }
    assert history_checkpoint_ids == checkpoint_ids

    reopened_store = SleepStore(tmp_path / "sleep.db")
    reopened_repository = DerivedResultRepository(reopened_store)
    assert reopened_repository.schema_version() == 1
    assert reopened_repository.get(result.public_id) == result
    assert reopened_repository.get_by_work_item(item.public_id) == result
    assert reopened_repository.get_by_output_ref(result.output_ref) == result


def test_derived_result_completion_is_atomic_with_work_item_status(tmp_path):
    source_id = f"ev_{uuid4()}"
    sources = {source_id}
    registry = SourceRegistry().register("event", lambda value: value in sources)
    store = SleepStore(tmp_path / "sleep.db")
    repository = DerivedResultRepository(store)
    job = store.create_job()

    def make_item():
        item = WorkItem.create(
            job_id=job["id"],
            source_ref=SourceRef("event", source_id),
            processor="derived-echo",
            processor_version="1",
        )
        item = store.create_work_item(item, source_registry=registry)
        return store.begin_work_item(item.public_id)

    first = make_item()
    second = make_item()
    shared_output_ref = f"dout_{uuid4()}"

    first_result = FinalizeResult.create(
        work_item=first,
        output={"result": "first"},
    )
    repository.commit_final_result(
        first.public_id,
        first_result,
        source_registry=registry,
        output_ref=shared_output_ref,
    )

    second_result = FinalizeResult.create(
        work_item=second,
        output={"result": "second"},
    )
    with pytest.raises(ValueError, match="Cannot commit DerivedResult"):
        repository.commit_final_result(
            second.public_id,
            second_result,
            source_registry=registry,
            output_ref=shared_output_ref,
        )

    assert store.get_work_item(first.public_id).status == "completed"
    assert store.get_work_item(second.public_id).status == "running"
    assert repository.get_by_work_item(second.public_id) is None


def test_missing_source_blocks_completion_and_result_commit(tmp_path):
    store, repository, executor, item, _, exists = _event_work(tmp_path)
    exists.clear()

    with pytest.raises(ValueError, match="Dangling source"):
        executor.run(item.public_id, ["alpha"])

    assert store.get_work_item(item.public_id).status == "running"
    assert repository.get_by_work_item(item.public_id) is None
    assert len(store.list_checkpoints(item.public_id)) == 1


def test_result_is_derived_not_a_raw_or_verified_source_kind(tmp_path):
    _, _, executor, item, _, _ = _event_work(tmp_path)

    result = executor.run(item.public_id, ["alpha"]).final_result
    record = result.to_dict()

    assert record["authority"] == "derived"
    assert record["sources"] == [item.source_ref.to_dict()]
    assert record["id"].startswith("dr_")
    assert not record["id"].startswith(("ev_", "mem_", "kn_"))
    assert record["output_ref"].startswith("dout_")


def test_real_memory_result_keeps_provenance_to_source_event(tmp_path):
    fixture = _real_sources(tmp_path)
    store = SleepStore(tmp_path / "sleep.db")
    repository = DerivedResultRepository(store)
    job = store.create_job()
    source = SourceRef("memory", fixture["memory"]["id"])
    item = WorkItem.create(
        job_id=job["id"],
        source_ref=source,
        processor="deterministic-text",
        processor_version="1",
    )
    item = store.create_work_item(item, source_registry=fixture["registry"])
    processor = DeterministicTextConsolidationProcessor()
    executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=ProcessorRegistry().register(processor),
        source_registry=fixture["registry"],
        derived_results=repository,
    )

    before = fixture["memory_store"].get_memory(source.source_id)
    chunk = fixture["reader"].read(source).to_chunk()
    result = executor.run(item.public_id, [chunk]).final_result
    after = fixture["memory_store"].get_memory(source.source_id)

    assert result.source_refs == (source,)
    assert fixture["memory_store"].source_events(source.source_id) == [
        fixture["event"].event_id
    ]
    assert before == after


def test_real_knowledge_result_preserves_evidence_and_authority(tmp_path):
    fixture = _real_sources(tmp_path)
    store = SleepStore(tmp_path / "sleep.db")
    repository = DerivedResultRepository(store)
    job = store.create_job()
    source = SourceRef("knowledge", fixture["knowledge"]["id"])
    item = WorkItem.create(
        job_id=job["id"],
        source_ref=source,
        processor="deterministic-text",
        processor_version="1",
    )
    item = store.create_work_item(item, source_registry=fixture["registry"])
    processor = DeterministicTextConsolidationProcessor()
    executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=ProcessorRegistry().register(processor),
        source_registry=fixture["registry"],
        derived_results=repository,
    )

    before = fixture["knowledge_layer"].describe(source.source_id)
    with fixture["memory_store"].transaction() as connection:
        knowledge_count_before = connection.execute(
            "SELECT COUNT(*) AS count FROM knowledge"
        ).fetchone()["count"]

    chunk = fixture["reader"].read(source).to_chunk()
    result = executor.run(item.public_id, [chunk]).final_result

    after = fixture["knowledge_layer"].describe(source.source_id)
    with fixture["memory_store"].transaction() as connection:
        knowledge_count_after = connection.execute(
            "SELECT COUNT(*) AS count FROM knowledge"
        ).fetchone()["count"]

    assert result.authority == "derived"
    assert result.source_refs == (source,)
    assert before == after
    assert after["knowledge"]["status"] == "confirmed"
    assert after["supporting_sources"] == [fixture["memory"]["id"]]
    assert fixture["memory_store"].source_events(fixture["memory"]["id"]) == [
        fixture["event"].event_id
    ]
    assert knowledge_count_after == knowledge_count_before


def test_repository_lists_results_by_job_without_mixing_jobs(tmp_path):
    store, repository, executor, item, registry, _ = _event_work(tmp_path)
    first = executor.run(item.public_id, ["first"]).final_result

    other_job = store.create_job()
    other_source = SourceRef("event", f"ev_{uuid4()}")
    other_sources = {other_source.source_id}
    other_registry = SourceRegistry().register(
        "event",
        lambda source_id: source_id in other_sources,
    )
    other_item = WorkItem.create(
        job_id=other_job["id"],
        source_ref=other_source,
        processor="derived-echo",
        processor_version="1",
    )
    other_item = store.create_work_item(other_item, source_registry=other_registry)
    other_executor = SleepChunkExecutor(
        sleep_store=store,
        processor_registry=ProcessorRegistry().register(EchoProcessor()),
        source_registry=other_registry,
        derived_results=repository,
    )
    second = other_executor.run(other_item.public_id, ["second"]).final_result

    assert repository.list_results(job_id=item.job_id) == [first]
    assert repository.list_results(job_id=other_job["id"]) == [second]
    assert repository.list_results() == [first, second]
    assert registry.require(item.source_ref) == item.source_ref


def test_repository_rejects_finalize_result_for_different_work_item(tmp_path):
    store, repository, _, item, registry, _ = _event_work(tmp_path)
    other = WorkItem.create(
        job_id=item.job_id,
        source_ref=item.source_ref,
        processor=item.processor,
        processor_version=item.processor_version,
    )
    other = store.create_work_item(other, source_registry=registry)
    other = store.begin_work_item(other.public_id)
    mismatched = FinalizeResult.create(
        work_item=item,
        output={"wrong": True},
    )

    with pytest.raises(ValueError, match="work_item_id does not match"):
        repository.commit_final_result(
            other.public_id,
            mismatched,
            source_registry=registry,
        )

    assert store.get_work_item(other.public_id).status == "running"
    assert repository.get_by_work_item(other.public_id) is None
