from dataclasses import dataclass
from enum import StrEnum

from anima.internal_state.store import InternalStateStore
from anima.internal_state.transition_rules import (
    load_transition_rules_config,
    validate_transition_rules_config,
)
from anima.internal_state.variables import StateName, StateVariableRegistry


class SignalKind(StrEnum):
    WORKLOAD_LOW = "workload_low"
    WORKLOAD_NORMAL = "workload_normal"
    WORKLOAD_HIGH = "workload_high"
    INFORMATION_GAP = "information_gap"
    INFORMATION_CONFLICT = "information_conflict"
    INFORMATION_CONFIRMED_INDIRECT = "information_confirmed_indirect"
    INFORMATION_CONFIRMED_DIRECT = "information_confirmed_direct"
    FAILURE = "failure"
    PROGRESS = "progress"
    STRATEGY_CHANGED = "strategy_changed"
    VERIFIED_PROGRESS = "verified_progress"
    VERIFIED_SUCCESS = "verified_success"


class RepetitionMode(StrEnum):
    NONE = "none"
    ESCALATING_FAILURE = "escalating_failure"
    DIMINISHING_SUCCESS = "diminishing_success"


@dataclass(frozen=True)
class StateSignal:
    kind: SignalKind | str
    source_id: str
    reason: str
    importance: int = 1
    goal_id: str | None = None
    candidate_id: str | None = None
    timestamp: str | None = None


@dataclass(frozen=True)
class _RuleEffect:
    state_name: StateName
    delta_key: str
    rule_name: str
    importance_scaled: bool = False
    repetition_mode: RepetitionMode = RepetitionMode.NONE


_SIGNAL_EFFECTS = {
    SignalKind.WORKLOAD_LOW: (
        _RuleEffect(StateName.FATIGUE, "workload_low", "workload_low"),
    ),
    SignalKind.WORKLOAD_NORMAL: (
        _RuleEffect(StateName.FATIGUE, "workload_normal", "workload_normal"),
    ),
    SignalKind.WORKLOAD_HIGH: (
        _RuleEffect(StateName.FATIGUE, "workload_high", "workload_high"),
    ),
    SignalKind.INFORMATION_GAP: (
        _RuleEffect(
            StateName.UNCERTAINTY,
            "information_gap",
            "information_gap",
            importance_scaled=True,
        ),
    ),
    SignalKind.INFORMATION_CONFLICT: (
        _RuleEffect(
            StateName.UNCERTAINTY,
            "information_conflict",
            "information_conflict",
            importance_scaled=True,
        ),
    ),
    SignalKind.INFORMATION_CONFIRMED_INDIRECT: (
        _RuleEffect(
            StateName.UNCERTAINTY,
            "information_confirmed_indirect",
            "information_confirmed_indirect",
            importance_scaled=True,
        ),
    ),
    SignalKind.INFORMATION_CONFIRMED_DIRECT: (
        _RuleEffect(
            StateName.UNCERTAINTY,
            "information_confirmed_direct",
            "information_confirmed_direct",
            importance_scaled=True,
        ),
    ),
    SignalKind.FAILURE: (
        _RuleEffect(
            StateName.FRUSTRATION,
            "failure",
            "failure",
            repetition_mode=RepetitionMode.ESCALATING_FAILURE,
        ),
    ),
    SignalKind.PROGRESS: (
        _RuleEffect(
            StateName.FRUSTRATION,
            "progress_frustration",
            "progress",
        ),
    ),
    SignalKind.STRATEGY_CHANGED: (
        _RuleEffect(
            StateName.FRUSTRATION,
            "strategy_changed",
            "strategy_changed",
        ),
    ),
    SignalKind.VERIFIED_PROGRESS: (
        _RuleEffect(
            StateName.FRUSTRATION,
            "progress_frustration",
            "progress",
        ),
        _RuleEffect(
            StateName.SATISFACTION,
            "verified_progress_satisfaction",
            "verified_progress",
            importance_scaled=True,
            repetition_mode=RepetitionMode.DIMINISHING_SUCCESS,
        ),
    ),
    SignalKind.VERIFIED_SUCCESS: (
        _RuleEffect(
            StateName.FRUSTRATION,
            "verified_success_frustration",
            "verified_success",
        ),
        _RuleEffect(
            StateName.SATISFACTION,
            "verified_success_satisfaction",
            "verified_success",
            importance_scaled=True,
            repetition_mode=RepetitionMode.DIMINISHING_SUCCESS,
        ),
    ),
}

_CAUSE_TYPES = {
    SignalKind.WORKLOAD_LOW: "event",
    SignalKind.WORKLOAD_NORMAL: "event",
    SignalKind.WORKLOAD_HIGH: "event",
    SignalKind.INFORMATION_GAP: "event",
    SignalKind.INFORMATION_CONFLICT: "event",
    SignalKind.INFORMATION_CONFIRMED_INDIRECT: "result",
    SignalKind.INFORMATION_CONFIRMED_DIRECT: "result",
    SignalKind.FAILURE: "result",
    SignalKind.PROGRESS: "result",
    SignalKind.STRATEGY_CHANGED: "result",
    SignalKind.VERIFIED_PROGRESS: "result",
    SignalKind.VERIFIED_SUCCESS: "result",
}

