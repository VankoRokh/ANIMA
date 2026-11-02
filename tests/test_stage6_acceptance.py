from decimal import Decimal
from uuid import uuid4

import pytest

from anima.agent.executor import build_sandbox_registry
from anima.cognition.action_choice import ActionChoiceCoordinator
from anima.cognition.coordinator import CognitiveCoordinator, CoordinatorDirective
from anima.cognition.proposals import (
    CognitiveDispatcher,
    CognitiveProposal,
    ProposalKind,
)
from anima.cognition.recovery import Stage6RecoveryCoordinator
from anima.cognition.routing import CognitiveDestination, CognitiveRouter
from anima.diagnostics.stage6 import Stage6TraceRecorder
from anima.diagnostics.unified_trace import UnifiedTrace, UnifiedTraceStore
from anima.execution.contracts import ActionSpec, VerificationSpec
from anima.execution.coordinator import ExecutionCoordinator
from anima.execution.sandbox import SandboxExecutor
from anima.execution.verification import (
    DeterministicGoalVerifier,
    FILE_CONTENT_EQUALS,
    FileObserver,
    GoalVerificationBridge,
)
from anima.internal_state.choice_engine import Candidate
from anima.ir import CanonicalTask
from anima.resolution import resolve
from tests.test_stage6_sleep_lifecycle import _environment as _sleep_environment
from tests.test_stage6_unified_trace_recovery import (
    _RespondBackend,
    _base_environment,
    _choice_task,
    _conflict_task,
    _now,
)


class _StaticBackend:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        return self.proposal


class _FailingBackend:
    def __init__(self):
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        raise RuntimeError("controlled Stage 6 backend failure")


def _open_task(text="bounded FAST work"):
    return CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation="OPEN_TEXT",
        raw_input=text,
        output_contract="text",
    )


def _action_specs():
    return (
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
    )


