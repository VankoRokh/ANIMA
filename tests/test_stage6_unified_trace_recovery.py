from datetime import datetime, timezone
from uuid import uuid4

from anima.agent.executor import build_sandbox_registry
from anima.cognition.action_choice import ActionChoiceCoordinator
from anima.cognition.coordinator import CognitiveCoordinator
from anima.cognition.proposals import CognitiveDispatcher, CognitiveProposal
from anima.cognition.recovery import Stage6RecoveryCoordinator
from anima.cognition.routing import CognitiveDestination, CognitiveRouter
from anima.diagnostics.stage6 import Stage6TraceRecorder
from anima.diagnostics.unified_trace import UnifiedTrace, UnifiedTraceStore
from anima.execution.contracts import ActionSpec, ExecutionAction, VerificationSpec
from anima.execution.coordinator import ExecutionCoordinator
from anima.execution.sandbox import SandboxExecutor
from anima.execution.store import ExecutionStore
from anima.execution.verification import (
    DeterministicGoalVerifier,
    FILE_CONTENT_EQUALS,
    FileObserver,
    GoalVerificationBridge,
)
from anima.internal_state.choice_engine import Candidate
from anima.ir import CanonicalTask, Evidence
from anima.resolution import resolve
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
from anima.sleep.runtime_integration import SleepRuntimeIntegration
from anima.sleep.store import SleepStore
from anima.sleep.task_lifecycle import TaskSleepCoordinator, TaskSleepLinkStore
from anima.tasks.store import TaskStore
from tests.harness import AnimaTestHarness


class _RespondBackend:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        return CognitiveProposal.respond(self.text)


class _TraceSleepProcessor(SleepProcessor):
    def __init__(self):
        super().__init__(
            ProcessorDescriptor(
                name="stage6-trace-sleep-test",
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


def _attach_sleep_runtime(anima, root, *, trace, source=None, with_work=False):
    sleep_store = SleepStore(root / "sleep.db")
    source_registry = SourceRegistry()
    processors = ProcessorRegistry()
    item = None
    job = None

    if with_work:
        source = source or SourceRef("asset", f"asset_{uuid4()}")
        source_registry.register(
            "asset",
            lambda source_id: source_id == source.source_id,
        )
        processors.register(_TraceSleepProcessor())

    derived = DerivedResultRepository(sleep_store)
    executor = SleepChunkExecutor(
        sleep_store=sleep_store,
        processor_registry=processors,
        source_registry=source_registry,
        derived_results=derived,
    )
    sleep_runtime = SleepRuntimeIntegration(
        sleep_store=sleep_store,
        executor=executor,
        trace=trace,
    )
    anima.runtime = Runtime(
        anima=anima.state,
        identity=anima.identity,
        event_bus=anima.event_bus,
        event_log=anima.event_log,
        memory=anima.memory,
        memory_processor=anima.memory_processor,
        event_processing=anima.event_processing,
        trace=trace,
        metrics=anima.metrics,
        internal_state=anima.internal_state,
        sleep_runtime=sleep_runtime,
    )
    anima.scenario_runner = ScenarioRunner(anima.runtime)

    if with_work:
        job = sleep_store.create_job()
        item = WorkItem.create(
            job_id=job["id"],
            source_ref=source,
            processor="stage6-trace-sleep-test",
            processor_version="1",
        )
        item = sleep_store.create_work_item(
            item,
            source_registry=source_registry,
        )

    return {
        "sleep_store": sleep_store,
        "sleep_runtime": sleep_runtime,
        "source": source,
        "job": job,
        "item": item,
    }


def _base_environment(root, *, trace, with_sleep_work=False, create_entities=True):
    anima = AnimaTestHarness(root)
    sleep = _attach_sleep_runtime(
        anima,
        root,
        trace=trace,
        with_work=with_sleep_work,
    )
    tasks = TaskStore(root / "tasks.db")
    executions = ExecutionStore(root / "execution.db")
    links = TaskSleepLinkStore(root / "task_sleep.db")
    sleep_coordinator = TaskSleepCoordinator(
        runtime=anima.runtime,
        task_store=tasks,
        link_store=links,
        execution_store=executions,
        trace=trace,
    )

    goal = task = None
    if create_entities:
        goal = anima.internal_state.goals.create_goal(
            source="test",
            priority=1.0,
            description="produce verified Stage 6 result",
            success_criterion="result.txt contains 42",
            reason="Stage 6.6 test",
            timestamp=_now(),
        )
        task = tasks.create_task(
            source="test",
            description="persistent Stage 6.6 task",
            reason="Stage 6.6 test",
            goal_id=goal["id"],
            timestamp=_now(),
        )
        task = tasks.transition_task(
            task.public_id,
            "active",
            reason="activate Stage 6.6 task",
            timestamp=_now(),
        )

    return {
        "anima": anima,
        "tasks": tasks,
        "executions": executions,
        "links": links,
        "sleep_coordinator": sleep_coordinator,
        "goal": goal,
        "task": task,
        **sleep,
    }


def _conflict_task():
    observed = _now()
    return CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation="RESOLVE_CONFLICT",
        subject="device",
        predicate="state",
        evidence=(
            Evidence(
                "ev_a",
                "A",
                subject="device",
                predicate="state",
                provenance=("mem_alpha",),
                confidence=0.8,
                observed_at=observed,
            ),
            Evidence(
                "ev_b",
                "B",
                subject="device",
                predicate="state",
                provenance=("mem_beta",),
                confidence=0.9,
                observed_at=observed,
            ),
        ),
        output_contract="text",
    )


def _choice_task():
    return CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation="CHOOSE_ACTION",
        candidates=("WRITE_RESULT", "READ_INPUT"),
        output_contract="candidate",
    )


