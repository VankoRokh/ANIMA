import pytest

from anima.internal_state.goal_arbitration import GoalArbitrator
from anima.internal_state.goal_progress import (
    GoalObservation,
    GoalObservationKind,
    GoalProgressEngine,
    VerificationKind,
)
from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore
from anima.internal_state.transition_engine import TransitionEngine


T0 = "2026-10-26T18:00:00+00:00"
T1 = "2026-10-26T18:01:00+00:00"
T2 = "2026-10-26T18:02:00+00:00"
T3 = "2026-10-26T18:03:00+00:00"

GOAL_A = "goal_11111111-1111-4111-8111-111111111111"
GOAL_B = "goal_22222222-2222-4222-8222-222222222222"
GOAL_C = "goal_33333333-3333-4333-8333-333333333333"


def _stores(tmp_path):
    state = InternalStateStore(tmp_path / "internal_state.db")
    goals = GoalStore(state)
    progress = GoalProgressEngine(goals, TransitionEngine(state))
    return state, goals, progress


def _create(goals, *, goal_id=GOAL_A, priority=1.0, timestamp=T0):
    return goals.create_goal(
        source="test",
        priority=priority,
        description=f"Goal {goal_id}",
        success_criterion="observable criterion",
        reason="test goal",
        timestamp=timestamp,
        public_id=goal_id,
    )


def _observation(kind, *, goal_id=GOAL_A, verification="observation",
                 candidate="candidate_a", criterion=False, timestamp=T1,
                 source="obs_1", reason="verified test observation",
                 importance=1):
    return GoalObservation(
        goal_id=goal_id,
        kind=kind,
        source_id=source,
        reason=reason,
        verification=verification,
        candidate_id=candidate,
        importance=importance,
        criterion_satisfied=criterion,
        timestamp=timestamp,
    )


def test_unverified_observation_cannot_mutate_goal_or_state(tmp_path):
    state, goals, progress = _stores(tmp_path)
    _create(goals)
    state_count = state.transition_count()
    goal_history = len(goals.list_goal_transitions(goal_id=GOAL_A))

    with pytest.raises(ValueError, match="Unverified"):
        progress.process(
            _observation(GoalObservationKind.PROGRESS, verification="unverified")
        )

    assert goals.get_goal(GOAL_A)["status"] == "active"
    assert state.transition_count() == state_count
    assert len(goals.list_goal_transitions(goal_id=GOAL_A)) == goal_history


def test_verified_progress_keeps_goal_active_and_updates_internal_state(tmp_path):
    state, goals, progress = _stores(tmp_path)
    _create(goals)
    state.apply_state_transition(
        state_name="frustration",
        delta=0.3,
        cause_type="test",
        rule_id="test.seed",
        reason="seed",
        timestamp=T0,
    )

    result = progress.process(
        _observation(GoalObservationKind.PROGRESS, importance=2)
    )

    assert result.goal["status"] == "active"
    assert result.goal_transition is None
    assert [item["state_name"] for item in result.state_transitions] == [
        "frustration",
        "satisfaction",
    ]
    assert {item["goal_id"] for item in result.state_transitions} == {GOAL_A}
    assert {item["candidate_id"] for item in result.state_transitions} == {
        "candidate_a"
    }


def test_failure_keeps_goal_active_and_raises_frustration(tmp_path):
    state, goals, progress = _stores(tmp_path)
    _create(goals)

    result = progress.process(_observation(GoalObservationKind.FAILURE))

    assert result.goal["status"] == "active"
    assert result.goal_transition is None
    assert len(result.state_transitions) == 1
    assert result.state_transitions[0]["state_name"] == "frustration"
    assert result.state_transitions[0]["delta"] > 0.0


def test_success_requires_satisfied_criterion(tmp_path):
    state, goals, progress = _stores(tmp_path)
    _create(goals)
    before = state.transition_count()

    with pytest.raises(ValueError, match="satisfied success criterion"):
        progress.process(_observation(GoalObservationKind.SUCCESS))

    assert goals.get_goal(GOAL_A)["status"] == "active"
    assert state.transition_count() == before


def test_non_success_cannot_claim_satisfied_criterion(tmp_path):
    _, goals, progress = _stores(tmp_path)
    _create(goals)

    with pytest.raises(ValueError, match="reported as Goal success"):
        progress.process(
            _observation(GoalObservationKind.PROGRESS, criterion=True)
        )


def test_verified_success_completes_goal_and_records_state_effect(tmp_path):
    state, goals, progress = _stores(tmp_path)
    _create(goals)

    result = progress.process(
        _observation(
            GoalObservationKind.SUCCESS,
            verification=VerificationKind.CONFIRMED_RESULT,
            criterion=True,
            source="result_success",
            reason="criterion observed as satisfied",
        )
    )

    assert result.goal["status"] == "completed"
    assert result.goal["resolution_reason"] == "criterion observed as satisfied"
    assert result.goal_transition["to_status"] == "completed"
    assert result.goal_transition["source_id"] == "result_success"
    assert any(item["state_name"] == "satisfaction" for item in result.state_transitions)


