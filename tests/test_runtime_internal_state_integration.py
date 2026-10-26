import pytest

from anima.internal_state.choice_engine import Candidate
from anima.internal_state.goal_progress import (
    GoalObservation,
    GoalObservationKind,
    VerificationKind,
)
from anima.internal_state.transition_engine import SignalKind, StateSignal
from tests.harness import AnimaTestHarness


T0 = "2026-10-26T18:00:00+00:00"
T1 = "2026-10-26T18:01:00+00:00"
T2 = "2026-10-26T18:02:00+00:00"
T3 = "2026-10-26T18:03:00+00:00"
GOAL_A = "goal_11111111-1111-4111-8111-111111111111"
GOAL_B = "goal_22222222-2222-4222-8222-222222222222"


def _goal(runtime, *, public_id=GOAL_A, priority=1.0, timestamp=T0):
    return runtime.create_goal(
        source="test",
        priority=priority,
        description="resolve the runtime integration scenario",
        success_criterion="verified scenario result is observed",
        reason="Stage 2.10 integration test",
        timestamp=timestamp,
        public_id=public_id,
    )


def test_runtime_snapshot_exposes_neutral_internal_state(tmp_path):
    anima = AnimaTestHarness(tmp_path)

    snapshot = anima.snapshot()["internal_state"]

    assert snapshot["states"] == {
        "fatigue": 0.0,
        "uncertainty": 0.0,
        "frustration": 0.0,
        "satisfaction": 0.0,
    }
    assert snapshot["state_transition_count"] == 0
    assert snapshot["goals"] == []
    assert snapshot["last_choice"] is None
    assert snapshot["expression"]["profile"] == {
        "energy": 0.5,
        "caution": 0.0,
        "tension": 0.0,
        "positive_affect": 0.0,
    }


def test_runtime_processes_state_signal_and_snapshot_preserves_cause(tmp_path):
    anima = AnimaTestHarness(tmp_path)

    transitions = anima.runtime.process_state_signal(
        StateSignal(
            kind=SignalKind.INFORMATION_CONFLICT,
            source_id="ev_conflict",
            reason="conflicting observations",
            importance=2,
            timestamp=T1,
        )
    )
    snapshot = anima.snapshot()["internal_state"]

    assert len(transitions) == 1
    assert snapshot["states"]["uncertainty"] > 0.0
    assert snapshot["state_transition_count"] == 1
    assert snapshot["recent_state_transitions"][0]["source_id"] == "ev_conflict"
    assert snapshot["recent_state_transitions"][0]["cause_type"] == "event"
    assert snapshot["expression"]["profile"]["caution"] > 0.0


