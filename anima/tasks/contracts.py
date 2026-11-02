from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


TASK_ID_PREFIX = "task_"
TASK_TRANSITION_ID_PREFIX = "tt_"
TASK_STATUSES = {
    "queued",
    "active",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
}
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
ALLOWED_TASK_TRANSITIONS = {
    "queued": {"active", "failed", "cancelled"},
    "active": {"interrupted", "completed", "failed", "cancelled"},
    "interrupted": {"active", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(value, label):
    if value is None:
        return None
    return _require_text(value, label)


def _validate_timestamp(value, label):
    value = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return value


def _validate_prefixed_uuid4(value, *, prefix, label):
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(f"{label} must be a {prefix}UUIDv4")
    raw_uuid = value[len(prefix):]
    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a {prefix}UUIDv4") from error
    if parsed.version != 4 or str(parsed) != raw_uuid:
        raise ValueError(f"{label} must be a {prefix}UUIDv4")
    return value


def validate_task_id(value):
    return _validate_prefixed_uuid4(
        value,
        prefix=TASK_ID_PREFIX,
        label="Task public_id",
    )


def validate_transition_id(value):
    return _validate_prefixed_uuid4(
        value,
        prefix=TASK_TRANSITION_ID_PREFIX,
        label="TaskTransition public_id",
    )


def validate_goal_id(value):
    if value is None:
        return None
    return _validate_prefixed_uuid4(
        value,
        prefix="goal_",
        label="Task goal_id",
    )


@dataclass(frozen=True, slots=True)
class Task:
    public_id: str
    source: str
    source_id: str | None
    goal_id: str | None
    description: str
    status: str
    created_at: str
    updated_at: str
    resolved_at: str | None = None
    terminal_reason: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "public_id", validate_task_id(self.public_id))
        object.__setattr__(self, "source", _require_text(self.source, "Task source"))
        object.__setattr__(
            self,
            "source_id",
            _optional_text(self.source_id, "Task source_id"),
        )
        object.__setattr__(self, "goal_id", validate_goal_id(self.goal_id))
        object.__setattr__(
            self,
            "description",
            _require_text(self.description, "Task description"),
        )
        if self.status not in TASK_STATUSES:
            raise ValueError(f"Unknown Task status: {self.status!r}")
        object.__setattr__(
            self,
            "created_at",
            _validate_timestamp(self.created_at, "Task created_at"),
        )
        object.__setattr__(
            self,
            "updated_at",
            _validate_timestamp(self.updated_at, "Task updated_at"),
        )

        terminal = self.status in TERMINAL_TASK_STATUSES
        if terminal:
            object.__setattr__(
                self,
                "resolved_at",
                _validate_timestamp(self.resolved_at, "Task resolved_at"),
            )
            object.__setattr__(
                self,
                "terminal_reason",
                _require_text(self.terminal_reason, "Task terminal_reason"),
            )
        else:
            if self.resolved_at is not None or self.terminal_reason is not None:
                raise ValueError(
                    "Non-terminal Task cannot contain resolved_at or terminal_reason"
                )

        created = datetime.fromisoformat(self.created_at)
        updated = datetime.fromisoformat(self.updated_at)
        if updated < created:
            raise ValueError("Task updated_at cannot precede created_at")
        if self.resolved_at is not None:
            resolved = datetime.fromisoformat(self.resolved_at)
            if resolved < created or resolved < updated:
                raise ValueError(
                    "Task resolved_at cannot precede created_at or updated_at"
                )

    def to_dict(self):
        return {
            "id": self.public_id,
            "source": self.source,
            "source_id": self.source_id,
            "goal_id": self.goal_id,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
            "terminal_reason": self.terminal_reason,
        }


@dataclass(frozen=True, slots=True)
class TaskTransition:
    public_id: str
    task_id: str
    timestamp: str
    from_status: str | None
    to_status: str
    source_id: str | None
    reason: str

    def __post_init__(self):
        object.__setattr__(
            self,
            "public_id",
            validate_transition_id(self.public_id),
        )
        object.__setattr__(self, "task_id", validate_task_id(self.task_id))
        object.__setattr__(
            self,
            "timestamp",
            _validate_timestamp(self.timestamp, "TaskTransition timestamp"),
        )
        if self.from_status is not None and self.from_status not in TASK_STATUSES:
            raise ValueError(
                f"Unknown TaskTransition from_status: {self.from_status!r}"
            )
        if self.to_status not in TASK_STATUSES:
            raise ValueError(
                f"Unknown TaskTransition to_status: {self.to_status!r}"
            )
        object.__setattr__(
            self,
            "source_id",
            _optional_text(self.source_id, "TaskTransition source_id"),
        )
        object.__setattr__(
            self,
            "reason",
            _require_text(self.reason, "TaskTransition reason"),
        )

    def to_dict(self):
        return {
            "id": self.public_id,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "source_id": self.source_id,
            "reason": self.reason,
        }
