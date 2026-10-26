import json
import math
from pathlib import Path

from anima.config.paths import PROJECT_ROOT


TIME_CONFIG_SCHEMA_VERSION = 1
DEFAULT_TIME_CONFIG_PATH = PROJECT_ROOT / "config" / "internal_state_time.json"


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _require_non_negative(value, label):
    if not _is_finite_number(value) or float(value) < 0.0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return float(value)


def validate_time_rules_config(config):
    if not isinstance(config, dict):
        raise ValueError("Internal State time config root must be an object")

    expected_root = {
        "schema_version",
        "ruleset_version",
        "awake_work_period_seconds",
        "fatigue",
        "frustration",
        "satisfaction",
    }
    if set(config) != expected_root:
        raise ValueError("Invalid Internal State time config fields")

    if config["schema_version"] != TIME_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported Internal State time config schema: "
            f"{config['schema_version']!r}"
        )

    ruleset_version = config["ruleset_version"]
    if (
        not isinstance(ruleset_version, int)
        or isinstance(ruleset_version, bool)
        or ruleset_version < 1
    ):
        raise ValueError("Time ruleset_version must be a positive integer")

    work_period = config["awake_work_period_seconds"]
    if not _is_finite_number(work_period) or float(work_period) <= 0.0:
        raise ValueError("awake_work_period_seconds must be a positive finite number")

    fatigue = config["fatigue"]
    if not isinstance(fatigue, dict) or set(fatigue) != {
        "awake_segments",
        "beyond_rate_per_hour",
        "recovery_rate_per_hour",
    }:
        raise ValueError("Invalid fatigue time config")

    segments = fatigue["awake_segments"]
    if not isinstance(segments, list) or not segments:
        raise ValueError("fatigue.awake_segments must be a non-empty list")

    previous_ratio = 0.0
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or set(segment) != {
            "until_ratio",
            "rate_per_hour",
        }:
            raise ValueError(f"Invalid fatigue awake segment at index {index}")

        ratio = segment["until_ratio"]
        if (
            not _is_finite_number(ratio)
            or not previous_ratio < float(ratio) <= 1.0
        ):
            raise ValueError(
                "fatigue awake segment until_ratio values must be strictly "
                "increasing within 0.0..1.0"
            )
        previous_ratio = float(ratio)
        _require_non_negative(
            segment["rate_per_hour"],
            f"fatigue.awake_segments[{index}].rate_per_hour",
        )

    if previous_ratio != 1.0:
        raise ValueError("Last fatigue awake segment must end at ratio 1.0")

    _require_non_negative(
        fatigue["beyond_rate_per_hour"],
        "fatigue.beyond_rate_per_hour",
    )
    _require_non_negative(
        fatigue["recovery_rate_per_hour"],
        "fatigue.recovery_rate_per_hour",
    )

    frustration = config["frustration"]
    if not isinstance(frustration, dict) or set(frustration) != {
        "recovery_rate_per_hour"
    }:
        raise ValueError("Invalid frustration time config")
    _require_non_negative(
        frustration["recovery_rate_per_hour"],
        "frustration.recovery_rate_per_hour",
    )

    satisfaction = config["satisfaction"]
    if not isinstance(satisfaction, dict) or set(satisfaction) != {
        "decay_rate_per_hour"
    }:
        raise ValueError("Invalid satisfaction time config")
    _require_non_negative(
        satisfaction["decay_rate_per_hour"],
        "satisfaction.decay_rate_per_hour",
    )

    return config


def load_time_rules_config(config_file=None):
    path = Path(config_file) if config_file is not None else DEFAULT_TIME_CONFIG_PATH
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Internal State time config not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid Internal State time config {path}: malformed JSON"
        ) from error
    return validate_time_rules_config(config)
