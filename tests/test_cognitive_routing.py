from uuid import uuid4

import pytest

from anima.cognition.contracts import CognitiveView
from anima.cognition.coordinator import CognitiveCoordinator, CoordinatorDirective
from anima.cognition.fast import FastResult, ProjectedFastRequest
from anima.cognition.proposals import (
    CognitiveDispatcher,
    CognitiveProposal,
    ProjectedFastProposalAdapter,
    ProposalKind,
    ProposalValidator,
    RoutedCognitiveRequest,
)
from anima.cognition.routing import (
    CognitiveDestination,
    CognitiveRole,
    CognitiveRouter,
    ROUTING_POLICY_VERSION,
)
from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask, Evidence
from anima.resolution import ResolutionRoute, resolve
from anima.tasks.store import TaskStore


class RecordingBackend:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        return self.proposal


class RecordingProjectedFastBackend:
    def __init__(self, text="fast answer"):
        self.text = text
        self.calls = []

    def complete_projected(self, request):
        self.calls.append(request)
        return FastResult(self.text)


def active_task(store):
    task = store.create_task(
        source="test",
        description="route one cognitive turn",
        reason="created for routing test",
    )
    return store.transition_task(task.public_id, "active", reason="activated")


def canonical(operation="OPEN", **kwargs):
    return CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation=operation,
        **kwargs,
    )


def conflict_task():
    return canonical(
        "QUERY_FACT",
        subject="device",
        predicate="location",
        evidence=(
            Evidence("old", "A", "device", "location", ("mem_old",), 0.8,
                     "2026-11-01T10:00:00+04:00"),
            Evidence("new", "B", "device", "location", ("mem_new",), 1.0,
                     "2026-11-02T10:00:00+04:00"),
        ),
    )


def action_choice_task():
    return canonical(
        "CHOOSE_ACTION",
        candidates=("A", "B"),
        output_contract="candidate",
    )


def test_router_uses_fast_for_baseline_open_reasoning():
    task = canonical("OPEN", raw_input="Think about this")
    resolution = resolve(task)
    assert resolution.route == ResolutionRoute.COGNITIVE_REQUIRED

    decision = CognitiveRouter().route(task, resolution)

    assert decision.destination == CognitiveDestination.FAST
    assert decision.role == CognitiveRole.FAST
    assert decision.reason == "bounded_fast_baseline"
    assert decision.policy_version == ROUTING_POLICY_VERSION


def test_router_uses_deep_only_for_explicit_conflict_reasoning():
    task = conflict_task()
    resolution = resolve(task)
    assert resolution.reason == "conflicting_or_multiple_facts"

    decision = CognitiveRouter().route(task, resolution)

    assert decision.destination == CognitiveDestination.DEEP
    assert decision.role == CognitiveRole.DEEP
    assert decision.reason == "explicit_conflict_reasoning"

    explicit = canonical("RESOLVE_CONFLICT", raw_input="Resolve supplied conflict")
    explicit_decision = CognitiveRouter().route(explicit, resolve(explicit))
    assert explicit_decision.destination == CognitiveDestination.DEEP


def test_router_blocks_action_choice_until_stage_6_3():
    task = action_choice_task()
    resolution = resolve(task)
    assert resolution.route == ResolutionRoute.COGNITIVE_REQUIRED

    decision = CognitiveRouter().route(task, resolution)

    assert decision.destination == CognitiveDestination.BLOCKED
    assert decision.role is None
    assert decision.blocked is True
    assert decision.reason == "action_choice_reserved_for_stage_6_3"


def test_router_rejects_non_cognitive_resolution_and_traces_reason():
    trace = DiagnosticTrace()
    router = CognitiveRouter(trace=trace)
    deterministic = canonical(
        "CALCULATE",
        arguments={"left": 2, "right": 3, "operator": "+"},
    )
    with pytest.raises(ValueError, match="COGNITIVE_REQUIRED"):
        router.route(deterministic, resolve(deterministic))

    task = conflict_task()
    router.route(task, resolve(task))
    message = trace.entries()[-1]["message"]
    assert task.task_id in message
    assert task.source_id in message
    assert "DEEP" in message
    assert "explicit_conflict_reasoning" in message
    assert ROUTING_POLICY_VERSION in message


