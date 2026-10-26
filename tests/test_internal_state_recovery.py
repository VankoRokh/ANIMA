import pytest

from anima.internal_state.goal_progress import (
    GoalObservation,
    GoalObservationKind,
    VerificationKind,
)
from anima.internal_state.transition_engine import StateSignal, SignalKind
from tests.harness import AnimaTestHarness


T0 = "2026-10-26T10:00:00+00:00"
T1 = "2026-10-26T11:00:00+00:00"
T2 = "2026-10-26T12:00:00+00:00"
T3 = "2026-10-26T13:00:00+00:00"


def _goal(anima, *, source_id=None):
    return anima.runtime.create_goal(
        source="test",
        priority=1.0,
        description="Recovery test goal",
        success_criterion="verified result",
        reason="create recovery test goal",
        source_id=source_id,
        timestamp=T0,
    )


def test_replayed_state_signal_is_idempotent(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    signal = StateSignal(
        kind=SignalKind.WORKLOAD_NORMAL,
        source_id="event_workload_1",
        reason="same workload event",
        timestamp=T1,
    )

    first = anima.runtime.process_state_signal(signal)
    value_after_first = anima.internal_state_store.get_state("fatigue")["value"]
    count_after_first = anima.internal_state_store.transition_count()

    second = anima.runtime.process_state_signal(signal)

    assert [item["id"] for item in second] == [item["id"] for item in first]
    assert anima.internal_state_store.get_state("fatigue")["value"] == value_after_first
    assert anima.internal_state_store.transition_count() == count_after_first == 1
    assert anima.snapshot()["internal_state"]["recovery"] == {
        "processing_operations": 0,
        "completed_operations": 1,
    }


def test_source_reuse_with_different_payload_is_rejected(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    anima.runtime.process_state_signal(
        StateSignal(
            kind=SignalKind.WORKLOAD_LOW,
            source_id="event_conflict",
            reason="original signal",
            timestamp=T1,
        )
    )

    with pytest.raises(ValueError, match="different payload"):
        anima.runtime.process_state_signal(
            StateSignal(
                kind=SignalKind.WORKLOAD_HIGH,
                source_id="event_conflict",
                reason="changed signal",
                timestamp=T1,
            )
        )

    assert anima.internal_state_store.transition_count() == 1


def test_replayed_verified_progress_does_not_duplicate_effects(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)
    observation = GoalObservation(
        goal_id=goal["id"],
        kind=GoalObservationKind.PROGRESS,
        source_id="result_progress_1",
        reason="verified progress",
        verification=VerificationKind.CONFIRMED_RESULT,
        candidate_id="candidate_a",
        importance=2,
        timestamp=T1,
    )

    first = anima.runtime.observe_goal(observation)
    transition_ids = [item["id"] for item in first.state_transitions]
    state_after_first = anima.snapshot()["internal_state"]["states"]

    second = anima.runtime.observe_goal(observation)

    assert [item["id"] for item in second.state_transitions] == transition_ids
    assert anima.snapshot()["internal_state"]["states"] == state_after_first
    assert anima.internal_state_store.transition_count() == 2


def test_replayed_success_returns_completed_goal_without_duplicates(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)
    observation = GoalObservation(
        goal_id=goal["id"],
        kind=GoalObservationKind.SUCCESS,
        source_id="result_success_1",
        reason="criterion verified",
        verification=VerificationKind.CONFIRMED_RESULT,
        candidate_id="candidate_a",
        importance=3,
        criterion_satisfied=True,
        timestamp=T1,
    )

    first = anima.runtime.observe_goal(observation)
    state_count = anima.internal_state_store.transition_count()
    goal_history_count = len(
        anima.internal_state.goals.list_goal_transitions(goal_id=goal["id"])
    )

    second = anima.runtime.observe_goal(observation)

    assert first.goal["status"] == second.goal["status"] == "completed"
    assert [item["id"] for item in second.state_transitions] == [
        item["id"] for item in first.state_transitions
    ]
    assert anima.internal_state_store.transition_count() == state_count == 2
    assert len(
        anima.internal_state.goals.list_goal_transitions(goal_id=goal["id"])
    ) == goal_history_count == 2


def test_restart_recovers_partially_applied_multi_state_signal(tmp_path, monkeypatch):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)
    signal = StateSignal(
        kind=SignalKind.VERIFIED_PROGRESS,
        source_id="result_partial_signal",
        reason="partial verified progress",
        importance=2,
        goal_id=goal["id"],
        candidate_id="candidate_a",
        timestamp=T1,
    )

    original = anima.internal_state_store.apply_state_transition
    calls = 0

    def fail_second_transition(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated crash between state effects")
        return original(**kwargs)

    monkeypatch.setattr(
        anima.internal_state_store,
        "apply_state_transition",
        fail_second_transition,
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        anima.runtime.process_state_signal(signal)

    assert anima.internal_state_store.transition_count() == 1
    assert anima.snapshot()["internal_state"]["recovery"]["processing_operations"] == 1

    recovered = AnimaTestHarness(tmp_path)
    snapshot = recovered.snapshot()["internal_state"]

    assert snapshot["state_transition_count"] == 2
    assert snapshot["states"]["satisfaction"] > 0.0
    assert snapshot["recovery"] == {
        "processing_operations": 0,
        "completed_operations": 1,
    }
    assert any(
        "recovered pending sources result_partial_signal" in line
        for line in recovered.trace.lines()
    )


def test_restart_recovers_goal_transition_after_state_effects(tmp_path, monkeypatch):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)
    observation = GoalObservation(
        goal_id=goal["id"],
        kind=GoalObservationKind.SUCCESS,
        source_id="result_partial_goal",
        reason="verified success before simulated crash",
        verification=VerificationKind.CONFIRMED_RESULT,
        candidate_id="candidate_a",
        importance=2,
        criterion_satisfied=True,
        timestamp=T1,
    )

    def fail_goal_transition(*args, **kwargs):
        raise RuntimeError("simulated crash before Goal transition")

    monkeypatch.setattr(
        anima.internal_state.goals,
        "transition_goal",
        fail_goal_transition,
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        anima.runtime.observe_goal(observation)

    assert anima.internal_state_store.transition_count() == 2
    assert anima.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    assert anima.snapshot()["internal_state"]["recovery"]["processing_operations"] == 1

    recovered = AnimaTestHarness(tmp_path)
    recovered_goal = recovered.internal_state.goals.get_goal(goal["id"])

    assert recovered_goal["status"] == "completed"
    assert recovered.internal_state_store.transition_count() == 2
    assert len(
        recovered.internal_state.goals.list_goal_transitions(goal_id=goal["id"])
    ) == 2
    assert recovered.snapshot()["internal_state"]["recovery"] == {
        "processing_operations": 0,
        "completed_operations": 1,
    }


def test_source_id_cannot_be_reused_across_operation_kinds(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)
    source_id = "shared_source"

    anima.runtime.process_state_signal(
        StateSignal(
            kind=SignalKind.WORKLOAD_LOW,
            source_id=source_id,
            reason="workload event",
            timestamp=T1,
        )
    )

    with pytest.raises(ValueError, match="different Stage 2 operation"):
        anima.runtime.observe_goal(
            GoalObservation(
                goal_id=goal["id"],
                kind=GoalObservationKind.FAILURE,
                source_id=source_id,
                reason="failure result",
                verification=VerificationKind.OBSERVATION,
                candidate_id="candidate_a",
                timestamp=T2,
            )
        )


def test_invalid_mutation_does_not_leave_pending_operation(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)

    with pytest.raises(ValueError, match="Unverified Goal observations"):
        anima.runtime.observe_goal(
            GoalObservation(
                goal_id=goal["id"],
                kind=GoalObservationKind.PROGRESS,
                source_id="invalid_unverified",
                reason="not verified",
                verification=VerificationKind.UNVERIFIED,
                candidate_id="candidate_a",
                timestamp=T1,
            )
        )

    assert anima.snapshot()["internal_state"]["recovery"] == {
        "processing_operations": 0,
        "completed_operations": 0,
    }


def test_time_evaluation_has_no_restart_drift(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)
    anima.runtime.observe_goal(
        GoalObservation(
            goal_id=goal["id"],
            kind=GoalObservationKind.PROGRESS,
            source_id="progress_for_time",
            reason="seed satisfaction",
            verification=VerificationKind.CONFIRMED_RESULT,
            candidate_id="candidate_a",
            importance=3,
            timestamp=T1,
        )
    )

    anima.runtime.evaluate_internal_time(
        now=T3,
        mode="awake",
        period_started_at=T1,
    )
    before = anima.snapshot()["internal_state"]

    reopened = AnimaTestHarness(tmp_path)
    repeated = reopened.runtime.evaluate_internal_time(
        now=T3,
        mode="awake",
        period_started_at=T1,
    )
    after = reopened.snapshot()["internal_state"]

    assert repeated == ()
    assert after["states"] == before["states"]
    assert after["state_transition_count"] == before["state_transition_count"]


def test_completed_operation_journal_survives_restart(tmp_path):
    first = AnimaTestHarness(tmp_path)
    signal = StateSignal(
        kind=SignalKind.INFORMATION_GAP,
        source_id="event_persistent_receipt",
        reason="missing information",
        importance=2,
        timestamp=T1,
    )
    first.runtime.process_state_signal(signal)

    reopened = AnimaTestHarness(tmp_path)
    before_count = reopened.internal_state_store.transition_count()
    replay = reopened.runtime.process_state_signal(signal)

    assert len(replay) == 1
    assert reopened.internal_state_store.transition_count() == before_count
    assert reopened.snapshot()["internal_state"]["recovery"] == {
        "processing_operations": 0,
        "completed_operations": 1,
    }
