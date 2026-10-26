import json

import pytest

from anima.internal_state.store import InternalStateStore
from anima.internal_state.time_dynamics import TimeDynamics
from anima.internal_state.time_rules import validate_time_rules_config


START = "2026-10-26T00:00:00+00:00"
HOUR_1 = "2026-10-26T01:00:00+00:00"
HOUR_2 = "2026-10-26T02:00:00+00:00"
HOUR_3 = "2026-10-26T03:00:00+00:00"
HOUR_4 = "2026-10-26T04:00:00+00:00"
HOUR_6 = "2026-10-26T06:00:00+00:00"
HOUR_7 = "2026-10-26T07:00:00+00:00"
HOUR_8 = "2026-10-26T08:00:00+00:00"
HOUR_9 = "2026-10-26T09:00:00+00:00"


def _engine(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    return store, TimeDynamics(store)


def _seed(store, state_name, value, timestamp=START):
    return store.apply_state_transition(
        state_name=state_name,
        delta=value,
        cause_type="test",
        rule_id=f"test.seed.{state_name}",
        reason="seed state for time dynamics test",
        timestamp=timestamp,
    )


def test_awake_fatigue_growth_accelerates_near_work_period_limit(tmp_path):
    store, dynamics = _engine(tmp_path)

    dynamics.evaluate(now=HOUR_1, mode="awake", period_started_at=START)
    early_hour_delta = store.get_state("fatigue")["value"]

    dynamics.evaluate(now=HOUR_7, mode="awake", period_started_at=START)
    before_last_hour = store.get_state("fatigue")["value"]
    dynamics.evaluate(now=HOUR_8, mode="awake", period_started_at=START)
    near_limit_delta = store.get_state("fatigue")["value"] - before_last_hour

    assert near_limit_delta > early_hour_delta


def test_awake_fatigue_growth_is_stronger_beyond_work_period(tmp_path):
    store, dynamics = _engine(tmp_path)

    dynamics.evaluate(now=HOUR_8, mode="awake", period_started_at=START)
    before_beyond = store.get_state("fatigue")["value"]
    dynamics.evaluate(now=HOUR_9, mode="awake", period_started_at=START)

    beyond_delta = store.get_state("fatigue")["value"] - before_beyond
    assert beyond_delta == pytest.approx(0.07)


def test_workload_transition_does_not_erase_unapplied_awake_time(tmp_path):
    store, dynamics = _engine(tmp_path)
    store.apply_state_transition(
        state_name="fatigue",
        delta=0.1,
        cause_type="event",
        source_id="ev_workload",
        rule_id="stage2.fatigue.workload_normal.v1",
        reason="workload before first time evaluation",
        timestamp=HOUR_2,
    )

    transitions = dynamics.evaluate(
        now=HOUR_3,
        mode="awake",
        period_started_at=START,
    )

    fatigue = next(item for item in transitions if item["state_name"] == "fatigue")
    assert store.get_state("fatigue")["value"] == pytest.approx(0.13)
    assert fatigue["elapsed_seconds"] == 10800.0


def test_recovery_mode_reduces_fatigue_and_records_elapsed_time(tmp_path):
    store, dynamics = _engine(tmp_path)
    _seed(store, "fatigue", 0.5)

    transitions = dynamics.evaluate(
        now=HOUR_2,
        mode="recovery",
        period_started_at=START,
    )

    fatigue = next(item for item in transitions if item["state_name"] == "fatigue")
    assert store.get_state("fatigue")["value"] == pytest.approx(0.34)
    assert fatigue["cause_type"] == "time"
    assert fatigue["elapsed_seconds"] == 7200.0
    assert fatigue["rule_id"] == "stage2.fatigue.time_recovery.v1"


def test_frustration_recovers_toward_baseline_without_overshoot(tmp_path):
    store, dynamics = _engine(tmp_path)
    _seed(store, "frustration", 0.05)

    dynamics.evaluate(now=HOUR_2, mode="awake", period_started_at=START)

    assert store.get_state("frustration")["value"] == 0.0


def test_satisfaction_decays_toward_baseline_without_overshoot(tmp_path):
    store, dynamics = _engine(tmp_path)
    _seed(store, "satisfaction", 0.05)

    dynamics.evaluate(now=HOUR_2, mode="recovery", period_started_at=START)

    assert store.get_state("satisfaction")["value"] == 0.0


def test_uncertainty_does_not_change_from_elapsed_time(tmp_path):
    store, dynamics = _engine(tmp_path)
    _seed(store, "uncertainty", 0.6)
    count_before = store.transition_count("uncertainty")

    transitions = dynamics.evaluate(
        now=HOUR_9,
        mode="awake",
        period_started_at=START,
    )

    assert store.get_state("uncertainty")["value"] == 0.6
    assert store.transition_count("uncertainty") == count_before
    assert all(item["state_name"] != "uncertainty" for item in transitions)


def test_same_evaluation_time_is_idempotent_and_adds_no_history(tmp_path):
    store, dynamics = _engine(tmp_path)

    dynamics.evaluate(now=HOUR_2, mode="awake", period_started_at=START)
    snapshot = {item["name"]: item["value"] for item in store.list_states()}
    count = store.transition_count()

    assert dynamics.evaluate(now=HOUR_2, mode="awake", period_started_at=START) == ()
    assert {item["name"]: item["value"] for item in store.list_states()} == snapshot
    assert store.transition_count() == count


def test_split_evaluations_match_one_shot_evaluation(tmp_path):
    one_store = InternalStateStore(tmp_path / "one.db")
    split_store = InternalStateStore(tmp_path / "split.db")
    _seed(one_store, "frustration", 0.5)
    _seed(one_store, "satisfaction", 0.5)
    _seed(split_store, "frustration", 0.5)
    _seed(split_store, "satisfaction", 0.5)

    one = TimeDynamics(one_store)
    split = TimeDynamics(split_store)

    one.evaluate(now=HOUR_8, mode="awake", period_started_at=START)
    for timestamp in (HOUR_2, HOUR_4, HOUR_6, HOUR_8):
        split.evaluate(now=timestamp, mode="awake", period_started_at=START)

    one_snapshot = {item["name"]: item["value"] for item in one_store.list_states()}
    split_snapshot = {item["name"]: item["value"] for item in split_store.list_states()}
    assert split_snapshot == pytest.approx(one_snapshot)


def test_reopen_continues_from_last_persisted_transition_without_drift(tmp_path):
    database = tmp_path / "internal_state.db"
    store = InternalStateStore(database)
    dynamics = TimeDynamics(store)

    dynamics.evaluate(now=HOUR_2, mode="awake", period_started_at=START)
    fatigue_before_restart = store.get_state("fatigue")["value"]

    reopened = InternalStateStore(database)
    resumed = TimeDynamics(reopened)
    transitions = resumed.evaluate(
        now=HOUR_3,
        mode="awake",
        period_started_at=START,
    )

    fatigue = next(item for item in transitions if item["state_name"] == "fatigue")
    assert reopened.get_state("fatigue")["value"] > fatigue_before_restart
    assert fatigue["elapsed_seconds"] == 3600.0


def test_equal_inputs_and_injected_time_produce_equal_state(tmp_path):
    first_store = InternalStateStore(tmp_path / "first.db")
    second_store = InternalStateStore(tmp_path / "second.db")
    _seed(first_store, "frustration", 0.4)
    _seed(first_store, "satisfaction", 0.3)
    _seed(second_store, "frustration", 0.4)
    _seed(second_store, "satisfaction", 0.3)

    TimeDynamics(first_store).evaluate(
        now=HOUR_7,
        mode="awake",
        period_started_at=START,
    )
    TimeDynamics(second_store).evaluate(
        now=HOUR_7,
        mode="awake",
        period_started_at=START,
    )

    first = {item["name"]: item["value"] for item in first_store.list_states()}
    second = {item["name"]: item["value"] for item in second_store.list_states()}
    assert first == second


def test_time_dynamics_clamps_fatigue_at_maximum(tmp_path):
    store, dynamics = _engine(tmp_path)
    _seed(store, "fatigue", 0.98)

    transitions = dynamics.evaluate(
        now=HOUR_9,
        mode="awake",
        period_started_at=START,
    )

    fatigue = next(item for item in transitions if item["state_name"] == "fatigue")
    assert fatigue["after"] == 1.0
    assert store.get_state("fatigue")["value"] == 1.0


def test_zero_elapsed_time_creates_no_time_transitions(tmp_path):
    store, dynamics = _engine(tmp_path)
    _seed(store, "frustration", 0.4)
    before = store.transition_count()

    assert dynamics.evaluate(now=START, mode="awake", period_started_at=START) == ()
    assert store.transition_count() == before


def test_period_start_after_now_is_rejected(tmp_path):
    _, dynamics = _engine(tmp_path)

    with pytest.raises(ValueError, match="cannot be later than now"):
        dynamics.evaluate(
            now=HOUR_1,
            mode="awake",
            period_started_at=HOUR_2,
        )


def test_naive_timestamp_is_rejected(tmp_path):
    _, dynamics = _engine(tmp_path)

    with pytest.raises(ValueError, match="UTC offset"):
        dynamics.evaluate(
            now="2026-10-26T01:00:00",
            mode="awake",
            period_started_at=START,
        )


def test_time_config_requires_work_period_ending_segment(tmp_path):
    config = {
        "schema_version": 1,
        "ruleset_version": 1,
        "awake_work_period_seconds": 28800,
        "fatigue": {
            "awake_segments": [
                {"until_ratio": 0.5, "rate_per_hour": 0.01},
                {"until_ratio": 0.9, "rate_per_hour": 0.02},
            ],
            "beyond_rate_per_hour": 0.07,
            "recovery_rate_per_hour": 0.08,
        },
        "frustration": {"recovery_rate_per_hour": 0.03},
        "satisfaction": {"decay_rate_per_hour": 0.04},
    }

    with pytest.raises(ValueError, match="end at ratio 1.0"):
        validate_time_rules_config(config)


def test_time_ruleset_must_match_store_ruleset(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    config = {
        "schema_version": 1,
        "ruleset_version": 2,
        "awake_work_period_seconds": 28800,
        "fatigue": {
            "awake_segments": [
                {"until_ratio": 1.0, "rate_per_hour": 0.01},
            ],
            "beyond_rate_per_hour": 0.07,
            "recovery_rate_per_hour": 0.08,
        },
        "frustration": {"recovery_rate_per_hour": 0.03},
        "satisfaction": {"decay_rate_per_hour": 0.04},
    }

    with pytest.raises(ValueError, match="must match"):
        TimeDynamics(store, rules_config=config)