def test_cognitive_view_supports_roles_but_fast_request_remains_fast_only():
    fast_view = CognitiveView("FAST", {"input": "hello"})
    deep_view = CognitiveView("DEEP", {"input": "hello"})
    assert fast_view.consumer == "FAST"
    assert deep_view.consumer == "DEEP"

    ProjectedFastRequest("src", fast_view)
    with pytest.raises(ValueError, match="FAST cognitive view"):
        ProjectedFastRequest("src", deep_view)
    with pytest.raises(ValueError, match="FAST or DEEP"):
        CognitiveView("AUTO", {})


def test_proposal_validator_enables_only_respond_in_6_2():
    validator = ProposalValidator()

    accepted = validator.validate(CognitiveProposal.respond("hello"))
    assert accepted.accepted is True
    assert accepted.reason == "accepted_response"

    malformed = validator.validate(CognitiveProposal.respond(" "))
    assert malformed.accepted is False
    assert malformed.reason == "invalid_response_payload"

    for kind in (
        ProposalKind.PROPOSE_ACTION,
        ProposalKind.PROPOSE_TASK,
        ProposalKind.REQUEST_CONTEXT,
    ):
        rejected = validator.validate(CognitiveProposal(kind, {"candidate": "x"}))
        assert rejected.accepted is False
        assert rejected.reason == "proposal_kind_not_enabled"


def test_routed_request_binds_view_to_system_selected_role():
    task_id = f"task_{uuid4()}"
    request = RoutedCognitiveRequest(
        persistent_task_id=task_id,
        canonical_task_id="ct_1",
        source_id="src_1",
        role=CognitiveRole.DEEP,
        view=CognitiveView("DEEP", {"input": "conflict"}),
    )
    assert request.role == CognitiveRole.DEEP

    with pytest.raises(ValueError, match="match selected role"):
        RoutedCognitiveRequest(
            persistent_task_id=task_id,
            canonical_task_id="ct_1",
            source_id="src_1",
            role=CognitiveRole.DEEP,
            view=CognitiveView("FAST", {"input": "conflict"}),
        )


