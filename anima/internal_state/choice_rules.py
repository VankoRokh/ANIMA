import json
import math
from pathlib import Path

from anima.config.paths import PROJECT_ROOT


CHOICE_RULE_CONFIG_SCHEMA_VERSION = 1
DEFAULT_CHOICE_RULES_PATH = PROJECT_ROOT / "config" / "internal_state_choice.json"

WEIGHT_KEYS = {
    "fatigue_effort",
    "uncertainty_information_gain",
    "uncertainty_irreversible_risk",
    "frustration_repeated_failure",
    "frustration_alternative",
    "satisfaction_verified_continuation",
}


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def validate_choice_rules_config(config):
    if not isinstance(config, dict):
        raise ValueError("Choice rules config root must be an object")

    expected = {
        "schema_version",
        "ruleset_version",
        "score_minimum",
        "score_maximum",
        "weights",
    }
    if set(config) != expected:
        raise ValueError("Invalid Choice rules config fields")

    if config["schema_version"] != CHOICE_RULE_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported Choice rules config schema: {config['schema_version']!r}"
        )

    ruleset_version = config["ruleset_version"]
    if (
        not isinstance(ruleset_version, int)
        or isinstance(ruleset_version, bool)
        or ruleset_version < 1
    ):
        raise ValueError("Choice ruleset_version must be a positive integer")

    minimum = config["score_minimum"]
    maximum = config["score_maximum"]
    if not _is_finite_number(minimum) or not _is_finite_number(maximum):
        raise ValueError("Choice score bounds must be finite numbers")
    if float(minimum) != 0.0 or float(maximum) != 1.0:
        raise ValueError("Choice score bounds must use the Stage 2 range 0.0..1.0")

    weights = config["weights"]
    if not isinstance(weights, dict) or set(weights) != WEIGHT_KEYS:
        raise ValueError("Choice weights do not match Stage 2 baseline modifiers")

    for name, value in weights.items():
        if not _is_finite_number(value) or not 0.0 < float(value) <= 1.0:
            raise ValueError(f"Choice weight {name} must be within (0.0, 1.0]")

    satisfaction = float(weights["satisfaction_verified_continuation"])
    other_weights = [
        float(value)
        for name, value in weights.items()
        if name != "satisfaction_verified_continuation"
    ]
    if satisfaction >= min(other_weights):
        raise ValueError(
            "Satisfaction continuation weight must remain weaker than all other baseline modifiers"
        )

    return config


def load_choice_rules_config(config_file=None):
    path = (
        Path(config_file)
        if config_file is not None
        else DEFAULT_CHOICE_RULES_PATH
    )
    try:
        with path.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError as error:
        raise ValueError(f"Choice rules config not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid Choice rules config {path}: malformed JSON"
        ) from error

    return validate_choice_rules_config(config)
