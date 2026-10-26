import json

import pytest

from anima.internal_state.choice_engine import Candidate, ChoiceEngine
from anima.internal_state.choice_rules import (
    load_choice_rules_config,
    validate_choice_rules_config,
)
from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore


T1 = "2026-10-26T20:00:00+00:00"
T2 = "2026-10-26T20:01:00+00:00"


def _setup(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    goals = GoalStore(store)
    goal = goals.create_goal(
        source="test",
        priority=1.0,
        description="choose a route",
        success_criterion="route produces the expected result",
        reason="choice test",
        timestamp=T1,
    )
    return store, goals, goal, ChoiceEngine(store, goal_store=goals)


def _seed(store, state_name, value):
    return store.apply_state_transition(
        state_name=state_name,
        delta=value,
        cause_type="test",
        source_id=f"seed_{state_name}",
        rule_id=f"test.seed.{state_name}",
        reason="seed Choice Engine state",
        timestamp=T1,
    )


def _evaluation(result, candidate_id):
    return next(
        item for item in result["evaluations"]
        if item["candidate_id"] == candidate_id
    )


def _modifier(evaluation, name):
    return next(item for item in evaluation["modifiers"] if item["name"] == name)


def test_choice_rules_config_loads_and_satisfaction_is_weakest():
    config = load_choice_rules_config()
    weights = config["weights"]

    satisfaction = weights["satisfaction_verified_continuation"]
    assert satisfaction < min(
        value for name, value in weights.items()
        if name != "satisfaction_verified_continuation"
    )


def test_choice_rules_reject_strong_satisfaction_weight():
    config = load_choice_rules_config()
    broken = json.loads(json.dumps(config))
    broken["weights"]["satisfaction_verified_continuation"] = 0.20

    with pytest.raises(ValueError, match="must remain weaker"):
        validate_choice_rules_config(broken)


def test_neutral_state_preserves_base_evaluation(tmp_path):
    _, _, goal, engine = _setup(tmp_path)
    result = engine.choose(
        goal["id"],
        [
            Candidate("candidate_a", 0.70, effort_cost=1.0),
            Candidate("candidate_b", 0.60, information_gain=1.0),
        ],
    )

    assert result["selected_candidate_id"] == "candidate_a"
    for evaluation in result["evaluations"]:
        assert evaluation["modifier_total"] == 0.0
        assert evaluation["final_score"] == evaluation["base_score"]


def test_high_fatigue_can_prefer_lower_effort_candidate(tmp_path):
    store, _, goal, engine = _setup(tmp_path)
    _seed(store, "fatigue", 1.0)

    result = engine.choose(
        goal["id"],
        [
            Candidate("expensive", 0.75, effort_cost=1.0),
            Candidate("cheap", 0.65, effort_cost=0.0),
        ],
    )

    assert result["selected_candidate_id"] == "cheap"
    penalty = _modifier(_evaluation(result, "expensive"), "fatigue_effort_penalty")
    assert penalty["contribution"] == pytest.approx(-0.25)


def test_uncertainty_rewards_information_gain(tmp_path):
    store, _, goal, engine = _setup(tmp_path)
    _seed(store, "uncertainty", 1.0)

    result = engine.choose(
        goal["id"],
        [
            Candidate("act_now", 0.70),
            Candidate("inspect", 0.55, information_gain=1.0),
        ],
    )

    assert result["selected_candidate_id"] == "inspect"
    bonus = _modifier(
        _evaluation(result, "inspect"),
        "uncertainty_information_gain_bonus",
    )
    assert bonus["contribution"] == pytest.approx(0.20)


def test_uncertainty_penalizes_irreversible_risk(tmp_path):
    store, _, goal, engine = _setup(tmp_path)
    _seed(store, "uncertainty", 1.0)

    result = engine.choose(
        goal["id"],
        [
            Candidate("risky", 0.75, irreversible_risk=1.0),
            Candidate("reversible", 0.65),
        ],
    )

    assert result["selected_candidate_id"] == "reversible"
    penalty = _modifier(
        _evaluation(result, "risky"),
        "uncertainty_irreversible_risk_penalty",
    )
    assert penalty["contribution"] == pytest.approx(-0.20)


def test_frustration_discourages_failed_strategy_and_supports_alternative(tmp_path):
    store, _, goal, engine = _setup(tmp_path)
    _seed(store, "frustration", 1.0)

    result = engine.choose(
        goal["id"],
        [
            Candidate("repeat", 0.75, repeated_failure=1.0),
            Candidate("alternative", 0.55, alternative_value=1.0),
        ],
    )

    assert result["selected_candidate_id"] == "alternative"
    repeat_penalty = _modifier(
        _evaluation(result, "repeat"),
        "frustration_repeated_failure_penalty",
    )
    alternative_bonus = _modifier(
        _evaluation(result, "alternative"),
        "frustration_alternative_bonus",
    )
    assert repeat_penalty["contribution"] == pytest.approx(-0.25)
    assert alternative_bonus["contribution"] == pytest.approx(0.15)


def test_satisfaction_only_adds_small_verified_continuation_bonus(tmp_path):
    store, _, goal, engine = _setup(tmp_path)
    _seed(store, "satisfaction", 1.0)

    result = engine.choose(
        goal["id"],
        [
            Candidate("continue", 0.50, verified_continuation=1.0),
            Candidate("other", 0.54),
        ],
    )

    assert result["selected_candidate_id"] == "continue"
    bonus = _modifier(
        _evaluation(result, "continue"),
        "satisfaction_verified_continuation_bonus",
    )
    assert bonus["contribution"] == pytest.approx(0.06)


def test_every_modifier_is_bounded_by_configured_weight(tmp_path):
    store, _, goal, engine = _setup(tmp_path)
    for state_name in ("fatigue", "uncertainty", "frustration", "satisfaction"):
        _seed(store, state_name, 1.0)

    result = engine.choose(
        goal["id"],
        [
            Candidate(
                "all_features",
                0.50,
                effort_cost=1.0,
                information_gain=1.0,
                irreversible_risk=1.0,
                repeated_failure=1.0,
                alternative_value=1.0,
                verified_continuation=1.0,
            )
        ],
    )

    evaluation = result["evaluations"][0]
    for modifier in evaluation["modifiers"]:
        assert abs(modifier["contribution"]) <= modifier["bound"]


def test_score_trace_reconstructs_clamped_final_score(tmp_path):
    store, _, goal, engine = _setup(tmp_path)
    _seed(store, "uncertainty", 1.0)
    _seed(store, "frustration", 1.0)
    _seed(store, "satisfaction", 1.0)

    result = engine.choose(
        goal["id"],
        [
            Candidate(
                "positive",
                0.95,
                information_gain=1.0,
                alternative_value=1.0,
                verified_continuation=1.0,
            )
        ],
    )
    evaluation = result["evaluations"][0]

    assert evaluation["unclamped_score"] > 1.0
    assert evaluation["final_score"] == 1.0
    assert (
        evaluation["base_score"]
        + evaluation["modifier_total"]
        + evaluation["clamp_delta"]
    ) == pytest.approx(evaluation["final_score"])
    assert sum(
        item["contribution"] for item in evaluation["modifiers"]
    ) == pytest.approx(evaluation["modifier_total"])


def test_score_is_clamped_at_lower_boundary(tmp_path):
    store, _, goal, engine = _setup(tmp_path)
    _seed(store, "fatigue", 1.0)
    _seed(store, "frustration", 1.0)

    result = engine.choose(
        goal["id"],
        [Candidate("bad", 0.10, effort_cost=1.0, repeated_failure=1.0)],
    )

    evaluation = result["evaluations"][0]
    assert evaluation["unclamped_score"] < 0.0
    assert evaluation["final_score"] == 0.0


def test_tie_break_is_deterministic_by_candidate_id(tmp_path):
    _, _, goal, engine = _setup(tmp_path)

    result = engine.choose(
        goal["id"],
        [Candidate("candidate_b", 0.5), Candidate("candidate_a", 0.5)],
    )

    assert result["selected_candidate_id"] == "candidate_a"
    assert [item["candidate_id"] for item in result["evaluations"]] == [
        "candidate_a",
        "candidate_b",
    ]


def test_duplicate_candidate_ids_are_rejected(tmp_path):
    _, _, goal, engine = _setup(tmp_path)

    with pytest.raises(ValueError, match="must be unique"):
        engine.choose(
            goal["id"],
            [Candidate("same", 0.5), Candidate("same", 0.4)],
        )


def test_invalid_candidate_feature_is_rejected(tmp_path):
    _, _, goal, engine = _setup(tmp_path)

    with pytest.raises(ValueError, match="effort_cost"):
        engine.choose(goal["id"], [Candidate("bad", 0.5, effort_cost=1.1)])


def test_choice_requires_at_least_one_candidate(tmp_path):
    _, _, goal, engine = _setup(tmp_path)

    with pytest.raises(ValueError, match="at least one Candidate"):
        engine.choose(goal["id"], [])


def test_choice_rejects_non_active_goal(tmp_path):
    _, goals, goal, engine = _setup(tmp_path)
    goals.transition_goal(
        goal["id"],
        to_status="completed",
        reason="verified complete",
        timestamp=T2,
    )

    with pytest.raises(ValueError, match="requires an active Goal"):
        engine.choose(goal["id"], [Candidate("candidate", 0.5)])


def test_choice_is_read_only_for_goals_state_and_candidates(tmp_path):
    store, goals, goal, engine = _setup(tmp_path)
    _seed(store, "fatigue", 0.5)
    candidates = [
        Candidate("candidate_a", 0.6, effort_cost=0.5),
        Candidate("candidate_b", 0.5),
    ]
    states_before = store.list_states()
    transitions_before = store.transition_count()
    goals_before = goals.goal_count()
    goal_history_before = len(goals.list_goal_transitions(goal_id=goal["id"]))

    result = engine.choose(goal["id"], candidates)

    assert store.list_states() == states_before
    assert store.transition_count() == transitions_before
    assert goals.goal_count() == goals_before
    assert len(goals.list_goal_transitions(goal_id=goal["id"])) == goal_history_before
    assert {item["candidate_id"] for item in result["evaluations"]} == {
        candidate.candidate_id for candidate in candidates
    }


def test_same_state_and_candidates_produce_same_choice_after_reopen(tmp_path):
    database = tmp_path / "internal_state.db"
    store = InternalStateStore(database)
    goals = GoalStore(store)
    goal = goals.create_goal(
        source="test",
        priority=1.0,
        description="stable choice",
        success_criterion="same result",
        reason="reopen test",
        timestamp=T1,
    )
    _seed(store, "uncertainty", 0.7)
    candidates = [
        Candidate("inspect", 0.55, information_gain=0.9),
        Candidate("act", 0.62, irreversible_risk=0.8),
    ]

    first = ChoiceEngine(store, goal_store=goals).choose(goal["id"], candidates)

    reopened = InternalStateStore(database)
    second = ChoiceEngine(reopened).choose(goal["id"], candidates)

    assert second == first