def test_one_persistent_trace_covers_stage6_causal_path_and_survives_reopen(tmp_path):
    trace_store = UnifiedTraceStore(tmp_path / "trace.db")
    trace = UnifiedTrace(trace_store)
    recorder = Stage6TraceRecorder(trace)
    env = _base_environment(
        tmp_path,
        trace=trace,
        with_sleep_work=True,
    )
    task = env["task"]
    goal = env["goal"]

    fast = _RespondBackend("fast")
    deep = _RespondBackend("deep")
    coordinator = CognitiveCoordinator(task_store=env["tasks"], trace=trace)
    router = CognitiveRouter(trace=trace, enable_action_choice=True)
    dispatcher = CognitiveDispatcher(
        fast_backend=fast,
        deep_backend=deep,
        trace=trace,
    )

    with recorder.task_scope(task, goal_status="active") as trace_id:
        conflict = _conflict_task()
        coordinated = coordinator.process(task.public_id, conflict)
        recorder.resolution(coordinated)
        decision = router.route(conflict, coordinated.resolution)
        assert decision.destination == CognitiveDestination.DEEP
        recorder.route(conflict, decision)
        dispatched = dispatcher.dispatch(
            decision,
            persistent_task_id=task.public_id,
            task=conflict,
            resolution=coordinated.resolution,
        )
        assert dispatched.accepted is True
        recorder.dispatch(dispatched)

        choice_task = _choice_task()
        choice_resolution = resolve(choice_task)
        choice_route = router.route(choice_task, choice_resolution)
        assert choice_route.destination == CognitiveDestination.CHOICE
        recorder.route(choice_task, choice_route)
        choice = ActionChoiceCoordinator(
            task_store=env["tasks"],
            choice_engine=env["anima"].internal_state.choice_engine,
            trace=trace,
        ).choose(
            task.public_id,
            choice_task,
            choice_resolution,
            [
                Candidate("WRITE_RESULT", 0.80),
                Candidate("READ_INPUT", 0.20, information_gain=1.0),
            ],
        )
        assert choice.selected_candidate_id == "WRITE_RESULT"
        recorder.choice(choice)

        entered = env["sleep_coordinator"].request_sleep(
            task.public_id,
            env["job"]["id"],
        )
        recorder.sleep(entered, event="entered")
        sleep_result = env["anima"].runtime.process_sleep_work(
            env["item"].public_id,
            ["sleep-evidence"],
            max_new_chunks=None,
        )
        assert sleep_result.status == "completed"
        woke = env["sleep_coordinator"].wake(task.public_id)
        assert woke.link.status == "closed"
        recorder.sleep(woke, event="wake")

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "input.txt").write_text("input", encoding="utf-8")
        registry = build_sandbox_registry()
        executor = SandboxExecutor(
            root=sandbox,
            registry=registry,
            store=env["executions"],
        )
        execution = ExecutionCoordinator(
            task_store=env["tasks"],
            goal_store=env["anima"].internal_state.goals,
            execution_store=env["executions"],
            registry=registry,
            executor=executor,
            trace=trace,
        ).prepare_and_execute(
            choice,
            (
                ActionSpec(
                    "WRITE_RESULT",
                    "fs.write",
                    "1",
                    {"path": "result.txt", "content": "42"},
                ),
                ActionSpec(
                    "READ_INPUT",
                    "fs.read",
                    "1",
                    {"path": "input.txt"},
                ),
            ),
            created_at=_now(),
        )
        assert execution.receipt.status == "succeeded"
        recorder.execution(execution)

        spec = VerificationSpec.create(
            goal_id=goal["id"],
            criterion_kind=FILE_CONTENT_EQUALS,
            parameters={"path": "result.txt", "expected": "42"},
        )
        observation = FileObserver(sandbox).observe(
            execution.action,
            execution.receipt,
            path="result.txt",
        )
        recorder.observation(execution.action, observation)
        verification = DeterministicGoalVerifier().verify(
            spec,
            action=execution.action,
            observations=(observation,),
        )
        recorder.verification(execution.action, verification)
        applied = GoalVerificationBridge(env["anima"].internal_state).apply(
            spec=spec,
            action=execution.action,
            result=verification,
            observations=(observation,),
        )
        assert applied.progress_result.goal["status"] == "completed"

        completed_task = env["tasks"].transition_task(
            task.public_id,
            "completed",
            reason="verified Goal completed",
            source_id=verification.public_id,
            timestamp=_now(),
        )

    recorder.finish(
        trace_id,
        task=completed_task,
        goal_status="completed",
        success=True,
        reason="verified Stage 6 task completed",
    )

    reopened = UnifiedTraceStore(tmp_path / "trace.db")
    stored_trace = reopened.get_trace(trace_id)
    events = reopened.list_events(trace_id)

    assert reopened.schema_version() == 1
    assert stored_trace.status == "completed"
    assert stored_trace.task_id == task.public_id
    assert stored_trace.goal_id == goal["id"]
    assert stored_trace.outcome["task_status"] == "completed"
    assert stored_trace.outcome["goal_status"] == "completed"
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))

    structured = {(event.component, event.event): event for event in events}
    assert ("coordinator", "resolution") in structured
    assert ("cognitive_router", "route") in structured
    assert ("cognitive_dispatch", "completion") in structured
    assert ("action_choice", "selected") in structured
    assert ("task_sleep", "entered") in structured
    assert ("task_sleep", "wake") in structured
    assert ("execution", "receipt") in structured
    assert ("observation", "observed") in structured
    assert ("verification", "result") in structured
    assert ("stage6", "outcome") in structured

    context = structured[("cognitive_dispatch", "completion")].payload["context"]
    assert context["consumer"] == "DEEP"
    assert context["evidence_count"] == 2
    assert context["provenance_ref_count"] == 2
    choice_payload = structured[("action_choice", "selected")].payload
    assert choice_payload["evaluations"]
    assert all(item["modifiers"] for item in choice_payload["evaluations"])

    # Existing component diagnostics were persisted under the same causal trace too.
    assert any(event.component == "cognitive_dispatch" and event.event == "call" for event in events)
    assert any(event.component == "cognitive_dispatch" and event.event == "proposal" for event in events)


