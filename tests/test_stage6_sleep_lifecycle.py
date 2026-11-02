from datetime import datetime, timezone
from uuid import uuid4

import pytest

from anima.agent.executor import build_sandbox_registry
from anima.execution.contracts import ActionSpec, ExecutionAction
from anima.execution.sandbox import SandboxExecutor
from anima.execution.store import ExecutionStore
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
from anima.sleep.task_lifecycle import TaskSleepCoordinator, TaskSleepLinkStore
from anima.tasks.store import TaskStore
from tests.harness import AnimaTestHarness


class Stage6SleepProcessor(SleepProcessor):
    def __init__(self):
        super().__init__(
            ProcessorDescriptor(
                name="stage6-sleep-test",
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


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _attach_sleep_runtime(anima, root, *, source):
    sleep_store = SleepStore(root / "sleep.db")
    source_registry = SourceRegistry().register(
        "asset",
        lambda source_id: source_id == source.source_id,
    )
    processors = ProcessorRegistry().register(Stage6SleepProcessor())
    derived = DerivedResultRepository(sleep_store)
    executor = SleepChunkExecutor(
        sleep_store=sleep_store,
        processor_registry=processors,
        source_registry=source_registry,
        derived_results=derived,
    )
    operations = RecoveryOperationRepository(
        sleep_store,
        derived_results=derived,
    )
    recovery = SleepRecoveryCoordinator(
        operations=operations,
        effects=CognitiveEffectStore(anima.memory_store),
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
    return sleep_store, source_registry, sleep_runtime


def _environment(root, *, source=None, create_entities=True):
    anima = AnimaTestHarness(root)
    source = source or SourceRef("asset", f"asset_{uuid4()}")
    sleep_store, source_registry, sleep_runtime = _attach_sleep_runtime(
        anima,
        root,
        source=source,
    )
    tasks = TaskStore(root / "tasks.db")
    links = TaskSleepLinkStore(root / "task_sleep.db")
    executions = ExecutionStore(root / "execution.db")
    coordinator = TaskSleepCoordinator(
        runtime=anima.runtime,
        task_store=tasks,
        link_store=links,
        execution_store=executions,
        trace=anima.trace,
    )

    goal = task = job = item = None
    if create_entities:
        goal = anima.internal_state.goals.create_goal(
            source="test",
            priority=1.0,
            description="continue work across Sleep",
            success_criterion="Task remains resumable",
            reason="Stage 6.5 test",
            timestamp=_now(),
        )
        task = tasks.create_task(
            source="test",
            description="persistent work unit",
            reason="Stage 6.5 test",
            goal_id=goal["id"],
            timestamp=_now(),
        )
        task = tasks.transition_task(
            task.public_id,
            "active",
            reason="activate Stage 6.5 task",
            timestamp=_now(),
        )
        job = sleep_store.create_job()
        item = WorkItem.create(
            job_id=job["id"],
            source_ref=source,
            processor="stage6-sleep-test",
            processor_version="1",
        )
        item = sleep_store.create_work_item(
            item,
            source_registry=source_registry,
        )

    return {
        "anima": anima,
        "source": source,
        "sleep_store": sleep_store,
        "sleep_runtime": sleep_runtime,
        "source_registry": source_registry,
        "tasks": tasks,
        "links": links,
        "executions": executions,
        "coordinator": coordinator,
        "goal": goal,
        "task": task,
        "job": job,
        "item": item,
    }


def test_task_sleep_link_store_persists_association_and_phase(tmp_path):
    env = _environment(tmp_path)
    link = env["links"].create_link(
        task_id=env["task"].public_id,
        goal_id=env["goal"]["id"],
        sleep_job_id=env["job"]["id"],
        reason="test link",
    )
    link = env["links"].transition(
        link.public_id,
        "sleeping",
        reason="entered sleep",
    )

    reopened = TaskSleepLinkStore(tmp_path / "task_sleep.db")
    restored = reopened.get_active_for_task(env["task"].public_id)

    assert reopened.schema_version() == 1
    assert restored.public_id == link.public_id
    assert restored.goal_id == env["goal"]["id"]
    assert restored.sleep_job_id == env["job"]["id"]
    assert restored.status == "sleeping"


def test_active_task_checkpoint_wake_resume(tmp_path):
    env = _environment(tmp_path)
    turn = env["coordinator"].request_sleep(
        env["task"].public_id,
        env["job"]["id"],
    )

    assert turn.task_status == "interrupted"
    assert turn.goal_status == "active"
    assert turn.sleep_job_status == "running"
    assert turn.anima_status == "sleeping"
    assert turn.link.status == "sleeping"

    outcome = env["anima"].runtime.process_sleep_work(
        env["item"].public_id,
        ["alpha", "beta"],
        max_new_chunks=1,
    )
    assert outcome.status == "checkpointed"
    assert env["sleep_store"].get_job(env["job"]["id"])["status"] == "checkpointed"
    assert env["tasks"].get_task(env["task"].public_id).status == "interrupted"

    resumed = env["coordinator"].wake(env["task"].public_id)

    assert resumed.link.status == "resumed"
    assert resumed.task_status == "active"
    assert resumed.goal_status == "active"
    assert resumed.sleep_job_status == "interrupted"
    assert resumed.anima_status == "awake"
    assert [
        transition["to_status"]
        for transition in env["tasks"].list_transitions(env["task"].public_id)
    ] == ["queued", "active", "interrupted", "active"]


def test_sleep_is_blocked_at_unresolved_execution_boundary(tmp_path):
    env = _environment(tmp_path)
    registry = build_sandbox_registry()
    action = ExecutionAction.from_spec(
        ActionSpec(
            "WRITE_RESULT",
            "fs.write",
            "1",
            {"path": "result.txt", "content": "42"},
        ),
        registry=registry,
        persistent_task_id=env["task"].public_id,
        goal_id=env["goal"]["id"],
        created_at=_now(),
    )
    env["executions"].create_operation(action, registry=registry)

    with pytest.raises(RuntimeError, match="prepared/executing/uncertain"):
        env["coordinator"].request_sleep(
            env["task"].public_id,
            env["job"]["id"],
        )

    assert env["tasks"].get_task(env["task"].public_id).status == "active"
    assert env["sleep_store"].get_job(env["job"]["id"])["status"] == "queued"
    assert env["links"].get_active_for_task(env["task"].public_id) is None


def test_checkpointed_sleep_link_recovers_after_process_restart(tmp_path):
    env = _environment(tmp_path)
    env["coordinator"].request_sleep(
        env["task"].public_id,
        env["job"]["id"],
    )
    first = env["anima"].runtime.process_sleep_work(
        env["item"].public_id,
        ["alpha", "beta"],
        max_new_chunks=1,
    )
    assert first.status == "checkpointed"
    assert env["anima"].state.get()["status"] == "sleeping"

    restarted = _environment(
        tmp_path,
        source=env["source"],
        create_entities=False,
    )
    recovery = restarted["coordinator"].recover()

    assert recovery["restored"] == 1
    link = restarted["links"].get_active_for_task(env["task"].public_id)
    assert link.status == "sleeping"
    assert restarted["tasks"].get_task(env["task"].public_id).status == "interrupted"
    assert restarted["anima"].state.get()["status"] == "sleeping"

    completed = restarted["anima"].runtime.process_sleep_work(
        env["item"].public_id,
        ["alpha", "beta"],
        max_new_chunks=None,
    )
    assert completed.status == "completed"
    assert completed.resumed_from_sequence == 1
    assert completed.final_result["output"] == {"values": ["alpha", "beta"]}

    resumed = restarted["coordinator"].wake(env["task"].public_id)
    assert resumed.link.status == "resumed"
    assert resumed.task_status == "active"
    assert resumed.sleep_job_status == "completed"
    assert resumed.anima_status == "awake"


def test_committed_keyed_side_effect_is_not_repeated_across_sleep_wake(tmp_path):
    env = _environment(tmp_path)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    registry = build_sandbox_registry()
    executor = SandboxExecutor(
        root=sandbox,
        registry=registry,
        store=env["executions"],
    )
    action = ExecutionAction.from_spec(
        ActionSpec(
            "WRITE_RESULT",
            "fs.write",
            "1",
            {"path": "result.txt", "content": "42"},
        ),
        registry=registry,
        persistent_task_id=env["task"].public_id,
        goal_id=env["goal"]["id"],
        created_at=_now(),
    )
    env["executions"].create_operation(action, registry=registry)
    first = executor.execute(action)
    assert first.status == "succeeded"

    env["coordinator"].request_sleep(
        env["task"].public_id,
        env["job"]["id"],
    )
    env["coordinator"].wake(env["task"].public_id)

    target = sandbox / "result.txt"
    target.write_text("external-change", encoding="utf-8")
    replay = executor.execute(action)

    assert replay.status == "succeeded"
    assert target.read_text(encoding="utf-8") == "external-change"
    assert env["executions"].get_operation(action.operation_id)["status"] == "succeeded"
