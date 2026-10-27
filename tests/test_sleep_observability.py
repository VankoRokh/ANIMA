from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from anima.runtime import Runtime
from anima.scenario import ScenarioRunner
from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.derived import DerivedResultRepository
from anima.sleep.execution import SleepChunkExecutor
from anima.sleep.observability import SleepObservability, SleepResourceBudget
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


class MutableClock:
    def __init__(self):
        self.value = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class ObservableProcessor(SleepProcessor):
    def __init__(self):
        super().__init__(
            ProcessorDescriptor(
                name="observable-test",
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


def _fixture(tmp_path, *, budget=None, work_specs=None):
    anima = AnimaTestHarness(tmp_path)
    sleep_store = SleepStore(tmp_path / "sleep.db")
    sources = set()
    source_registry = SourceRegistry().register(
        "asset",
        lambda source_id: source_id in sources,
    )
    derived_results = DerivedResultRepository(sleep_store)
    executor = SleepChunkExecutor(
        sleep_store=sleep_store,
        processor_registry=ProcessorRegistry().register(ObservableProcessor()),
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
    clock = MutableClock()
    observability = SleepObservability(
        sleep_store=sleep_store,
        memory_store=anima.memory_store,
        now=clock,
        resource_probe=lambda: {
            "cpu_user_seconds": 1.25,
            "cpu_system_seconds": 0.5,
            "max_rss_kb": 12345,
        },
    )
    sleep_runtime = SleepRuntimeIntegration(
        sleep_store=sleep_store,
        executor=executor,
        recovery=recovery,
        observability=observability,
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

    job = sleep_store.create_job()
    items = []
    for spec in work_specs or [{"priority": 3, "cost_hint": "normal"}]:
        source = SourceRef("asset", f"asset_{uuid4()}")
        sources.add(source.source_id)
        item = WorkItem.create(
            job_id=job["id"],
            source_ref=source,
            processor="observable-test",
            processor_version="1",
            priority=spec.get("priority", 0),
            cost_hint=spec.get("cost_hint", "normal"),
        )
        items.append(
            sleep_store.create_work_item(
                item,
                source_registry=source_registry,
            )
        )

    anima.runtime.activate_sleep_job(job["id"], budget=budget)
    return {
        "anima": anima,
        "sleep_store": sleep_store,
        "sleep_runtime": sleep_runtime,
        "observability": observability,
        "clock": clock,
        "job": job,
        "items": items,
    }


def _enter_sleep(fixture):
    fixture["anima"].runtime.wake()
    fixture["anima"].runtime.sleep()


def test_resource_budget_validation():
    assert SleepResourceBudget().to_dict() == {
        "max_committed_chunks": None,
        "max_cost_units": None,
        "max_elapsed_seconds": None,
    }
    with pytest.raises(ValueError, match="max_committed_chunks"):
        SleepResourceBudget(max_committed_chunks=-1)
    with pytest.raises(ValueError, match="max_cost_units"):
        SleepResourceBudget(max_cost_units=True)
    with pytest.raises(ValueError, match="max_elapsed_seconds"):
        SleepResourceBudget(max_elapsed_seconds=-0.1)


def test_snapshot_exposes_queue_choice_progress_budget_and_resources(tmp_path):
    fixture = _fixture(
        tmp_path,
        budget=SleepResourceBudget(
            max_committed_chunks=5,
            max_cost_units=6,
            max_elapsed_seconds=30,
        ),
        work_specs=[
            {"priority": 9, "cost_hint": "cheap"},
            {"priority": 2, "cost_hint": "expensive"},
        ],
    )
    snapshot = fixture["anima"].snapshot()["sleep"]

    assert snapshot["active_job_id"] == fixture["job"]["id"]
    assert snapshot["job_status"] == "queued"
    assert snapshot["queue"]["total"] == 2
    assert snapshot["queue"]["processed"] == 0
    assert snapshot["queue"]["skipped"] == 0
    assert snapshot["queue"]["failed"] == 0
    assert snapshot["queue"]["selected_cost_units"] == 5
    assert snapshot["current_work_item"]["priority"] == 9
    assert snapshot["current_work_item"]["cost_hint"] == "cheap"
    assert snapshot["current_work_item"]["selection_reason"]["priority"] == 9
    assert snapshot["current_chunk"] == {
        "last_committed_sequence": None,
        "next_sequence": 0,
    }
    assert snapshot["budget"]["limits"] == {
        "max_committed_chunks": 5,
        "max_cost_units": 6,
        "max_elapsed_seconds": 30,
    }
    assert snapshot["budget"]["usage"]["committed_chunks"] == 0
    assert snapshot["budget"]["usage"]["cost_units"] == 0
    assert snapshot["metrics"]["cpu_user_seconds"] == 1.25
    assert snapshot["metrics"]["cpu_system_seconds"] == 0.5
    assert snapshot["metrics"]["max_rss_kb"] == 12345
    assert snapshot["metrics"]["storage_bytes"]["sleep_db"] > 0
    assert snapshot["metrics"]["storage_bytes"]["memory_db"] > 0


def test_chunk_budget_pauses_at_safe_boundary_and_blocks_extra_work(tmp_path):
    fixture = _fixture(
        tmp_path,
        budget=SleepResourceBudget(max_committed_chunks=1),
    )
    _enter_sleep(fixture)
    item = fixture["items"][0]

    first = fixture["anima"].runtime.process_sleep_work(
        item.public_id,
        ["alpha", "beta"],
        max_new_chunks=None,
    )

    assert first.status == "checkpointed"
    assert first.processed_chunks == 1
    assert first.stop_reason == "budget:committed_chunks"
    assert [
        checkpoint["sequence"]
        for checkpoint in fixture["sleep_store"].list_checkpoints(item.public_id)
    ] == [0]
    assert fixture["sleep_store"].get_job(fixture["job"]["id"])["status"] == "checkpointed"

    blocked = fixture["anima"].runtime.process_sleep_work(
        item.public_id,
        ["alpha", "beta"],
        max_new_chunks=None,
    )
    assert blocked.processed_chunks == 0
    assert blocked.stop_reason == "budget:committed_chunks"
    assert fixture["sleep_store"].get_work_item(item.public_id).attempts == 1

    snapshot = fixture["anima"].snapshot()["sleep"]
    assert snapshot["budget"]["exhausted"] is True
    assert snapshot["budget"]["reason"] == "budget:committed_chunks"
    assert snapshot["budget"]["remaining"]["committed_chunks"] == 0


def test_exact_chunk_budget_finishes_when_stream_ends_at_limit(tmp_path):
    fixture = _fixture(
        tmp_path,
        budget=SleepResourceBudget(max_committed_chunks=1),
    )
    _enter_sleep(fixture)
    item = fixture["items"][0]

    outcome = fixture["anima"].runtime.process_sleep_work(
        item.public_id,
        ["only"],
        max_new_chunks=None,
    )

    assert outcome.status == "completed"
    assert outcome.stop_reason is None
    assert outcome.final_result.output == {"values": ["only"]}
    assert fixture["sleep_store"].get_job(fixture["job"]["id"])["status"] == "completed"


def test_cost_budget_blocks_new_work_item_but_does_not_double_charge_resume(tmp_path):
    fixture = _fixture(
        tmp_path,
        budget=SleepResourceBudget(max_cost_units=2),
        work_specs=[
            {"priority": 5, "cost_hint": "normal"},
            {"priority": 4, "cost_hint": "normal"},
        ],
    )
    _enter_sleep(fixture)
    first, second = fixture["items"]

    checkpointed = fixture["anima"].runtime.process_sleep_work(
        first.public_id,
        ["a", "b"],
        max_new_chunks=1,
    )
    assert checkpointed.status == "checkpointed"
    assert checkpointed.stop_reason == "chunk_limit"

    completed = fixture["anima"].runtime.process_sleep_work(
        first.public_id,
        ["a", "b"],
        max_new_chunks=None,
    )
    assert completed.status == "completed"
    assert fixture["anima"].snapshot()["sleep"]["budget"]["usage"]["cost_units"] == 2

    blocked = fixture["anima"].runtime.process_sleep_work(
        second.public_id,
        ["second"],
        max_new_chunks=None,
    )
    assert blocked.processed_chunks == 0
    assert blocked.stop_reason == "budget:cost_units"
    assert fixture["sleep_store"].get_work_item(second.public_id).status == "queued"


def test_elapsed_budget_is_checked_at_safe_runtime_boundary(tmp_path):
    fixture = _fixture(
        tmp_path,
        budget=SleepResourceBudget(max_elapsed_seconds=10),
    )
    _enter_sleep(fixture)
    fixture["clock"].advance(10)
    item = fixture["items"][0]

    outcome = fixture["anima"].runtime.process_sleep_work(
        item.public_id,
        ["late"],
        max_new_chunks=None,
    )

    assert outcome.processed_chunks == 0
    assert outcome.stop_reason == "budget:elapsed_seconds"
    assert fixture["sleep_store"].list_checkpoints(item.public_id) == []
    snapshot = fixture["anima"].snapshot()["sleep"]
    assert snapshot["metrics"]["elapsed_seconds"] == 10.0
    assert snapshot["budget"]["remaining"]["elapsed_seconds"] == 0.0


def test_reconfigured_budget_clears_exhaustion_and_resumes(tmp_path):
    fixture = _fixture(
        tmp_path,
        budget=SleepResourceBudget(max_committed_chunks=1),
    )
    _enter_sleep(fixture)
    item = fixture["items"][0]

    stopped = fixture["anima"].runtime.process_sleep_work(
        item.public_id,
        ["a", "b"],
        max_new_chunks=None,
    )
    assert stopped.stop_reason == "budget:committed_chunks"

    fixture["anima"].runtime.configure_sleep_budget(
        fixture["job"]["id"],
        SleepResourceBudget(max_committed_chunks=2),
    )
    resumed = fixture["anima"].runtime.process_sleep_work(
        item.public_id,
        ["a", "b"],
        max_new_chunks=None,
    )

    assert resumed.status == "completed"
    assert resumed.resumed_from_sequence == 1
    assert resumed.final_result.output == {"values": ["a", "b"]}
    assert fixture["anima"].snapshot()["sleep"]["budget"]["exhausted"] is False


def test_budget_and_elapsed_state_survive_observability_reopen(tmp_path):
    fixture = _fixture(
        tmp_path,
        budget=SleepResourceBudget(
            max_committed_chunks=7,
            max_cost_units=4,
            max_elapsed_seconds=60,
        ),
    )
    fixture["clock"].advance(15)

    reopened_store = SleepStore(tmp_path / "sleep.db")
    reopened = SleepObservability(
        sleep_store=reopened_store,
        memory_store=fixture["anima"].memory_store,
        now=fixture["clock"],
        resource_probe=lambda: {
            "cpu_user_seconds": 2.0,
            "cpu_system_seconds": 1.0,
            "max_rss_kb": 20000,
        },
    )
    snapshot = reopened.snapshot(fixture["job"]["id"])

    assert reopened.schema_version() == 1
    assert snapshot["budget"]["limits"] == {
        "max_committed_chunks": 7,
        "max_cost_units": 4,
        "max_elapsed_seconds": 60.0,
    }
    assert snapshot["metrics"]["elapsed_seconds"] == 15.0
    assert snapshot["metrics"]["max_rss_kb"] == 20000


def test_headless_scenario_exposes_budget_stop_reason_and_snapshot(tmp_path):
    fixture = _fixture(tmp_path)
    anima = fixture["anima"]
    job = fixture["job"]
    item = fixture["items"][0]

    anima.runtime.configure_sleep_budget(
        job["id"],
        SleepResourceBudget(max_committed_chunks=1),
    )
    results = anima.run_scenario(
        [
            {"action": "wake"},
            {"action": "sleep"},
            {
                "action": "sleep_process",
                "work_item_id": item.public_id,
                "chunks": ["a", "b"],
                "max_new_chunks": None,
            },
            {"action": "snapshot"},
        ]
    )

    assert results[2]["stop_reason"] == "budget:committed_chunks"
    sleep_snapshot = results[3]["snapshot"]["sleep"]
    assert sleep_snapshot["queue"]["by_status"]["checkpointed"] == 1
    assert sleep_snapshot["current_chunk"]["next_sequence"] == 1
    assert sleep_snapshot["budget"]["reason"] == "budget:committed_chunks"
    assert any(
        "budget exhausted" in entry["message"]
        for entry in fixture["anima"].trace.entries()
    )