_GOAL_SCOPED_SIGNALS = {
    SignalKind.FAILURE,
    SignalKind.PROGRESS,
    SignalKind.STRATEGY_CHANGED,
    SignalKind.VERIFIED_PROGRESS,
    SignalKind.VERIFIED_SUCCESS,
}


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


class TransitionEngine:
    def __init__(
        self,
        store,
        *,
        rules_config=None,
        rules_config_file=None,
        registry=None,
    ):
        if not isinstance(store, InternalStateStore):
            raise TypeError("TransitionEngine store must be an InternalStateStore")
        if rules_config is not None and rules_config_file is not None:
            raise ValueError(
                "Provide rules_config or rules_config_file, not both"
            )

        self.store = store
        self.rules = (
            validate_transition_rules_config(rules_config)
            if rules_config is not None
            else load_transition_rules_config(rules_config_file)
        )
        self.registry = registry or StateVariableRegistry(store.config)

    @property
    def ruleset_version(self):
        return self.rules["ruleset_version"]

    @staticmethod
    def _coerce_kind(kind):
        try:
            return SignalKind(kind)
        except (ValueError, TypeError) as error:
            raise ValueError(f"Unknown Internal State signal: {kind!r}") from error

    def _validate_signal(self, signal):
        if not isinstance(signal, StateSignal):
            raise TypeError("TransitionEngine requires a StateSignal")

        kind = self._coerce_kind(signal.kind)
        source_id = _require_text(signal.source_id, "StateSignal source_id")
        reason = _require_text(signal.reason, "StateSignal reason")

        importance = signal.importance
        if (
            not isinstance(importance, int)
            or isinstance(importance, bool)
            or importance not in range(4)
        ):
            raise ValueError("StateSignal importance must be an integer from 0 to 3")

        goal_id = signal.goal_id
        candidate_id = signal.candidate_id
        if goal_id is not None:
            goal_id = _require_text(goal_id, "StateSignal goal_id")
        if candidate_id is not None:
            candidate_id = _require_text(candidate_id, "StateSignal candidate_id")

        if kind in _GOAL_SCOPED_SIGNALS:
            if goal_id is None or candidate_id is None:
                raise ValueError(
                    f"{kind.value} requires goal_id and candidate_id "
                    "to preserve repetition scope"
                )

        return StateSignal(
            kind=kind,
            source_id=source_id,
            reason=reason,
            importance=importance,
            goal_id=goal_id,
            candidate_id=candidate_id,
            timestamp=signal.timestamp,
        )

    def _rule_id(self, effect):
        return (
            f"stage2.{effect.state_name.value}.{effect.rule_name}"
            f".v{self.ruleset_version}"
        )

    def _prior_same_rule_count(self, effect, signal, rule_id):
        if effect.repetition_mode is RepetitionMode.NONE:
            return 0

        history = self.store.list_state_transitions(
            state_name=effect.state_name.value
        )
        count = 0

        for transition in reversed(history):
            if (
                transition["goal_id"] != signal.goal_id
                or transition["candidate_id"] != signal.candidate_id
            ):
                continue

            if transition["rule_id"] == rule_id:
                count += 1
                continue

            break

        return count

    def _repetition_factor(self, effect, prior_count):
        if effect.repetition_mode is RepetitionMode.NONE:
            return None

        repetition = self.rules["repetition"]

        if effect.repetition_mode is RepetitionMode.ESCALATING_FAILURE:
            factor = 1.0 + (
                prior_count * float(repetition["failure_growth_per_repeat"])
            )
            return min(
                float(repetition["failure_max_factor"]),
                factor,
            )

        factor = 1.0 / (
            1.0
            + prior_count * float(repetition["success_decay_per_repeat"])
        )
        return max(
            float(repetition["success_min_factor"]),
            factor,
        )

    def _importance_factor(self, effect, importance):
        if not effect.importance_scaled:
            return 1.0
        return float(
            self.rules["importance_multipliers"][str(importance)]
        )

    def _effective_delta(self, effect, signal, repetition_factor):
        base_delta = float(self.rules["deltas"][effect.delta_key])
        importance_factor = self._importance_factor(
            effect,
            signal.importance,
        )
        repetition_multiplier = (
            repetition_factor if repetition_factor is not None else 1.0
        )
        raw_delta = base_delta * importance_factor * repetition_multiplier

        current = float(
            self.store.get_state(effect.state_name.value)["value"]
        )
        target = self.registry.clamp(
            effect.state_name,
            current + raw_delta,
        )
        return target - current

    def process(self, signal):
        signal = self._validate_signal(signal)
        transitions = []

        for effect in _SIGNAL_EFFECTS[signal.kind]:
            rule_id = self._rule_id(effect)
            prior_count = self._prior_same_rule_count(
                effect,
                signal,
                rule_id,
            )
            repetition_factor = self._repetition_factor(
                effect,
                prior_count,
            )
            delta = self._effective_delta(
                effect,
                signal,
                repetition_factor,
            )

            transition = self.store.apply_state_transition(
                state_name=effect.state_name.value,
                delta=delta,
                cause_type=_CAUSE_TYPES[signal.kind],
                source_id=signal.source_id,
                rule_id=rule_id,
                reason=signal.reason,
                importance=signal.importance,
                repetition_factor=repetition_factor,
                goal_id=signal.goal_id,
                candidate_id=signal.candidate_id,
                timestamp=signal.timestamp,
            )
            transitions.append(transition)

        return tuple(transitions)