def test_stage6_end_to_end_controlled_restart_completes_without_duplicate_effect(tmp_path):
    """Primary 6.8 acceptance: one causal Task survives a persistence boundary."""

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
    task_id = task.public_id
    goal_id = goal["id"]

    fast = _RespondBackend("FAST_OK")
    deep = _RespondBackend("DEEP_OK")
    coordinator = CognitiveCoordinator(task_store=env["tasks"], trace=trace)
    router = CognitiveRouter(trace=trace, enable_action_choice=True)
    dispatcher = CognitiveDispatcher(
        fast_backend=fast,
        deep_backend=deep,
        trace=trace,
    )

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
    )

    with recorder.task_scope(task, goal_status="active") as trace_id:
        # FAST is selected by the system. Its output is only a validated proposal.
        fast_task = _open_task()
        fast_coordinated = coordinator.process(task_id, fast_task)
        assert fast_coordinated.directive == CoordinatorDirective.ROUTE_COGNITION
        recorder.resolution(fast_coordinated)
        fast_route = router.route(fast_task, fast_coordinated.resolution)
        assert fast_route.destination == CognitiveDestination.FAST
        recorder.route(fast_task, fast_route)
        fast_dispatch = dispatcher.dispatch(
            fast_route,
            persistent_task_id=task_id,
            task=fast_task,
            resolution=fast_coordinated.resolution,
        )
        assert fast_dispatch.accepted is True
        recorder.dispatch(fast_dispatch)

        # Explicit conflict is routed to DEEP, still without persistence authority.
        deep_task = _conflict_task()
        deep_coordinated = coordinator.process(task_id, deep_task)
        recorder.resolution(deep_coordinated)
        deep_route = router.route(deep_task, deep_coordinated.resolution)
        assert deep_route.destination == CognitiveDestination.DEEP
        recorder.route(deep_task, deep_route)
        deep_dispatch = dispatcher.dispatch(
            deep_route,
            persistent_task_id=task_id,
            task=deep_task,
            resolution=deep_coordinated.resolution,
        )
        assert deep_dispatch.accepted is True
        recorder.dispatch(deep_dispatch)

        # CHOICE stays system-owned; no model receives this route.
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
            task_id,
            choice_task,
            choice_resolution,
            [
                Candidate("WRITE_RESULT", 0.80),
                Candidate("READ_INPUT", 0.20, information_gain=1.0),
            ],
        )
        assert choice.selected_candidate_id == "WRITE_RESULT"
        recorder.choice(choice)

        # Existing Stage 3 Sleep participates in the same Task lifecycle.
        entered = env["sleep_coordinator"].request_sleep(
            task_id,
            env["job"]["id"],
        )
        recorder.sleep(entered, event="entered")
        sleep_result = env["anima"].runtime.process_sleep_work(
            env["item"].public_id,
            ["bounded-sleep-evidence"],
            max_new_chunks=None,
        )
        assert sleep_result.status == "completed"
        woke = env["sleep_coordinator"].wake(task_id)
        assert woke.task_status == "active"
        recorder.sleep(woke, event="wake")

        verification_spec = VerificationSpec.create(
            goal_id=goal_id,
            criterion_kind=FILE_CONTENT_EQUALS,
            parameters={"path": "result.txt", "expected": "42"},
        )
        action = execution.prepare(
            choice,
            _action_specs(),
            created_at=_now(),
        )
        env["executions"].save_verification_spec(action, verification_spec)

        # Controlled crash point: the side effect exists but the operation commit
        # does not. Recovery must reconcile it without a second write.
        env["executions"].transition_operation(
            action.operation_id,
            "executing",
            reason="Stage 6.8 controlled crash after effect before commit",
        )
        target = sandbox / "result.txt"
        target.write_text("42", encoding="utf-8")
        before_restart_mtime = target.stat().st_mtime_ns
        trace.record_event(
            component="stage6",
            event="controlled_restart",
            message="stage6: controlled restart after effect before operation commit",
            action_id=action.public_id,
            operation_id=action.operation_id,
            payload={"crash_point": "after_effect_before_commit"},
        )
        operation_id = action.operation_id
        original_action_id = action.public_id
        original_verification_spec_id = verification_spec.public_id
        fast_calls_before_restart = len(fast.calls)
        deep_calls_before_restart = len(deep.calls)

    # Treat the following section as a new process. Only scalar persisted identity
    # is carried across; typed execution/verification contracts are reloaded.
    del action, verification_spec, choice

    restarted_trace_store = UnifiedTraceStore(tmp_path / "trace.db")
    restarted_trace = UnifiedTrace(restarted_trace_store)
    restarted_recorder = Stage6TraceRecorder(restarted_trace)
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
    recovery_turns = recovery.recover()

    assert len(recovery_turns) == 1
    recovered = recovery_turns[0]
    assert recovered.trace_id == trace_id
    assert recovered.task_id == task_id
    assert recovered.goal_id == goal_id
    assert recovered.task_status == "active"
    assert recovered.goal_status == "active"
    assert recovered.executing_to_uncertain == 1
    assert recovered.uncertain_operations == 1

    restored_action = restarted["executions"].load_action(operation_id)
    restored_spec = restarted["executions"].load_verification_spec(operation_id)
    assert restored_action.public_id == original_action_id
    assert restored_action.operation_id == operation_id
    assert restored_action.persistent_task_id == task_id
    assert restored_action.goal_id == goal_id
    assert restored_spec.public_id == original_verification_spec_id
    assert restored_spec.goal_id == goal_id

    restarted_executor = SandboxExecutor(
        root=sandbox,
        registry=registry,
        store=restarted["executions"],
    )
    restarted_execution = ExecutionCoordinator(
        task_store=restarted["tasks"],
        goal_store=restarted["anima"].internal_state.goals,
        execution_store=restarted["executions"],
        registry=registry,
        executor=restarted_executor,
        trace=restarted_trace,
    )

    with restarted_trace.bind(trace_id):
        execution_turn = restarted_execution.execute(restored_action)
        assert execution_turn.receipt.status == "succeeded"
        assert target.read_text(encoding="utf-8") == "42"
        assert target.stat().st_mtime_ns == before_restart_mtime
        restarted_recorder.execution(execution_turn)

        observation = FileObserver(sandbox).observe(
            restored_action,
            execution_turn.receipt,
            path="result.txt",
        )
        restarted_recorder.observation(restored_action, observation)
        verification = DeterministicGoalVerifier().verify(
            restored_spec,
            action=restored_action,
            observations=(observation,),
        )
        assert verification.criterion_satisfied is True
        restarted_recorder.verification(restored_action, verification)
        applied = GoalVerificationBridge(restarted["anima"].internal_state).apply(
            spec=restored_spec,
            action=restored_action,
            result=verification,
            observations=(observation,),
        )
        assert applied.progress_result.goal["status"] == "completed"

        completed_task = restarted["tasks"].transition_task(
            task_id,
            "completed",
            reason="Stage 6.8 independently verified Goal completed",
            source_id=verification.public_id,
            timestamp=_now(),
        )

    restarted_recorder.finish(
        trace_id,
        task=completed_task,
        goal_status="completed",
        success=True,
        reason="Stage 6.8 end-to-end acceptance completed",
    )

    stored_trace = restarted_trace_store.get_trace(trace_id)
    events = restarted_trace_store.list_events(trace_id)
    routes = [
        event.payload["destination"]
        for event in events
        if event.component == "cognitive_router" and event.event == "route"
    ]
    choice_events = [
        event
        for event in events
        if event.component == "action_choice" and event.event == "selected"
    ]

    assert stored_trace.status == "completed"
    assert stored_trace.task_id == task_id
    assert stored_trace.goal_id == goal_id
    assert stored_trace.outcome["task_status"] == "completed"
    assert stored_trace.outcome["goal_status"] == "completed"
    assert restarted["tasks"].get_task(task_id).status == "completed"
    assert restarted["anima"].internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert restarted["executions"].get_operation(operation_id)["status"] == "succeeded"
    assert routes == ["FAST", "DEEP", "CHOICE"]
    assert fast_calls_before_restart == 1
    assert deep_calls_before_restart == 1
    assert any(event.event == "controlled_restart" for event in events)
    assert any(event.component == "recovery" for event in events)
    assert any(event.component == "task_sleep" and event.event == "entered" for event in events)
    assert any(event.component == "task_sleep" and event.event == "wake" for event in events)
    assert any(event.component == "observation" for event in events)
    assert any(event.component == "verification" for event in events)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert len(choice_events) == 1
    assert choice_events[0].payload["evaluations"]
    assert all(
        item["final_score"] is not None
        for item in choice_events[0].payload["evaluations"]
    )
    assert all(
        abs(float(modifier["contribution"])) <= float(modifier["bound"]) + 1e-12
        for item in choice_events[0].payload["evaluations"]
        for modifier in item["modifiers"]
    )


