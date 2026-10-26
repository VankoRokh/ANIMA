import math

import pytest

from anima.internal_state.variables import (
    ChoiceRole,
    StateName,
    StateVariableRegistry,
    TimeBehavior,
)


def make_config(*, fatigue_baseline=0.0):
    return {
        "schema_version": 1,
        "ruleset_version": 1,
        "states": {
            "fatigue": {
                "minimum": 0.0,
                "baseline": fatigue_baseline,
                "maximum": 1.0,
            },
            "uncertainty": {
                "minimum": 0.0,
                "baseline": 0.0,
                "maximum": 1.0,
            },
            "frustration": {
                "minimum": 0.0,
                "baseline": 0.0,
                "maximum": 1.0,
            },
            "satisfaction": {
                "minimum": 0.0,
                "baseline": 0.0,
                "maximum": 1.0,
            },
        },
    }


def test_state_variable_registry_exposes_exact_stage2_baseline():
    registry = StateVariableRegistry(make_config())

    assert registry.names() == (
        "fatigue",
        "uncertainty",
        "frustration",
        "satisfaction",
    )
    assert [definition.name for definition in registry.list()] == list(StateName)


def test_state_variables_have_distinct_semantics():
    registry = StateVariableRegistry(make_config())

    fatigue = registry.get("fatigue")
    uncertainty = registry.get("uncertainty")
    frustration = registry.get("frustration")
    satisfaction = registry.get("satisfaction")

    assert fatigue.time_behavior == TimeBehavior.AWAKE_ACCUMULATION
    assert fatigue.choice_role == ChoiceRole.COST_AVOIDANCE

    assert uncertainty.time_behavior == TimeBehavior.PERSISTENT_UNTIL_EVIDENCE
    assert uncertainty.choice_role == ChoiceRole.INFORMATION_SEEKING

    assert frustration.time_behavior == TimeBehavior.RECOVER_TO_BASELINE
    assert frustration.choice_role == ChoiceRole.STRATEGY_CHANGE

    assert satisfaction.time_behavior == TimeBehavior.DECAY_TO_BASELINE
    assert satisfaction.choice_role == ChoiceRole.VERIFIED_CONTINUATION

    assert len({item.description for item in registry.list()}) == 4


def test_state_variable_bounds_and_baseline_come_from_config():
    registry = StateVariableRegistry(make_config(fatigue_baseline=0.25))
    fatigue = registry.get(StateName.FATIGUE)

    assert fatigue.minimum == 0.0
    assert fatigue.baseline == 0.25
    assert fatigue.maximum == 1.0
    assert fatigue.is_baseline(0.25) is True
    assert fatigue.is_baseline(0.5) is False


@pytest.mark.parametrize("value", [True, "0.5", math.inf, -math.inf, math.nan])
def test_state_variable_rejects_non_finite_or_non_numeric_values(value):
    fatigue = StateVariableRegistry(make_config()).get("fatigue")

    with pytest.raises(ValueError, match="finite number"):
        fatigue.validate_value(value)


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_state_variable_rejects_values_outside_range(value):
    fatigue = StateVariableRegistry(make_config()).get("fatigue")

    with pytest.raises(ValueError, match="within 0.0..1.0"):
        fatigue.validate_value(value)


def test_state_variable_clamp_is_explicit_and_bounded():
    registry = StateVariableRegistry(make_config())

    assert registry.clamp("fatigue", -0.25) == 0.0
    assert registry.clamp("fatigue", 0.4) == 0.4
    assert registry.clamp("fatigue", 1.5) == 1.0


def test_state_snapshot_requires_all_four_known_states():
    registry = StateVariableRegistry(make_config())
    valid = {
        "fatigue": 0.2,
        "uncertainty": 0.3,
        "frustration": 0.4,
        "satisfaction": 0.5,
    }

    assert registry.validate_snapshot(valid) == valid

    missing = dict(valid)
    missing.pop("uncertainty")
    with pytest.raises(ValueError, match="missing: uncertainty"):
        registry.validate_snapshot(missing)

    unknown = dict(valid)
    unknown["curiosity"] = 0.1
    with pytest.raises(ValueError, match="unknown: curiosity"):
        registry.validate_snapshot(unknown)


def test_unknown_state_name_is_rejected():
    registry = StateVariableRegistry(make_config())

    with pytest.raises(ValueError, match="Unknown Internal State"):
        registry.get("curiosity")
