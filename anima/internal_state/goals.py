import math
import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4

from anima.internal_state.store import InternalStateStore


GOAL_ID_PREFIX = "goal_"
GOAL_TRANSITION_ID_PREFIX = "gt_"
GOAL_STATUSES = {"active", "blocked", "completed", "cancelled"}
TERMINAL_GOAL_STATUSES = {"completed", "cancelled"}
ALLOWED_GOAL_TRANSITIONS = {
    "active": {"blocked", "completed", "cancelled"},
    "blocked": {"active", "completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_timestamp(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _validate_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _validate_optional_string(value, label):
    if value is not None:
        _validate_non_empty_string(value, label)


def _validate_prefixed_uuid4(public_id, prefix, label):
    if not isinstance(public_id, str) or not public_id.startswith(prefix):
        raise ValueError(f"{label} must be a {prefix}UUIDv4")

    raw_uuid = public_id[len(prefix):]
    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a {prefix}UUIDv4") from error

    if parsed.version != 4 or str(parsed) != raw_uuid:
        raise ValueError(f"{label} must be a {prefix}UUIDv4")


class GoalStore:
    """Stage 2 Goal lifecycle over the shared Internal State SQLite database."""

    def __init__(self, internal_state_store):
        if not isinstance(internal_state_store, InternalStateStore):
            raise TypeError("GoalStore requires an InternalStateStore")
        self.internal_state_store = internal_state_store
        self.database_file = internal_state_store.database_file

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _row_to_goal(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "source": row["source"],
            "priority": row["priority"],
            "status": row["status"],
            "description": row["description"],
            "success_criterion": row["success_criterion"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
            "resolution_reason": row["resolution_reason"],
        }

    @staticmethod
    def _row_to_goal_transition(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "goal_id": row["goal_id"],
            "timestamp": row["timestamp"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
            "source_id": row["source_id"],
            "reason": row["reason"],
        }

    def create_goal(
        self,
        *,
        source,
        priority,
        description,
        success_criterion,
        reason,
        source_id=None,
        timestamp=None,
        public_id=None,
        transition_id=None,
    ):
        _validate_non_empty_string(source, "Goal source")
        _validate_non_empty_string(description, "Goal description")
        _validate_non_empty_string(success_criterion, "Goal success_criterion")
        _validate_non_empty_string(reason, "Goal creation reason")
        _validate_optional_string(source_id, "Goal source_id")

        if (
            not _is_number(priority)
            or not math.isfinite(float(priority))
            or priority < 0.0
        ):
            raise ValueError("Goal priority must be a finite non-negative number")
        priority = float(priority)

        timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
        _parse_timestamp(timestamp, "Goal timestamp")

        public_id = public_id or f"{GOAL_ID_PREFIX}{uuid4()}"
        transition_id = transition_id or f"{GOAL_TRANSITION_ID_PREFIX}{uuid4()}"
        _validate_prefixed_uuid4(public_id, GOAL_ID_PREFIX, "Goal public_id")
        _validate_prefixed_uuid4(
            transition_id,
            GOAL_TRANSITION_ID_PREFIX,
            "GoalTransition public_id",
        )

        try:
            with self.internal_state_store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO goals(
                        public_id, source, priority, status, description,
                        success_criterion, created_at, updated_at,
                        resolved_at, resolution_reason
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        public_id,
                        source.strip(),
                        priority,
                        description.strip(),
                        success_criterion.strip(),
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO goal_transitions(
                        public_id, goal_id, timestamp, from_status,
                        to_status, source_id, reason
                    ) VALUES (?, ?, ?, NULL, 'active', ?, ?)
                    """,
                    (
                        transition_id,
                        public_id,
                        timestamp,
                        source_id.strip() if source_id is not None else None,
                        reason.strip(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Cannot create Goal {public_id}: {error}") from error

        return self.get_goal(public_id)

    def get_goal(self, public_id):
        _validate_prefixed_uuid4(public_id, GOAL_ID_PREFIX, "Goal public_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM goals WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_goal(row)

    def list_goals(self, *, status=None):
        if status is not None and status not in GOAL_STATUSES:
            raise ValueError(f"Unknown Goal status: {status!r}")

        query = "SELECT * FROM goals"
        values = ()
        if status is not None:
            query += " WHERE status = ?"
            values = (status,)
        query += " ORDER BY priority DESC, row_id"

        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._row_to_goal(row) for row in rows]

    def list_active_goals(self):
        return self.list_goals(status="active")

    def transition_goal(
        self,
        public_id,
        *,
        to_status,
        reason,
        source_id=None,
        timestamp=None,
        transition_id=None,
    ):
        _validate_prefixed_uuid4(public_id, GOAL_ID_PREFIX, "Goal public_id")
        if to_status not in GOAL_STATUSES:
            raise ValueError(f"Unknown Goal status: {to_status!r}")
        _validate_non_empty_string(reason, "GoalTransition reason")
        _validate_optional_string(source_id, "GoalTransition source_id")

        timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
        transition_time = _parse_timestamp(timestamp, "GoalTransition timestamp")

        transition_id = transition_id or f"{GOAL_TRANSITION_ID_PREFIX}{uuid4()}"
        _validate_prefixed_uuid4(
            transition_id,
            GOAL_TRANSITION_ID_PREFIX,
            "GoalTransition public_id",
        )

        try:
            with self.internal_state_store.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM goals WHERE public_id = ?",
                    (public_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown Goal: {public_id}")

                from_status = row["status"]
                if to_status not in ALLOWED_GOAL_TRANSITIONS[from_status]:
                    raise ValueError(
                        f"Invalid Goal transition: {from_status} -> {to_status}"
                    )

                updated_at = _parse_timestamp(row["updated_at"], "Goal updated_at")
                if transition_time < updated_at:
                    raise ValueError(
                        "GoalTransition timestamp must not be earlier than Goal updated_at"
                    )

                resolved_at = timestamp if to_status in TERMINAL_GOAL_STATUSES else None
                resolution_reason = (
                    reason.strip() if to_status in TERMINAL_GOAL_STATUSES else None
                )

                connection.execute(
                    """
                    UPDATE goals
                    SET status = ?, updated_at = ?,
                        resolved_at = ?, resolution_reason = ?
                    WHERE public_id = ?
                    """,
                    (
                        to_status,
                        timestamp,
                        resolved_at,
                        resolution_reason,
                        public_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO goal_transitions(
                        public_id, goal_id, timestamp, from_status,
                        to_status, source_id, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transition_id,
                        public_id,
                        timestamp,
                        from_status,
                        to_status,
                        source_id.strip() if source_id is not None else None,
                        reason.strip(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot apply GoalTransition {transition_id}: {error}"
            ) from error

        return self.get_goal(public_id)

    def get_goal_transition(self, public_id):
        _validate_prefixed_uuid4(
            public_id,
            GOAL_TRANSITION_ID_PREFIX,
            "GoalTransition public_id",
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM goal_transitions WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_goal_transition(row)

    def list_goal_transitions(self, *, goal_id=None, limit=None):
        if goal_id is not None:
            _validate_prefixed_uuid4(goal_id, GOAL_ID_PREFIX, "Goal public_id")

        if limit is not None and (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 0
        ):
            raise ValueError("GoalTransition limit must be a non-negative integer or null")

        if limit == 0:
            return []

        clauses = []
        values = []
        if goal_id is not None:
            clauses.append("goal_id = ?")
            values.append(goal_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            values.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM goal_transitions
                {where}
                ORDER BY row_id DESC
                {limit_sql}
                """,
                values,
            ).fetchall()

        return [
            self._row_to_goal_transition(row)
            for row in reversed(rows)
        ]

    def goal_count(self, status=None):
        if status is not None and status not in GOAL_STATUSES:
            raise ValueError(f"Unknown Goal status: {status!r}")

        query = "SELECT COUNT(*) AS count FROM goals"
        values = ()
        if status is not None:
            query += " WHERE status = ?"
            values = (status,)

        with self._connect() as connection:
            row = connection.execute(query, values).fetchone()
        return row["count"]
