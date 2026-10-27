import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from anima.config.paths import get_data_dir


SCHEMA_VERSION = 1

AGENT_RUN_ID_PREFIX = "ar_"
AGENT_RUN_TRANSITION_ID_PREFIX = "art_"
AGENT_STEP_ID_PREFIX = "ast_"
AGENT_STEP_TRANSITION_ID_PREFIX = "astt_"
AGENT_OPERATION_ID_PREFIX = "aop_"
ACTION_ID_PREFIX = "act_"

AGENT_RUN_STATUSES = {
    "queued",
    "running",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
}
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
ALLOWED_RUN_TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"interrupted", "completed", "failed", "cancelled"},
    "interrupted": {"running", "completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

AGENT_STEP_STATUSES = {
    "planning",
    "planned",
    "selected",
    "executing",
    "executed",
    "observed",
    "verified",
    "completed",
    "failed",
    "cancelled",
}
TERMINAL_STEP_STATUSES = {"completed", "failed", "cancelled"}
ALLOWED_STEP_TRANSITIONS = {
    "planning": {"planned", "failed", "cancelled"},
    "planned": {"selected", "completed", "failed", "cancelled"},
    "selected": {"executing", "failed", "cancelled"},
    "executing": {"executed", "failed"},
    "executed": {"observed", "failed"},
    "observed": {"verified", "failed"},
    "verified": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

AGENT_OPERATION_STATUSES = {
    "prepared",
    "executing",
    "succeeded",
    "failed",
    "uncertain",
    "cancelled",
}
TERMINAL_OPERATION_STATUSES = {"succeeded", "failed", "cancelled"}
ALLOWED_OPERATION_TRANSITIONS = {
    "prepared": {"executing", "cancelled"},
    "executing": {"succeeded", "failed", "uncertain"},
    "uncertain": {"executing", "succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}
IDEMPOTENCY_CLASSES = {"repeat_safe", "keyed", "none"}

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    goal_id TEXT NOT NULL,
    planner TEXT NOT NULL,
    planner_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'interrupted', 'completed', 'failed', 'cancelled')
    ),
    terminal_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_goal_created
    ON agent_runs(goal_id, created_at, row_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status_created
    ON agent_runs(status, created_at, row_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_one_non_terminal_per_goal
    ON agent_runs(goal_id)
    WHERE status IN ('queued', 'running', 'interrupted');

CREATE TABLE IF NOT EXISTS agent_run_transitions (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    from_status TEXT CHECK (
        from_status IS NULL OR from_status IN (
            'queued', 'running', 'interrupted', 'completed', 'failed', 'cancelled'
        )
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('queued', 'running', 'interrupted', 'completed', 'failed', 'cancelled')
    ),
    reason TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES agent_runs(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_run_transitions_run_time
    ON agent_run_transitions(run_id, timestamp, row_id);

CREATE TABLE IF NOT EXISTS agent_steps (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    status TEXT NOT NULL CHECK (
        status IN (
            'planning', 'planned', 'selected', 'executing', 'executed',
            'observed', 'verified', 'completed', 'failed', 'cancelled'
        )
    ),
    terminal_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, sequence),
    FOREIGN KEY (run_id) REFERENCES agent_runs(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run_sequence
    ON agent_steps(run_id, sequence, row_id);
CREATE INDEX IF NOT EXISTS idx_agent_steps_status
    ON agent_steps(status, created_at, row_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_steps_one_non_terminal_per_run
    ON agent_steps(run_id)
    WHERE status IN (
        'planning', 'planned', 'selected', 'executing',
        'executed', 'observed', 'verified'
    );

CREATE TABLE IF NOT EXISTS agent_step_transitions (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    step_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    from_status TEXT CHECK (
        from_status IS NULL OR from_status IN (
            'planning', 'planned', 'selected', 'executing', 'executed',
            'observed', 'verified', 'completed', 'failed', 'cancelled'
        )
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN (
            'planning', 'planned', 'selected', 'executing', 'executed',
            'observed', 'verified', 'completed', 'failed', 'cancelled'
        )
    ),
    reason TEXT NOT NULL,
    FOREIGN KEY (step_id) REFERENCES agent_steps(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_step_transitions_step_time
    ON agent_step_transitions(step_id, timestamp, row_id);

CREATE TABLE IF NOT EXISTS agent_operations (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    action_id TEXT UNIQUE,
    operation_kind TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK (
        length(request_hash) = 64 AND request_hash = lower(request_hash)
    ),
    idempotency_class TEXT NOT NULL CHECK (
        idempotency_class IN ('repeat_safe', 'keyed', 'none')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('prepared', 'executing', 'succeeded', 'failed', 'uncertain', 'cancelled')
    ),
    status_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES agent_runs(public_id) ON DELETE CASCADE,
    FOREIGN KEY (step_id) REFERENCES agent_steps(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_operations_run_step
    ON agent_operations(run_id, step_id, row_id);
CREATE INDEX IF NOT EXISTS idx_agent_operations_status
    ON agent_operations(status, created_at, row_id);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_timestamp(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")


def _validate_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _validate_prefixed_uuid4(public_id, *, prefix, label):
    if not isinstance(public_id, str) or not public_id.startswith(prefix):
        raise ValueError(f"{label} must be a {prefix}UUIDv4")
    raw_uuid = public_id[len(prefix):]
    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a {prefix}UUIDv4") from error
    if parsed.version != 4 or str(parsed) != raw_uuid:
        raise ValueError(f"{label} must be a {prefix}UUIDv4")


def _validate_goal_id(goal_id):
    _validate_prefixed_uuid4(goal_id, prefix="goal_", label="AgentRun goal_id")


def _validate_run_id(public_id):
    _validate_prefixed_uuid4(
        public_id,
        prefix=AGENT_RUN_ID_PREFIX,
        label="AgentRun public_id",
    )


def _validate_step_id(public_id):
    _validate_prefixed_uuid4(
        public_id,
        prefix=AGENT_STEP_ID_PREFIX,
        label="AgentStep public_id",
    )


def _validate_operation_id(public_id):
    _validate_prefixed_uuid4(
        public_id,
        prefix=AGENT_OPERATION_ID_PREFIX,
        label="AgentOperation public_id",
    )


def _validate_action_id(public_id):
    _validate_prefixed_uuid4(
        public_id,
        prefix=ACTION_ID_PREFIX,
        label="Action public_id",
    )


def _validate_run_status(status):
    if status not in AGENT_RUN_STATUSES:
        raise ValueError(f"Unknown AgentRun status: {status!r}")


def _validate_step_status(status):
    if status not in AGENT_STEP_STATUSES:
        raise ValueError(f"Unknown AgentStep status: {status!r}")


def _validate_operation_status(status):
    if status not in AGENT_OPERATION_STATUSES:
        raise ValueError(f"Unknown AgentOperation status: {status!r}")


class AgentStore:
    """Persistent Stage 4 Agent execution state and operation identity."""

    def __init__(self, database_file=None):
        self.database_file = (
            Path(database_file)
            if database_file is not None
            else get_data_dir() / "agent.db"
        )
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is not None and row["value"] != str(SCHEMA_VERSION):
                    raise ValueError(
                        f"Unsupported Agent database schema in {self.database_file}"
                    )

                connection.executescript(SCHEMA_SQL)
                if row is None:
                    connection.execute(
                        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                final_row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
        except ValueError:
            raise
        except sqlite3.DatabaseError as error:
            raise ValueError(
                f"Cannot initialize Agent database {self.database_file}: {error}"
            ) from error

        if final_row is None or final_row["value"] != str(SCHEMA_VERSION):
            raise ValueError(
                f"Unsupported Agent database schema in {self.database_file}"
            )

    @contextmanager
    def transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def schema_version(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    @staticmethod
    def _row_to_run(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "goal_id": row["goal_id"],
            "planner": row["planner"],
            "planner_version": row["planner_version"],
            "status": row["status"],
            "terminal_reason": row["terminal_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_run_transition(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "run_id": row["run_id"],
            "timestamp": row["timestamp"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
            "reason": row["reason"],
        }

    @staticmethod
    def _row_to_step(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "run_id": row["run_id"],
            "sequence": row["sequence"],
            "status": row["status"],
            "terminal_reason": row["terminal_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_step_transition(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "step_id": row["step_id"],
            "timestamp": row["timestamp"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
            "reason": row["reason"],
        }

    @staticmethod
    def _row_to_operation(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "run_id": row["run_id"],
            "step_id": row["step_id"],
            "action_id": row["action_id"],
            "operation_kind": row["operation_kind"],
            "request_hash": row["request_hash"],
            "idempotency_class": row["idempotency_class"],
            "status": row["status"],
            "status_reason": row["status_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_run(
        self,
        *,
        goal_id,
        planner,
        planner_version,
        public_id=None,
        created_at=None,
        reason="run created",
    ):
        public_id = public_id or f"{AGENT_RUN_ID_PREFIX}{uuid4()}"
        created_at = created_at or _now()
        _validate_run_id(public_id)
        _validate_goal_id(goal_id)
        _validate_non_empty_string(planner, "AgentRun planner")
        _validate_non_empty_string(planner_version, "AgentRun planner_version")
        _validate_timestamp(created_at, "AgentRun created_at")
        _validate_non_empty_string(reason, "AgentRun transition reason")
        transition_id = f"{AGENT_RUN_TRANSITION_ID_PREFIX}{uuid4()}"

        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO agent_runs(
                        public_id, goal_id, planner, planner_version,
                        status, terminal_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', NULL, ?, ?)
                    """,
                    (
                        public_id,
                        goal_id,
                        planner.strip(),
                        planner_version.strip(),
                        created_at,
                        created_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO agent_run_transitions(
                        public_id, run_id, timestamp, from_status, to_status, reason
                    ) VALUES (?, ?, ?, NULL, 'queued', ?)
                    """,
                    (transition_id, public_id, created_at, reason.strip()),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Cannot create AgentRun {public_id}: {error}") from error

        return self.get_run(public_id)

    def get_run(self, public_id):
        _validate_run_id(public_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_run(row)

    def list_runs(self, *, goal_id=None, status=None):
        clauses = []
        values = []
        if goal_id is not None:
            _validate_goal_id(goal_id)
            clauses.append("goal_id = ?")
            values.append(goal_id)
        if status is not None:
            _validate_run_status(status)
            clauses.append("status = ?")
            values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs" + where + " ORDER BY row_id",
                tuple(values),
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def list_run_transitions(self, public_id):
        _validate_run_id(public_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_run_transitions
                WHERE run_id = ?
                ORDER BY row_id
                """,
                (public_id,),
            ).fetchall()
        return [self._row_to_run_transition(row) for row in rows]

    def transition_run(self, public_id, to_status, *, reason, timestamp=None):
        _validate_run_id(public_id)
        _validate_run_status(to_status)
        _validate_non_empty_string(reason, "AgentRun transition reason")
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "AgentRun transition timestamp")
        transition_id = f"{AGENT_RUN_TRANSITION_ID_PREFIX}{uuid4()}"

        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown AgentRun: {public_id}")

            from_status = row["status"]
            if to_status not in ALLOWED_RUN_TRANSITIONS[from_status]:
                raise ValueError(
                    f"Invalid AgentRun transition: {from_status} -> {to_status}"
                )

            if to_status in TERMINAL_RUN_STATUSES:
                active_step = connection.execute(
                    """
                    SELECT public_id FROM agent_steps
                    WHERE run_id = ?
                      AND status IN (
                        'planning', 'planned', 'selected', 'executing',
                        'executed', 'observed', 'verified'
                      )
                    LIMIT 1
                    """,
                    (public_id,),
                ).fetchone()
                if active_step is not None:
                    raise ValueError(
                        "Cannot terminate AgentRun with a non-terminal AgentStep"
                    )

                active_operation = connection.execute(
                    """
                    SELECT public_id FROM agent_operations
                    WHERE run_id = ?
                      AND status IN ('prepared', 'executing', 'uncertain')
                    LIMIT 1
                    """,
                    (public_id,),
                ).fetchone()
                if active_operation is not None:
                    raise ValueError(
                        "Cannot terminate AgentRun with a non-terminal AgentOperation"
                    )

            terminal_reason = (
                reason.strip() if to_status in TERMINAL_RUN_STATUSES else None
            )
            connection.execute(
                """
                UPDATE agent_runs
                SET status = ?, terminal_reason = ?, updated_at = ?
                WHERE public_id = ?
                """,
                (to_status, terminal_reason, timestamp, public_id),
            )
            connection.execute(
                """
                INSERT INTO agent_run_transitions(
                    public_id, run_id, timestamp, from_status, to_status, reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    transition_id,
                    public_id,
                    timestamp,
                    from_status,
                    to_status,
                    reason.strip(),
                ),
            )

        return self.get_run(public_id)

    def create_step(
        self,
        *,
        run_id,
        public_id=None,
        sequence=None,
        created_at=None,
        reason="step created",
    ):
        public_id = public_id or f"{AGENT_STEP_ID_PREFIX}{uuid4()}"
        created_at = created_at or _now()
        _validate_step_id(public_id)
        _validate_run_id(run_id)
        _validate_timestamp(created_at, "AgentStep created_at")
        _validate_non_empty_string(reason, "AgentStep transition reason")
        if sequence is not None and (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 0
        ):
            raise ValueError("AgentStep sequence must be a non-negative integer")

        transition_id = f"{AGENT_STEP_TRANSITION_ID_PREFIX}{uuid4()}"
        try:
            with self.transaction() as connection:
                run = connection.execute(
                    "SELECT status FROM agent_runs WHERE public_id = ?",
                    (run_id,),
                ).fetchone()
                if run is None:
                    raise ValueError(f"Unknown AgentRun: {run_id}")
                if run["status"] != "running":
                    raise ValueError(
                        f"AgentStep requires a running AgentRun, got {run['status']}"
                    )

                if sequence is None:
                    row = connection.execute(
                        """
                        SELECT MAX(sequence) AS max_sequence
                        FROM agent_steps WHERE run_id = ?
                        """,
                        (run_id,),
                    ).fetchone()
                    sequence = (
                        0
                        if row["max_sequence"] is None
                        else row["max_sequence"] + 1
                    )

                connection.execute(
                    """
                    INSERT INTO agent_steps(
                        public_id, run_id, sequence, status,
                        terminal_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, 'planning', NULL, ?, ?)
                    """,
                    (public_id, run_id, sequence, created_at, created_at),
                )
                connection.execute(
                    """
                    INSERT INTO agent_step_transitions(
                        public_id, step_id, timestamp, from_status, to_status, reason
                    ) VALUES (?, ?, ?, NULL, 'planning', ?)
                    """,
                    (transition_id, public_id, created_at, reason.strip()),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Cannot create AgentStep {public_id}: {error}") from error

        return self.get_step(public_id)

    def get_step(self, public_id):
        _validate_step_id(public_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_steps WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_step(row)

    def list_steps(self, *, run_id=None, status=None):
        clauses = []
        values = []
        if run_id is not None:
            _validate_run_id(run_id)
            clauses.append("run_id = ?")
            values.append(run_id)
        if status is not None:
            _validate_step_status(status)
            clauses.append("status = ?")
            values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_steps" + where + " ORDER BY row_id",
                tuple(values),
            ).fetchall()
        return [self._row_to_step(row) for row in rows]

    def list_step_transitions(self, public_id):
        _validate_step_id(public_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_step_transitions
                WHERE step_id = ?
                ORDER BY row_id
                """,
                (public_id,),
            ).fetchall()
        return [self._row_to_step_transition(row) for row in rows]

    def transition_step(self, public_id, to_status, *, reason, timestamp=None):
        _validate_step_id(public_id)
        _validate_step_status(to_status)
        _validate_non_empty_string(reason, "AgentStep transition reason")
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "AgentStep transition timestamp")
        transition_id = f"{AGENT_STEP_TRANSITION_ID_PREFIX}{uuid4()}"

        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_steps WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown AgentStep: {public_id}")

            from_status = row["status"]
            if to_status not in ALLOWED_STEP_TRANSITIONS[from_status]:
                raise ValueError(
                    f"Invalid AgentStep transition: {from_status} -> {to_status}"
                )

            if to_status in TERMINAL_STEP_STATUSES:
                active_operation = connection.execute(
                    """
                    SELECT public_id FROM agent_operations
                    WHERE step_id = ?
                      AND status IN ('prepared', 'executing', 'uncertain')
                    LIMIT 1
                    """,
                    (public_id,),
                ).fetchone()
                if active_operation is not None:
                    raise ValueError(
                        "Cannot terminate AgentStep with a non-terminal AgentOperation"
                    )

            terminal_reason = (
                reason.strip() if to_status in TERMINAL_STEP_STATUSES else None
            )
            connection.execute(
                """
                UPDATE agent_steps
                SET status = ?, terminal_reason = ?, updated_at = ?
                WHERE public_id = ?
                """,
                (to_status, terminal_reason, timestamp, public_id),
            )
            connection.execute(
                """
                INSERT INTO agent_step_transitions(
                    public_id, step_id, timestamp, from_status, to_status, reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    transition_id,
                    public_id,
                    timestamp,
                    from_status,
                    to_status,
                    reason.strip(),
                ),
            )

        return self.get_step(public_id)

    def create_operation(
        self,
        *,
        run_id,
        step_id,
        operation_kind,
        request_hash,
        idempotency_class,
        action_id=None,
        public_id=None,
        created_at=None,
        reason="operation prepared",
    ):
        public_id = public_id or f"{AGENT_OPERATION_ID_PREFIX}{uuid4()}"
        created_at = created_at or _now()
        _validate_operation_id(public_id)
        _validate_run_id(run_id)
        _validate_step_id(step_id)
        if action_id is not None:
            _validate_action_id(action_id)
        _validate_non_empty_string(operation_kind, "AgentOperation operation_kind")
        if (
            not isinstance(request_hash, str)
            or not _SHA256_PATTERN.fullmatch(request_hash)
        ):
            raise ValueError(
                "AgentOperation request_hash must be lowercase SHA-256 hex"
            )
        if idempotency_class not in IDEMPOTENCY_CLASSES:
            raise ValueError(
                f"Unknown AgentOperation idempotency_class: {idempotency_class!r}"
            )
        _validate_timestamp(created_at, "AgentOperation created_at")
        _validate_non_empty_string(reason, "AgentOperation status_reason")

        try:
            with self.transaction() as connection:
                run = connection.execute(
                    "SELECT status FROM agent_runs WHERE public_id = ?",
                    (run_id,),
                ).fetchone()
                if run is None:
                    raise ValueError(f"Unknown AgentRun: {run_id}")
                if run["status"] != "running":
                    raise ValueError(
                        f"AgentOperation requires a running AgentRun, got {run['status']}"
                    )

                step = connection.execute(
                    "SELECT run_id, status FROM agent_steps WHERE public_id = ?",
                    (step_id,),
                ).fetchone()
                if step is None:
                    raise ValueError(f"Unknown AgentStep: {step_id}")
                if step["run_id"] != run_id:
                    raise ValueError(
                        "AgentOperation step_id must belong to the supplied AgentRun"
                    )
                if step["status"] != "selected":
                    raise ValueError(
                        "AgentOperation requires a selected AgentStep, "
                        f"got {step['status']}"
                    )

                connection.execute(
                    """
                    INSERT INTO agent_operations(
                        public_id, run_id, step_id, action_id, operation_kind,
                        request_hash, idempotency_class, status, status_reason,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?, ?)
                    """,
                    (
                        public_id,
                        run_id,
                        step_id,
                        action_id,
                        operation_kind.strip(),
                        request_hash,
                        idempotency_class,
                        reason.strip(),
                        created_at,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot create AgentOperation {public_id}: {error}"
            ) from error

        return self.get_operation(public_id)

    def get_operation(self, public_id):
        _validate_operation_id(public_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_operations WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_operation(row)

    def list_operations(self, *, run_id=None, step_id=None, status=None):
        clauses = []
        values = []
        if run_id is not None:
            _validate_run_id(run_id)
            clauses.append("run_id = ?")
            values.append(run_id)
        if step_id is not None:
            _validate_step_id(step_id)
            clauses.append("step_id = ?")
            values.append(step_id)
        if status is not None:
            _validate_operation_status(status)
            clauses.append("status = ?")
            values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_operations" + where + " ORDER BY row_id",
                tuple(values),
            ).fetchall()
        return [self._row_to_operation(row) for row in rows]

    def transition_operation(self, public_id, to_status, *, reason, timestamp=None):
        _validate_operation_id(public_id)
        _validate_operation_status(to_status)
        _validate_non_empty_string(reason, "AgentOperation status_reason")
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "AgentOperation transition timestamp")

        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM agent_operations WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown AgentOperation: {public_id}")

            from_status = row["status"]
            if to_status not in ALLOWED_OPERATION_TRANSITIONS[from_status]:
                raise ValueError(
                    f"Invalid AgentOperation transition: {from_status} -> {to_status}"
                )

            connection.execute(
                """
                UPDATE agent_operations
                SET status = ?, status_reason = ?, updated_at = ?
                WHERE public_id = ?
                """,
                (to_status, reason.strip(), timestamp, public_id),
            )

        return self.get_operation(public_id)
