"""Persistent, system-owned causal trace for Stage 6 integration.

The trace is evidence, not authority. Task/Goal/Memory/Execution/Sleep state remains
owned by their existing stores. UnifiedTrace subclasses the legacy DiagnosticTrace
so existing components can keep calling ``record(message)`` unchanged while a
bound Stage 6 trace additionally persists those messages in ``trace.db``.
"""

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from anima.diagnostics.trace import DiagnosticTrace
from anima.tasks.contracts import validate_goal_id, validate_task_id


SCHEMA_VERSION = 1
TRACE_ID_PREFIX = "tr_"
TRACE_EVENT_ID_PREFIX = "tre_"
TRACE_STATUSES = {"open", "completed", "failed"}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage6_traces (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    goal_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('open', 'completed', 'failed')),
    outcome_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_stage6_trace_one_open_per_task
    ON stage6_traces(task_id)
    WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_stage6_trace_status
    ON stage6_traces(status, created_at, row_id);

CREATE TABLE IF NOT EXISTS stage6_trace_events (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    trace_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    timestamp TEXT NOT NULL,
    component TEXT NOT NULL,
    event TEXT NOT NULL,
    message TEXT NOT NULL,
    task_id TEXT NOT NULL,
    goal_id TEXT,
    canonical_task_id TEXT,
    source_id TEXT,
    action_id TEXT,
    operation_id TEXT,
    observation_id TEXT,
    verification_id TEXT,
    sleep_job_id TEXT,
    payload_json TEXT NOT NULL,
    UNIQUE(trace_id, sequence),
    FOREIGN KEY (trace_id) REFERENCES stage6_traces(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stage6_trace_events_trace_sequence
    ON stage6_trace_events(trace_id, sequence, row_id);
CREATE INDEX IF NOT EXISTS idx_stage6_trace_events_task
    ON stage6_trace_events(task_id, row_id);
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


def _validate_prefixed_uuid4(value, *, prefix, label):
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(f"{label} must be a {prefix}UUIDv4")
    raw = value[len(prefix):]
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a {prefix}UUIDv4") from error
    if parsed.version != 4 or str(parsed) != raw:
        raise ValueError(f"{label} must be a {prefix}UUIDv4")
    return value


def _json_copy(value, label):
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be JSON-compatible") from error


def _validate_trace_id(value):
    return _validate_prefixed_uuid4(
        value,
        prefix=TRACE_ID_PREFIX,
        label="Stage6Trace public_id",
    )


def _validate_event_id(value):
    return _validate_prefixed_uuid4(
        value,
        prefix=TRACE_EVENT_ID_PREFIX,
        label="Stage6TraceEvent public_id",
    )


@dataclass(frozen=True, slots=True)
class Stage6Trace:
    public_id: str
    task_id: str
    goal_id: str | None
    status: str
    outcome: dict | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Stage6TraceEvent:
    public_id: str
    trace_id: str
    sequence: int
    timestamp: str
    component: str
    event: str
    message: str
    task_id: str
    goal_id: str | None
    canonical_task_id: str | None
    source_id: str | None
    action_id: str | None
    operation_id: str | None
    observation_id: str | None
    verification_id: str | None
    sleep_job_id: str | None
    payload: dict


class UnifiedTraceStore:
    """Persistent Stage 6 trace/event journal with no system-state authority."""

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
                elif row["value"] != str(SCHEMA_VERSION):
                    raise ValueError(
                        f"Unsupported unified trace schema in {self.database_file}"
                    )
        except ValueError:
            raise
        except sqlite3.DatabaseError as error:
            raise ValueError(
                f"Cannot initialize unified trace database {self.database_file}: {error}"
            ) from error

    def schema_version(self):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    @staticmethod
    def _trace_row(row):
        if row is None:
            return None
        return Stage6Trace(
            public_id=row["public_id"],
            task_id=row["task_id"],
            goal_id=row["goal_id"],
            status=row["status"],
            outcome=(None if row["outcome_json"] is None else json.loads(row["outcome_json"])),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _event_row(row):
        if row is None:
            return None
        return Stage6TraceEvent(
            public_id=row["public_id"],
            trace_id=row["trace_id"],
            sequence=row["sequence"],
            timestamp=row["timestamp"],
            component=row["component"],
            event=row["event"],
            message=row["message"],
            task_id=row["task_id"],
            goal_id=row["goal_id"],
            canonical_task_id=row["canonical_task_id"],
            source_id=row["source_id"],
            action_id=row["action_id"],
            operation_id=row["operation_id"],
            observation_id=row["observation_id"],
            verification_id=row["verification_id"],
            sleep_job_id=row["sleep_job_id"],
            payload=json.loads(row["payload_json"]),
        )

    def create_trace(self, *, task_id, goal_id=None, timestamp=None, public_id=None):
        validate_task_id(task_id)
        if goal_id is not None:
            validate_goal_id(goal_id)
        timestamp = _validate_timestamp(timestamp or _now(), "Stage6Trace timestamp")
        public_id = _validate_trace_id(public_id or f"{TRACE_ID_PREFIX}{uuid4()}")
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO stage6_traces(
                        public_id, task_id, goal_id, status, outcome_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'open', NULL, ?, ?)
                    """,
                    (public_id, task_id, goal_id, timestamp, timestamp),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Cannot create Stage6Trace: {error}") from error
        return self.get_trace(public_id)

    def get_trace(self, trace_id):
        _validate_trace_id(trace_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM stage6_traces WHERE public_id = ?",
                (trace_id,),
            ).fetchone()
        return self._trace_row(row)

    def get_open_for_task(self, task_id):
        validate_task_id(task_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM stage6_traces
                WHERE task_id = ? AND status = 'open'
                ORDER BY row_id DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return self._trace_row(row)

    def append_event(
        self,
        trace_id,
        *,
        component,
        event,
        message,
        payload=None,
        timestamp=None,
        canonical_task_id=None,
        source_id=None,
        action_id=None,
        operation_id=None,
        observation_id=None,
        verification_id=None,
        sleep_job_id=None,
        public_id=None,
    ):
        _validate_trace_id(trace_id)
        component = _require_text(component, "Stage6TraceEvent component")
        event = _require_text(event, "Stage6TraceEvent event")
        message = _require_text(message, "Stage6TraceEvent message")
        timestamp = _validate_timestamp(timestamp or _now(), "Stage6TraceEvent timestamp")
        public_id = _validate_event_id(public_id or f"{TRACE_EVENT_ID_PREFIX}{uuid4()}")
        payload = _json_copy({} if payload is None else payload, "Stage6TraceEvent payload")
        optional = {
            "canonical_task_id": canonical_task_id,
            "source_id": source_id,
            "action_id": action_id,
            "operation_id": operation_id,
            "observation_id": observation_id,
            "verification_id": verification_id,
            "sleep_job_id": sleep_job_id,
        }
        optional = {key: _optional_text(value, f"Stage6TraceEvent {key}") for key, value in optional.items()}

        with self.transaction() as connection:
            trace = connection.execute(
                "SELECT * FROM stage6_traces WHERE public_id = ?",
                (trace_id,),
            ).fetchone()
            if trace is None:
                raise ValueError(f"Unknown Stage6Trace: {trace_id}")
            if trace["status"] != "open":
                raise ValueError(f"Cannot append to terminal Stage6Trace: {trace['status']}")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM stage6_trace_events WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()["sequence"]
            connection.execute(
                """
                INSERT INTO stage6_trace_events(
                    public_id, trace_id, sequence, timestamp, component, event,
                    message, task_id, goal_id, canonical_task_id, source_id,
                    action_id, operation_id, observation_id, verification_id,
                    sleep_job_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    public_id,
                    trace_id,
                    sequence,
                    timestamp,
                    component,
                    event,
                    message,
                    trace["task_id"],
                    trace["goal_id"],
                    optional["canonical_task_id"],
                    optional["source_id"],
                    optional["action_id"],
                    optional["operation_id"],
                    optional["observation_id"],
                    optional["verification_id"],
                    optional["sleep_job_id"],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            )
            connection.execute(
                "UPDATE stage6_traces SET updated_at = ? WHERE public_id = ?",
                (timestamp, trace_id),
            )
        return self.list_events(trace_id)[-1]

    def list_events(self, trace_id):
        _validate_trace_id(trace_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM stage6_trace_events
                WHERE trace_id = ? ORDER BY sequence, row_id
                """,
                (trace_id,),
            ).fetchall()
        return [self._event_row(row) for row in rows]

    def close_trace(self, trace_id, *, status, outcome, timestamp=None):
        _validate_trace_id(trace_id)
        if status not in {"completed", "failed"}:
            raise ValueError("Stage6Trace terminal status must be completed or failed")
        outcome = _json_copy(outcome, "Stage6Trace outcome")
        timestamp = _validate_timestamp(timestamp or _now(), "Stage6Trace timestamp")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM stage6_traces WHERE public_id = ?",
                (trace_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown Stage6Trace: {trace_id}")
            if row["status"] != "open":
                raise ValueError(f"Stage6Trace already terminal: {row['status']}")
            connection.execute(
                """
                UPDATE stage6_traces
                SET status = ?, outcome_json = ?, updated_at = ?
                WHERE public_id = ? AND status = 'open'
                """,
                (
                    status,
                    json.dumps(outcome, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    timestamp,
                    trace_id,
                ),
            )
        return self.get_trace(trace_id)


class UnifiedTrace(DiagnosticTrace):
    """Legacy-compatible in-memory trace plus persistent bound Stage 6 events."""

    def __init__(self, store):
        if not isinstance(store, UnifiedTraceStore):
            raise TypeError("UnifiedTrace store must be UnifiedTraceStore")
        super().__init__()
        self.store = store
        self._context_stack = []

    def resume_or_begin(self, *, task_id, goal_id=None):
        validate_task_id(task_id)
        if goal_id is not None:
            validate_goal_id(goal_id)
        existing = self.store.get_open_for_task(task_id)
        if existing is not None:
            if existing.goal_id != goal_id:
                raise ValueError("Open Stage6Trace Goal does not match Task Goal")
            return existing.public_id
        return self.store.create_trace(task_id=task_id, goal_id=goal_id).public_id

    @contextmanager
    def bind(self, trace_id, **references):
        trace = self.store.get_trace(trace_id)
        if trace is None:
            raise ValueError(f"Unknown Stage6Trace: {trace_id}")
        if trace.status != "open":
            raise ValueError(f"Cannot bind terminal Stage6Trace: {trace.status}")
        context = {
            "trace_id": trace_id,
            "canonical_task_id": references.get("canonical_task_id"),
            "source_id": references.get("source_id"),
            "action_id": references.get("action_id"),
            "operation_id": references.get("operation_id"),
            "observation_id": references.get("observation_id"),
            "verification_id": references.get("verification_id"),
            "sleep_job_id": references.get("sleep_job_id"),
        }
        self._context_stack.append(context)
        try:
            yield trace
        finally:
            popped = self._context_stack.pop()
            if popped is not context:
                raise RuntimeError("UnifiedTrace context stack corruption")

    def _current(self):
        return self._context_stack[-1] if self._context_stack else None

    @staticmethod
    def _classify(message):
        if ":" not in message:
            return "runtime", "message"
        prefix, remainder = message.split(":", 1)
        component = prefix.strip().replace(" ", "_") or "runtime"
        remainder = remainder.strip()
        event = remainder.split(" ", 1)[0] if remainder else "message"
        if "=" in event or not event:
            event = "message"
        return component, event

    def record(self, message):
        super().record(message)
        context = self._current()
        if context is None:
            return
        component, event = self._classify(message)
        self.store.append_event(
            context["trace_id"],
            component=component,
            event=event,
            message=message,
            canonical_task_id=context["canonical_task_id"],
            source_id=context["source_id"],
            action_id=context["action_id"],
            operation_id=context["operation_id"],
            observation_id=context["observation_id"],
            verification_id=context["verification_id"],
            sleep_job_id=context["sleep_job_id"],
        )

    def record_event(self, *, component, event, message, payload=None, **references):
        super().record(message)
        context = self._current()
        if context is None:
            raise RuntimeError("Structured Stage 6 trace event requires a bound trace")
        merged = dict(context)
        for key, value in references.items():
            if key not in merged:
                raise ValueError(f"Unknown Stage6Trace reference: {key}")
            if value is not None:
                merged[key] = value
        return self.store.append_event(
            merged["trace_id"],
            component=component,
            event=event,
            message=message,
            payload=payload,
            canonical_task_id=merged["canonical_task_id"],
            source_id=merged["source_id"],
            action_id=merged["action_id"],
            operation_id=merged["operation_id"],
            observation_id=merged["observation_id"],
            verification_id=merged["verification_id"],
            sleep_job_id=merged["sleep_job_id"],
        )

    def close(self, trace_id, *, success, task_status, goal_status=None, reason):
        if type(success) is not bool:
            raise ValueError("UnifiedTrace close success must be boolean")
        outcome = {
            "task_status": _require_text(task_status, "UnifiedTrace task_status"),
            "goal_status": _optional_text(goal_status, "UnifiedTrace goal_status"),
            "reason": _require_text(reason, "UnifiedTrace close reason"),
        }
        return self.store.close_trace(
            trace_id,
            status="completed" if success else "failed",
            outcome=outcome,
        )


def record_structured(trace, *, component, event, message, payload=None, **references):
    """Record rich data when UnifiedTrace is active; preserve legacy trace behavior."""
    if trace is None:
        return None
    if isinstance(trace, UnifiedTrace):
        return trace.record_event(
            component=component,
            event=event,
            message=message,
            payload=payload,
            **references,
        )
    if not isinstance(trace, DiagnosticTrace):
        raise TypeError("trace must be DiagnosticTrace, UnifiedTrace, or null")
    trace.record(message)
    return None


__all__ = [
    "Stage6Trace",
    "Stage6TraceEvent",
    "UnifiedTrace",
    "UnifiedTraceStore",
    "record_structured",
]