def test_runtime_goal_creation_and_arbitration_are_visible(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    _goal(anima.runtime, public_id=GOAL_A, priority=1.0, timestamp=T0)
    _goal(anima.runtime, public_id=GOAL_B, priority=3.0, timestamp=T1)

    arbitration = anima.runtime.arbitrate_goals()
    snapshot = anima.snapshot()["internal_state"]

    assert arbitration.selected_goal_id == GOAL_B
    assert snapshot["goal_arbitration"]["selected_goal_id"] == GOAL_B
    assert [item["id"] for item in snapshot["goals"]] == [GOAL_B, GOAL_A]


def test_runtime_choice_is_visible_with_component_scores(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    _goal(anima.runtime)

    for index, timestamp in enumerate((T1, T2, T3), start=1):
        anima.runtime.process_state_signal(
            StateSignal(
                kind=SignalKind.INFORMATION_CONFLICT,
                source_id=f"ev_conflict_{index}",
                reason="missing reliable resolution",
                importance=3,
                timestamp=timestamp,
            )
        )

    result = anima.runtime.choose(
        GOAL_A,
        [
            Candidate(
                "inspect",
                0.56,
                information_gain=1.0,
            ),
            Candidate(
                "act",
                0.70,
                irreversible_risk=1.0,
            ),
        ],
    )
    snapshot = anima.snapshot()["internal_state"]

    assert result["selected_candidate_id"] == "inspect"
    assert snapshot["last_choice"]["selected_candidate_id"] == "inspect"
    evaluations = snapshot["last_choice"]["evaluations"]
    assert {item["candidate_id"] for item in evaluations} == {"inspect", "act"}
    assert all("modifier_total" in item for item in evaluations)
    assert all(item["modifiers"] for item in evaluations)


def test_runtime_goal_observation_updates_goal_state_and_expression(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    _goal(anima.runtime)

    result = anima.runtime.observe_goal(
        GoalObservation(
            goal_id=GOAL_A,
            kind=GoalObservationKind.PROGRESS,
            source_id="result_progress",
            reason="verified partial progress",
            verification=VerificationKind.CONFIRMED_RESULT,
            candidate_id="candidate_a",
            importance=2,
            timestamp=T1,
        )
    )
    snapshot = anima.snapshot()["internal_state"]

    assert result.goal["status"] == "active"
    assert snapshot["states"]["satisfaction"] > 0.0
    assert snapshot["expression"]["profile"]["positive_affect"] > 0.0
    assert snapshot["state_transition_count"] == 2


def test_runtime_verified_success_completes_goal_and_removes_it_from_arbitration(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    _goal(anima.runtime)

    result = anima.runtime.observe_goal(
        GoalObservation(
            goal_id=GOAL_A,
            kind=GoalObservationKind.SUCCESS,
            source_id="result_success",
            reason="success criterion verified",
            verification=VerificationKind.CONFIRMED_RESULT,
            candidate_id="candidate_a",
            importance=2,
            criterion_satisfied=True,
            timestamp=T1,
        )
    )
    snapshot = anima.snapshot()["internal_state"]

    assert result.goal["status"] == "completed"
    assert snapshot["goal_arbitration"]["selected_goal_id"] is None
    assert snapshot["goals"][0]["status"] == "completed"

    with pytest.raises(ValueError, match="requires an active Goal"):
        anima.runtime.choose(
            GOAL_A,
            [Candidate("candidate_a", 0.5)],
        )


def test_runtime_time_evaluation_is_visible_in_snapshot(tmp_path):
    anima = AnimaTestHarness(tmp_path)

    transitions = anima.runtime.evaluate_internal_time(
        now="2026-10-26T20:00:00+00:00",
        mode="awake",
        period_started_at=T0,
    )
    snapshot = anima.snapshot()["internal_state"]

    fatigue = next(
        item for item in transitions
        if item["state_name"] == "fatigue"
    )
    assert fatigue["cause_type"] == "time"
    assert snapshot["states"]["fatigue"] > 0.0


def test_snapshot_is_read_only_for_internal_state(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    anima.runtime.process_state_signal(
        StateSignal(
            kind=SignalKind.INFORMATION_GAP,
            source_id="ev_gap",
            reason="missing data",
            timestamp=T1,
        )
    )
    before = anima.internal_state_store.transition_count()

    first = anima.snapshot()["internal_state"]
    second = anima.snapshot()["internal_state"]

    assert anima.internal_state_store.transition_count() == before
    assert second == first


def test_runtime_trace_records_stage2_operations(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    _goal(anima.runtime)
    anima.runtime.choose(
        GOAL_A,
        [Candidate("candidate_a", 0.5)],
    )

    messages = [
        item["message"]
        for item in anima.snapshot()["diagnostics"]["trace"]
    ]

    assert any("internal_state: goal created" in item for item in messages)
    assert any("internal_state: choice" in item for item in messages)


def test_scenario_runner_executes_full_internal_state_decision_chain(tmp_path):
    anima = AnimaTestHarness(tmp_path)

    results = anima.run_scenario([
        {"action": "wake"},
        {
            "action": "goal_create",
            "goal_id": GOAL_A,
            "source": "scenario",
            "priority": 1.0,
            "description": "choose a safe route",
            "success_criterion": "verified route succeeds",
            "reason": "integration scenario",
            "timestamp": T0,
        },
        {
            "action": "state_signal",
            "kind": "information_conflict",
            "source_id": "ev_conflict_1",
            "reason": "conflict 1",
            "importance": 3,
            "timestamp": T1,
        },
        {
            "action": "state_signal",
            "kind": "information_conflict",
            "source_id": "ev_conflict_2",
            "reason": "conflict 2",
            "importance": 3,
            "timestamp": T2,
        },
        {
            "action": "state_signal",
            "kind": "information_conflict",
            "source_id": "ev_conflict_3",
            "reason": "conflict 3",
            "importance": 3,
            "timestamp": T3,
        },
        {
            "action": "choice",
            "goal_id": GOAL_A,
            "candidates": [
                {
                    "candidate_id": "inspect",
                    "base_score": 0.56,
                    "information_gain": 1.0,
                },
                {
                    "candidate_id": "act",
                    "base_score": 0.70,
                    "irreversible_risk": 1.0,
                },
            ],
        },
        {"action": "snapshot"},
    ])

    assert results[-2]["selected_candidate_id"] == "inspect"
    snapshot = results[-1]["snapshot"]["internal_state"]
    assert snapshot["states"]["uncertainty"] == pytest.approx(0.6)
    assert snapshot["last_choice"]["selected_candidate_id"] == "inspect"
    assert snapshot["expression"]["profile"]["caution"] == pytest.approx(0.48)
    assert snapshot["state_transition_count"] == 3


def test_scenario_runner_supports_verified_goal_result(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    _goal(anima.runtime)

    result = anima.run_scenario([
        {
            "action": "goal_observation",
            "goal_id": GOAL_A,
            "kind": "success",
            "source_id": "verified_result",
            "reason": "criterion observed",
            "verification": "confirmed_result",
            "candidate_id": "candidate_a",
            "importance": 2,
            "criterion_satisfied": True,
            "timestamp": T1,
        },
        {"action": "snapshot"},
    ])

    assert result[0]["goal"]["status"] == "completed"
    assert result[1]["snapshot"]["internal_state"]["goals"][0]["status"] == "completed"


def test_scenario_runner_rejects_invalid_choice_candidate(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    _goal(anima.runtime)

    with pytest.raises(
        ValueError,
        match="Scenario step 0: Choice Candidate must contain",
    ):
        anima.run_scenario([
            {
                "action": "choice",
                "goal_id": GOAL_A,
                "candidates": [{"candidate_id": "missing_score"}],
            }
        ])
