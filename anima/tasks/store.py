import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from anima.config.paths import get_data_dir
from anima.tasks.contracts import (
    ALLOWED_TASK_TRANSITIONS,
    TASK_ID_PREFIX,
    TASK_STATUSES,
    TASK_TRANSITION_ID_PREFIX,
    TERMINAL_TASK_STATUSES,
    Task,
    TaskTransition,
    validate_goal_id,
    validate_task_id,
    validate_transition_id,
)


SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_id TEXT,
    goal_id TEXT,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'active', 'interrupted', 'completed', 'failed', 'cancelled')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    terminal_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_created
    ON tasks(status, created_at, row_id);
CREATE INDEX IF NOT EXISTS idx_tasks_goal_created
    ON tasks(goal_id, created_at, row_id);
CREATE INDEX IF NOT EXISTS idx_tasks_source
    ON tasks(source_id, created_at, row_id);

CREATE TABLE IF NOT EXISTS task_transitions (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    from_status TEXT CHECK (
        from_status IS NULL OR from_status IN (
            'queued', 'active', 'interrupted', 'completed', 'failed', 'cancelled'
        )
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('queued', 'active', 'interrupted', 'completed', 'failed', 'cancelled')
    ),
    source_id TEXT,
    reason TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_transitions_task_time
    ON task_transitions(task_id, timestamp, row_id);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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


def _validate_status(status):
    if status not in TASK_STATUSES:
        raise ValueError(f"Unknown Task status: {status!r}")
    return status


class TaskStore:
    """System-owned persistence for Stage 6 Tasks.

    Task persistence deliberately contains no model, backend or Planner fields.
    Goal references are logical IDs only; Goal lifecycle remains owned by
    InternalState/GoalStore in its separate database.
    """

    def __init__(self, database_file=None):
        self.database_file = (
            Path(database_file)
            if database_file is not None
            else get_data_dir() / "tasks.db"
        )
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def transaction(self):
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN")
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self):
        with closing(self._connect()) as connection, connection:
            connection.executescript(SCHEMA_SQL)
            connection.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None or row["value"] != str(SCHEMA_VERSION):
                raise ValueError(
                    f"Unsupported TaskStore schema in {self.database_file}"
                )

    def schema_version(self):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        if row is None:
            raise ValueError("TaskStore schema is not initialized")
        return int(row["value"])

    @staticmethod
    def _row_to_task(row):
        if row is None:
            return None
        return Task(
            public_id=row["public_id"],
            source=row["source"],
            source_id=row["source_id"],
            goal_id=row["goal_id"],
            description=row["description"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            resolved_at=row["resolved_at"],
            terminal_reason=row["terminal_reason"],
        )

    @staticmethod
    def _row_to_transition(row):
        if row is None:
            return None
        return TaskTransition(
            public_id=row["public_id"],
            task_id=row["task_id"],
            timestamp=row["timestamp"],
            from_status=row["from_status"],
            to_status=row["to_status"],
            source_id=row["source_id"],
            reason=row["reason"],
        )

    def create_task(
        self,
        *,
        source,
        description,
        reason,
        source_id=None,
        goal_id=None,
        timestamp=None,
        public_id=None,
        transition_id=None,
    ):
        source = _require_text(source, "Task source")
        description = _require_text(description, "Task description")
        reason = _require_text(reason, "Task creation reason")
        source_id = _optional_text(source_id, "Task source_id")
        goal_id = validate_goal_id(goal_id)
        timestamp = _validate_timestamp(timestamp or _now(), "Task timestamp")
        public_id = public_id or f"{TASK_ID_PREFIX}{uuid4()}"
        transition_id = transition_id or f"{TASK_TRANSITION_ID_PREFIX}{uuid4()}"
        validate_task_id(public_id)
        validate_transition_id(transition_id)

        task = Task(
            public_id=public_id,
            source=source,
            source_id=source_id,
            goal_id=goal_id,
            description=description,
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
        )
        transition = TaskTransition(
            public_id=transition_id,
            task_id=public_id,
            timestamp=timestamp,
            from_status=None,
            to_status="queued",
            source_id=source_id,
            reason=reason,
        )

        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO tasks(
                        public_id, source, source_id, goal_id, description, status,
                        created_at, updated_at, resolved_at, terminal_reason
                    ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, NULL, NULL)
                    """,
                    (
                        task.public_id,
                        task.source,
                        task.source_id,
                        task.goal_id,
                        task.description,
                        task.created_at,
                        task.updated_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO task_transitions(
                        public_id, task_id, timestamp, from_status,
                        to_status, source_id, reason
                    ) VALUES (?, ?, ?, NULL, 'queued', ?, ?)
                    """,
                    (
                        transition.public_id,
                        transition.task_id,
                        transition.timestamp,
                        transition.source_id,
                        transition.reason,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Cannot create Task {public_id}: {error}") from error

        return self.get_task(public_id)

    def get_task(self, public_id):
        validate_task_id(public_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_task(row)

    def list_tasks(self, *, status=None, goal_id=None):
        if status is not None:
            _validate_status(status)
        if goal_id is not None:
            validate_goal_id(goal_id)

        clauses = []
        values = []
        if status is not None:
            clauses.append("status = ?")
            values.append(status)
        if goal_id is not None:
            clauses.append("goal_id = ?")
            values.append(goal_id)

        query = "SELECT * FROM tasks"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at, row_id"

        with closing(self._connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._row_to_task(row) for row in rows]

    def transition_task(
        self,
        public_id,
        to_status,
        *,
        reason,
        source_id=None,
        timestamp=None,
        transition_id=None,
    ):
        validate_task_id(public_id)
        _validate_status(to_status)
        reason = _require_text(reason, "Task transition reason")
        source_id = _optional_text(source_id, "Task transition source_id")
        timestamp = _validate_timestamp(timestamp or _now(), "Task transition timestamp")
        transition_id = transition_id or f"{TASK_TRANSITION_ID_PREFIX}{uuid4()}"
        validate_transition_id(transition_id)

        try:
            with self.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM tasks WHERE public_id = ?",
                    (public_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown Task: {public_id}")
                current = self._row_to_task(row)
                if to_status not in ALLOWED_TASK_TRANSITIONS[current.status]:
                    raise ValueError(
                        f"Invalid Task transition: {current.status} -> {to_status}"
                    )

                resolved_at = timestamp if to_status in TERMINAL_TASK_STATUSES else None
                terminal_reason = reason if resolved_at is not None else None
                updated = Task(
                    public_id=current.public_id,
                    source=current.source,
                    source_id=current.source_id,
                    goal_id=current.goal_id,
                    description=current.description,
                    status=to_status,
                    created_at=current.created_at,
                    updated_at=timestamp,
                    resolved_at=resolved_at,
                    terminal_reason=terminal_reason,
                )
                transition = TaskTransition(
                    public_id=transition_id,
                    task_id=public_id,
                    timestamp=timestamp,
                    from_status=current.status,
                    to_status=to_status,
                    source_id=source_id,
                    reason=reason,
                )

                cursor = connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, updated_at = ?, resolved_at = ?, terminal_reason = ?
                    WHERE public_id = ? AND status = ?
                    """,
                    (
                        updated.status,
                        updated.updated_at,
                        updated.resolved_at,
                        updated.terminal_reason,
                        public_id,
                        current.status,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"Task changed concurrently while transitioning: {public_id}"
                    )
                connection.execute(
                    """
                    INSERT INTO task_transitions(
                        public_id, task_id, timestamp, from_status,
                        to_status, source_id, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transition.public_id,
                        transition.task_id,
                        transition.timestamp,
                        transition.from_status,
                        transition.to_status,
                        transition.source_id,
                        transition.reason,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot transition Task {public_id} to {to_status}: {error}"
            ) from error

        return self.get_task(public_id)

    def list_transitions(self, public_id):
        validate_task_id(public_id)
        if self.get_task(public_id) is None:
            raise ValueError(f"Unknown Task: {public_id}")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_transitions
                WHERE task_id = ?
                ORDER BY timestamp, row_id
                """,
                (public_id,),
            ).fetchall()
        return [self._row_to_transition(row) for row in rows]
