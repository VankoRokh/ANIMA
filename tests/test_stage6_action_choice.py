from uuid import uuid4

import pytest

from anima.cognition.action_choice import ActionChoiceCoordinator
from anima.cognition.proposals import CognitiveDispatcher, CognitiveProposal
from anima.cognition.routing import CognitiveDestination, CognitiveRouter
from anima.diagnostics.trace import DiagnosticTrace
from anima.internal_state.choice_engine import Candidate, ChoiceEngine
from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore
from anima.ir import CanonicalTask, HardConstraint
from anima.resolution import resolve
from anima.tasks.store import TaskStore


T1 = "2026-11-02T12:00:00+00:00"
T2 = "2026-11-02T12:01:00+00:00"


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        return CognitiveProposal.respond("model must not choose actions")


def setup_choice(tmp_path, *, link_goal=True):
    state_store = InternalStateStore(tmp_path / "internal_state.db")
    goal_store = GoalStore(state_store)
    goal = goal_store.create_goal(
        source="test",
        priority=1.0,
        description="choose a safe action",
        success_criterion="selected action can later be independently verified",
        reason="Stage 6.3 choice test",
        timestamp=T1,
    )
    task_store = TaskStore(tmp_path / "tasks.db")
    persistent = task_store.create_task(
        source="test",
        description="select among resolved action candidates",
        reason="Stage 6.3 choice test",
        goal_id=goal["id"] if link_goal else None,
        timestamp=T1,
    )
    persistent = task_store.transition_task(
        persistent.public_id,
        "active",
        reason="activate Stage 6.3 task",
        timestamp=T1,
    )
    engine = ChoiceEngine(state_store, goal_store=goal_store)
    return state_store, goal_store, goal, task_store, persistent, engine


def action_task(*, candidates=("ACT", "INSPECT"), constraints=()):
    return CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation="CHOOSE_ACTION",
        candidates=candidates,
        constraints=constraints,
        output_contract="candidate",
    )


def seed_state(store, name, value):
    return store.apply_state_transition(
        state_name=name,
        delta=value,
        cause_type="test",
        source_id=f"seed_{name}",
        rule_id=f"test.stage6_3.{name}",
        reason="seed Stage 6.3 Internal State",
        timestamp=T2,
    )


def test_action_choice_route_is_capability_gated_and_never_a_model_role():
    task = action_task()
    resolution = resolve(task)
    assert resolution.reason == "multiple_actions_without_policy"

    closed = CognitiveRouter().route(task, resolution)
    assert closed.destination == CognitiveDestination.BLOCKED
    assert closed.reason == "action_choice_reserved_for_stage_6_3"

    opened = CognitiveRouter(enable_action_choice=True).route(task, resolution)
    assert opened.destination == CognitiveDestination.CHOICE
    assert opened.reason == "system_action_choice"
    assert opened.role is None


def test_model_dispatcher_rejects_system_choice_route_without_backend_calls(tmp_path):
    _, _, _, task_store, persistent, _ = setup_choice(tmp_path)
    task = action_task()
    resolution = resolve(task)
    decision = CognitiveRouter(enable_action_choice=True).route(task, resolution)
    fast = RecordingBackend()
    deep = RecordingBackend()

    with pytest.raises(ValueError, match="ActionChoiceCoordinator"):
        CognitiveDispatcher(fast_backend=fast, deep_backend=deep).dispatch(
            decision,
            persistent_task_id=persistent.public_id,
            task=task,
            resolution=resolution,
        )

    assert fast.calls == []
    assert deep.calls == []
    assert task_store.get_task(persistent.public_id).status == "active"


def test_neutral_internal_state_preserves_system_baseline(tmp_path):
    _, goal_store, goal, task_store, persistent, engine = setup_choice(tmp_path)
    task = action_task()
    resolution = resolve(task)
    trace = DiagnosticTrace()
    coordinator = ActionChoiceCoordinator(
        task_store=task_store,
        choice_engine=engine,
        trace=trace,
    )
    task_before = task_store.list_transitions(persistent.public_id)
    goal_before = goal_store.list_goal_transitions(goal_id=goal["id"])

    turn = coordinator.choose(
        persistent.public_id,
        task,
        resolution,
        [
            Candidate("ACT", 0.70),
            Candidate("INSPECT", 0.55, information_gain=1.0),
        ],
    )

    assert turn.goal_id == goal["id"]
    assert turn.baseline_selected_candidate_id == "ACT"
    assert turn.selected_candidate_id == "ACT"
    assert turn.state_changed_selection is False
    assert turn.choice["state_snapshot"]["uncertainty"] == pytest.approx(0.0)
    assert task_store.list_transitions(persistent.public_id) == task_before
    assert goal_store.list_goal_transitions(goal_id=goal["id"]) == goal_before
    assert "baseline=ACT" in trace.entries()[-1]["message"]
    assert "selected=ACT" in trace.entries()[-1]["message"]