def test_blocked_goal_gets_failure_like_signal_and_leaves_active_set(tmp_path):
    state, goals, progress = _stores(tmp_path)
    _create(goals)

    result = progress.process(_observation(GoalObservationKind.BLOCKED))

    assert result.goal["status"] == "blocked"
    assert result.goal_transition["to_status"] == "blocked"
    assert result.state_transitions[0]["state_name"] == "frustration"
    assert goals.list_active_goals() == []


def test_reactivation_returns_blocked_goal_to_active_without_fake_reward(tmp_path):
    state, goals, progress = _stores(tmp_path)
    _create(goals)
    progress.process(_observation(GoalObservationKind.BLOCKED, timestamp=T1))
    count = state.transition_count()

    result = progress.process(
        _observation(
            GoalObservationKind.REACTIVATED,
            candidate=None,
            timestamp=T2,
            source="obs_reactivate",
            reason="blocker removed",
        )
    )

    assert result.goal["status"] == "active"
    assert result.goal_transition["from_status"] == "blocked"
    assert result.goal_transition["to_status"] == "active"
    assert result.state_transitions == ()
    assert state.transition_count() == count


def test_progress_requires_active_goal_until_reactivated(tmp_path):
    _, goals, progress = _stores(tmp_path)
    _create(goals)
    progress.process(_observation(GoalObservationKind.BLOCKED, timestamp=T1))

    with pytest.raises(ValueError, match="requires an active Goal"):
        progress.process(
            _observation(GoalObservationKind.PROGRESS, timestamp=T2)
        )


def test_observation_cannot_precede_latest_goal_transition(tmp_path):
    _, goals, progress = _stores(tmp_path)
    _create(goals)
    progress.process(_observation(GoalObservationKind.BLOCKED, timestamp=T2))

    with pytest.raises(ValueError, match="must not be earlier"):
        progress.process(
            _observation(
                GoalObservationKind.REACTIVATED,
                candidate=None,
                timestamp=T1,
            )
        )


def test_arbitration_orders_active_goals_by_priority(tmp_path):
    _, goals, _ = _stores(tmp_path)
    _create(goals, goal_id=GOAL_A, priority=1.0, timestamp=T0)
    _create(goals, goal_id=GOAL_B, priority=3.0, timestamp=T1)
    _create(goals, goal_id=GOAL_C, priority=2.0, timestamp=T2)

    result = GoalArbitrator(goals).evaluate()

    assert result.selected_goal_id == GOAL_B
    assert [item.goal_id for item in result.entries] == [GOAL_B, GOAL_C, GOAL_A]
    assert all(
        "Internal State does not alter Goal priority" in item.reason
        for item in result.entries
    )


def test_arbitration_ties_use_created_at_then_goal_id(tmp_path):
    _, goals, _ = _stores(tmp_path)
    _create(goals, goal_id=GOAL_C, priority=2.0, timestamp=T1)
    _create(goals, goal_id=GOAL_A, priority=2.0, timestamp=T0)
    _create(goals, goal_id=GOAL_B, priority=2.0, timestamp=T1)

    result = GoalArbitrator(goals).evaluate()

    assert [item.goal_id for item in result.entries] == [GOAL_A, GOAL_B, GOAL_C]


def test_arbitration_excludes_non_active_goals(tmp_path):
    _, goals, progress = _stores(tmp_path)
    _create(goals, goal_id=GOAL_A, priority=1.0, timestamp=T0)
    _create(goals, goal_id=GOAL_B, priority=5.0, timestamp=T0)
    _create(goals, goal_id=GOAL_C, priority=4.0, timestamp=T0)

    progress.process(
        _observation(
            GoalObservationKind.BLOCKED,
            goal_id=GOAL_B,
            timestamp=T1,
        )
    )
    progress.process(
        _observation(
            GoalObservationKind.SUCCESS,
            goal_id=GOAL_C,
            criterion=True,
            timestamp=T1,
        )
    )

    result = GoalArbitrator(goals).evaluate()
    assert [item.goal_id for item in result.entries] == [GOAL_A]


def test_arbitration_is_read_only(tmp_path):
    state, goals, _ = _stores(tmp_path)
    _create(goals, goal_id=GOAL_A, priority=1.0)
    _create(goals, goal_id=GOAL_B, priority=2.0)
    goal_count = goals.goal_count()
    state_count = state.transition_count()
    goal_history = len(goals.list_goal_transitions())

    GoalArbitrator(goals).evaluate()

    assert goals.goal_count() == goal_count
    assert state.transition_count() == state_count
    assert len(goals.list_goal_transitions()) == goal_history


def test_reopen_keeps_same_arbitration_order(tmp_path):
    database = tmp_path / "internal_state.db"
    state = InternalStateStore(database)
    goals = GoalStore(state)
    _create(goals, goal_id=GOAL_A, priority=2.0, timestamp=T0)
    _create(goals, goal_id=GOAL_B, priority=3.0, timestamp=T1)

    before = GoalArbitrator(goals).evaluate()
    reopened = GoalStore(InternalStateStore(database))
    after = GoalArbitrator(reopened).evaluate()

    assert after.selected_goal_id == before.selected_goal_id
    assert [item.goal_id for item in after.entries] == [
        item.goal_id for item in before.entries
    ]
