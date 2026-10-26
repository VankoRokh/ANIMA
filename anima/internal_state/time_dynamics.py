from datetime import datetime, timezone
from enum import StrEnum

from anima.internal_state.store import InternalStateStore
from anima.internal_state.time_rules import (
    load_time_rules_config,
    validate_time_rules_config,
)
from anima.internal_state.variables import StateName, StateVariableRegistry


_SECONDS_PER_HOUR = 3600.0
_EPSILON = 1e-12


class TimeMode(StrEnum):
    AWAKE = "awake"
    RECOVERY = "recovery"


def _parse_timestamp(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


class TimeDynamics:
    def __init__(
        self,
        store,
        *,
        rules_config=None,
        rules_config_file=None,
        registry=None,
    ):
        if not isinstance(store, InternalStateStore):
            raise TypeError("TimeDynamics store must be an InternalStateStore")
        if rules_config is not None and rules_config_file is not None:
            raise ValueError("Provide rules_config or rules_config_file, not both")

        self.store = store
        self.rules = (
            validate_time_rules_config(rules_config)
            if rules_config is not None
            else load_time_rules_config(rules_config_file)
        )
        self.registry = registry or StateVariableRegistry(store.config)

        if self.rules["ruleset_version"] != self.store.ruleset_version():
            raise ValueError(
                "Time ruleset version must match Internal State store ruleset"
            )

    @property
    def ruleset_version(self):
        return self.rules["ruleset_version"]

    @staticmethod
    def _coerce_mode(mode):
        try:
            return TimeMode(mode)
        except (ValueError, TypeError) as error:
            raise ValueError(f"Unknown Internal State time mode: {mode!r}") from error

    def _latest_transition_time(self, state_name, *, time_only=False):
        transitions = self.store.list_state_transitions(
            state_name=state_name.value
        )
        if time_only:
            transitions = [
                item for item in transitions
                if item["cause_type"] == "time"
            ]
        if not transitions:
            return None
        return _parse_timestamp(
            transitions[-1]["timestamp"],
            f"latest {state_name.value} transition timestamp",
        )

    def _cursor(self, state_name, period_started, now, *, time_only=False):
        latest = self._latest_transition_time(state_name, time_only=time_only)
        if latest is not None and latest > now:
            raise ValueError(
                f"Latest {state_name.value} transition is later than evaluation time"
            )
        if latest is None:
            return period_started
        return max(period_started, latest)

    def _integrate_awake_fatigue(self, start_elapsed, end_elapsed):
        if end_elapsed <= start_elapsed:
            return 0.0

        work_period = float(self.rules["awake_work_period_seconds"])
        fatigue = self.rules["fatigue"]
        total = 0.0
        cursor = start_elapsed

        for segment in fatigue["awake_segments"]:
            boundary = float(segment["until_ratio"]) * work_period
            if cursor >= boundary:
                continue
            segment_end = min(end_elapsed, boundary)
            if segment_end > cursor:
                hours = (segment_end - cursor) / _SECONDS_PER_HOUR
                total += hours * float(segment["rate_per_hour"])
                cursor = segment_end
            if cursor >= end_elapsed:
                return total

        if cursor < end_elapsed:
            hours = (end_elapsed - cursor) / _SECONDS_PER_HOUR
            total += hours * float(fatigue["beyond_rate_per_hour"])

        return total

    def _toward_baseline_delta(self, state_name, rate_per_hour, elapsed_seconds):
        definition = self.registry.get(state_name)
        current = float(self.store.get_state(state_name.value)["value"])
        baseline = float(definition.baseline)
        if current == baseline or elapsed_seconds <= 0.0:
            return 0.0

        magnitude = float(rate_per_hour) * (elapsed_seconds / _SECONDS_PER_HOUR)
        if current > baseline:
            target = max(baseline, current - magnitude)
        else:
            target = min(baseline, current + magnitude)
        target = definition.clamp(target)
        return target - current

    def _fatigue_delta(self, mode, period_started, cursor, now):
        current = float(self.store.get_state(StateName.FATIGUE.value)["value"])
        definition = self.registry.get(StateName.FATIGUE)

        if mode is TimeMode.AWAKE:
            start_elapsed = (cursor - period_started).total_seconds()
            end_elapsed = (now - period_started).total_seconds()
            raw_delta = self._integrate_awake_fatigue(start_elapsed, end_elapsed)
        else:
            elapsed = (now - cursor).total_seconds()
            raw_delta = -float(
                self.rules["fatigue"]["recovery_rate_per_hour"]
            ) * (elapsed / _SECONDS_PER_HOUR)

        target = definition.clamp(current + raw_delta)
        return target - current

    def _record(
        self,
        *,
        state_name,
        delta,
        now_text,
        elapsed_seconds,
        rule_name,
        reason,
    ):
        if abs(delta) <= _EPSILON:
            return None
        return self.store.apply_state_transition(
            state_name=state_name.value,
            delta=delta,
            cause_type="time",
            rule_id=(
                f"stage2.{state_name.value}.{rule_name}.v{self.ruleset_version}"
            ),
            reason=reason,
            elapsed_seconds=elapsed_seconds,
            timestamp=now_text,
        )

    def evaluate(self, *, now, mode, period_started_at):
        mode = self._coerce_mode(mode)
        now_dt = _parse_timestamp(now, "TimeDynamics now")
        period_started = _parse_timestamp(
            period_started_at,
            "TimeDynamics period_started_at",
        )
        if period_started > now_dt:
            raise ValueError("TimeDynamics period_started_at cannot be later than now")

        now_text = now_dt.isoformat(timespec="seconds")
        transitions = []

        fatigue_cursor = self._cursor(
            StateName.FATIGUE,
            period_started,
            now_dt,
            time_only=True,
        )
        fatigue_elapsed = (now_dt - fatigue_cursor).total_seconds()
        fatigue_delta = self._fatigue_delta(
            mode,
            period_started,
            fatigue_cursor,
            now_dt,
        )
        fatigue_transition = self._record(
            state_name=StateName.FATIGUE,
            delta=fatigue_delta,
            now_text=now_text,
            elapsed_seconds=fatigue_elapsed,
            rule_name=("time_awake" if mode is TimeMode.AWAKE else "time_recovery"),
            reason=(
                "fatigue accumulated from elapsed awake time"
                if mode is TimeMode.AWAKE
                else "fatigue recovered during recovery period"
            ),
        )
        if fatigue_transition is not None:
            transitions.append(fatigue_transition)

        frustration_cursor = self._cursor(
            StateName.FRUSTRATION,
            period_started,
            now_dt,
        )
        frustration_elapsed = (now_dt - frustration_cursor).total_seconds()
        frustration_delta = self._toward_baseline_delta(
            StateName.FRUSTRATION,
            self.rules["frustration"]["recovery_rate_per_hour"],
            frustration_elapsed,
        )
        frustration_transition = self._record(
            state_name=StateName.FRUSTRATION,
            delta=frustration_delta,
            now_text=now_text,
            elapsed_seconds=frustration_elapsed,
            rule_name="time_recovery",
            reason="frustration recovered toward baseline over elapsed time",
        )
        if frustration_transition is not None:
            transitions.append(frustration_transition)

        satisfaction_cursor = self._cursor(
            StateName.SATISFACTION,
            period_started,
            now_dt,
        )
        satisfaction_elapsed = (now_dt - satisfaction_cursor).total_seconds()
        satisfaction_delta = self._toward_baseline_delta(
            StateName.SATISFACTION,
            self.rules["satisfaction"]["decay_rate_per_hour"],
            satisfaction_elapsed,
        )
        satisfaction_transition = self._record(
            state_name=StateName.SATISFACTION,
            delta=satisfaction_delta,
            now_text=now_text,
            elapsed_seconds=satisfaction_elapsed,
            rule_name="time_decay",
            reason="satisfaction decayed toward baseline over elapsed time",
        )
        if satisfaction_transition is not None:
            transitions.append(satisfaction_transition)

        # uncertainty is intentionally absent: elapsed time alone is not evidence.
        return tuple(transitions)