def test_dispatcher_calls_only_selected_backend_and_validates_proposal(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    persistent = active_task(store)
    fast = RecordingBackend(CognitiveProposal.respond("fast"))
    deep = RecordingBackend(CognitiveProposal.respond("deep"))
    router = CognitiveRouter()
    dispatcher = CognitiveDispatcher(fast_backend=fast, deep_backend=deep)

    open_task = canonical("OPEN", raw_input="simple reasoning")
    open_resolution = resolve(open_task)
    fast_turn = dispatcher.dispatch(
        router.route(open_task, open_resolution),
        persistent_task_id=persistent.public_id,
        task=open_task,
        resolution=open_resolution,
    )
    assert fast_turn.accepted is True
    assert fast_turn.request.role == CognitiveRole.FAST
    assert fast_turn.proposal.payload["text"] == "fast"
    assert len(fast.calls) == 1
    assert len(deep.calls) == 0

    conflict = conflict_task()
    conflict_resolution = resolve(conflict)
    deep_turn = dispatcher.dispatch(
        router.route(conflict, conflict_resolution),
        persistent_task_id=persistent.public_id,
        task=conflict,
        resolution=conflict_resolution,
    )
    assert deep_turn.accepted is True
    assert deep_turn.request.role == CognitiveRole.DEEP
    assert deep_turn.request.view.consumer == "DEEP"
    assert deep_turn.proposal.payload["text"] == "deep"
    assert len(fast.calls) == 1
    assert len(deep.calls) == 1


def test_blocked_route_calls_no_backend(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    persistent = active_task(store)
    fast = RecordingBackend(CognitiveProposal.respond("must not run"))
    deep = RecordingBackend(CognitiveProposal.respond("must not run"))
    router = CognitiveRouter()
    dispatcher = CognitiveDispatcher(fast_backend=fast, deep_backend=deep)
    task = action_choice_task()
    resolution = resolve(task)

    turn = dispatcher.dispatch(
        router.route(task, resolution),
        persistent_task_id=persistent.public_id,
        task=task,
        resolution=resolution,
    )

    assert turn.backend_called is False
    assert turn.accepted is False
    assert turn.request is None
    assert turn.proposal is None
    assert turn.validation.reason == "action_choice_reserved_for_stage_6_3"
    assert fast.calls == []
    assert deep.calls == []


def test_disabled_proposal_kind_is_returned_but_not_accepted(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    persistent = active_task(store)
    fast = RecordingBackend(
        CognitiveProposal(ProposalKind.PROPOSE_TASK, {"description": "spawn work"})
    )
    deep = RecordingBackend(CognitiveProposal.respond("unused"))
    task = canonical("OPEN", raw_input="simple")
    resolution = resolve(task)

    turn = CognitiveDispatcher(fast_backend=fast, deep_backend=deep).dispatch(
        CognitiveRouter().route(task, resolution),
        persistent_task_id=persistent.public_id,
        task=task,
        resolution=resolution,
    )

    assert turn.backend_called is True
    assert turn.proposal.kind == ProposalKind.PROPOSE_TASK
    assert turn.accepted is False
    assert turn.validation.reason == "proposal_kind_not_enabled"
    assert store.get_task(persistent.public_id).status == "active"


def test_projected_fast_adapter_preserves_stage5_backend_boundary():
    backend = RecordingProjectedFastBackend("adapted")
    adapter = ProjectedFastProposalAdapter(backend)
    request = RoutedCognitiveRequest(
        persistent_task_id=f"task_{uuid4()}",
        canonical_task_id="ct_1",
        source_id="src_1",
        role=CognitiveRole.FAST,
        view=CognitiveView("FAST", {"input": "hello"}),
    )

    proposal = adapter.complete(request)

    assert proposal.kind == ProposalKind.RESPOND
    assert proposal.payload["text"] == "adapted"
    assert len(backend.calls) == 1
    assert isinstance(backend.calls[0], ProjectedFastRequest)


def test_coordinator_router_dispatcher_remain_separate_system_boundaries(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    persistent = active_task(store)
    trace = DiagnosticTrace()
    coordinator = CognitiveCoordinator(task_store=store, trace=trace)
    router = CognitiveRouter(trace=trace)
    fast = RecordingBackend(CognitiveProposal.respond("final text"))
    deep = RecordingBackend(CognitiveProposal.respond("unused"))
    dispatcher = CognitiveDispatcher(
        fast_backend=fast,
        deep_backend=deep,
        trace=trace,
    )
    task = canonical("OPEN", raw_input="hello")

    coordinator_turn = coordinator.process(persistent.public_id, task)
    assert coordinator_turn.directive == CoordinatorDirective.ROUTE_COGNITION
    decision = router.route(coordinator_turn.canonical_task, coordinator_turn.resolution)
    dispatch_turn = dispatcher.dispatch(
        decision,
        persistent_task_id=persistent.public_id,
        task=coordinator_turn.canonical_task,
        resolution=coordinator_turn.resolution,
    )

    assert dispatch_turn.accepted is True
    assert dispatch_turn.proposal.payload["text"] == "final text"
    assert store.get_task(persistent.public_id).status == "active"
    messages = [entry["message"] for entry in trace.entries()]
    assert any(message.startswith("coordinator: resolved") for message in messages)
    assert any(message.startswith("cognitive_router:") for message in messages)
    assert any(message.startswith("cognitive_dispatch: proposal") for message in messages)
