import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from anima.config.paths import get_data_dir


SCHEMA_VERSION = 1
SLEEP_JOB_ID_PREFIX = "sj_"
SLEEP_JOB_TRANSITION_ID_PREFIX = "sjt_"
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
            with self._connect() as connection:
                connection.executescript(SCHEMA_SQL)
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
        except sqlite3.DatabaseError as error:
            raise ValueError(
                f"Cannot initialize Sleep database {self.database_file}: {error}"
            ) from error

        if row is None or row["value"] != str(SCHEMA_VERSION):
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
        with self._connect() as connection:
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
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sleep_jobs WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_job(row)

    def list_jobs(self, *, status=None):
        if status is not None:
            _validate_job_status(status)
        with self._connect() as connection:
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
        with self._connect() as connection:
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
