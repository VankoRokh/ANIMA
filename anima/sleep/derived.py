import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from anima.sleep.contracts import SourceRegistry, SourceRef
from anima.sleep.processors import FinalizeResult
from anima.sleep.store import SleepStore


DERIVED_SCHEMA_KEY = "derived_results_schema_version"
DERIVED_SCHEMA_VERSION = 1
DERIVED_RESULT_ID_PREFIX = "dr_"
DERIVED_OUTPUT_ID_PREFIX = "dout_"
DERIVED_AUTHORITY = "derived"

DERIVED_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS derived_results (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    work_item_id TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL,
    work_kind TEXT NOT NULL,
    processor TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    authority TEXT NOT NULL CHECK (authority = 'derived'),
    output_ref TEXT NOT NULL UNIQUE,
    output_json TEXT NOT NULL,
    transformation_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (work_item_id) REFERENCES work_items(public_id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES sleep_jobs(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_derived_results_job
    ON derived_results(job_id, row_id);
CREATE INDEX IF NOT EXISTS idx_derived_results_processor
    ON derived_results(processor, processor_version, row_id);

CREATE TABLE IF NOT EXISTS derived_result_sources (
    result_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('event', 'memory', 'knowledge', 'asset')
    ),
    source_id TEXT NOT NULL,
    PRIMARY KEY (result_id, ordinal),
    UNIQUE (result_id, source_kind, source_id),
    FOREIGN KEY (result_id) REFERENCES derived_results(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_derived_result_sources_source
    ON derived_result_sources(source_kind, source_id, result_id);
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


@dataclass(frozen=True, slots=True)
class DerivedResult:
    public_id: str
    work_item_id: str
    job_id: str
    work_kind: str
    source_refs: tuple[SourceRef, ...]
    processor: str
    processor_version: str
    authority: str
    transformation_history: tuple[dict, ...]
    output_ref: str
    output: object
    created_at: str

    def __post_init__(self):
        _validate_prefixed_uuid4(
            self.public_id,
            prefix=DERIVED_RESULT_ID_PREFIX,
            label="DerivedResult public_id",
        )
        _validate_prefixed_uuid4(
            self.output_ref,
            prefix=DERIVED_OUTPUT_ID_PREFIX,
            label="DerivedResult output_ref",
        )
        if not isinstance(self.source_refs, tuple) or not self.source_refs:
            raise ValueError("DerivedResult source_refs must be a non-empty tuple")
        if not all(isinstance(source, SourceRef) for source in self.source_refs):
            raise ValueError("DerivedResult source_refs must contain SourceRef objects")
        if self.authority != DERIVED_AUTHORITY:
            raise ValueError("DerivedResult authority must be 'derived'")
        if not isinstance(self.transformation_history, tuple):
            raise ValueError("DerivedResult transformation_history must be a tuple")
        _json_dumps(list(self.transformation_history), "DerivedResult transformation history")
        _json_dumps(self.output, "DerivedResult output")
        _validate_timestamp(self.created_at, "DerivedResult created_at")

    def to_dict(self):
        return {
            "id": self.public_id,
            "work_item_id": self.work_item_id,
            "job_id": self.job_id,
            "work_kind": self.work_kind,
            "sources": [source.to_dict() for source in self.source_refs],
            "processor": self.processor,
            "processor_version": self.processor_version,
            "authority": self.authority,
            "transformation_history": [
                dict(step) for step in self.transformation_history
            ],
            "output_ref": self.output_ref,
            "output": self.output,
            "created_at": self.created_at,
        }


class DerivedResultRepository:
    """Persistent derived-output layer stored inside the existing sleep.db."""

    def __init__(self, sleep_store):
        if not isinstance(sleep_store, SleepStore):
            raise ValueError("sleep_store must be a SleepStore")
        self.sleep_store = sleep_store
        self._initialize()

    def _initialize(self):
        with self.sleep_store.transaction() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (DERIVED_SCHEMA_KEY,),
            ).fetchone()
            if row is not None and row["value"] != str(DERIVED_SCHEMA_VERSION):
                raise ValueError(
                    "Unsupported derived-result schema in "
                    f"{self.sleep_store.database_file}"
                )
            connection.executescript(DERIVED_SCHEMA_SQL)
            if row is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES(?, ?)",
                    (DERIVED_SCHEMA_KEY, str(DERIVED_SCHEMA_VERSION)),
                )

    def schema_version(self):
        with self.sleep_store._connect() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (DERIVED_SCHEMA_KEY,),
            ).fetchone()
        if row is None:
            raise ValueError("Derived-result schema is not initialized")
        return int(row["value"])

    @staticmethod
    def _source_rows(connection, result_id):
        return connection.execute(
            """
            SELECT source_kind, source_id
            FROM derived_result_sources
            WHERE result_id = ?
            ORDER BY ordinal
            """,
            (result_id,),
        ).fetchall()

    @classmethod
    def _row_to_result(cls, connection, row):
        if row is None:
            return None
        source_refs = tuple(
            SourceRef(kind=source["source_kind"], source_id=source["source_id"])
            for source in cls._source_rows(connection, row["public_id"])
        )
        transformation = json.loads(row["transformation_json"])
        return DerivedResult(
            public_id=row["public_id"],
            work_item_id=row["work_item_id"],
            job_id=row["job_id"],
            work_kind=row["work_kind"],
            source_refs=source_refs,
            processor=row["processor"],
            processor_version=row["processor_version"],
            authority=row["authority"],
            transformation_history=tuple(dict(step) for step in transformation),
            output_ref=row["output_ref"],
            output=json.loads(row["output_json"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _history_from_rows(checkpoints, *, processor, processor_version):
        history = [
            {
                "kind": "chunk",
                "sequence": checkpoint["sequence"],
                "checkpoint_ref": checkpoint["public_id"],
            }
            for checkpoint in checkpoints
        ]
        history.append(
            {
                "kind": "finalize",
                "processor": processor,
                "processor_version": processor_version,
            }
        )
        return history

    def commit_final_result(
        self,
        work_item_id,
        final_result,
        *,
        source_registry,
        result_id=None,
        output_ref=None,
        created_at=None,
    ):
        if not isinstance(final_result, FinalizeResult):
            raise ValueError("final_result must be a FinalizeResult")
        if not isinstance(source_registry, SourceRegistry):
            raise ValueError("source_registry must be a SourceRegistry")

        work_item = self.sleep_store.get_work_item(work_item_id)
        if work_item is None:
            raise ValueError(f"Unknown WorkItem: {work_item_id}")
        if final_result.work_item_id != work_item.public_id:
            raise ValueError("FinalizeResult work_item_id does not match WorkItem")
        if final_result.source_ref != work_item.source_ref:
            raise ValueError("FinalizeResult source_ref does not match WorkItem")
        if final_result.processor != work_item.processor:
            raise ValueError("FinalizeResult processor does not match WorkItem")
        if final_result.processor_version != work_item.processor_version:
            raise ValueError("FinalizeResult processor_version does not match WorkItem")

        # Cross-store source existence cannot be protected by the sleep.db transaction,
        # but a missing source must be detected before completion is committed.
        source_registry.require(work_item.source_ref)

        result_id = result_id or f"{DERIVED_RESULT_ID_PREFIX}{uuid4()}"
        output_ref = output_ref or f"{DERIVED_OUTPUT_ID_PREFIX}{uuid4()}"
        created_at = created_at or _now()
        _validate_prefixed_uuid4(
            result_id,
            prefix=DERIVED_RESULT_ID_PREFIX,
            label="DerivedResult public_id",
        )
        _validate_prefixed_uuid4(
            output_ref,
            prefix=DERIVED_OUTPUT_ID_PREFIX,
            label="DerivedResult output_ref",
        )
        _validate_timestamp(created_at, "DerivedResult created_at")
        output_json = _json_dumps(final_result.output, "DerivedResult output")

        try:
            with self.sleep_store.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM work_items WHERE public_id = ?",
                    (work_item_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown WorkItem: {work_item_id}")
                if row["status"] != "running":
                    raise ValueError(
                        "Derived result can be committed only for running WorkItem: "
                        f"{row['status']}"
                    )
                if row["processor"] != final_result.processor:
                    raise ValueError("Stored WorkItem processor changed before finalize")
                if row["processor_version"] != final_result.processor_version:
                    raise ValueError(
                        "Stored WorkItem processor_version changed before finalize"
                    )
                if (
                    row["source_kind"] != final_result.source_ref.kind
                    or row["source_id"] != final_result.source_ref.source_id
                ):
                    raise ValueError("Stored WorkItem source changed before finalize")

                checkpoints = connection.execute(
                    """
                    SELECT public_id, sequence
                    FROM work_item_checkpoints
                    WHERE work_item_id = ?
                    ORDER BY sequence, row_id
                    """,
                    (work_item_id,),
                ).fetchall()
                history = self._history_from_rows(
                    checkpoints,
                    processor=row["processor"],
                    processor_version=row["processor_version"],
                )
                transformation_json = _json_dumps(
                    history,
                    "DerivedResult transformation history",
                )

                connection.execute(
                    """
                    INSERT INTO derived_results(
                        public_id, work_item_id, job_id, work_kind,
                        processor, processor_version, authority,
                        output_ref, output_json, transformation_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'derived', ?, ?, ?, ?)
                    """,
                    (
                        result_id,
                        work_item_id,
                        row["job_id"],
                        row["work_kind"],
                        row["processor"],
                        row["processor_version"],
                        output_ref,
                        output_json,
                        transformation_json,
                        created_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO derived_result_sources(
                        result_id, ordinal, source_kind, source_id
                    ) VALUES (?, 0, ?, ?)
                    """,
                    (
                        result_id,
                        row["source_kind"],
                        row["source_id"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE work_items
                    SET status = 'completed', updated_at = ?
                    WHERE public_id = ?
                    """,
                    (created_at, work_item_id),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot commit DerivedResult {result_id}: {error}"
            ) from error

        return self.get(result_id)

    def get(self, result_id):
        _validate_prefixed_uuid4(
            result_id,
            prefix=DERIVED_RESULT_ID_PREFIX,
            label="DerivedResult public_id",
        )
        with self.sleep_store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM derived_results WHERE public_id = ?",
                (result_id,),
            ).fetchone()
            return self._row_to_result(connection, row)

    def get_by_work_item(self, work_item_id):
        with self.sleep_store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM derived_results WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
            return self._row_to_result(connection, row)

    def get_by_output_ref(self, output_ref):
        _validate_prefixed_uuid4(
            output_ref,
            prefix=DERIVED_OUTPUT_ID_PREFIX,
            label="DerivedResult output_ref",
        )
        with self.sleep_store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM derived_results WHERE output_ref = ?",
                (output_ref,),
            ).fetchone()
            return self._row_to_result(connection, row)

    def list_results(self, *, job_id=None):
        with self.sleep_store._connect() as connection:
            if job_id is None:
                rows = connection.execute(
                    "SELECT * FROM derived_results ORDER BY row_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM derived_results WHERE job_id = ? ORDER BY row_id",
                    (job_id,),
                ).fetchall()
            return [self._row_to_result(connection, row) for row in rows]
