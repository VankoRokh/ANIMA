import math

import pytest

from anima.internal_state.choice_engine import Candidate
from anima.internal_state.goal_progress import (
    GoalObservation,
    GoalObservationKind,
    VerificationKind,
)
from anima.internal_state.transition_engine import SignalKind, StateSignal
from tests.harness import AnimaTestHarness


T0 = "2026-10-26T10:00:00+00:00"
T1 = "2026-10-26T11:00:00+00:00"
T2 = "2026-10-26T12:00:00+00:00"
T3 = "2026-10-26T13:00:00+00:00"
T7 = "2026-10-26T17:00:00+00:00"
T8 = "2026-10-26T18:00:00+00:00"
T9 = "2026-10-26T19:00:00+00:00"
T10 = "2026-10-26T20:00:00+00:00"


def _goal(anima, suffix="main", priority=1.0):
    return anima.runtime.create_goal(
        source="stage2_validation",
        priority=priority,
        description=f"Stage 2 validation goal {suffix}",
        success_criterion="verified validation result",
        reason="canonical Stage 2 validation setup",
        source_id=f"stage2_goal_{suffix}",
        timestamp=T0,
    )


def _signal(
    anima,
    kind,
    source_id,
    *,
    importance=1,
    goal_id=None,
    candidate_id=None,
    timestamp=T1,
):
    return anima.runtime.process_state_signal(
        StateSignal(
            kind=kind,
            source_id=source_id,
            reason=f"Stage 2 validation signal {source_id}",
            importance=importance,
            goal_id=goal_id,
            candidate_id=candidate_id,
            timestamp=timestamp,
        )
    )


def _observation(
    anima,
    goal_id,
    kind,
    source_id,
    *,
    candidate_id=None,
    verification=VerificationKind.CONFIRMED_RESULT,
    importance=1,
    criterion_satisfied=False,
    timestamp=T2,
):
    return anima.runtime.observe_goal(
        GoalObservation(
            goal_id=goal_id,
            kind=kind,
            source_id=source_id,
            reason=f"Stage 2 validation observation {source_id}",
            verification=verification,
            candidate_id=candidate_id,
            importance=importance,
            criterion_satisfied=criterion_satisfied,
            timestamp=timestamp,
        )
    )


def _decision_candidates():
    return [
        Candidate(
            candidate_id="direct_action",
            base_score=0.72,
            effort_cost=1.0,
            irreversible_risk=1.0,
        ),
        Candidate(
            candidate_id="inspect_first",
            base_score=0.65,
            information_gain=1.0,
            alternative_value=1.0,
        ),
    ]


def test_stage2_neutral_baseline_prefers_base_score(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)

    choice = anima.runtime.choose(goal["id"], _decision_candidates())
    snapshot = anima.snapshot()["internal_state"]

    assert choice["selected_candidate_id"] == "direct_action"
    assert snapshot["states"] == {
        "fatigue": 0.0,
        "frustration": 0.0,
        "satisfaction": 0.0,
        "uncertainty": 0.0,
    }
    assert snapshot["state_transition_count"] == 0


def test_stage2_fatigue_can_change_candidate_choice_without_changing_goal(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)
    candidates = _decision_candidates()

    neutral = anima.runtime.choose(goal["id"], candidates)
    for index in range(5):
        _signal(
            anima,
            SignalKind.WORKLOAD_HIGH,
            f"fatigue_workload_{index}",
        )
    altered = anima.runtime.choose(goal["id"], candidates)

    assert neutral["selected_candidate_id"] == "direct_action"
    assert altered["selected_candidate_id"] == "inspect_first"
    assert anima.internal_state_store.get_state("fatigue")["value"] > 0.0
    assert anima.internal_state.goals.get_goal(goal["id"])["status"] == "active"

    direct = next(
        item for item in altered["evaluations"]
        if item["candidate_id"] == "direct_action"
    )
    fatigue_modifier = next(
        item for item in direct["modifiers"]
        if item["name"] == "fatigue_effort_penalty"
    )
    assert fatigue_modifier["contribution"] < 0.0


