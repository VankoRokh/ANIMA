import json
import math
from pathlib import Path

from anima.config.paths import PROJECT_ROOT


TRANSITION_RULE_CONFIG_SCHEMA_VERSION = 1
DEFAULT_TRANSITION_RULES_PATH = PROJECT_ROOT / "config" / "internal_state_transitions.json"

DELTA_KEYS = {
    "workload_low",
    "workload_normal",
    "workload_high",
    "information_gap",
    "information_conflict",
    "information_confirmed_indirect",
    "information_confirmed_direct",
    "failure",
    "progress_frustration",
    "strategy_changed",
    "verified_success_frustration",
    "verified_progress_satisfaction",
    "verified_success_satisfaction",
}

POSITIVE_DELTA_KEYS = {
    "workload_low",
    "workload_normal",
    "workload_high",
    "information_gap",
    "information_conflict",
    "failure",
    "verified_progress_satisfaction",
    "verified_success_satisfaction",
}

NEGATIVE_DELTA_KEYS = DELTA_KEYS - POSITIVE_DELTA_KEYS

REPETITION_KEYS = {
    "failure_growth_per_repeat",
    "failure_max_factor",
    "success_decay_per_repeat",
    "success_min_factor",
}


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def validate_transition_rules_config(config):
    if not isinstance(config, dict):
        raise ValueError("Transition rules config root must be an object")

    expected = {
        "schema_version",
        "ruleset_version",
        "importance_multipliers",
        "deltas",
        "repetition",
    }
    if set(config) != expected:
        raise ValueError("Invalid Transition rules config fields")

    if config["schema_version"] != TRANSITION_RULE_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported Transition rules config schema: "
            f"{config['schema_version']!r}"
        )

    ruleset_version = config["ruleset_version"]
    if (
        not isinstance(ruleset_version, int)
        or isinstance(ruleset_version, bool)
        or ruleset_version < 1
    ):
        raise ValueError("Transition ruleset_version must be a positive integer")

    importance = config["importance_multipliers"]
    if not isinstance(importance, dict) or set(importance) != {"0", "1", "2", "3"}:
        raise ValueError("Transition importance_multipliers must define 0..3")
    for level, multiplier in importance.items():
        if not _is_finite_number(multiplier) or float(multiplier) <= 0.0:
            raise ValueError(
                f"Transition importance multiplier {level} must be positive"
            )

    deltas = config["deltas"]
    if not isinstance(deltas, dict) or set(deltas) != DELTA_KEYS:
        raise ValueError("Transition deltas do not match Stage 2 baseline rules")
    for name, value in deltas.items():
        if not _is_finite_number(value) or float(value) == 0.0:
            raise ValueError(f"Transition delta {name} must be finite and non-zero")
        if name in POSITIVE_DELTA_KEYS and float(value) <= 0.0:
            raise ValueError(f"Transition delta {name} must be positive")
        if name in NEGATIVE_DELTA_KEYS and float(value) >= 0.0:
            raise ValueError(f"Transition delta {name} must be negative")

    if not (
        float(deltas["workload_low"])
        < float(deltas["workload_normal"])
        < float(deltas["workload_high"])
    ):
        raise ValueError("Workload deltas must increase low < normal < high")

    if abs(float(deltas["information_confirmed_direct"])) <= abs(
        float(deltas["information_confirmed_indirect"])
    ):
        raise ValueError(
            "Direct confirmation must reduce uncertainty more than indirect confirmation"
        )

    repetition = config["repetition"]
    if not isinstance(repetition, dict) or set(repetition) != REPETITION_KEYS:
        raise ValueError("Invalid Transition repetition config fields")

    for name in ("failure_growth_per_repeat", "success_decay_per_repeat"):
        value = repetition[name]
        if not _is_finite_number(value) or float(value) <= 0.0:
            raise ValueError(f"{name} must be a positive finite number")

    failure_max = repetition["failure_max_factor"]
    if not _is_finite_number(failure_max) or float(failure_max) < 1.0:
        raise ValueError("failure_max_factor must be >= 1.0")

    success_min = repetition["success_min_factor"]
    if (
        not _is_finite_number(success_min)
        or not 0.0 < float(success_min) <= 1.0
    ):
        raise ValueError("success_min_factor must be within (0.0, 1.0]")

    return config


def load_transition_rules_config(config_file=None):
    path = (
        Path(config_file)
        if config_file is not None
        else DEFAULT_TRANSITION_RULES_PATH
    )
    try:
        with path.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError as error:
        raise ValueError(f"Transition rules config not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid Transition rules config {path}: malformed JSON"
        ) from error

    return validate_transition_rules_config(config)
