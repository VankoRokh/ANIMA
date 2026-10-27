import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from anima.config.paths import get_data_dir
from anima.sleep.contracts import (
    WORK_ITEM_ID_PREFIX,
    WORK_ITEM_STATUSES,
    SourceRegistry,
    SourceRef,
    WorkItem,
)


SCHEMA_VERSION = 3
SLEEP_JOB_ID_PREFIX = "sj_"
SLEEP_JOB_TRANSITION_ID_PREFIX = "sjt_"
WORK_CHECKPOINT_ID_PREFIX = "wcp_"
SLEEP_JOB_STATUSES = {
    "queued",
    "running",
    "checkpointed",
    "interrupted",
    "completed",
    "failed",
}

ALLOWED_JOB_TRANSITIONS = {
    "queued": {"running", "failed"},
    "running": {"checkpointed", "interrupted", "completed", "failed"},
    "checkpointed": {"running", "interrupted", "completed", "failed"},
    "interrupted": {"running", "failed"},
    "failed": {"queued"},
    "completed": set(),
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sleep_jobs (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'checkpointed', 'interrupted', 'completed', 'failed')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sleep_jobs_status_created
    ON sleep_jobs(status, created_at);

CREATE TABLE IF NOT EXISTS sleep_job_transitions (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    from_status TEXT CHECK (
        from_status IS NULL OR from_status IN (
            'queued', 'running', 'checkpointed', 'interrupted', 'completed', 'failed'
        )
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('queued', 'running', 'checkpointed', 'interrupted', 'completed', 'failed')
    ),
    reason TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES sleep_jobs(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sleep_job_transitions_job_time
    ON sleep_job_transitions(job_id, timestamp, row_id);

CREATE TABLE IF NOT EXISTS work_items (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL,
    work_kind TEXT NOT NULL CHECK (work_kind IN ('CONSOLIDATE')),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('event', 'memory', 'knowledge', 'asset')
    ),
    source_id TEXT NOT NULL,
    processor TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0 CHECK (priority >= 0),
    cost_hint TEXT NOT NULL CHECK (
        cost_hint IN ('cheap', 'normal', 'expensive')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'checkpointed', 'completed', 'failed', 'skipped')
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    checkpoint_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES sleep_jobs(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_work_items_job_status
    ON work_items(job_id, status, row_id);
CREATE INDEX IF NOT EXISTS idx_work_items_source
    ON work_items(source_kind, source_id);
CREATE INDEX IF NOT EXISTS idx_work_items_priority
    ON work_items(job_id, priority DESC, row_id);

CREATE TABLE IF NOT EXISTS work_item_checkpoints (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    work_item_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    checkpoint_json TEXT NOT NULL,
    local_result_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(work_item_id, sequence),
    FOREIGN KEY (work_item_id) REFERENCES work_items(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_work_item_checkpoints_item_sequence
    ON work_item_checkpoints(work_item_id, sequence, row_id);
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


def _validate_non_negative_int(value, label):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


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
        raise ValueError(f"{label} must be JSON-serializable") from error


def _validate_uuid4_id(public_id, *, prefix, label):
    if not isinstance(public_id, str) or not public_id.startswith(prefix):
        raise ValueError(f"{label} must be a {prefix}UUIDv4")
    raw_uuid = public_id[len(prefix):]
    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a {prefix}UUIDv4") from error
    if parsed.version != 4 or str(parsed) != raw_uuid:
        raise ValueError(f"{label} must be a {prefix}UUIDv4")


def _validate_job_id(public_id):
    _validate_uuid4_id(
        public_id,
        prefix=SLEEP_JOB_ID_PREFIX,
        label="SleepJob public_id",
    )


def _validate_job_status(status):
    if status not in SLEEP_JOB_STATUSES:
        raise ValueError(f"Unknown SleepJob status: {status!r}")


def _validate_work_item_id(public_id):
    _validate_uuid4_id(
        public_id,
        prefix=WORK_ITEM_ID_PREFIX,
        label="WorkItem public_id",
    )


def _validate_checkpoint_id(public_id):
    _validate_uuid4_id(
        public_id,
        prefix=WORK_CHECKPOINT_ID_PREFIX,
        label="Work checkpoint public_id",
    )


class SleepStore:
    def __init__(self, database_file=None):
        self.database_file = (
            Path(database_file)
            if database_file is not None
            else get_data_dir() / "sleep.db"
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
            with closing(self._connect()) as connection, connection:
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

                supported_existing = {"1", "2", str(SCHEMA_VERSION)}
                if row is not None and row["value"] not in supported_existing:
                    raise ValueError(
                        f"Unsupported Sleep database schema in {self.database_file}"
                    )

                connection.executescript(SCHEMA_SQL)

                if row is None:
                    connection.execute(
                        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                elif row["value"] != str(SCHEMA_VERSION):
                    connection.execute(
                        "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                        (str(SCHEMA_VERSION),),
                    )

                final_row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
        except ValueError:
            raise
        except sqlite3.DatabaseError as error:
            raise ValueError(
                f"Cannot initialize Sleep database {self.database_file}: {error}"
            ) from error

        if final_row is None or final_row["value"] != str(SCHEMA_VERSION):
            raise ValueError(
                f"Unsupported Sleep database schema in {self.database_file}"
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
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    @staticmethod
    def _row_to_job(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_transition(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "job_id": row["job_id"],
            "timestamp": row["timestamp"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
            "reason": row["reason"],
        }

    @staticmethod
    def _row_to_work_item(row):
        if row is None:
            return None
        return WorkItem(
            public_id=row["public_id"],
            job_id=row["job_id"],
            work_kind=row["work_kind"],
            source_ref=SourceRef(
                kind=row["source_kind"],
                source_id=row["source_id"],
            ),
            processor=row["processor"],
            processor_version=row["processor_version"],
            priority=row["priority"],
            cost_hint=row["cost_hint"],
            status=row["status"],
            attempts=row["attempts"],
            checkpoint_ref=row["checkpoint_ref"],
        )

    @staticmethod
    def _row_to_checkpoint(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "work_item_id": row["work_item_id"],
            "sequence": row["sequence"],
            "checkpoint": json.loads(row["checkpoint_json"]),
            "local_result": (
                None
                if row["local_result_json"] is None
                else json.loads(row["local_result_json"])
            ),
            "created_at": row["created_at"],
        }

    def create_job(self, *, public_id=None, created_at=None, reason="job created"):
        public_id = public_id or f"{SLEEP_JOB_ID_PREFIX}{uuid4()}"
        created_at = created_at or _now()
        _validate_job_id(public_id)
        _validate_timestamp(created_at, "SleepJob created_at")
        _validate_non_empty_string(reason, "SleepJob transition reason")

        transition_id = f"{SLEEP_JOB_TRANSITION_ID_PREFIX}{uuid4()}"
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO sleep_jobs(public_id, status, created_at, updated_at)
                    VALUES (?, 'queued', ?, ?)
                    """,
                    (public_id, created_at, created_at),
                )
                connection.execute(
                    """
                    INSERT INTO sleep_job_transitions(
                        public_id, job_id, timestamp, from_status, to_status, reason
                    ) VALUES (?, ?, ?, NULL, 'queued', ?)
                    """,
                    (transition_id, public_id, created_at, reason),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Cannot create SleepJob {public_id}: {error}") from error

        return self.get_job(public_id)

    def get_job(self, public_id):
        _validate_job_id(public_id)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM sleep_jobs WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_job(row)

    def list_jobs(self, *, status=None):
        if status is not None:
            _validate_job_status(status)
        with closing(self._connect()) as connection, connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM sleep_jobs ORDER BY row_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM sleep_jobs WHERE status = ? ORDER BY row_id",
                    (status,),
                ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_transitions(self, public_id):
        _validate_job_id(public_id)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT * FROM sleep_job_transitions
                WHERE job_id = ?
                ORDER BY row_id
                """,
                (public_id,),
            ).fetchall()
        return [self._row_to_transition(row) for row in rows]

    def transition_job(self, public_id, to_status, *, reason, timestamp=None):
        _validate_job_id(public_id)
        _validate_job_status(to_status)
        _validate_non_empty_string(reason, "SleepJob transition reason")
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "SleepJob transition timestamp")
        transition_id = f"{SLEEP_JOB_TRANSITION_ID_PREFIX}{uuid4()}"

        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM sleep_jobs WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown SleepJob: {public_id}")

            from_status = row["status"]
            if to_status not in ALLOWED_JOB_TRANSITIONS[from_status]:
                raise ValueError(
                    f"Invalid SleepJob transition: {from_status} -> {to_status}"
                )

            connection.execute(
                """
                UPDATE sleep_jobs
                SET status = ?, updated_at = ?
                WHERE public_id = ?
                """,
                (to_status, timestamp, public_id),
            )
            connection.execute(
                """
                INSERT INTO sleep_job_transitions(
                    public_id, job_id, timestamp, from_status, to_status, reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    transition_id,
                    public_id,
                    timestamp,
                    from_status,
                    to_status,
                    reason,
                ),
            )

        return self.get_job(public_id)

    def create_work_item(self, work_item, *, source_registry, created_at=None):
        if not isinstance(work_item, WorkItem):
            raise ValueError("create_work_item() requires a WorkItem")
        if not isinstance(source_registry, SourceRegistry):
            raise ValueError("source_registry must be a SourceRegistry")

        source_registry.require(work_item.source_ref)
        created_at = created_at or _now()
        _validate_timestamp(created_at, "WorkItem created_at")

        try:
            with self.transaction() as connection:
                job = connection.execute(
                    "SELECT public_id FROM sleep_jobs WHERE public_id = ?",
                    (work_item.job_id,),
                ).fetchone()
                if job is None:
                    raise ValueError(f"Unknown SleepJob: {work_item.job_id}")

                connection.execute(
                    """
                    INSERT INTO work_items(
                        public_id, job_id, work_kind,
                        source_kind, source_id,
                        processor, processor_version,
                        priority, cost_hint, status, attempts,
                        checkpoint_ref, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        work_item.public_id,
                        work_item.job_id,
                        work_item.work_kind,
                        work_item.source_ref.kind,
                        work_item.source_ref.source_id,
                        work_item.processor,
                        work_item.processor_version,
                        work_item.priority,
                        work_item.cost_hint,
                        work_item.status,
                        work_item.attempts,
                        work_item.checkpoint_ref,
                        created_at,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot create WorkItem {work_item.public_id}: {error}"
            ) from error

        return self.get_work_item(work_item.public_id)

    def get_work_item(self, public_id):
        _validate_work_item_id(public_id)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_work_item(row)

    def list_work_items(self, *, job_id=None, status=None):
        if job_id is not None:
            _validate_job_id(job_id)
        if status is not None and status not in WORK_ITEM_STATUSES:
            raise ValueError(f"Unknown WorkItem status: {status!r}")

        clauses = []
        values = []
        if job_id is not None:
            clauses.append("job_id = ?")
            values.append(job_id)
        if status is not None:
            clauses.append("status = ?")
            values.append(status)

        where = ""
        if clauses:
            where = " WHERE " + " AND ".join(clauses)

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM work_items" + where + " ORDER BY row_id",
                tuple(values),
            ).fetchall()
        return [self._row_to_work_item(row) for row in rows]

    def begin_work_item(self, public_id, *, timestamp=None):
        _validate_work_item_id(public_id)
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "WorkItem begin timestamp")

        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM work_items WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown WorkItem: {public_id}")
            if row["status"] not in {"queued", "checkpointed"}:
                raise ValueError(
                    f"Cannot begin WorkItem from status: {row['status']}"
                )
            connection.execute(
                """
                UPDATE work_items
                SET status = 'running', attempts = attempts + 1, updated_at = ?
                WHERE public_id = ?
                """,
                (timestamp, public_id),
            )

        return self.get_work_item(public_id)

    def commit_work_item_chunk(
        self,
        public_id,
        *,
        sequence,
        checkpoint,
        local_result=None,
        checkpoint_id=None,
        timestamp=None,
    ):
        _validate_work_item_id(public_id)
        _validate_non_negative_int(sequence, "Work checkpoint sequence")
        checkpoint_id = checkpoint_id or f"{WORK_CHECKPOINT_ID_PREFIX}{uuid4()}"
        _validate_checkpoint_id(checkpoint_id)
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "Work checkpoint timestamp")
        checkpoint_json = _json_dumps(checkpoint, "Work checkpoint")
        local_result_json = (
            None
            if local_result is None
            else _json_dumps(local_result, "Work checkpoint local_result")
        )

        try:
            with self.transaction() as connection:
                work_item = connection.execute(
                    "SELECT status FROM work_items WHERE public_id = ?",
                    (public_id,),
                ).fetchone()
                if work_item is None:
                    raise ValueError(f"Unknown WorkItem: {public_id}")
                if work_item["status"] != "running":
                    raise ValueError(
                        "Chunk can be committed only for running WorkItem: "
                        f"{work_item['status']}"
                    )

                latest = connection.execute(
                    """
                    SELECT sequence FROM work_item_checkpoints
                    WHERE work_item_id = ?
                    ORDER BY sequence DESC, row_id DESC
                    LIMIT 1
                    """,
                    (public_id,),
                ).fetchone()
                expected = 0 if latest is None else latest["sequence"] + 1
                if sequence != expected:
                    raise ValueError(
                        f"Work checkpoint sequence must be {expected}, got {sequence}"
                    )

                connection.execute(
                    """
                    INSERT INTO work_item_checkpoints(
                        public_id, work_item_id, sequence,
                        checkpoint_json, local_result_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        checkpoint_id,
                        public_id,
                        sequence,
                        checkpoint_json,
                        local_result_json,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    UPDATE work_items
                    SET checkpoint_ref = ?, updated_at = ?
                    WHERE public_id = ?
                    """,
                    (checkpoint_id, timestamp, public_id),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot commit WorkItem checkpoint {checkpoint_id}: {error}"
            ) from error

        return self.get_checkpoint(checkpoint_id)

    def get_checkpoint(self, checkpoint_id):
        _validate_checkpoint_id(checkpoint_id)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM work_item_checkpoints WHERE public_id = ?",
                (checkpoint_id,),
            ).fetchone()
        return self._row_to_checkpoint(row)

    def list_checkpoints(self, public_id):
        _validate_work_item_id(public_id)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT * FROM work_item_checkpoints
                WHERE work_item_id = ?
                ORDER BY sequence, row_id
                """,
                (public_id,),
            ).fetchall()
        return [self._row_to_checkpoint(row) for row in rows]

    def get_latest_checkpoint(self, public_id):
        _validate_work_item_id(public_id)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT * FROM work_item_checkpoints
                WHERE work_item_id = ?
                ORDER BY sequence DESC, row_id DESC
                LIMIT 1
                """,
                (public_id,),
            ).fetchone()
        return self._row_to_checkpoint(row)

    def pause_work_item(self, public_id, *, timestamp=None):
        _validate_work_item_id(public_id)
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "WorkItem pause timestamp")

        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status, checkpoint_ref FROM work_items WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown WorkItem: {public_id}")
            if row["status"] != "running":
                raise ValueError(
                    f"Cannot checkpoint WorkItem from status: {row['status']}"
                )
            if row["checkpoint_ref"] is None:
                raise ValueError("Cannot checkpoint WorkItem before first committed chunk")
            connection.execute(
                """
                UPDATE work_items
                SET status = 'checkpointed', updated_at = ?
                WHERE public_id = ?
                """,
                (timestamp, public_id),
            )

        return self.get_work_item(public_id)

    def complete_work_item(self, public_id, *, timestamp=None):
        _validate_work_item_id(public_id)
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "WorkItem completion timestamp")

        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM work_items WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown WorkItem: {public_id}")
            if row["status"] != "running":
                raise ValueError(
                    f"Cannot complete WorkItem from status: {row['status']}"
                )
            connection.execute(
                """
                UPDATE work_items
                SET status = 'completed', updated_at = ?
                WHERE public_id = ?
                """,
                (timestamp, public_id),
            )

        return self.get_work_item(public_id)
