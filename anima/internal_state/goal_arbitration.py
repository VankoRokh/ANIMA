from dataclasses import dataclass
from datetime import datetime, timezone

from anima.internal_state.goals import GoalStore


@dataclass(frozen=True)
class GoalRankEntry:
    rank: int
    goal_id: str
    priority: float
    created_at: str
    reason: str


@dataclass(frozen=True)
class GoalArbitrationResult:
    selected_goal_id: str | None
    entries: tuple[GoalRankEntry, ...]


def _parse_timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Goal created_at must include a UTC offset")
    return parsed.astimezone(timezone.utc)


class GoalArbitrator:
    """Deterministically rank existing active Goals without mutating them."""

    def __init__(self, goal_store):
        if not isinstance(goal_store, GoalStore):
            raise TypeError("GoalArbitrator requires a GoalStore")
        self.goal_store = goal_store

    @staticmethod
    def _sort_key(goal):
        return (
            -float(goal["priority"]),
            _parse_timestamp(goal["created_at"]),
            goal["id"],
        )

    def evaluate(self):
        goals = sorted(
            self.goal_store.list_active_goals(),
            key=self._sort_key,
        )
        reason = (
            "active Goal priority desc; ties by created_at asc then goal_id asc; "
            "Internal State does not alter Goal priority"
        )
        entries = tuple(
            GoalRankEntry(
                rank=index,
                goal_id=goal["id"],
                priority=float(goal["priority"]),
                created_at=goal["created_at"],
                reason=reason,
            )
            for index, goal in enumerate(goals, start=1)
        )
        return GoalArbitrationResult(
            selected_goal_id=entries[0].goal_id if entries else None,
            entries=entries,
        )