def test_restart_recovery_marks_executing_uncertain_then_reconciles_without_rewrite(tmp_path):
    first_store = UnifiedTraceStore(tmp_path / "trace.db")
    first_trace = UnifiedTrace(first_store)
    env = _base_environment(tmp_path, trace=first_trace)
    task = env["task"]
    goal = env["goal"]
    trace_id = first_trace.resume_or_begin(task_id=task.public_id, goal_id=goal["id"])
    with first_trace.bind(trace_id):
        first_trace.record_event(
            component="stage6",
            event="before_restart",
            message="stage6: simulated crash after side effect before operation commit",
            payload={"crash_point": "after_effect_before_commit"},
        )

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    registry = build_sandbox_registry()
    action = ExecutionAction.from_spec(
        ActionSpec(
            "WRITE_RESULT",
            "fs.write",
            "1",
            {"path": "result.txt", "content": "42"},
        ),
        registry=registry,
        persistent_task_id=task.public_id,
        goal_id=goal["id"],
        created_at=_now(),
    )
    env["executions"].create_operation(action, registry=registry)
    env["executions"].transition_operation(
        action.operation_id,
        "executing",
        reason="simulated process died after effect",
    )
    target = sandbox / "result.txt"
    target.write_text("42", encoding="utf-8")
    before = target.stat().st_mtime_ns

    # Reconstruct the system from persistent stores, including trace.db.
    restarted_trace_store = UnifiedTraceStore(tmp_path / "trace.db")
    restarted_trace = UnifiedTrace(restarted_trace_store)
    restarted = _base_environment(
        tmp_path,
        trace=restarted_trace,
        create_entities=False,
    )
    recovery = Stage6RecoveryCoordinator(
        task_store=restarted["tasks"],
        internal_state=restarted["anima"].internal_state,
        execution_store=restarted["executions"],
        sleep_coordinator=restarted["sleep_coordinator"],
        trace=restarted_trace,
    )
    turns = recovery.recover()

    assert len(turns) == 1
    turn = turns[0]
    assert turn.trace_id == trace_id
    assert turn.task_id == task.public_id
    assert turn.goal_id == goal["id"]
    assert turn.executing_to_uncertain == 1
    assert turn.uncertain_operations == 1
    assert turn.succeeded_operations == 0
    assert restarted["executions"].get_operation(action.operation_id)["status"] == "uncertain"

    executor = SandboxExecutor(
        root=sandbox,
        registry=registry,
        store=restarted["executions"],
    )
    receipt = executor.execute(action)

    assert receipt.status == "succeeded"
    assert restarted["executions"].get_operation(action.operation_id)["status"] == "succeeded"
    assert target.read_text(encoding="utf-8") == "42"
    assert target.stat().st_mtime_ns == before

    events = restarted_trace_store.list_events(trace_id)
    assert events[0].event == "before_restart"
    assert any(event.event == "execution_normalized" for event in events)
    assert any(event.component == "recovery" and event.event == "normalized" for event in events)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


