from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from anima.internal_state.goals import GoalStore
from anima.internal_state.transition_engine import (
    SignalKind,
    StateSignal,
    TransitionEngine,
)


class GoalObservationKind(StrEnum):
    FAILURE = "failure"
    PROGRESS = "progress"
    BLOCKED = "blocked"
    REACTIVATED = "reactivated"
    SUCCESS = "success"


class VerificationKind(StrEnum):
    UNVERIFIED = "unverified"
    OBSERVATION = "observation"
    CONFIRMED_RESULT = "confirmed_result"


@dataclass(frozen=True)
class GoalObservation:
    goal_id: str
    kind: GoalObservationKind | str
    source_id: str
    reason: str
    verification: VerificationKind | str
    candidate_id: str | None = None
    importance: int = 1
    criterion_satisfied: bool = False
    timestamp: str | None = None


@dataclass(frozen=True)
class GoalProgressResult:
    goal: dict
    state_transitions: tuple[dict, ...]
    goal_transition: dict | None


_CANDIDATE_SCOPED = {
    GoalObservationKind.FAILURE,
    GoalObservationKind.PROGRESS,
    GoalObservationKind.BLOCKED,
    GoalObservationKind.SUCCESS,
}

_ACTIVE_ONLY = {
    GoalObservationKind.FAILURE,
    GoalObservationKind.PROGRESS,
    GoalObservationKind.BLOCKED,
}


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


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


class GoalProgressEngine:
    """Apply verified observations to Goal lifecycle and Internal State."""

    def __init__(self, goal_store, transition_engine):
        if not isinstance(goal_store, GoalStore):
            raise TypeError("GoalProgressEngine goal_store must be a GoalStore")
        if not isinstance(transition_engine, TransitionEngine):
            raise TypeError(
                "GoalProgressEngine transition_engine must be a TransitionEngine"
            )
        if goal_store.database_file != transition_engine.store.database_file:
            raise ValueError(
                "GoalProgressEngine stores must use the same internal_state.db"
            )

        self.goal_store = goal_store
        self.transition_engine = transition_engine

    @staticmethod
    def _coerce_kind(kind):
        try:
            return GoalObservationKind(kind)
        except (ValueError, TypeError) as error:
            raise ValueError(f"Unknown Goal observation kind: {kind!r}") from error

    @staticmethod
    def _coerce_verification(verification):
        try:
            return VerificationKind(verification)
        except (ValueError, TypeError) as error:
            raise ValueError(
                f"Unknown Goal verification kind: {verification!r}"
            ) from error

    def _validate(self, observation):
        if not isinstance(observation, GoalObservation):
            raise TypeError("GoalProgressEngine requires a GoalObservation")

        kind = self._coerce_kind(observation.kind)
        verification = self._coerce_verification(observation.verification)
        if verification is VerificationKind.UNVERIFIED:
            raise ValueError(
                "Unverified Goal observations cannot change Goal or Internal State"
            )

        source_id = _require_text(observation.source_id, "GoalObservation source_id")
        reason = _require_text(observation.reason, "GoalObservation reason")

        importance = observation.importance
        if (
            not isinstance(importance, int)
            or isinstance(importance, bool)
            or importance not in range(4)
        ):
            raise ValueError(
                "GoalObservation importance must be an integer from 0 to 3"
            )

        if not isinstance(observation.criterion_satisfied, bool):
            raise ValueError("GoalObservation criterion_satisfied must be boolean")

        candidate_id = observation.candidate_id
        if kind in _CANDIDATE_SCOPED:
            candidate_id = _require_text(
                candidate_id,
                "GoalObservation candidate_id",
            )
        elif candidate_id is not None:
            candidate_id = _require_text(
                candidate_id,
                "GoalObservation candidate_id",
            )

        if kind is GoalObservationKind.SUCCESS:
            if not observation.criterion_satisfied:
                raise ValueError(
                    "Goal success requires an explicitly satisfied success criterion"
                )
        elif observation.criterion_satisfied:
            raise ValueError(
                "A satisfied success criterion must be reported as Goal success"
            )

        goal = self.goal_store.get_goal(observation.goal_id)
        if goal is None:
            raise ValueError(f"Unknown Goal: {observation.goal_id}")

        if kind in _ACTIVE_ONLY and goal["status"] != "active":
            raise ValueError(
                f"{kind.value} requires an active Goal, got {goal['status']}"
            )
        if kind is GoalObservationKind.REACTIVATED and goal["status"] != "blocked":
            raise ValueError(
                f"reactivated requires a blocked Goal, got {goal['status']}"
            )
        if kind is GoalObservationKind.SUCCESS and goal["status"] not in {
            "active",
            "blocked",
        }:
            raise ValueError(
                f"success requires an active or blocked Goal, got {goal['status']}"
            )

        timestamp = observation.timestamp or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        observed_at = _parse_timestamp(timestamp, "GoalObservation timestamp")
        goal_updated_at = _parse_timestamp(goal["updated_at"], "Goal updated_at")
        if observed_at < goal_updated_at:
            raise ValueError(
                "GoalObservation timestamp must not be earlier than Goal updated_at"
            )

        return GoalObservation(
            goal_id=goal["id"],
            kind=kind,
            source_id=source_id,
            reason=reason,
            verification=verification,
            candidate_id=candidate_id,
            importance=importance,
            criterion_satisfied=observation.criterion_satisfied,
            timestamp=timestamp,
        )

    def _state_signal(self, observation):
        mapping = {
            GoalObservationKind.FAILURE: SignalKind.FAILURE,
            GoalObservationKind.PROGRESS: SignalKind.VERIFIED_PROGRESS,
            # A verified blocker is treated as a failure-like anti-looping signal.
            GoalObservationKind.BLOCKED: SignalKind.FAILURE,
            GoalObservationKind.SUCCESS: SignalKind.VERIFIED_SUCCESS,
        }
        signal_kind = mapping.get(observation.kind)
        if signal_kind is None:
            return ()

        return self.transition_engine.process(
            StateSignal(
                kind=signal_kind,
                source_id=observation.source_id,
                reason=observation.reason,
                importance=observation.importance,
                goal_id=observation.goal_id,
                candidate_id=observation.candidate_id,
                timestamp=observation.timestamp,
            )
        )

    def process(self, observation):
        observation = self._validate(observation)
        state_transitions = self._state_signal(observation)
        goal_transition = None

        if observation.kind is GoalObservationKind.BLOCKED:
            self.goal_store.transition_goal(
                observation.goal_id,
                to_status="blocked",
                reason=observation.reason,
                source_id=observation.source_id,
                timestamp=observation.timestamp,
            )
        elif observation.kind is GoalObservationKind.REACTIVATED:
            self.goal_store.transition_goal(
                observation.goal_id,
                to_status="active",
                reason=observation.reason,
                source_id=observation.source_id,
                timestamp=observation.timestamp,
            )
        elif observation.kind is GoalObservationKind.SUCCESS:
            self.goal_store.transition_goal(
                observation.goal_id,
                to_status="completed",
                reason=observation.reason,
                source_id=observation.source_id,
                timestamp=observation.timestamp,
            )

        if observation.kind in {
            GoalObservationKind.BLOCKED,
            GoalObservationKind.REACTIVATED,
            GoalObservationKind.SUCCESS,
        }:
            goal_transition = self.goal_store.list_goal_transitions(
                goal_id=observation.goal_id,
                limit=1,
            )[0]

        return GoalProgressResult(
            goal=self.goal_store.get_goal(observation.goal_id),
            state_transitions=tuple(state_transitions),
            goal_transition=goal_transition,
        )
