import json

import pytest

from anima.internal_state.store import InternalStateStore
from anima.internal_state.transition_engine import (
    SignalKind,
    StateSignal,
    TransitionEngine,
)
from anima.internal_state.transition_rules import (
    load_transition_rules_config,
    validate_transition_rules_config,
)


T1 = "2026-10-26T18:00:00+00:00"
T2 = "2026-10-26T18:01:00+00:00"
T3 = "2026-10-26T18:02:00+00:00"
T4 = "2026-10-26T18:03:00+00:00"


def make_engine(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    return store, TransitionEngine(store)


def signal(kind, *, source="ev_test", reason="test", importance=1,
           goal=None, candidate=None, timestamp=T1):
    return StateSignal(
        kind=kind,
        source_id=source,
        reason=reason,
        importance=importance,
        goal_id=goal,
        candidate_id=candidate,
        timestamp=timestamp,
    )


def test_transition_rules_config_loads():
    config = load_transition_rules_config()
    assert config["schema_version"] == 1
    assert config["ruleset_version"] == 1
    assert config["deltas"]["workload_low"] < config["deltas"]["workload_normal"]
    assert config["deltas"]["workload_normal"] < config["deltas"]["workload_high"]


def test_transition_rules_reject_wrong_delta_sign():
    config = load_transition_rules_config()
    broken = json.loads(json.dumps(config))
    broken["deltas"]["failure"] = -0.1

    with pytest.raises(ValueError, match="failure must be positive"):
        validate_transition_rules_config(broken)


def test_workload_levels_raise_fatigue_by_distinct_amounts(tmp_path):
    deltas = []
    for kind in (
        SignalKind.WORKLOAD_LOW,
        SignalKind.WORKLOAD_NORMAL,
        SignalKind.WORKLOAD_HIGH,
    ):
        case = tmp_path / kind.value
        case.mkdir()
        store = InternalStateStore(case / "state.db")
        engine = TransitionEngine(store)
        transition = engine.process(signal(kind))[0]
        deltas.append(transition["delta"])

    assert deltas[0] < deltas[1] < deltas[2]


def test_uncertainty_importance_changes_delta(tmp_path):
    low_dir = tmp_path / "low"
    high_dir = tmp_path / "high"
    low_dir.mkdir()
    high_dir.mkdir()

    low_store = InternalStateStore(low_dir / "state.db")
    high_store = InternalStateStore(high_dir / "state.db")
    low = TransitionEngine(low_store).process(
        signal(SignalKind.INFORMATION_GAP, importance=0)
    )[0]
    high = TransitionEngine(high_store).process(
        signal(SignalKind.INFORMATION_GAP, importance=3)
    )[0]

    assert high["delta"] > low["delta"] > 0.0


def test_direct_confirmation_reduces_uncertainty_more_than_indirect(tmp_path):
    direct_dir = tmp_path / "direct"
    indirect_dir = tmp_path / "indirect"
    direct_dir.mkdir()
    indirect_dir.mkdir()

    direct_store = InternalStateStore(direct_dir / "state.db")
    indirect_store = InternalStateStore(indirect_dir / "state.db")
    for store in (direct_store, indirect_store):
        store.apply_state_transition(
            state_name="uncertainty",
            delta=0.5,
            cause_type="test",
            source_id="seed",
            rule_id="test.seed",
            reason="seed",
            timestamp=T1,
        )

    direct = TransitionEngine(direct_store).process(
        signal(
            SignalKind.INFORMATION_CONFIRMED_DIRECT,
            source="result_direct",
            timestamp=T2,
        )
    )[0]
    indirect = TransitionEngine(indirect_store).process(
        signal(
            SignalKind.INFORMATION_CONFIRMED_INDIRECT,
            source="result_indirect",
            timestamp=T2,
        )
    )[0]

    assert abs(direct["delta"]) > abs(indirect["delta"])
    assert direct["delta"] < 0.0
    assert indirect["delta"] < 0.0


def test_repeated_failure_escalates_with_bounded_factor(tmp_path):
    store, engine = make_engine(tmp_path)
    factors = []
    deltas = []

    for index, timestamp in enumerate((T1, T2, T3), start=1):
        transition = engine.process(
            signal(
                SignalKind.FAILURE,
                source=f"result_{index}",
                goal="goal_a",
                candidate="candidate_a",
                timestamp=timestamp,
            )
        )[0]
        factors.append(transition["repetition_factor"])
        deltas.append(transition["delta"])

    assert factors == [1.0, 1.5, 2.0]
    assert deltas[0] < deltas[1] < deltas[2]


def test_progress_breaks_failure_series(tmp_path):
    store, engine = make_engine(tmp_path)

    first = engine.process(
        signal(
            SignalKind.FAILURE,
            source="fail_1",
            goal="goal_a",
            candidate="candidate_a",
            timestamp=T1,
        )
    )[0]
    second = engine.process(
        signal(
            SignalKind.FAILURE,
            source="fail_2",
            goal="goal_a",
            candidate="candidate_a",
            timestamp=T2,
        )
    )[0]

    engine.process(
        signal(
            SignalKind.PROGRESS,
            source="progress",
            goal="goal_a",
            candidate="candidate_a",
            timestamp=T3,
        )
    )
    after_progress = engine.process(
        signal(
            SignalKind.FAILURE,
            source="fail_3",
            goal="goal_a",
            candidate="candidate_a",
            timestamp=T4,
        )
    )[0]

    assert first["repetition_factor"] == 1.0
    assert second["repetition_factor"] == 1.5
    assert after_progress["repetition_factor"] == 1.0


def test_new_candidate_has_separate_failure_series(tmp_path):
    store, engine = make_engine(tmp_path)

    engine.process(
        signal(
            SignalKind.FAILURE,
            source="fail_a1",
            goal="goal_a",
            candidate="candidate_a",
            timestamp=T1,
        )
    )
    second_a = engine.process(
        signal(
            SignalKind.FAILURE,
            source="fail_a2",
            goal="goal_a",
            candidate="candidate_a",
            timestamp=T2,
        )
    )[0]
    first_b = engine.process(
        signal(
            SignalKind.FAILURE,
            source="fail_b1",
            goal="goal_a",
            candidate="candidate_b",
            timestamp=T3,
        )
    )[0]

    assert second_a["repetition_factor"] == 1.5
    assert first_b["repetition_factor"] == 1.0


def test_verified_progress_changes_frustration_and_satisfaction(tmp_path):
    store, engine = make_engine(tmp_path)
    engine.process(
        signal(
            SignalKind.FAILURE,
            source="failure",
            goal="goal_a",
            candidate="candidate_a",
            timestamp=T1,
        )
    )

    transitions = engine.process(
        signal(
            SignalKind.VERIFIED_PROGRESS,
            source="progress",
            reason="verified progress",
            importance=2,
            goal="goal_a",
            candidate="candidate_a",
            timestamp=T2,
        )
    )

    assert [item["state_name"] for item in transitions] == [
        "frustration",
        "satisfaction",
    ]
    assert transitions[0]["delta"] < 0.0
    assert transitions[1]["delta"] > 0.0
    assert {item["source_id"] for item in transitions} == {"progress"}


def test_repeated_verified_success_has_diminishing_satisfaction(tmp_path):
    store, engine = make_engine(tmp_path)
    satisfaction_factors = []

    for index, timestamp in enumerate((T1, T2, T3), start=1):
        transitions = engine.process(
            signal(
                SignalKind.VERIFIED_SUCCESS,
                source=f"success_{index}",
                importance=1,
                goal="goal_a",
                candidate="candidate_a",
                timestamp=timestamp,
            )
        )
        satisfaction = next(
            item for item in transitions
            if item["state_name"] == "satisfaction"
        )
        satisfaction_factors.append(satisfaction["repetition_factor"])

    assert satisfaction_factors[0] == 1.0
    assert satisfaction_factors[0] > satisfaction_factors[1] > satisfaction_factors[2]


def test_success_importance_changes_satisfaction_delta(tmp_path):
    low_dir = tmp_path / "low"
    high_dir = tmp_path / "high"
    low_dir.mkdir()
    high_dir.mkdir()

    low_store = InternalStateStore(low_dir / "state.db")
    high_store = InternalStateStore(high_dir / "state.db")

    low = next(
        item for item in TransitionEngine(low_store).process(
            signal(
                SignalKind.VERIFIED_SUCCESS,
                importance=0,
                goal="goal_a",
                candidate="candidate_a",
            )
        )
        if item["state_name"] == "satisfaction"
    )
    high = next(
        item for item in TransitionEngine(high_store).process(
            signal(
                SignalKind.VERIFIED_SUCCESS,
                importance=3,
                goal="goal_a",
                candidate="candidate_a",
            )
        )
        if item["state_name"] == "satisfaction"
    )

    assert high["delta"] > low["delta"] > 0.0


def test_engine_clamps_effect_to_state_boundary(tmp_path):
    store, engine = make_engine(tmp_path)
    store.apply_state_transition(
        state_name="fatigue",
        delta=0.98,
        cause_type="test",
        source_id="seed",
        rule_id="test.seed",
        reason="seed",
        timestamp=T1,
    )

    transition = engine.process(
        signal(
            SignalKind.WORKLOAD_HIGH,
            source="load",
            timestamp=T2,
        )
    )[0]

    assert transition["before"] == 0.98
    assert transition["after"] == 1.0
    assert transition["delta"] == pytest.approx(0.02)


def test_repetition_sensitive_signal_requires_scope(tmp_path):
    _, engine = make_engine(tmp_path)

    with pytest.raises(ValueError, match="requires goal_id and candidate_id"):
        engine.process(signal(SignalKind.FAILURE))


def test_same_state_and_signal_produce_same_delta(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    first_store = InternalStateStore(first_dir / "state.db")
    second_store = InternalStateStore(second_dir / "state.db")
    first = TransitionEngine(first_store).process(
        signal(
            SignalKind.INFORMATION_CONFLICT,
            source="same_source",
            importance=2,
        )
    )[0]
    second = TransitionEngine(second_store).process(
        signal(
            SignalKind.INFORMATION_CONFLICT,
            source="same_source",
            importance=2,
        )
    )[0]

    assert first["delta"] == second["delta"]
    assert first["after"] == second["after"]
    assert first["rule_id"] == second["rule_id"]


def test_stage25_transitions_do_not_apply_time_dynamics(tmp_path):
    store, engine = make_engine(tmp_path)

    transition = engine.process(
        signal(
            SignalKind.WORKLOAD_NORMAL,
            source="work",
        )
    )[0]

    assert transition["elapsed_seconds"] is None