def test_committed_succeeded_operation_is_never_reset_by_stage6_recovery(tmp_path):
    trace_store = UnifiedTraceStore(tmp_path / "trace.db")
    trace = UnifiedTrace(trace_store)
    env = _base_environment(tmp_path, trace=trace)
    task = env["task"]
    goal = env["goal"]
    trace_id = trace.resume_or_begin(task_id=task.public_id, goal_id=goal["id"])

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    registry = build_sandbox_registry()
    action = ExecutionAction.from_spec(
        ActionSpec(
            "WRITE_RESULT",
            "fs.write",
            "1",
            {"path": "result.txt", "content": "42"},
        ),
        registry=registry,
        persistent_task_id=task.public_id,
        goal_id=goal["id"],
        created_at=_now(),
    )
    env["executions"].create_operation(action, registry=registry)
    executor = SandboxExecutor(
        root=sandbox,
        registry=registry,
        store=env["executions"],
    )
    assert executor.execute(action).status == "succeeded"

    recovery = Stage6RecoveryCoordinator(
        task_store=env["tasks"],
        internal_state=env["anima"].internal_state,
        execution_store=env["executions"],
        sleep_coordinator=env["sleep_coordinator"],
        trace=trace,
    )
    turn = recovery.recover()[0]

    assert turn.trace_id == trace_id
    assert turn.executing_to_uncertain == 0
    assert turn.succeeded_operations == 1
    assert env["executions"].get_operation(action.operation_id)["status"] == "succeeded"
