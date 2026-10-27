import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from anima.memory.memory_store import MemoryStore
from anima.sleep.derived import DerivedResult, DerivedResultRepository
from anima.sleep.store import SleepStore


RECOVERY_SCHEMA_KEY = "sleep_recovery_schema_version"
RECOVERY_SCHEMA_VERSION = 1
EFFECT_SCHEMA_KEY = "sleep_effect_receipts_schema_version"
EFFECT_SCHEMA_VERSION = 1
OPERATION_ID_PREFIX = "sop_"
DEFAULT_EFFECT_KIND = "register_derived_output"
OPERATION_STATUSES = {"prepared", "applied", "failed"}

RECOVERY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sleep_operations (
    operation_key TEXT PRIMARY KEY,
    canonical_result_id TEXT NOT NULL,
    canonical_output_ref TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    effect_kind TEXT NOT NULL,
    logical_payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('prepared', 'applied', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (work_item_id) REFERENCES work_items(public_id) ON DELETE CASCADE,
    FOREIGN KEY (canonical_result_id) REFERENCES derived_results(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sleep_operations_status
    ON sleep_operations(status, created_at, operation_key);
CREATE INDEX IF NOT EXISTS idx_sleep_operations_result
    ON sleep_operations(canonical_result_id);
"""

EFFECT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sleep_effect_receipts (
    operation_key TEXT PRIMARY KEY,
    effect_kind TEXT NOT NULL,
    canonical_result_id TEXT NOT NULL,
    canonical_output_ref TEXT NOT NULL,
    logical_payload_json TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sleep_effect_receipts_result
    ON sleep_effect_receipts(canonical_result_id);
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


def _require_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


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


def _validate_operation_key(value):
    if not isinstance(value, str) or not value.startswith(OPERATION_ID_PREFIX):
        raise ValueError("Sleep operation key must be a sop_ UUIDv5")
    raw_uuid = value[len(OPERATION_ID_PREFIX):]
    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError("Sleep operation key must be a sop_ UUIDv5") from error
    if parsed.version != 5 or str(parsed) != raw_uuid:
        raise ValueError("Sleep operation key must be a sop_ UUIDv5")


def _logical_identity(result, effect_kind):
    return {
        "effect_kind": effect_kind,
        "work_kind": result.work_kind,
        "sources": [source.to_dict() for source in result.source_refs],
        "processor": result.processor,
        "processor_version": result.processor_version,
    }


def _logical_payload(result):
    output_json = _json_dumps(result.output, "DerivedResult output")
    return {
        "authority": result.authority,
        "work_kind": result.work_kind,
        "sources": [source.to_dict() for source in result.source_refs],
        "processor": result.processor,
        "processor_version": result.processor_version,
        "output_sha256": hashlib.sha256(output_json.encode("utf-8")).hexdigest(),
    }


def stable_operation_key(result, effect_kind=DEFAULT_EFFECT_KIND):
    if not isinstance(result, DerivedResult):
        raise ValueError("result must be a DerivedResult")
    _require_non_empty_string(effect_kind, "Sleep effect kind")
    identity_json = _json_dumps(
        _logical_identity(result, effect_kind),
        "Sleep operation identity",
    )
    operation_key = (
        f"{OPERATION_ID_PREFIX}"
        f"{uuid5(NAMESPACE_URL, 'anima:sleep:' + identity_json)}"
    )
    _validate_operation_key(operation_key)
    return operation_key


@dataclass(frozen=True, slots=True)
class RecoveryOperation:
    operation_key: str
    canonical_result_id: str
    canonical_output_ref: str
    work_item_id: str
    job_id: str
    effect_kind: str
    logical_payload: dict
    status: str
    attempts: int
    last_error: str | None
    created_at: str
    updated_at: str

    def __post_init__(self):
        _validate_operation_key(self.operation_key)
        for value, label in (
            (self.canonical_result_id, "canonical_result_id"),
            (self.canonical_output_ref, "canonical_output_ref"),
            (self.work_item_id, "work_item_id"),
            (self.job_id, "job_id"),
            (self.effect_kind, "effect_kind"),
        ):
            _require_non_empty_string(value, label)
        if self.status not in OPERATION_STATUSES:
            raise ValueError(f"Unknown Sleep operation status: {self.status!r}")
        if (
            not isinstance(self.attempts, int)
            or isinstance(self.attempts, bool)
            or self.attempts < 0
        ):
            raise ValueError("Sleep operation attempts must be a non-negative integer")
        if self.last_error is not None and (
            not isinstance(self.last_error, str) or not self.last_error.strip()
        ):
            raise ValueError("Sleep operation last_error must be a non-empty string or null")
        if not isinstance(self.logical_payload, dict):
            raise ValueError("Sleep operation logical_payload must be an object")
        _json_dumps(self.logical_payload, "Sleep operation logical_payload")
        _validate_timestamp(self.created_at, "Sleep operation created_at")
        _validate_timestamp(self.updated_at, "Sleep operation updated_at")

    def to_dict(self):
        return {
            "operation_key": self.operation_key,
            "canonical_result_id": self.canonical_result_id,
            "canonical_output_ref": self.canonical_output_ref,
            "work_item_id": self.work_item_id,
            "job_id": self.job_id,
            "effect_kind": self.effect_kind,
            "logical_payload": dict(self.logical_payload),
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    operation_key: str
    effect_kind: str
    canonical_result_id: str
    canonical_output_ref: str
    logical_payload: dict
    applied_at: str

    def __post_init__(self):
        _validate_operation_key(self.operation_key)
        _require_non_empty_string(self.effect_kind, "effect_kind")
        if not isinstance(self.logical_payload, dict):
            raise ValueError("Effect receipt logical_payload must be an object")
        _json_dumps(self.logical_payload, "Effect receipt logical_payload")
        _validate_timestamp(self.applied_at, "Effect receipt applied_at")


class RecoveryOperationRepository:
    """Persistent operation ledger in sleep.db for cross-store recovery."""

    def __init__(self, sleep_store, derived_results=None):
        if not isinstance(sleep_store, SleepStore):
            raise ValueError("sleep_store must be a SleepStore")
        if derived_results is None:
            derived_results = DerivedResultRepository(sleep_store)
        if not isinstance(derived_results, DerivedResultRepository):
            raise ValueError("derived_results must be a DerivedResultRepository")
        if derived_results.sleep_store is not sleep_store:
            raise ValueError("derived_results must use the same SleepStore")
        self.sleep_store = sleep_store
        self.derived_results = derived_results
        self._initialize()

    def _initialize(self):
        with self.sleep_store.transaction() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (RECOVERY_SCHEMA_KEY,),
            ).fetchone()
            if row is not None and row["value"] != str(RECOVERY_SCHEMA_VERSION):
                raise ValueError(
                    "Unsupported Sleep recovery schema in "
                    f"{self.sleep_store.database_file}"
                )
            connection.executescript(RECOVERY_SCHEMA_SQL)
            if row is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES(?, ?)",
                    (RECOVERY_SCHEMA_KEY, str(RECOVERY_SCHEMA_VERSION)),
                )

    @staticmethod
    def _row_to_operation(row):
        if row is None:
            return None
        return RecoveryOperation(
            operation_key=row["operation_key"],
            canonical_result_id=row["canonical_result_id"],
            canonical_output_ref=row["canonical_output_ref"],
            work_item_id=row["work_item_id"],
            job_id=row["job_id"],
            effect_kind=row["effect_kind"],
            logical_payload=json.loads(row["logical_payload_json"]),
            status=row["status"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def schema_version(self):
        with self.sleep_store._connect() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (RECOVERY_SCHEMA_KEY,),
            ).fetchone()
        if row is None:
            raise ValueError("Sleep recovery schema is not initialized")
        return int(row["value"])

    def prepare(self, result, *, effect_kind=DEFAULT_EFFECT_KIND, timestamp=None):
        if not isinstance(result, DerivedResult):
            raise ValueError("result must be a DerivedResult")
        if result.authority != "derived":
            raise ValueError("Only derived results can prepare Sleep effects")
        _require_non_empty_string(effect_kind, "Sleep effect kind")
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "Sleep operation timestamp")

        persisted = self.derived_results.get(result.public_id)
        if persisted is None or persisted != result:
            raise ValueError(
                "DerivedResult must be persisted unchanged before effect prepare"
            )

        operation_key = stable_operation_key(result, effect_kind)
        logical_payload = _logical_payload(result)
        payload_json = _json_dumps(logical_payload, "Sleep operation logical payload")

        with self.sleep_store.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM sleep_operations WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["effect_kind"] != effect_kind
                    or existing["logical_payload_json"] != payload_json
                ):
                    raise ValueError(
                        "Logical Sleep operation produced a different payload"
                    )
                return self._row_to_operation(existing)

            connection.execute(
                """
                INSERT INTO sleep_operations(
                    operation_key, canonical_result_id, canonical_output_ref,
                    work_item_id, job_id, effect_kind, logical_payload_json,
                    status, attempts, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', 0, NULL, ?, ?)
                """,
                (
                    operation_key,
                    result.public_id,
                    result.output_ref,
                    result.work_item_id,
                    result.job_id,
                    effect_kind,
                    payload_json,
                    timestamp,
                    timestamp,
                ),
            )

        return self.get(operation_key)

    def get(self, operation_key):
        _validate_operation_key(operation_key)
        with self.sleep_store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sleep_operations WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
        return self._row_to_operation(row)

    def list_operations(self, *, status=None):
        if status is not None and status not in OPERATION_STATUSES:
            raise ValueError(f"Unknown Sleep operation status: {status!r}")
        with self.sleep_store._connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM sleep_operations ORDER BY created_at, operation_key"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM sleep_operations
                    WHERE status = ?
                    ORDER BY created_at, operation_key
                    """,
                    (status,),
                ).fetchall()
        return [self._row_to_operation(row) for row in rows]

    def list_pending(self):
        with self.sleep_store._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sleep_operations
                WHERE status IN ('prepared', 'failed')
                ORDER BY created_at, operation_key
                """
            ).fetchall()
        return [self._row_to_operation(row) for row in rows]

    def mark_attempt(self, operation_key, *, timestamp=None):
        _validate_operation_key(operation_key)
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "Sleep operation attempt timestamp")
        with self.sleep_store.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM sleep_operations WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown Sleep operation: {operation_key}")
            if row["status"] != "applied":
                connection.execute(
                    """
                    UPDATE sleep_operations
                    SET attempts = attempts + 1, status = 'prepared',
                        last_error = NULL, updated_at = ?
                    WHERE operation_key = ?
                    """,
                    (timestamp, operation_key),
                )
        return self.get(operation_key)

    def mark_failed(self, operation_key, error, *, timestamp=None):
        _validate_operation_key(operation_key)
        _require_non_empty_string(error, "Sleep operation error")
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "Sleep operation failure timestamp")
        with self.sleep_store.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM sleep_operations WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown Sleep operation: {operation_key}")
            if row["status"] == "applied":
                raise ValueError("Applied Sleep operation cannot become failed")
            connection.execute(
                """
                UPDATE sleep_operations
                SET status = 'failed', last_error = ?, updated_at = ?
                WHERE operation_key = ?
                """,
                (error, timestamp, operation_key),
            )
        return self.get(operation_key)

    def mark_applied(self, operation_key, *, timestamp=None):
        _validate_operation_key(operation_key)
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "Sleep operation applied timestamp")
        with self.sleep_store.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM sleep_operations WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown Sleep operation: {operation_key}")
            if row["status"] != "applied":
                connection.execute(
                    """
                    UPDATE sleep_operations
                    SET status = 'applied', last_error = NULL, updated_at = ?
                    WHERE operation_key = ?
                    """,
                    (timestamp, operation_key),
                )
        return self.get(operation_key)


class CognitiveEffectStore:
    """Idempotent receipt store inside memory.db; it does not elevate authority."""

    def __init__(self, memory_store):
        if not isinstance(memory_store, MemoryStore):
            raise ValueError("memory_store must be a MemoryStore")
        self.memory_store = memory_store
        self._initialize()

    def _initialize(self):
        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (EFFECT_SCHEMA_KEY,),
            ).fetchone()
            if row is not None and row["value"] != str(EFFECT_SCHEMA_VERSION):
                raise ValueError(
                    "Unsupported Sleep effect receipt schema in "
                    f"{self.memory_store.database_file}"
                )
            connection.executescript(EFFECT_SCHEMA_SQL)
            if row is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES(?, ?)",
                    (EFFECT_SCHEMA_KEY, str(EFFECT_SCHEMA_VERSION)),
                )

    @staticmethod
    def _row_to_receipt(row):
        if row is None:
            return None
        return EffectReceipt(
            operation_key=row["operation_key"],
            effect_kind=row["effect_kind"],
            canonical_result_id=row["canonical_result_id"],
            canonical_output_ref=row["canonical_output_ref"],
            logical_payload=json.loads(row["logical_payload_json"]),
            applied_at=row["applied_at"],
        )

    def schema_version(self):
        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (EFFECT_SCHEMA_KEY,),
            ).fetchone()
        if row is None:
            raise ValueError("Sleep effect receipt schema is not initialized")
        return int(row["value"])

    def get(self, operation_key):
        _validate_operation_key(operation_key)
        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM sleep_effect_receipts WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
        return self._row_to_receipt(row)

    def count(self):
        with self.memory_store.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM sleep_effect_receipts"
            ).fetchone()
        return row["count"]

    def apply_once(self, operation, *, timestamp=None):
        if not isinstance(operation, RecoveryOperation):
            raise ValueError("operation must be a RecoveryOperation")
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "Sleep effect timestamp")
        payload_json = _json_dumps(
            operation.logical_payload,
            "Sleep effect logical payload",
        )

        with self.memory_store.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM sleep_effect_receipts WHERE operation_key = ?",
                (operation.operation_key,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["effect_kind"] != operation.effect_kind
                    or existing["canonical_result_id"] != operation.canonical_result_id
                    or existing["canonical_output_ref"] != operation.canonical_output_ref
                    or existing["logical_payload_json"] != payload_json
                ):
                    raise ValueError(
                        "Existing Sleep effect receipt conflicts with operation"
                    )
                return self._row_to_receipt(existing)

            connection.execute(
                """
                INSERT INTO sleep_effect_receipts(
                    operation_key, effect_kind, canonical_result_id,
                    canonical_output_ref, logical_payload_json, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation.operation_key,
                    operation.effect_kind,
                    operation.canonical_result_id,
                    operation.canonical_output_ref,
                    payload_json,
                    timestamp,
                ),
            )

        return self.get(operation.operation_key)


class SleepRecoveryCoordinator:
    """Recover WorkItems and reconcile at-least-once effects without duplication."""

    def __init__(self, *, operations, effects):
        if not isinstance(operations, RecoveryOperationRepository):
            raise ValueError("operations must be a RecoveryOperationRepository")
        if not isinstance(effects, CognitiveEffectStore):
            raise ValueError("effects must be a CognitiveEffectStore")
        self.operations = operations
        self.effects = effects
        self.sleep_store = operations.sleep_store
        self.derived_results = operations.derived_results

    def prepare_result(self, result, *, effect_kind=DEFAULT_EFFECT_KIND):
        return self.operations.prepare(result, effect_kind=effect_kind)

    def apply(self, operation_key):
        operation = self.operations.get(operation_key)
        if operation is None:
            raise ValueError(f"Unknown Sleep operation: {operation_key}")

        if operation.status == "applied":
            receipt = self.effects.get(operation_key)
            if receipt is None:
                raise ValueError(
                    "Applied Sleep operation is missing its external receipt"
                )
            return receipt

        operation = self.operations.mark_attempt(operation_key)
        try:
            receipt = self.effects.apply_once(operation)
        except Exception as error:
            self.operations.mark_failed(operation_key, str(error))
            raise
        self.operations.mark_applied(operation_key)
        return receipt

    def publish_result(self, result, *, effect_kind=DEFAULT_EFFECT_KIND):
        operation = self.prepare_result(result, effect_kind=effect_kind)
        receipt = self.apply(operation.operation_key)
        return self.operations.get(operation.operation_key), receipt

    def recover_pending(self):
        receipts = []
        for operation in self.operations.list_pending():
            receipts.append(self.apply(operation.operation_key))
        return receipts

    def recover_work_item(self, work_item_id, *, timestamp=None):
        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "WorkItem recovery timestamp")
        work_item = self.sleep_store.get_work_item(work_item_id)
        if work_item is None:
            raise ValueError(f"Unknown WorkItem: {work_item_id}")

        result = self.derived_results.get_by_work_item(work_item_id)
        if work_item.status == "completed":
            if result is None:
                raise ValueError(
                    "Completed WorkItem is missing its persistent DerivedResult"
                )
            return work_item
        if result is not None:
            raise ValueError(
                "Non-completed WorkItem already has a persistent DerivedResult"
            )

        latest = self.sleep_store.get_latest_checkpoint(work_item_id)
        if work_item.status == "running":
            if latest is None:
                if work_item.checkpoint_ref is not None:
                    raise ValueError(
                        "Running WorkItem has checkpoint_ref without persisted checkpoint"
                    )
                target_status = "queued"
            else:
                if work_item.checkpoint_ref != latest["id"]:
                    raise ValueError(
                        "Running WorkItem checkpoint_ref does not match latest checkpoint"
                    )
                target_status = "checkpointed"

            with self.sleep_store.transaction() as connection:
                connection.execute(
                    """
                    UPDATE work_items
                    SET status = ?, updated_at = ?
                    WHERE public_id = ? AND status = 'running'
                    """,
                    (target_status, timestamp, work_item_id),
                )
            return self.sleep_store.get_work_item(work_item_id)

        if work_item.status == "checkpointed":
            if latest is None or work_item.checkpoint_ref != latest["id"]:
                raise ValueError("Checkpointed WorkItem has inconsistent checkpoint state")
        elif work_item.status == "queued":
            if latest is not None or work_item.checkpoint_ref is not None:
                raise ValueError("Queued WorkItem unexpectedly has checkpoint state")

        return work_item