def test_stage6_acceptance_deterministic_and_insufficient_paths_call_no_model(tmp_path):
    trace = UnifiedTrace(UnifiedTraceStore(tmp_path / "trace.db"))
    env = _base_environment(tmp_path, trace=trace)
    task_id = env["task"].public_id
    coordinator = CognitiveCoordinator(task_store=env["tasks"], trace=trace)
    fast = _RespondBackend("unused-fast")
    deep = _RespondBackend("unused-deep")
    CognitiveDispatcher(fast_backend=fast, deep_backend=deep, trace=trace)

    deterministic = CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation="CALCULATE",
        arguments={
            "left": Decimal("1.000001"),
            "right": Decimal("1.0"),
            "operator": "-",
        },
    )
    deterministic_turn = coordinator.process(task_id, deterministic)
    assert deterministic_turn.directive == CoordinatorDirective.FINAL
    assert deterministic_turn.final_result == Decimal("0.000001")

    insufficient = CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation="QUERY_FACT",
        subject="pet",
        predicate="color",
    )
    insufficient_turn = coordinator.process(task_id, insufficient)
    assert insufficient_turn.directive == CoordinatorDirective.NEEDS_DATA
    assert insufficient_turn.resolution.reason == "exact_fact_absent"

    assert fast.calls == []
    assert deep.calls == []
    assert env["tasks"].get_task(task_id).status == "active"


def test_stage6_acceptance_invalid_proposal_is_rejected_without_state_or_execution_mutation(tmp_path):
    trace = UnifiedTrace(UnifiedTraceStore(tmp_path / "trace.db"))
    env = _base_environment(tmp_path, trace=trace)
    task_id = env["task"].public_id
    goal_id = env["goal"]["id"]
    proposal = CognitiveProposal(
        ProposalKind.PROPOSE_ACTION,
        {"candidate": "WRITE_RESULT"},
    )
    fast = _StaticBackend(proposal)
    deep = _RespondBackend("unused")
    canonical = _open_task("proposal rejection")
    resolution = resolve(canonical)
    route = CognitiveRouter().route(canonical, resolution)
    turn = CognitiveDispatcher(fast_backend=fast, deep_backend=deep).dispatch(
        route,
        persistent_task_id=task_id,
        task=canonical,
        resolution=resolution,
    )

    assert turn.backend_called is True
    assert turn.accepted is False
    assert turn.validation.reason == "proposal_kind_not_enabled"
    assert len(fast.calls) == 1
    assert deep.calls == []
    assert env["tasks"].get_task(task_id).status == "active"
    assert env["anima"].internal_state.goals.get_goal(goal_id)["status"] == "active"
    assert env["executions"].list_operations(task_id=task_id) == []


