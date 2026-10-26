import json
import math
from pathlib import Path

from anima.config.paths import PROJECT_ROOT


EXPRESSION_RULE_CONFIG_SCHEMA_VERSION = 1
DEFAULT_EXPRESSION_RULES_PATH = (
    PROJECT_ROOT / "config" / "internal_state_expression.json"
)

AXIS_SPECS = {
    "energy": ("fatigue", -1),
    "caution": ("uncertainty", 1),
    "tension": ("frustration", 1),
    "positive_affect": ("satisfaction", 1),
}


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def validate_expression_rules_config(config):
    if not isinstance(config, dict):
        raise ValueError("Expression rules config root must be an object")

    expected = {"schema_version", "ruleset_version", "axes"}
    if set(config) != expected:
        raise ValueError("Invalid Expression rules config fields")

    if config["schema_version"] != EXPRESSION_RULE_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported Expression rules config schema: "
            f"{config['schema_version']!r}"
        )

    ruleset_version = config["ruleset_version"]
    if (
        not isinstance(ruleset_version, int)
        or isinstance(ruleset_version, bool)
        or ruleset_version < 1
    ):
        raise ValueError("Expression ruleset_version must be a positive integer")

    axes = config["axes"]
    if not isinstance(axes, dict) or set(axes) != set(AXIS_SPECS):
        raise ValueError(
            "Expression axes do not match the Stage 2 baseline profile"
        )

    for axis_name, (expected_state, expected_direction) in AXIS_SPECS.items():
        spec = axes[axis_name]
        if not isinstance(spec, dict) or set(spec) != {
            "baseline",
            "state",
            "direction",
            "weight",
        }:
            raise ValueError(
                f"Expression axis {axis_name!r} has invalid fields"
            )

        baseline = spec["baseline"]
        weight = spec["weight"]
        direction = spec["direction"]

        if (
            not _is_finite_number(baseline)
            or not 0.0 <= float(baseline) <= 1.0
        ):
            raise ValueError(
                f"Expression axis {axis_name!r} baseline must be within 0.0..1.0"
            )

        if (
            not _is_finite_number(weight)
            or not 0.0 < float(weight) <= 1.0
        ):
            raise ValueError(
                f"Expression axis {axis_name!r} weight must be within (0.0, 1.0]"
            )

        if spec["state"] != expected_state:
            raise ValueError(
                f"Expression axis {axis_name!r} must map from {expected_state!r}"
            )

        if direction != expected_direction or isinstance(direction, bool):
            raise ValueError(
                f"Expression axis {axis_name!r} has invalid direction"
            )

    return config


def load_expression_rules_config(config_file=None):
    path = (
        Path(config_file)
        if config_file is not None
        else DEFAULT_EXPRESSION_RULES_PATH
    )
    try:
        with path.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError as error:
        raise ValueError(f"Expression rules config not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid Expression rules config {path}: malformed JSON"
        ) from error

    return validate_expression_rules_config(config)
