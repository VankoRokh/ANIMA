"""Persistent Task/Goal-owned execution operation ledger for Stage 6."""

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from anima.agent.tools import ToolRegistry
from .contracts import ExecutionAction, VerificationSpec, thaw


SCHEMA_VERSION = 2
OPERATION_STATUSES = {
    "prepared",
    "executing",
    "succeeded",
    "failed",
    "uncertain",
    "cancelled",
}
ALLOWED_OPERATION_TRANSITIONS = {
    "prepared": {"executing", "cancelled"},
    "executing": {"succeeded", "failed", "uncertain"},
    "uncertain": {"executing", "succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_operations (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    action_id TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL,
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
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_operations_task
    ON execution_operations(task_id, row_id);
CREATE INDEX IF NOT EXISTS idx_execution_operations_goal
    ON execution_operations(goal_id, row_id);
CREATE INDEX IF NOT EXISTS idx_execution_operations_status
    ON execution_operations(status, created_at, row_id);

CREATE TABLE IF NOT EXISTS execution_actions (
    operation_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE,
    action_json TEXT NOT NULL,
    FOREIGN KEY (operation_id)
        REFERENCES execution_operations(public_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS execution_verification_specs (
    operation_id TEXT PRIMARY KEY,
    verification_spec_id TEXT NOT NULL UNIQUE,
    spec_json TEXT NOT NULL,
    FOREIGN KEY (operation_id)
        REFERENCES execution_operations(public_id)
        ON DELETE CASCADE
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_timestamp(value, label):
    value = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return value


def _json_dumps(value, label):
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be JSON-compatible") from error


def _action_json(action):
    if not isinstance(action, ExecutionAction):
        raise TypeError("Execution action serialization requires ExecutionAction")
    return _json_dumps(action.to_dict(), "ExecutionAction payload")


def _action_from_json(encoded):
    try:
        data = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("Persisted ExecutionAction payload is invalid JSON") from error
    required = {
        "id",
        "operation_id",
        "persistent_task_id",
        "goal_id",
        "candidate_id",
        "tool",
        "tool_version",
        "arguments",
        "created_at",
    }
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("Persisted ExecutionAction payload has invalid fields")
    return ExecutionAction(
        public_id=data["id"],
        operation_id=data["operation_id"],
        persistent_task_id=data["persistent_task_id"],
        goal_id=data["goal_id"],
        candidate_id=data["candidate_id"],
        tool=data["tool"],
        tool_version=data["tool_version"],
        arguments=data["arguments"],
        created_at=data["created_at"],
    )


def _verification_spec_json(spec):
    if not isinstance(spec, VerificationSpec):
        raise TypeError("Verification spec serialization requires VerificationSpec")
    return _json_dumps(
        {
            "id": spec.public_id,
            "goal_id": spec.goal_id,
            "criterion_kind": spec.criterion_kind,
            "parameters": thaw(spec.parameters),
        },
        "VerificationSpec payload",
    )


def _verification_spec_from_json(encoded):
    try:
        data = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("Persisted VerificationSpec payload is invalid JSON") from error
    required = {"id", "goal_id", "criterion_kind", "parameters"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("Persisted VerificationSpec payload has invalid fields")
    return VerificationSpec(
        public_id=data["id"],
        goal_id=data["goal_id"],
        criterion_kind=data["criterion_kind"],
        parameters=data["parameters"],
    )


def operation_kind(action):
    if not isinstance(action, ExecutionAction):
        raise TypeError("operation_kind requires ExecutionAction")
    return f"{action.tool}@{action.tool_version}"


def action_request_hash(action):
    if not isinstance(action, ExecutionAction):
        raise TypeError("action_request_hash requires ExecutionAction")
    payload = {
        "task_id": action.persistent_task_id,
        "goal_id": action.goal_id,
        "candidate_id": action.candidate_id,
        "tool": action.tool,
        "tool_version": action.tool_version,
        "arguments": thaw(action.arguments),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExecutionStore:
    """Persistent operation identity and validated execution intent.

    Schema v2 adds exact validated ``ExecutionAction`` and ``VerificationSpec``
    payloads so restart recovery does not depend on pre-crash Python objects.
    Legacy v1 operations remain readable as operation metadata, but missing v2
    payloads fail explicitly instead of being guessed or silently reconstructed.
    """

    def __init__(self, database_file):
        self.database_file = Path(database_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

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

    def _initialize(self):
        try:
            with closing(self._connect()) as connection, connection:
                connection.executescript(SCHEMA_SQL)
                row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                elif row["value"] == "1":
                    # v1 already has execution_operations. SCHEMA_SQL above creates
                    # the v2 intent tables. Historical rows cannot be backfilled
                    # because v1 deliberately did not retain exact validated payloads.
                    connection.execute(
                        "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                        (str(SCHEMA_VERSION),),
                    )
                elif row["value"] != str(SCHEMA_VERSION):
                    raise ValueError(
                        f"Unsupported execution database schema in {self.database_file}"
                    )
        except ValueError:
            raise
        except sqlite3.DatabaseError as error:
            raise ValueError(
                f"Cannot initialize execution database {self.database_file}: {error}"
            ) from error

    @staticmethod
    def _row(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "task_id": row["task_id"],
            "goal_id": row["goal_id"],
            "action_id": row["action_id"],
            "candidate_id": row["candidate_id"],
            "operation_kind": row["operation_kind"],
            "request_hash": row["request_hash"],
            "idempotency_class": row["idempotency_class"],
            "status": row["status"],
            "status_reason": row["status_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def schema_version(self):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    def create_operation(self, action, *, registry, reason="operation prepared"):
        if not isinstance(action, ExecutionAction):
            raise TypeError("ExecutionStore.create_operation requires ExecutionAction")
        if not isinstance(registry, ToolRegistry):
            raise TypeError("ExecutionStore registry must be ToolRegistry")
        reason = _require_text(reason, "Execution operation reason")
        descriptor = registry.get(action.tool, action.tool_version)
        descriptor.validate_input(thaw(action.arguments))
        created_at = _validate_timestamp(action.created_at, "Execution operation created_at")
        record = (
            action.operation_id,
            action.persistent_task_id,
            action.goal_id,
            action.public_id,
            action.candidate_id,
            operation_kind(action),
            action_request_hash(action),
            descriptor.idempotency,
            reason,
            created_at,
            created_at,
        )
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO execution_operations(
                        public_id, task_id, goal_id, action_id, candidate_id,
                        operation_kind, request_hash, idempotency_class,
                        status, status_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?, ?)
                    """,
                    record,
                )
                connection.execute(
                    """
                    INSERT INTO execution_actions(operation_id, action_id, action_json)
                    VALUES (?, ?, ?)
                    """,
                    (action.operation_id, action.public_id, _action_json(action)),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot create ExecutionOperation {action.operation_id}: {error}"
            ) from error
        return self.get_operation(action.operation_id)

    def get_operation(self, public_id):
        _require_text(public_id, "Execution operation public_id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM execution_operations WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row(row)

    def load_action(self, operation_id):
        """Reconstruct the exact validated ExecutionAction for one operation."""

        operation_id = _require_text(operation_id, "Execution operation public_id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT o.*, a.action_json
                FROM execution_operations AS o
                LEFT JOIN execution_actions AS a
                  ON a.operation_id = o.public_id
                WHERE o.public_id = ?
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown ExecutionOperation: {operation_id}")
        if row["action_json"] is None:
            raise ValueError(
                "ExecutionOperation has no persisted validated ExecutionAction payload; "
                "legacy schema-v1 operations require external recovery policy"
            )

        action = _action_from_json(row["action_json"])
        expected = {
            "operation_id": row["public_id"],
            "public_id": row["action_id"],
            "persistent_task_id": row["task_id"],
            "goal_id": row["goal_id"],
            "candidate_id": row["candidate_id"],
        }
        for field, value in expected.items():
            if getattr(action, field) != value:
                raise ValueError(
                    f"Persisted ExecutionAction {field} does not match ExecutionOperation"
                )
        if operation_kind(action) != row["operation_kind"]:
            raise ValueError(
                "Persisted ExecutionAction operation kind does not match ExecutionOperation"
            )
        if action_request_hash(action) != row["request_hash"]:
            raise ValueError(
                "Persisted ExecutionAction request hash does not match ExecutionOperation"
            )
        return action

    def save_verification_spec(self, action, spec):
        """Persist one typed verification contract for the validated Action."""

        if not isinstance(action, ExecutionAction):
            raise TypeError("save_verification_spec requires ExecutionAction")
        if not isinstance(spec, VerificationSpec):
            raise TypeError("save_verification_spec requires VerificationSpec")
        operation = self.get_operation(action.operation_id)
        if operation is None:
            raise ValueError(f"Unknown ExecutionOperation: {action.operation_id}")
        # Reuse the full persisted-action integrity check before binding verification.
        persisted_action = self.load_action(action.operation_id)
        if persisted_action != action:
            raise ValueError("VerificationSpec Action does not match persisted ExecutionAction")
        if spec.goal_id != action.goal_id:
            raise ValueError("VerificationSpec Goal does not match ExecutionAction Goal")

        encoded = _verification_spec_json(spec)
        try:
            with self.transaction() as connection:
                existing = connection.execute(
                    """
                    SELECT verification_spec_id, spec_json
                    FROM execution_verification_specs
                    WHERE operation_id = ?
                    """,
                    (action.operation_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["verification_spec_id"] == spec.public_id
                        and existing["spec_json"] == encoded
                    ):
                        return spec
                    raise ValueError(
                        "ExecutionOperation already has a different VerificationSpec"
                    )
                connection.execute(
                    """
                    INSERT INTO execution_verification_specs(
                        operation_id, verification_spec_id, spec_json
                    ) VALUES (?, ?, ?)
                    """,
                    (action.operation_id, spec.public_id, encoded),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot bind VerificationSpec to {action.operation_id}: {error}"
            ) from error
        return spec

    def load_verification_spec(self, operation_id):
        """Reconstruct the exact VerificationSpec bound before restart."""

        operation_id = _require_text(operation_id, "Execution operation public_id")
        operation = self.get_operation(operation_id)
        if operation is None:
            raise ValueError(f"Unknown ExecutionOperation: {operation_id}")
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT verification_spec_id, spec_json
                FROM execution_verification_specs
                WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            raise ValueError(
                "ExecutionOperation has no persisted VerificationSpec; "
                "recovery must not invent a verification contract"
            )
        spec = _verification_spec_from_json(row["spec_json"])
        if spec.public_id != row["verification_spec_id"]:
            raise ValueError(
                "Persisted VerificationSpec ID does not match execution binding"
            )
        if spec.goal_id != operation["goal_id"]:
            raise ValueError(
                "Persisted VerificationSpec Goal does not match ExecutionOperation"
            )
        return spec

    def transition_operation(self, public_id, to_status, *, reason, timestamp=None):
        public_id = _require_text(public_id, "Execution operation public_id")
        if to_status not in OPERATION_STATUSES:
            raise ValueError(f"Unknown ExecutionOperation status: {to_status!r}")
        reason = _require_text(reason, "Execution operation transition reason")
        timestamp = _validate_timestamp(timestamp or _now(), "Execution operation timestamp")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM execution_operations WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown ExecutionOperation: {public_id}")
            current = row["status"]
            if to_status not in ALLOWED_OPERATION_TRANSITIONS[current]:
                raise ValueError(
                    f"Invalid ExecutionOperation transition: {current} -> {to_status}"
                )
            cursor = connection.execute(
                """
                UPDATE execution_operations
                SET status = ?, status_reason = ?, updated_at = ?
                WHERE public_id = ? AND status = ?
                """,
                (to_status, reason, timestamp, public_id, current),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"ExecutionOperation changed concurrently: {public_id}"
                )
        return self.get_operation(public_id)

    def list_operations(self, *, task_id=None, goal_id=None, status=None):
        if status is not None and status not in OPERATION_STATUSES:
            raise ValueError(f"Unknown ExecutionOperation status: {status!r}")
        clauses = []
        values = []
        for field, value in (("task_id", task_id), ("goal_id", goal_id), ("status", status)):
            if value is not None:
                clauses.append(f"{field} = ?")
                values.append(value)
        query = "SELECT * FROM execution_operations"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at, row_id"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._row(row) for row in rows]


__all__ = [
    "ExecutionStore",
    "action_request_hash",
    "operation_kind",
]