def test_stage2_uncertainty_prefers_information_and_confirmation_quality_matters(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)

    for index in range(3):
        _signal(
            anima,
            SignalKind.INFORMATION_CONFLICT,
            f"uncertainty_conflict_{index}",
            importance=3,
        )

    choice = anima.runtime.choose(goal["id"], _decision_candidates())
    assert choice["selected_candidate_id"] == "inspect_first"

    indirect = _signal(
        anima,
        SignalKind.INFORMATION_CONFIRMED_INDIRECT,
        "uncertainty_indirect_confirmation",
        importance=1,
        timestamp=T2,
    )[0]
    direct = _signal(
        anima,
        SignalKind.INFORMATION_CONFIRMED_DIRECT,
        "uncertainty_direct_confirmation",
        importance=1,
        timestamp=T3,
    )[0]

    assert indirect["delta"] < 0.0
    assert direct["delta"] < 0.0
    assert abs(direct["delta"]) > abs(indirect["delta"])


def test_stage2_uncertainty_has_no_passive_time_decay_and_other_states_recover(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)

    _signal(anima, SignalKind.INFORMATION_CONFLICT, "time_uncertainty", importance=3)
    _signal(anima, SignalKind.WORKLOAD_HIGH, "time_fatigue")
    for index in range(3):
        _signal(
            anima,
            SignalKind.FAILURE,
            f"time_failure_{index}",
            goal_id=goal["id"],
            candidate_id="candidate_a",
        )
    _signal(
        anima,
        SignalKind.VERIFIED_PROGRESS,
        "time_progress",
        importance=3,
        goal_id=goal["id"],
        candidate_id="candidate_a",
    )

    before = anima.snapshot()["internal_state"]["states"]
    transitions = anima.runtime.evaluate_internal_time(
        now=T3,
        mode="recovery",
        period_started_at=T1,
    )
    after = anima.snapshot()["internal_state"]["states"]

    assert after["uncertainty"] == before["uncertainty"]
    assert after["fatigue"] < before["fatigue"]
    assert after["frustration"] < before["frustration"]
    assert after["satisfaction"] < before["satisfaction"]
    assert all(item["state_name"] != "uncertainty" for item in transitions)


def test_stage2_fatigue_time_curve_accelerates_and_recovery_lowers_it(tmp_path):
    early = AnimaTestHarness(tmp_path / "early")
    early_transition = early.runtime.evaluate_internal_time(
        now=T1,
        mode="awake",
        period_started_at=T0,
    )[0]

    late = AnimaTestHarness(tmp_path / "late")
    late.runtime.evaluate_internal_time(
        now=T7,
        mode="awake",
        period_started_at=T0,
    )
    late_transition = late.runtime.evaluate_internal_time(
        now=T8,
        mode="awake",
        period_started_at=T0,
    )[0]
    beyond_transition = late.runtime.evaluate_internal_time(
        now=T9,
        mode="awake",
        period_started_at=T0,
    )[0]
    before_recovery = late.internal_state_store.get_state("fatigue")["value"]
    late.runtime.evaluate_internal_time(
        now=T10,
        mode="recovery",
        period_started_at=T9,
    )
    after_recovery = late.internal_state_store.get_state("fatigue")["value"]

    assert late_transition["delta"] > early_transition["delta"]
    assert beyond_transition["delta"] >= late_transition["delta"]
    assert after_recovery < before_recovery


def test_stage2_repeated_failure_escalates_and_strategy_change_resets_series(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)

    failures = []
    for index in range(3):
        transition = _signal(
            anima,
            SignalKind.FAILURE,
            f"failure_series_{index}",
            goal_id=goal["id"],
            candidate_id="candidate_a",
        )[0]
        failures.append(transition)

    _signal(
        anima,
        SignalKind.STRATEGY_CHANGED,
        "strategy_changed",
        goal_id=goal["id"],
        candidate_id="candidate_a",
        timestamp=T2,
    )
    reset_failure = _signal(
        anima,
        SignalKind.FAILURE,
        "failure_after_strategy_change",
        goal_id=goal["id"],
        candidate_id="candidate_a",
        timestamp=T3,
    )[0]

    assert [item["repetition_factor"] for item in failures] == [1.0, 1.5, 2.0]
    assert failures[0]["delta"] < failures[1]["delta"] < failures[2]["delta"]
    assert reset_failure["repetition_factor"] == 1.0


def test_stage2_repeated_verified_progress_has_diminishing_satisfaction(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)

    satisfaction = []
    for index in range(3):
        transitions = _signal(
            anima,
            SignalKind.VERIFIED_PROGRESS,
            f"verified_progress_{index}",
            importance=2,
            goal_id=goal["id"],
            candidate_id="candidate_a",
        )
        satisfaction.append(
            next(item for item in transitions if item["state_name"] == "satisfaction")
        )

    assert satisfaction[0]["repetition_factor"] > satisfaction[1]["repetition_factor"]
    assert satisfaction[1]["repetition_factor"] > satisfaction[2]["repetition_factor"]
    assert satisfaction[0]["delta"] > satisfaction[1]["delta"] > satisfaction[2]["delta"]