def test_stage6_acceptance_backend_failure_is_isolated_and_traceable(tmp_path):
    trace_store = UnifiedTraceStore(tmp_path / "trace.db")
    trace = UnifiedTrace(trace_store)
    env = _base_environment(tmp_path, trace=trace)
    task_id = env["task"].public_id
    goal_id = env["goal"]["id"]
    failing = _FailingBackend()
    deep = _RespondBackend("unused")
    canonical = _open_task("backend failure")
    resolution = resolve(canonical)
    route = CognitiveRouter(trace=trace).route(canonical, resolution)
    dispatcher = CognitiveDispatcher(
        fast_backend=failing,
        deep_backend=deep,
        trace=trace,
    )

    trace_id = trace.resume_or_begin(task_id=task_id, goal_id=goal_id)
    with trace.bind(trace_id):
        with pytest.raises(RuntimeError, match="controlled Stage 6 backend failure"):
            dispatcher.dispatch(
                route,
                persistent_task_id=task_id,
                task=canonical,
                resolution=resolution,
            )

    events = trace_store.list_events(trace_id)
    assert len(failing.calls) == 1
    assert deep.calls == []
    assert env["tasks"].get_task(task_id).status == "active"
    assert env["anima"].internal_state.goals.get_goal(goal_id)["status"] == "active"
    assert env["executions"].list_operations(task_id=task_id) == []
    assert any(
        event.component == "cognitive_dispatch"
        and event.event == "backend_failure"
        for event in events
    )


def test_stage6_acceptance_backend_swap_does_not_move_identity_memory_task_or_goal(tmp_path):
    trace = UnifiedTrace(UnifiedTraceStore(tmp_path / "trace.db"))
    env = _base_environment(tmp_path, trace=trace)
    task = env["task"]
    goal = env["goal"]
    task_id = task.public_id
    goal_id = goal["id"]
    identity_before = dict(env["anima"].identity.get())
    memory_before = env["anima"].memory_store.export_debug()
    task_before = env["tasks"].get_task(task_id)
    goal_before = dict(env["anima"].internal_state.goals.get_goal(goal_id))

    canonical = _open_task("backend swap")
    resolution = resolve(canonical)
    route = CognitiveRouter().route(canonical, resolution)

    fast_a = _RespondBackend("backend-a")
    first = CognitiveDispatcher(
        fast_backend=fast_a,
        deep_backend=_RespondBackend("unused-a"),
    ).dispatch(
        route,
        persistent_task_id=task_id,
        task=canonical,
        resolution=resolution,
    )
    assert first.accepted is True

    fast_b = _RespondBackend("backend-b")
    second = CognitiveDispatcher(
        fast_backend=fast_b,
        deep_backend=_RespondBackend("unused-b"),
    ).dispatch(
        route,
        persistent_task_id=task_id,
        task=canonical,
        resolution=resolution,
    )
    assert second.accepted is True
    assert first.proposal.payload["text"] == "backend-a"
    assert second.proposal.payload["text"] == "backend-b"

    assert env["anima"].identity.get() == identity_before
    assert env["anima"].memory_store.export_debug() == memory_before
    assert env["tasks"].get_task(task_id) == task_before
    assert env["anima"].internal_state.goals.get_goal(goal_id) == goal_before
    assert env["executions"].list_operations(task_id=task_id) == []


def test_stage6_acceptance_sleep_checkpoint_resumes_after_process_restart(tmp_path):
    env = _sleep_environment(tmp_path)
    task_id = env["task"].public_id
    env["coordinator"].request_sleep(
        task_id,
        env["job"]["id"],
    )
    first = env["anima"].runtime.process_sleep_work(
        env["item"].public_id,
        ["alpha", "beta"],
        max_new_chunks=1,
    )
    assert first.status == "checkpointed"

    restarted = _sleep_environment(
        tmp_path,
        source=env["source"],
        create_entities=False,
    )
    summary = restarted["coordinator"].recover()
    assert summary["restored"] == 1

    completed = restarted["anima"].runtime.process_sleep_work(
        env["item"].public_id,
        ["alpha", "beta"],
        max_new_chunks=None,
    )
    assert completed.status == "completed"
    assert completed.resumed_from_sequence == 1
    assert completed.final_result.output == {"values": ["alpha", "beta"]}

    woke = restarted["coordinator"].wake(task_id)
    assert woke.task_status == "active"
    assert woke.sleep_job_status == "completed"
    assert restarted["links"].get_open_for_task(task_id) is None
