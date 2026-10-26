import math
from dataclasses import dataclass
from enum import StrEnum

from anima.internal_state.config import (
    load_internal_state_config,
    validate_internal_state_config,
)


class StateName(StrEnum):
    FATIGUE = "fatigue"
    UNCERTAINTY = "uncertainty"
    FRUSTRATION = "frustration"
    SATISFACTION = "satisfaction"


class TimeBehavior(StrEnum):
    AWAKE_ACCUMULATION = "awake_accumulation"
    PERSISTENT_UNTIL_EVIDENCE = "persistent_until_evidence"
    RECOVER_TO_BASELINE = "recover_to_baseline"
    DECAY_TO_BASELINE = "decay_to_baseline"


class ChoiceRole(StrEnum):
    COST_AVOIDANCE = "cost_avoidance"
    INFORMATION_SEEKING = "information_seeking"
    STRATEGY_CHANGE = "strategy_change"
    VERIFIED_CONTINUATION = "verified_continuation"


_SEMANTICS = {
    StateName.FATIGUE: {
        "description": (
            "Accumulated cost of prolonged activity and workload; "
            "it does not independently create a recovery goal."
        ),
        "time_behavior": TimeBehavior.AWAKE_ACCUMULATION,
        "choice_role": ChoiceRole.COST_AVOIDANCE,
    },
    StateName.UNCERTAINTY: {
        "description": (
            "Lack of reliable information required for the current choice; "
            "time alone does not resolve it."
        ),
        "time_behavior": TimeBehavior.PERSISTENT_UNTIL_EVIDENCE,
        "choice_role": ChoiceRole.INFORMATION_SEEKING,
    },
    StateName.FRUSTRATION: {
        "description": (
            "Signal that a repeated approach is failing to make progress; "
            "it is an anti-looping regulator, not anger."
        ),
        "time_behavior": TimeBehavior.RECOVER_TO_BASELINE,
        "choice_role": ChoiceRole.STRATEGY_CHANGE,
    },
    StateName.SATISFACTION: {
        "description": (
            "Signal of objectively verified progress or success; "
            "it is not a global reward function."
        ),
        "time_behavior": TimeBehavior.DECAY_TO_BASELINE,
        "choice_role": ChoiceRole.VERIFIED_CONTINUATION,
    },
}


def _coerce_finite_number(value, label):
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


@dataclass(frozen=True)
class StateVariableDefinition:
    name: StateName
    minimum: float
    baseline: float
    maximum: float
    description: str
    time_behavior: TimeBehavior
    choice_role: ChoiceRole

    def validate_value(self, value):
        numeric = _coerce_finite_number(value, f"{self.name} value")
        if not self.minimum <= numeric <= self.maximum:
            raise ValueError(
                f"{self.name} value must be within "
                f"{self.minimum}..{self.maximum}"
            )
        return numeric

    def clamp(self, value):
        numeric = _coerce_finite_number(value, f"{self.name} value")
        return min(self.maximum, max(self.minimum, numeric))

    def is_baseline(self, value):
        return self.validate_value(value) == self.baseline


class StateVariableRegistry:
    def __init__(self, config=None):
        config = (
            load_internal_state_config()
            if config is None
            else validate_internal_state_config(config)
        )
        definitions = {}

        for state_name in StateName:
            spec = config["states"][state_name.value]
            semantics = _SEMANTICS[state_name]
            definitions[state_name] = StateVariableDefinition(
                name=state_name,
                minimum=float(spec["minimum"]),
                baseline=float(spec["baseline"]),
                maximum=float(spec["maximum"]),
                description=semantics["description"],
                time_behavior=semantics["time_behavior"],
                choice_role=semantics["choice_role"],
            )

        self._definitions = definitions

    @staticmethod
    def _coerce_name(state_name):
        try:
            return StateName(state_name)
        except (ValueError, TypeError) as error:
            raise ValueError(f"Unknown Internal State: {state_name!r}") from error

    def get(self, state_name):
        return self._definitions[self._coerce_name(state_name)]

    def list(self):
        return [self._definitions[name] for name in StateName]

    def names(self):
        return tuple(name.value for name in StateName)

    def validate_snapshot(self, snapshot):
        if not isinstance(snapshot, dict):
            raise ValueError("Internal State snapshot must be an object")

        expected = set(self.names())
        actual = set(snapshot)
        if actual != expected:
            missing = expected - actual
            unknown = actual - expected
            details = []
            if missing:
                details.append("missing: " + ", ".join(sorted(missing)))
            if unknown:
                details.append("unknown: " + ", ".join(sorted(unknown)))
            raise ValueError(
                "Internal State snapshot fields mismatch ("
                + "; ".join(details)
                + ")"
            )

        return {
            name: self.get(name).validate_value(snapshot[name])
            for name in self.names()
        }

    def clamp(self, state_name, value):
        return self.get(state_name).clamp(value)
