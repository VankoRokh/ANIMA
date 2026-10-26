import math
from dataclasses import dataclass

from anima.internal_state.choice_rules import (
    load_choice_rules_config,
    validate_choice_rules_config,
)
from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore
from anima.internal_state.variables import StateName, StateVariableRegistry


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    base_score: float
    effort_cost: float = 0.0
    information_gain: float = 0.0
    irreversible_risk: float = 0.0
    repeated_failure: float = 0.0
    alternative_value: float = 0.0
    verified_continuation: float = 0.0


_FEATURE_FIELDS = (
    "effort_cost",
    "information_gain",
    "irreversible_risk",
    "repeated_failure",
    "alternative_value",
    "verified_continuation",
)


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _normalized_number(value, label):
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{label} must be a finite number")
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{label} must be within 0.0..1.0")
    return numeric


class ChoiceEngine:
    """Deterministic Candidate evaluation using bounded Internal State modifiers."""

    def __init__(
        self,
        store,
        *,
        goal_store=None,
        rules_config=None,
        rules_config_file=None,
        registry=None,
    ):
        if not isinstance(store, InternalStateStore):
            raise TypeError("ChoiceEngine store must be an InternalStateStore")
        if rules_config is not None and rules_config_file is not None:
            raise ValueError("Provide rules_config or rules_config_file, not both")

        self.store = store
        self.goal_store = goal_store or GoalStore(store)
        if not isinstance(self.goal_store, GoalStore):
            raise TypeError("ChoiceEngine goal_store must be a GoalStore")

        self.rules = (
            validate_choice_rules_config(rules_config)
            if rules_config is not None
            else load_choice_rules_config(rules_config_file)
        )
        if self.rules["ruleset_version"] != self.store.ruleset_version():
            raise ValueError(
                "Choice ruleset version must match Internal State store ruleset"
            )

        self.registry = registry or StateVariableRegistry(store.config)

    @property
    def ruleset_version(self):
        return self.rules["ruleset_version"]

    def _validate_candidate(self, candidate):
        if not isinstance(candidate, Candidate):
            raise TypeError("ChoiceEngine requires Candidate objects")

        candidate_id = _require_text(candidate.candidate_id, "Candidate candidate_id")
        values = {
            "base_score": _normalized_number(candidate.base_score, "Candidate base_score"),
        }
        for field in _FEATURE_FIELDS:
            values[field] = _normalized_number(
                getattr(candidate, field),
                f"Candidate {field}",
            )

        return Candidate(candidate_id=candidate_id, **values)

    def _state_snapshot(self):
        raw = {row["name"]: float(row["value"]) for row in self.store.list_states()}
        return self.registry.validate_snapshot(raw)

    def _activation(self, state_name, value):
        definition = self.registry.get(state_name)
        baseline = float(definition.baseline)
        maximum = float(definition.maximum)
        if value <= baseline or maximum <= baseline:
            return 0.0
        return (value - baseline) / (maximum - baseline)

    def _modifier(
        self,
        *,
        name,
        state_name,
        state_value,
        feature_name,
        feature_value,
        weight_name,
        direction,
    ):
        weight = float(self.rules["weights"][weight_name])
        activation = self._activation(state_name, state_value)
        contribution = direction * activation * feature_value * weight
        return {
            "name": name,
            "state": state_name.value,
            "state_value": state_value,
            "state_activation": activation,
            "feature": feature_name,
            "feature_value": feature_value,
            "weight": weight,
            "bound": weight,
            "contribution": contribution,
        }

    def _evaluate_candidate(self, candidate, snapshot):
        modifiers = (
            self._modifier(
                name="fatigue_effort_penalty",
                state_name=StateName.FATIGUE,
                state_value=snapshot[StateName.FATIGUE.value],
                feature_name="effort_cost",
                feature_value=candidate.effort_cost,
                weight_name="fatigue_effort",
                direction=-1.0,
            ),
            self._modifier(
                name="uncertainty_information_gain_bonus",
                state_name=StateName.UNCERTAINTY,
                state_value=snapshot[StateName.UNCERTAINTY.value],
                feature_name="information_gain",
                feature_value=candidate.information_gain,
                weight_name="uncertainty_information_gain",
                direction=1.0,
            ),
            self._modifier(
                name="uncertainty_irreversible_risk_penalty",
                state_name=StateName.UNCERTAINTY,
                state_value=snapshot[StateName.UNCERTAINTY.value],
                feature_name="irreversible_risk",
                feature_value=candidate.irreversible_risk,
                weight_name="uncertainty_irreversible_risk",
                direction=-1.0,
            ),
            self._modifier(
                name="frustration_repeated_failure_penalty",
                state_name=StateName.FRUSTRATION,
                state_value=snapshot[StateName.FRUSTRATION.value],
                feature_name="repeated_failure",
                feature_value=candidate.repeated_failure,
                weight_name="frustration_repeated_failure",
                direction=-1.0,
            ),
            self._modifier(
                name="frustration_alternative_bonus",
                state_name=StateName.FRUSTRATION,
                state_value=snapshot[StateName.FRUSTRATION.value],
                feature_name="alternative_value",
                feature_value=candidate.alternative_value,
                weight_name="frustration_alternative",
                direction=1.0,
            ),
            self._modifier(
                name="satisfaction_verified_continuation_bonus",
                state_name=StateName.SATISFACTION,
                state_value=snapshot[StateName.SATISFACTION.value],
                feature_name="verified_continuation",
                feature_value=candidate.verified_continuation,
                weight_name="satisfaction_verified_continuation",
                direction=1.0,
            ),
        )

        modifier_total = sum(item["contribution"] for item in modifiers)
        unclamped_score = candidate.base_score + modifier_total
        minimum = float(self.rules["score_minimum"])
        maximum = float(self.rules["score_maximum"])
        final_score = min(maximum, max(minimum, unclamped_score))
        clamp_delta = final_score - unclamped_score

        return {
            "candidate_id": candidate.candidate_id,
            "base_score": candidate.base_score,
            "modifiers": modifiers,
            "modifier_total": modifier_total,
            "unclamped_score": unclamped_score,
            "clamp_delta": clamp_delta,
            "final_score": final_score,
        }

    def choose(self, goal_id, candidates):
        goal_id = _require_text(goal_id, "Choice goal_id")
        goal = self.goal_store.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Unknown Goal: {goal_id}")
        if goal["status"] != "active":
            raise ValueError(
                f"Choice requires an active Goal, got {goal['status']!r}"
            )

        if not isinstance(candidates, (list, tuple)) or not candidates:
            raise ValueError("Choice requires at least one Candidate")

        validated = [self._validate_candidate(item) for item in candidates]
        candidate_ids = [item.candidate_id for item in validated]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Choice Candidate IDs must be unique")

        snapshot = self._state_snapshot()
        evaluations = [
            self._evaluate_candidate(candidate, snapshot)
            for candidate in validated
        ]
        ranked = sorted(
            evaluations,
            key=lambda item: (
                -item["final_score"],
                -item["base_score"],
                item["candidate_id"],
            ),
        )

        for index, item in enumerate(ranked, start=1):
            item["rank"] = index

        selected = ranked[0]
        return {
            "goal_id": goal_id,
            "ruleset_version": self.ruleset_version,
            "state_snapshot": snapshot,
            "selected_candidate_id": selected["candidate_id"],
            "evaluations": tuple(ranked),
        }
