from uuid import uuid4

import pytest

from anima.runtime import Runtime
from anima.scenario import ScenarioRunner
from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.derived import DerivedResultRepository
from anima.sleep.execution import SleepChunkExecutor
from anima.sleep.processors import (
    ChunkResult,
    FinalizeResult,
    ProcessorDescriptor,
    ProcessorRegistry,
    SleepProcessor,
)
from anima.sleep.recovery import (
    CognitiveEffectStore,
    RecoveryOperationRepository,
    SleepRecoveryCoordinator,
)
from anima.sleep.runtime_integration import SleepRuntimeIntegration
from anima.sleep.store import SleepStore
from tests.harness import AnimaTestHarness


class RuntimeSleepProcessor(SleepProcessor):
    def __init__(self):
        super().__init__(
            ProcessorDescriptor(
                name="runtime-sleep-test",
                version="1",
                work_kind="CONSOLIDATE",
                source_kinds=frozenset({"asset"}),
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


def _configured_harness(tmp_path, *, create_work=True):
    anima = AnimaTestHarness(tmp_path)
    sleep_store = SleepStore(tmp_path / "sleep.db")

    source = SourceRef("asset", f"asset_{uuid4()}")
    source_registry = SourceRegistry().register(
        "asset",
        lambda source_id: source_id == source.source_id,
    )
    processor_registry = ProcessorRegistry().register(RuntimeSleepProcessor())
    derived_results = DerivedResultRepository(sleep_store)
    executor = SleepChunkExecutor(
        sleep_store=sleep_store,
        processor_registry=processor_registry,
        source_registry=source_registry,
        derived_results=derived_results,
    )
    operations = RecoveryOperationRepository(
        sleep_store,
        derived_results=derived_results,
    )
    effects = CognitiveEffectStore(anima.memory_store)
    recovery = SleepRecoveryCoordinator(
        operations=operations,
        effects=effects,
    )
    sleep_runtime = SleepRuntimeIntegration(
        sleep_store=sleep_store,
        executor=executor,
        recovery=recovery,
        trace=anima.trace,
    )

    anima.runtime = Runtime(
        anima=anima.state,
        identity=anima.identity,
        event_bus=anima.event_bus,
        event_log=anima.event_log,
        memory=anima.memory,
        memory_processor=anima.memory_processor,
        event_processing=anima.event_processing,
        trace=anima.trace,
        metrics=anima.metrics,
        internal_state=anima.internal_state,
        sleep_runtime=sleep_runtime,
    )
    anima.scenario_runner = ScenarioRunner(anima.runtime)

    job = None
    item = None
    if create_work:
        job = sleep_store.create_job()
        item = WorkItem.create(
            job_id=job["id"],
            source_ref=source,
            processor="runtime-sleep-test",
            processor_version="1",
        )
        item = sleep_store.create_work_item(
            item,
            source_registry=source_registry,
        )

    return {
        "anima": anima,
        "sleep_store": sleep_store,
        "sleep_runtime": sleep_runtime,
        "recovery": recovery,
        "derived_results": derived_results,
        "source_registry": source_registry,
        "source": source,
        "job": job,
        "item": item,
    }


def test_headless_wake_sleep_checkpoint_wake_resume_complete_wake(tmp_path):
    fixture = _configured_harness(tmp_path)
    anima = fixture["anima"]
    job = fixture["job"]
    item = fixture["item"]

    results = anima.run_scenario(
        [
            {"action": "wake"},
            {"action": "sleep_job_activate", "job_id": job["id"]},
            {"action": "sleep"},
            {
                "action": "sleep_process",
                "work_item_id": item.public_id,
                "chunks": ["alpha", "beta"],
                "max_new_chunks": 1,
            },
            {"action": "snapshot"},
            {"action": "wake"},
            {"action": "snapshot"},
            {"action": "sleep"},
            {
                "action": "sleep_process",
                "work_item_id": item.public_id,
                "chunks": ["alpha", "beta"],
                "max_new_chunks": None,
            },
            {"action": "snapshot"},
            {"action": "wake"},
            {"action": "snapshot"},
        ]
    )

    first_process = results[3]
    sleeping_checkpoint = results[4]["snapshot"]
    awake_interrupted = results[6]["snapshot"]
    completed = results[8]
    sleeping_completed = results[9]["snapshot"]
    final = results[11]["snapshot"]

    assert first_process["status"] == "checkpointed"
    assert first_process["processed_chunks"] == 1
    assert first_process["final_result"] is None
    assert sleeping_checkpoint["state"]["status"] == "sleeping"
    assert sleeping_checkpoint["sleep"]["job_status"] == "checkpointed"
    assert sleeping_checkpoint["sleep"]["work_items"][0]["status"] == "checkpointed"

    assert awake_interrupted["state"]["status"] == "awake"
    assert awake_interrupted["sleep"]["job_status"] == "interrupted"
    assert awake_interrupted["sleep"]["work_items"][0]["status"] == "checkpointed"

    assert completed["status"] == "completed"
    assert completed["resumed_from_sequence"] == 1
    assert completed["processed_chunks"] == 1
    assert completed["final_result"]["authority"] == "derived"
    assert completed["final_result"]["output"] == {
        "values": ["alpha", "beta"]
    }
    assert sleeping_completed["state"]["status"] == "sleeping"
    assert sleeping_completed["sleep"]["job_status"] == "completed"

    assert final["state"]["status"] == "awake"
    assert final["sleep"] == {
        "active_job_id": None,
        "job_status": None,
        "work_items": [],
    }
    assert final["state"]["session"] == 3

    assert [
        transition["to_status"]
        for transition in fixture["sleep_store"].list_transitions(job["id"])
    ] == [
        "queued",
        "running",
        "checkpointed",
        "interrupted",
        "running",
        "completed",
    ]
    assert [
        checkpoint["sequence"]
        for checkpoint in fixture["sleep_store"].list_checkpoints(item.public_id)
    ] == [0, 1]
    assert fixture["sleep_store"].get_work_item(item.public_id).attempts == 2


def test_ordinary_sleep_without_active_job_remains_separate_from_sleep_processing(tmp_path):
    fixture = _configured_harness(tmp_path, create_work=False)
    anima = fixture["anima"]

    anima.runtime.wake()
    anima.runtime.sleep()
    snapshot = anima.snapshot()

    assert snapshot["state"]["status"] == "sleeping"
    assert snapshot["sleep"] == {
        "active_job_id": None,
        "job_status": None,
        "work_items": [],
    }
    assert fixture["sleep_store"].list_jobs() == []


def test_sleep_work_cannot_run_while_anima_is_awake(tmp_path):
    fixture = _configured_harness(tmp_path)
    anima = fixture["anima"]
    job = fixture["job"]
    item = fixture["item"]

    anima.runtime.wake()
    anima.runtime.activate_sleep_job(job["id"])

    with pytest.raises(RuntimeError, match="only while ANIMA is sleeping"):
        anima.runtime.process_sleep_work(
            item.public_id,
            ["alpha"],
        )

    assert fixture["sleep_store"].get_job(job["id"])["status"] == "queued"
    assert fixture["sleep_store"].get_work_item(item.public_id).status == "queued"


def test_active_sleep_job_rejects_work_from_another_job(tmp_path):
    fixture = _configured_harness(tmp_path)
    anima = fixture["anima"]
    store = fixture["sleep_store"]
    source_registry = fixture["source_registry"]

    other_job = store.create_job()
    other_item = WorkItem.create(
        job_id=other_job["id"],
        source_ref=fixture["source"],
        processor="runtime-sleep-test",
        processor_version="1",
    )
    other_item = store.create_work_item(
        other_item,
        source_registry=source_registry,
    )

    anima.runtime.wake()
    anima.runtime.activate_sleep_job(fixture["job"]["id"])
    anima.runtime.sleep()

    with pytest.raises(ValueError, match="does not belong to the active SleepJob"):
        anima.runtime.process_sleep_work(
            other_item.public_id,
            ["wrong job"],
        )

    assert store.get_work_item(other_item.public_id).status == "queued"


def test_runtime_rejects_second_nonterminal_active_job(tmp_path):
    fixture = _configured_harness(tmp_path)
    store = fixture["sleep_store"]
    second_job = store.create_job()

    fixture["anima"].runtime.activate_sleep_job(fixture["job"]["id"])
    with pytest.raises(RuntimeError, match="Another SleepJob is already active"):
        fixture["anima"].runtime.activate_sleep_job(second_job["id"])


def test_wake_recovers_running_work_to_safe_checkpoint_boundary(tmp_path):
    fixture = _configured_harness(tmp_path)
    anima = fixture["anima"]
    store = fixture["sleep_store"]
    job = fixture["job"]
    item = fixture["item"]

    anima.runtime.wake()
    anima.runtime.activate_sleep_job(job["id"])
    anima.runtime.sleep()

    store.begin_work_item(item.public_id)
    checkpoint = store.commit_work_item_chunk(
        item.public_id,
        sequence=0,
        checkpoint={"values": ["alpha"]},
        local_result={"accepted": "alpha"},
    )
    assert store.get_work_item(item.public_id).status == "running"

    anima.runtime.wake()

    restored = store.get_work_item(item.public_id)
    assert restored.status == "checkpointed"
    assert restored.checkpoint_ref == checkpoint["id"]
    assert store.get_job(job["id"])["status"] == "interrupted"
    assert anima.snapshot()["state"]["status"] == "awake"


def test_runtime_recovery_normalizes_stale_running_job_before_wake(tmp_path):
    fixture = _configured_harness(tmp_path)
    store = fixture["sleep_store"]
    job = fixture["job"]
    item = fixture["item"]

    store.transition_job(job["id"], "running", reason="simulated process start")
    store.begin_work_item(item.public_id)

    summary = fixture["sleep_runtime"].recover()

    assert summary == {"receipts": 0, "work_items": 1, "jobs": 1}
    assert store.get_work_item(item.public_id).status == "queued"
    assert store.get_job(job["id"])["status"] == "interrupted"


def test_scenario_sleep_process_validates_chunk_list(tmp_path):
    fixture = _configured_harness(tmp_path)
    anima = fixture["anima"]
    job = fixture["job"]
    item = fixture["item"]

    anima.runtime.wake()
    anima.runtime.activate_sleep_job(job["id"])
    anima.runtime.sleep()

    with pytest.raises(ValueError, match="chunks must be a list"):
        anima.run_scenario(
            [
                {
                    "action": "sleep_process",
                    "work_item_id": item.public_id,
                    "chunks": "not-a-list",
                }
            ]
        )
