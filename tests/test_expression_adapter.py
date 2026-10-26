from dataclasses import FrozenInstanceError
import json

import pytest

from anima.internal_state.expression_adapter import (
    ExpressionAdapter,
    ExpressionProfile,
)
from anima.internal_state.expression_rules import (
    load_expression_rules_config,
    validate_expression_rules_config,
)
from anima.internal_state.store import InternalStateStore


T1 = "2026-10-26T20:00:00+00:00"


def _setup(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    return store, ExpressionAdapter(store)


def _seed(store, state_name, value):
    return store.apply_state_transition(
        state_name=state_name,
        delta=value,
        cause_type="test",
        source_id=f"seed_{state_name}",
        rule_id=f"test.seed.{state_name}",
        reason="seed Expression Adapter state",
        timestamp=T1,
    )


def _axis(result, axis_name):
    return next(item for item in result["trace"] if item["axis"] == axis_name)


def test_expression_rules_config_loads_with_four_baseline_axes():
    config = load_expression_rules_config()

    assert set(config["axes"]) == {
        "energy",
        "caution",
        "tension",
        "positive_affect",
    }
    assert config["axes"]["energy"]["state"] == "fatigue"
    assert config["axes"]["caution"]["state"] == "uncertainty"
    assert config["axes"]["tension"]["state"] == "frustration"
    assert config["axes"]["positive_affect"]["state"] == "satisfaction"


def test_expression_rules_reject_wrong_state_mapping():
    config = load_expression_rules_config()
    broken = json.loads(json.dumps(config))
    broken["axes"]["energy"]["state"] = "satisfaction"

    with pytest.raises(ValueError, match="must map from"):
        validate_expression_rules_config(broken)


def test_expression_rules_reject_wrong_direction():
    config = load_expression_rules_config()
    broken = json.loads(json.dumps(config))
    broken["axes"]["caution"]["direction"] = -1

    with pytest.raises(ValueError, match="invalid direction"):
        validate_expression_rules_config(broken)


def test_neutral_state_returns_configured_baseline_profile(tmp_path):
    _, adapter = _setup(tmp_path)

    result = adapter.build_profile()

    assert result["profile"] == ExpressionProfile(
        energy=0.5,
        caution=0.0,
        tension=0.0,
        positive_affect=0.0,
    )
    assert all(item["contribution"] == 0.0 for item in result["trace"])


def test_fatigue_reduces_energy_only(tmp_path):
    store, adapter = _setup(tmp_path)
    _seed(store, "fatigue", 1.0)

    profile = adapter.build_profile()["profile"]

    assert profile.energy == 0.0
    assert profile.caution == 0.0
    assert profile.tension == 0.0
    assert profile.positive_affect == 0.0


def test_uncertainty_raises_caution_only(tmp_path):
    store, adapter = _setup(tmp_path)
    _seed(store, "uncertainty", 1.0)

    profile = adapter.build_profile()["profile"]

    assert profile.energy == 0.5
    assert profile.caution == pytest.approx(0.8)
    assert profile.tension == 0.0
    assert profile.positive_affect == 0.0


def test_frustration_raises_tension_only(tmp_path):
    store, adapter = _setup(tmp_path)
    _seed(store, "frustration", 1.0)

    profile = adapter.build_profile()["profile"]

    assert profile.energy == 0.5
    assert profile.caution == 0.0
    assert profile.tension == pytest.approx(0.8)
    assert profile.positive_affect == 0.0


def test_satisfaction_raises_positive_affect_only(tmp_path):
    store, adapter = _setup(tmp_path)
    _seed(store, "satisfaction", 1.0)

    profile = adapter.build_profile()["profile"]

    assert profile.energy == 0.5
    assert profile.caution == 0.0
    assert profile.tension == 0.0
    assert profile.positive_affect == pytest.approx(0.6)


def test_trace_reconstructs_each_axis_value(tmp_path):
    store, adapter = _setup(tmp_path)
    _seed(store, "fatigue", 0.4)
    _seed(store, "uncertainty", 0.5)
    _seed(store, "frustration", 0.6)
    _seed(store, "satisfaction", 0.7)

    result = adapter.build_profile()

    for item in result["trace"]:
        assert (
            item["baseline"]
            + item["contribution"]
            + item["clamp_delta"]
        ) == pytest.approx(item["value"])
    assert result["profile"].as_dict() == {
        item["axis"]: item["value"] for item in result["trace"]
    }


def test_expression_axis_is_clamped_at_lower_boundary(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    _seed(store, "fatigue", 1.0)
    config = load_expression_rules_config()
    custom = json.loads(json.dumps(config))
    custom["axes"]["energy"]["baseline"] = 0.2
    custom["axes"]["energy"]["weight"] = 1.0

    result = ExpressionAdapter(store, rules_config=custom).build_profile()
    energy = _axis(result, "energy")

    assert energy["unclamped_value"] == pytest.approx(-0.8)
    assert energy["value"] == 0.0
    assert energy["clamp_delta"] == pytest.approx(0.8)


def test_expression_axis_is_clamped_at_upper_boundary(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    _seed(store, "satisfaction", 1.0)
    config = load_expression_rules_config()
    custom = json.loads(json.dumps(config))
    custom["axes"]["positive_affect"]["baseline"] = 0.8
    custom["axes"]["positive_affect"]["weight"] = 0.8

    result = ExpressionAdapter(store, rules_config=custom).build_profile()
    positive = _axis(result, "positive_affect")

    assert positive["unclamped_value"] == pytest.approx(1.6)
    assert positive["value"] == 1.0
    assert positive["clamp_delta"] == pytest.approx(-0.6)


def test_expression_profile_is_immutable():
    profile = ExpressionProfile(0.5, 0.1, 0.2, 0.3)

    with pytest.raises(FrozenInstanceError):
        profile.energy = 0.9


def test_expression_adapter_is_read_only_for_internal_state(tmp_path):
    store, adapter = _setup(tmp_path)
    _seed(store, "frustration", 0.5)
    states_before = store.list_states()
    transition_count_before = store.transition_count()

    adapter.build_profile()

    assert store.list_states() == states_before
    assert store.transition_count() == transition_count_before


def test_same_state_produces_same_profile_after_reopen(tmp_path):
    database = tmp_path / "internal_state.db"
    store = InternalStateStore(database)
    _seed(store, "uncertainty", 0.6)
    _seed(store, "satisfaction", 0.3)

    first = ExpressionAdapter(store).build_profile()

    reopened = InternalStateStore(database)
    second = ExpressionAdapter(reopened).build_profile()

    assert second == first


def test_expression_ruleset_must_match_store_ruleset(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    config = load_expression_rules_config()
    broken = json.loads(json.dumps(config))
    broken["ruleset_version"] = store.ruleset_version() + 1

    with pytest.raises(ValueError, match="must match"):
        ExpressionAdapter(store, rules_config=broken)