def test_uncertainty_can_change_selection_via_bounded_choice_engine(tmp_path):
    state_store, _, _, task_store, persistent, engine = setup_choice(tmp_path)
    seed_state(state_store, "uncertainty", 1.0)
    task = action_task()
    resolution = resolve(task)

    turn = ActionChoiceCoordinator(
        task_store=task_store,
        choice_engine=engine,
    ).choose(
        persistent.public_id,
        task,
        resolution,
        [
            Candidate("ACT", 0.70),
            Candidate("INSPECT", 0.55, information_gain=1.0),
        ],
    )

    assert turn.baseline_selected_candidate_id == "ACT"
    assert turn.selected_candidate_id == "INSPECT"
    assert turn.state_changed_selection is True
    assert turn.choice["state_snapshot"]["uncertainty"] == pytest.approx(1.0)
    inspect = next(
        item for item in turn.choice["evaluations"]
        if item["candidate_id"] == "INSPECT"
    )
    modifier = next(
        item for item in inspect["modifiers"]
        if item["name"] == "uncertainty_information_gain_bonus"
    )
    assert modifier["contribution"] == pytest.approx(0.20)


def test_choice_requires_exact_resolver_candidate_set(tmp_path):
    _, _, _, task_store, persistent, engine = setup_choice(tmp_path)
    task = action_task()
    resolution = resolve(task)
    coordinator = ActionChoiceCoordinator(task_store=task_store, choice_engine=engine)

    with pytest.raises(ValueError, match="exactly match resolver remaining"):
        coordinator.choose(
            persistent.public_id,
            task,
            resolution,
            [Candidate("ACT", 0.7)],
        )

    with pytest.raises(ValueError, match="exactly match resolver remaining"):
        coordinator.choose(
            persistent.public_id,
            task,
            resolution,
            [
                Candidate("ACT", 0.7),
                Candidate("INSPECT", 0.5),
                Candidate("INVENTED", 0.9),
            ],
        )


def test_unresolved_hard_constraint_cannot_be_overridden_by_internal_state(tmp_path):
    _, _, _, task_store, persistent, engine = setup_choice(tmp_path)
    task = action_task(
        constraints=(HardConstraint("unknown_rule", "ACT", "UNSUPPORTED_RULE"),),
    )
    resolution = resolve(task)
    assert resolution.reason == "unsupported_hard_constraint"

    decision = CognitiveRouter(enable_action_choice=True).route(task, resolution)
    assert decision.destination == CognitiveDestination.BLOCKED
    assert decision.reason == "action_choice_requires_verified_candidate_set"

    coordinator = ActionChoiceCoordinator(task_store=task_store, choice_engine=engine)
    with pytest.raises(ValueError, match="fully verified admissible candidates"):
        coordinator.choose(
            persistent.public_id,
            task,
            resolution,
            [
                Candidate("ACT", 0.9),
                Candidate("INSPECT", 0.1),
            ],
        )


def test_choice_requires_persistent_task_linked_to_active_goal(tmp_path):
    _, _, _, task_store, persistent, engine = setup_choice(tmp_path, link_goal=False)
    task = action_task()
    resolution = resolve(task)

    with pytest.raises(ValueError, match="linked to Goal"):
        ActionChoiceCoordinator(
            task_store=task_store,
            choice_engine=engine,
        ).choose(
            persistent.public_id,
            task,
            resolution,
            [Candidate("ACT", 0.7), Candidate("INSPECT", 0.6)],
        )


def test_choice_engine_rejects_non_active_goal_through_stage6_bridge(tmp_path):
    _, goal_store, goal, task_store, persistent, engine = setup_choice(tmp_path)
    goal_store.transition_goal(
        goal["id"],
        to_status="blocked",
        reason="controlled test block",
        timestamp=T2,
    )
    task = action_task()
    resolution = resolve(task)

    with pytest.raises(ValueError, match="active Goal"):
        ActionChoiceCoordinator(
            task_store=task_store,
            choice_engine=engine,
        ).choose(
            persistent.public_id,
            task,
            resolution,
            [Candidate("ACT", 0.7), Candidate("INSPECT", 0.6)],
        )
