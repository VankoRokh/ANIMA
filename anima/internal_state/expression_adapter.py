from dataclasses import dataclass

from anima.internal_state.expression_rules import (
    AXIS_SPECS,
    load_expression_rules_config,
    validate_expression_rules_config,
)
from anima.internal_state.store import InternalStateStore
from anima.internal_state.variables import StateVariableRegistry


@dataclass(frozen=True)
class ExpressionProfile:
    energy: float
    caution: float
    tension: float
    positive_affect: float

    def as_dict(self):
        return {
            "energy": self.energy,
            "caution": self.caution,
            "tension": self.tension,
            "positive_affect": self.positive_affect,
        }


class ExpressionAdapter:
    """Read-only Internal State -> ExpressionProfile mapping."""

    def __init__(
        self,
        store,
        *,
        rules_config=None,
        rules_config_file=None,
        registry=None,
    ):
        if not isinstance(store, InternalStateStore):
            raise TypeError("ExpressionAdapter store must be an InternalStateStore")
        if rules_config is not None and rules_config_file is not None:
            raise ValueError(
                "Provide rules_config or rules_config_file, not both"
            )

        self.store = store
        self.rules = (
            validate_expression_rules_config(rules_config)
            if rules_config is not None
            else load_expression_rules_config(rules_config_file)
        )
        if self.rules["ruleset_version"] != self.store.ruleset_version():
            raise ValueError(
                "Expression ruleset version must match Internal State store ruleset"
            )

        self.registry = registry or StateVariableRegistry(store.config)

    @property
    def ruleset_version(self):
        return self.rules["ruleset_version"]

    def _state_snapshot(self):
        raw = {
            row["name"]: float(row["value"])
            for row in self.store.list_states()
        }
        return self.registry.validate_snapshot(raw)

    def _state_activation(self, state_name, state_value):
        definition = self.registry.get(state_name)
        baseline = float(definition.baseline)
        maximum = float(definition.maximum)
        if state_value <= baseline or maximum <= baseline:
            return 0.0
        return (state_value - baseline) / (maximum - baseline)

    @staticmethod
    def _clamp(value):
        return min(1.0, max(0.0, value))

    def build_profile(self):
        snapshot = self._state_snapshot()
        values = {}
        trace = []

        for axis_name in AXIS_SPECS:
            spec = self.rules["axes"][axis_name]
            state_name = spec["state"]
            state_value = snapshot[state_name]
            activation = self._state_activation(state_name, state_value)
            baseline = float(spec["baseline"])
            weight = float(spec["weight"])
            direction = int(spec["direction"])
            contribution = direction * activation * weight
            unclamped_value = baseline + contribution
            value = self._clamp(unclamped_value)
            clamp_delta = value - unclamped_value

            values[axis_name] = value
            trace.append(
                {
                    "axis": axis_name,
                    "baseline": baseline,
                    "state": state_name,
                    "state_value": state_value,
                    "state_activation": activation,
                    "direction": direction,
                    "weight": weight,
                    "contribution": contribution,
                    "unclamped_value": unclamped_value,
                    "clamp_delta": clamp_delta,
                    "value": value,
                }
            )

        profile = ExpressionProfile(**values)
        return {
            "ruleset_version": self.ruleset_version,
            "state_snapshot": snapshot,
            "profile": profile,
            "trace": tuple(trace),
        }