def test_stage2_goal_arbitration_respects_lifecycle_not_internal_state(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    low = _goal(anima, "low", priority=1.0)
    high = _goal(anima, "high", priority=5.0)

    assert anima.runtime.arbitrate_goals().selected_goal_id == high["id"]

    _observation(
        anima,
        high["id"],
        GoalObservationKind.BLOCKED,
        "high_blocked",
        candidate_id="candidate_high",
    )
    assert anima.runtime.arbitrate_goals().selected_goal_id == low["id"]

    _observation(
        anima,
        high["id"],
        GoalObservationKind.REACTIVATED,
        "high_reactivated",
        timestamp=T3,
    )
    assert anima.runtime.arbitrate_goals().selected_goal_id == high["id"]

    _observation(
        anima,
        high["id"],
        GoalObservationKind.SUCCESS,
        "high_completed",
        candidate_id="candidate_high",
        criterion_satisfied=True,
        timestamp=T3,
    )
    assert anima.runtime.arbitrate_goals().selected_goal_id == low["id"]

    anima.internal_state.goals.transition_goal(
        low["id"],
        to_status="cancelled",
        reason="validation cancellation",
        source_id="low_cancelled",
        timestamp=T3,
    )
    assert anima.runtime.arbitrate_goals().selected_goal_id is None

    with pytest.raises(ValueError, match="active Goal"):
        anima.runtime.choose(high["id"], _decision_candidates())


def test_stage2_expression_is_state_dependent_and_read_only(tmp_path):
    neutral = AnimaTestHarness(tmp_path / "neutral")
    altered = AnimaTestHarness(tmp_path / "altered")
    goal = _goal(altered)

    _signal(altered, SignalKind.INFORMATION_CONFLICT, "expression_uncertainty", importance=3)
    _signal(
        altered,
        SignalKind.FAILURE,
        "expression_failure",
        goal_id=goal["id"],
        candidate_id="candidate_a",
    )
    _signal(
        altered,
        SignalKind.VERIFIED_PROGRESS,
        "expression_progress",
        importance=2,
        goal_id=goal["id"],
        candidate_id="candidate_a",
    )

    neutral_profile = neutral.snapshot()["internal_state"]["expression"]["profile"]
    before_count = altered.internal_state_store.transition_count()
    before_states = altered.snapshot()["internal_state"]["states"]
    first = altered.internal_state.expression_adapter.build_profile()
    second = altered.internal_state.expression_adapter.build_profile()
    after_states = altered.snapshot()["internal_state"]["states"]

    assert first["profile"].caution > neutral_profile["caution"]
    assert first["profile"].positive_affect > neutral_profile["positive_affect"]
    assert first == second
    assert altered.internal_state_store.transition_count() == before_count
    assert after_states == before_states


def test_stage2_causal_history_and_choice_trace_are_reconstructable(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)

    _signal(anima, SignalKind.WORKLOAD_NORMAL, "trace_workload")
    _signal(anima, SignalKind.INFORMATION_GAP, "trace_uncertainty", importance=2)
    _signal(
        anima,
        SignalKind.FAILURE,
        "trace_failure",
        goal_id=goal["id"],
        candidate_id="candidate_a",
    )

    history = anima.internal_state_store.list_state_transitions()
    assert history
    for item in history:
        assert math.isclose(item["before"] + item["delta"], item["after"], abs_tol=1e-12)
        assert 0.0 <= item["before"] <= 1.0
        assert 0.0 <= item["after"] <= 1.0
        assert item["cause_type"]
        assert item["rule_id"]
        assert item["reason"]

    choice = anima.runtime.choose(goal["id"], _decision_candidates())
    for evaluation in choice["evaluations"]:
        modifier_sum = sum(item["contribution"] for item in evaluation["modifiers"])
        assert math.isclose(modifier_sum, evaluation["modifier_total"], abs_tol=1e-12)
        assert math.isclose(
            evaluation["base_score"] + evaluation["modifier_total"],
            evaluation["unclamped_score"],
            abs_tol=1e-12,
        )
        assert math.isclose(
            evaluation["unclamped_score"] + evaluation["clamp_delta"],
            evaluation["final_score"],
            abs_tol=1e-12,
        )
        for modifier in evaluation["modifiers"]:
            assert abs(modifier["contribution"]) <= modifier["bound"] + 1e-12


def test_stage2_restart_replay_is_idempotent_and_has_no_time_drift(tmp_path):
    first = AnimaTestHarness(tmp_path)
    signal = StateSignal(
        kind=SignalKind.INFORMATION_GAP,
        source_id="restart_information_gap",
        reason="restart validation information gap",
        importance=2,
        timestamp=T1,
    )
    initial = first.runtime.process_state_signal(signal)
    first.runtime.evaluate_internal_time(
        now=T3,
        mode="awake",
        period_started_at=T1,
    )
    before = first.snapshot()["internal_state"]

    reopened = AnimaTestHarness(tmp_path)
    replay = reopened.runtime.process_state_signal(signal)
    repeated_time = reopened.runtime.evaluate_internal_time(
        now=T3,
        mode="awake",
        period_started_at=T1,
    )
    after = reopened.snapshot()["internal_state"]

    assert [item["id"] for item in replay] == [item["id"] for item in initial]
    assert repeated_time == ()
    assert after["states"] == before["states"]
    assert after["state_transition_count"] == before["state_transition_count"]


def test_stage2_unverified_result_cannot_mutate_goal_or_state(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal = _goal(anima)
    before = anima.snapshot()["internal_state"]

    with pytest.raises(ValueError, match="Unverified Goal observations"):
        _observation(
            anima,
            goal["id"],
            GoalObservationKind.PROGRESS,
            "unverified_progress",
            candidate_id="candidate_a",
            verification=VerificationKind.UNVERIFIED,
        )

    after = anima.snapshot()["internal_state"]
    assert after["states"] == before["states"]
    assert after["state_transition_count"] == before["state_transition_count"]
    assert anima.internal_state.goals.get_goal(goal["id"])["status"] == "active"


def test_stage2_headless_canonical_scenario_exposes_full_decision_chain(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    goal_id = "goal_11111111-1111-4111-8111-111111111111"
    transition_id = "gt_22222222-2222-4222-8222-222222222222"

    results = anima.run_scenario(
        [
            {"action": "wake"},
            {"action": "user_input", "text": "Stage 2 canonical validation event"},
            {
                "action": "goal_create",
                "source": "validation",
                "priority": 3.0,
                "description": "Resolve canonical Stage 2 situation",
                "success_criterion": "verified progress is observed",
                "reason": "canonical validation goal",
                "source_id": "scenario_goal_source",
                "timestamp": T0,
                "goal_id": goal_id,
                "transition_id": transition_id,
            },
            {
                "action": "state_signal",
                "kind": "information_conflict",
                "source_id": "scenario_conflict_1",
                "reason": "conflicting evidence",
                "importance": 3,
                "timestamp": T1,
            },
            {
                "action": "state_signal",
                "kind": "information_conflict",
                "source_id": "scenario_conflict_2",
                "reason": "more conflicting evidence",
                "importance": 3,
                "timestamp": T1,
            },
            {
                "action": "choice",
                "goal_id": goal_id,
                "candidates": [
                    {
                        "candidate_id": "act_now",
                        "base_score": 0.72,
                        "irreversible_risk": 1.0,
                    },
                    {
                        "candidate_id": "inspect_first",
                        "base_score": 0.65,
                        "information_gain": 1.0,
                    },
                ],
            },
            {
                "action": "goal_observation",
                "goal_id": goal_id,
                "kind": "progress",
                "source_id": "scenario_verified_progress",
                "reason": "inspection produced verified progress",
                "verification": "confirmed_result",
                "candidate_id": "inspect_first",
                "importance": 2,
                "timestamp": T2,
            },
            {"action": "snapshot"},
            {"action": "sleep"},
        ]
    )

    choice_result = results[5]
    snapshot = results[7]["snapshot"]
    internal = snapshot["internal_state"]

    assert choice_result["selected_candidate_id"] == "inspect_first"
    assert internal["states"]["uncertainty"] > 0.0
    assert internal["states"]["satisfaction"] > 0.0
    assert internal["last_choice"]["selected_candidate_id"] == "inspect_first"
    assert internal["goals"][0]["status"] == "active"
    assert internal["expression"]["profile"]["caution"] > 0.0
    assert snapshot["memory"]["count"] == 1
    assert snapshot["state"]["events_processed"] == 2

    print("\nStage 2 canonical validation summary:")
    print(f"  selected candidate: {internal['last_choice']['selected_candidate_id']}")
    print(f"  states: {internal['states']}")
    print(f"  transitions: {internal['state_transition_count']}")
    print(f"  active goal: {internal['goal_arbitration']['selected_goal_id']}")
    print(f"  expression: {internal['expression']['profile']}")
