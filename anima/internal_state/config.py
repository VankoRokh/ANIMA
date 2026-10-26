import json
from pathlib import Path

from anima.config.paths import PROJECT_ROOT


CONFIG_SCHEMA_VERSION = 1
BASELINE_STATE_NAMES = {
    "fatigue",
    "uncertainty",
    "frustration",
    "satisfaction",
}
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "internal_state.json"


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_internal_state_config(config):
    if not isinstance(config, dict):
        raise ValueError("Internal State config root must be an object")

    required_fields = {"schema_version", "ruleset_version", "states"}
    if set(config) != required_fields:
        missing = required_fields - config.keys()
        unknown = config.keys() - required_fields
        details = []
        if missing:
            details.append("missing: " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown: " + ", ".join(sorted(unknown)))
        raise ValueError(
            "Invalid Internal State config fields (" + "; ".join(details) + ")"
        )

    if config["schema_version"] != CONFIG_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported Internal State config schema: "
            f"{config['schema_version']!r}"
        )

    ruleset_version = config["ruleset_version"]
    if (
        not isinstance(ruleset_version, int)
        or isinstance(ruleset_version, bool)
        or ruleset_version < 1
    ):
        raise ValueError("Internal State ruleset_version must be a positive integer")

    states = config["states"]
    if not isinstance(states, dict):
        raise ValueError("Internal State states must be an object")

    state_names = set(states)
    if state_names != BASELINE_STATE_NAMES:
        missing = BASELINE_STATE_NAMES - state_names
        unknown = state_names - BASELINE_STATE_NAMES
        details = []
        if missing:
            details.append("missing: " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown: " + ", ".join(sorted(unknown)))
        raise ValueError(
            "Internal State baseline states mismatch (" + "; ".join(details) + ")"
        )

    for state_name, spec in states.items():
        if not isinstance(spec, dict):
            raise ValueError(f"State {state_name!r} config must be an object")

        expected = {"minimum", "baseline", "maximum"}
        if set(spec) != expected:
            raise ValueError(
                f"State {state_name!r} config fields must be: "
                "baseline, maximum, minimum"
            )

        minimum = spec["minimum"]
        baseline = spec["baseline"]
        maximum = spec["maximum"]

        if not all(_is_number(value) for value in (minimum, baseline, maximum)):
            raise ValueError(f"State {state_name!r} bounds must be numeric")

        if float(minimum) != 0.0 or float(maximum) != 1.0:
            raise ValueError(
                f"State {state_name!r} must use the Stage 2 range 0.0..1.0"
            )

        if not minimum <= baseline <= maximum:
            raise ValueError(
                f"State {state_name!r} baseline must be within its range"
            )

    return config


def load_internal_state_config(config_file=None):
    config_path = Path(config_file) if config_file is not None else DEFAULT_CONFIG_PATH

    try:
        with config_path.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError as error:
        raise ValueError(
            f"Internal State config not found: {config_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid Internal State config {config_path}: malformed JSON"
        ) from error

    return validate_internal_state_config(config)
