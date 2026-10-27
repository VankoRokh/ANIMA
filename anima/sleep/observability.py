import resource
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from anima.memory.memory_store import MemoryStore
from anima.sleep.selection import COST_UNITS
from anima.sleep.store import SleepStore


OBSERVABILITY_SCHEMA_KEY = "sleep_observability_schema_version"
OBSERVABILITY_SCHEMA_VERSION = 1

OBSERVABILITY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sleep_job_observability (
    job_id TEXT PRIMARY KEY,
    max_committed_chunks INTEGER CHECK (
        max_committed_chunks IS NULL OR max_committed_chunks >= 0
    ),
    max_cost_units INTEGER CHECK (
        max_cost_units IS NULL OR max_cost_units >= 0
    ),
    max_elapsed_seconds REAL CHECK (
        max_elapsed_seconds IS NULL OR max_elapsed_seconds >= 0
    ),
    started_at TEXT NOT NULL,
    last_stop_reason TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES sleep_jobs(public_id) ON DELETE CASCADE
);
"""


def _utc_now():
    return datetime.now(timezone.utc)


def _validate_non_negative_int_or_none(value, label):
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer or null")


def _validate_non_negative_number_or_none(value, label):
    if value is None:
        return
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{label} must be a non-negative number or null")


def _validate_positive_int_or_none(value, label):
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer or null")


def _parse_timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Sleep observability timestamp must include UTC offset")
    return parsed


def _file_size(path):
    path = Path(path)
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _default_resource_probe():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "cpu_user_seconds": usage.ru_utime,
        "cpu_system_seconds": usage.ru_stime,
        "max_rss_kb": usage.ru_maxrss,
    }


@dataclass(frozen=True, slots=True)
class SleepResourceBudget:
    max_committed_chunks: int | None = None
    max_cost_units: int | None = None
    max_elapsed_seconds: float | None = None

    def __post_init__(self):
        _validate_non_negative_int_or_none(
            self.max_committed_chunks,
            "SleepResourceBudget max_committed_chunks",
        )
        _validate_non_negative_int_or_none(
            self.max_cost_units,
            "SleepResourceBudget max_cost_units",
        )
        _validate_non_negative_number_or_none(
            self.max_elapsed_seconds,
            "SleepResourceBudget max_elapsed_seconds",
        )

    def to_dict(self):
        return {
            "max_committed_chunks": self.max_committed_chunks,
            "max_cost_units": self.max_cost_units,
            "max_elapsed_seconds": self.max_elapsed_seconds,
        }


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed_new_chunks: int | None
    exhausted: bool
    reason: str | None
    usage: dict
    remaining: dict


class SleepObservability:
    """Persistent Sleep budget plus headless progress/resource snapshots."""

    def __init__(
        self,
        *,
        sleep_store,
        memory_store=None,
        now=None,
        resource_probe=None,
    ):
        if not isinstance(sleep_store, SleepStore):
            raise TypeError("sleep_store must be a SleepStore")
        if memory_store is not None and not isinstance(memory_store, MemoryStore):
            raise TypeError("memory_store must be a MemoryStore or null")
        if now is not None and not callable(now):
            raise TypeError("now must be callable or null")
        if resource_probe is not None and not callable(resource_probe):
            raise TypeError("resource_probe must be callable or null")

        self.sleep_store = sleep_store
        self.memory_store = memory_store
        self._now = now or _utc_now
        self._resource_probe = resource_probe or _default_resource_probe
        self._initialize()

    def _initialize(self):
        with self.sleep_store.transaction() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (OBSERVABILITY_SCHEMA_KEY,),
            ).fetchone()
            if row is not None and row["value"] != str(OBSERVABILITY_SCHEMA_VERSION):
                raise ValueError(
                    "Unsupported Sleep observability schema in "
                    f"{self.sleep_store.database_file}"
                )
            connection.executescript(OBSERVABILITY_SCHEMA_SQL)
            if row is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES(?, ?)",
                    (OBSERVABILITY_SCHEMA_KEY, str(OBSERVABILITY_SCHEMA_VERSION)),
                )

    def schema_version(self):
        with self.sleep_store._connect() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (OBSERVABILITY_SCHEMA_KEY,),
            ).fetchone()
        if row is None:
            raise ValueError("Sleep observability schema is not initialized")
        return int(row["value"])

    def _now_value(self):
        value = self._now()
        if not isinstance(value, datetime):
            raise ValueError("Sleep observability clock must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Sleep observability clock must be timezone-aware")
        return value

    def ensure_job(self, job_id, *, budget=None):
        job = self.sleep_store.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown SleepJob: {job_id}")
        if budget is not None and not isinstance(budget, SleepResourceBudget):
            raise TypeError("budget must be a SleepResourceBudget or null")

        now = self._now_value().isoformat(timespec="seconds")
        with self.sleep_store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM sleep_job_observability WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                limits = budget or SleepResourceBudget()
                connection.execute(
                    """
                    INSERT INTO sleep_job_observability(
                        job_id, max_committed_chunks, max_cost_units,
                        max_elapsed_seconds, started_at, last_stop_reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        job_id,
                        limits.max_committed_chunks,
                        limits.max_cost_units,
                        limits.max_elapsed_seconds,
                        now,
                        now,
                    ),
                )
            elif budget is not None:
                connection.execute(
                    """
                    UPDATE sleep_job_observability
                    SET max_committed_chunks = ?, max_cost_units = ?,
                        max_elapsed_seconds = ?, last_stop_reason = NULL,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        budget.max_committed_chunks,
                        budget.max_cost_units,
                        budget.max_elapsed_seconds,
                        now,
                        job_id,
                    ),
                )
        return self.budget(job_id)

    def configure_budget(self, job_id, budget):
        if not isinstance(budget, SleepResourceBudget):
            raise TypeError("budget must be a SleepResourceBudget")
        return self.ensure_job(job_id, budget=budget)

    def _profile_row(self, job_id):
        self.ensure_job(job_id)
        with self.sleep_store._connect() as connection:
            return connection.execute(
                "SELECT * FROM sleep_job_observability WHERE job_id = ?",
                (job_id,),
            ).fetchone()

    def budget(self, job_id):
        with self.sleep_store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sleep_job_observability WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return SleepResourceBudget()
        return SleepResourceBudget(
            max_committed_chunks=row["max_committed_chunks"],
            max_cost_units=row["max_cost_units"],
            max_elapsed_seconds=row["max_elapsed_seconds"],
        )

    def mark_stop_reason(self, job_id, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Sleep stop reason must be a non-empty string")
        self.ensure_job(job_id)
        now = self._now_value().isoformat(timespec="seconds")
        with self.sleep_store.transaction() as connection:
            connection.execute(
                """
                UPDATE sleep_job_observability
                SET last_stop_reason = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (reason, now, job_id),
            )

    def clear_stop_reason(self, job_id):
        self.ensure_job(job_id)
        now = self._now_value().isoformat(timespec="seconds")
        with self.sleep_store.transaction() as connection:
            connection.execute(
                """
                UPDATE sleep_job_observability
                SET last_stop_reason = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (now, job_id),
            )

    def _work_items(self, job_id):
        return self.sleep_store.list_work_items(job_id=job_id)

    @staticmethod
    def _cost_charged(item):
        return (
            item.checkpoint_ref is not None
            or item.status in {"completed", "failed"}
        )

    def _usage(self, job_id):
        items = self._work_items(job_id)
        counts = {
            "queued": 0,
            "running": 0,
            "checkpointed": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
        }
        committed_chunks = 0
        charged_cost_units = 0
        selected_cost_units = 0

        for item in items:
            counts[item.status] += 1
            checkpoints = self.sleep_store.list_checkpoints(item.public_id)
            committed_chunks += len(checkpoints)
            item_cost = COST_UNITS[item.cost_hint]
            selected_cost_units += item_cost
            if self._cost_charged(item):
                charged_cost_units += item_cost

        return {
            "committed_chunks": committed_chunks,
            "cost_units": charged_cost_units,
            "selected_cost_units": selected_cost_units,
            "counts": counts,
        }

    def _metrics(self, row):
        now = self._now_value()
        started_at = _parse_timestamp(row["started_at"])
        elapsed_seconds = max(0.0, (now - started_at).total_seconds())

        resources = dict(self._resource_probe())
        required = {"cpu_user_seconds", "cpu_system_seconds", "max_rss_kb"}
        if not required.issubset(resources):
            missing = ", ".join(sorted(required - resources.keys()))
            raise ValueError(f"Sleep resource probe missing fields: {missing}")

        sleep_bytes = _file_size(self.sleep_store.database_file)
        memory_bytes = (
            _file_size(self.memory_store.database_file)
            if self.memory_store is not None
            else 0
        )
        return {
            "elapsed_seconds": elapsed_seconds,
            "cpu_user_seconds": resources["cpu_user_seconds"],
            "cpu_system_seconds": resources["cpu_system_seconds"],
            "max_rss_kb": resources["max_rss_kb"],
            "storage_bytes": {
                "sleep_db": sleep_bytes,
                "memory_db": memory_bytes,
                "total": sleep_bytes + memory_bytes,
            },
        }

    @staticmethod
    def _remaining(limits, usage, elapsed_seconds):
        def remaining(limit, used):
            if limit is None:
                return None
            return max(0, limit - used)

        return {
            "committed_chunks": remaining(
                limits.max_committed_chunks,
                usage["committed_chunks"],
            ),
            "cost_units": remaining(
                limits.max_cost_units,
                usage["cost_units"],
            ),
            "elapsed_seconds": (
                None
                if limits.max_elapsed_seconds is None
                else max(0.0, limits.max_elapsed_seconds - elapsed_seconds)
            ),
        }

    def budget_decision(
        self,
        job_id,
        work_item_id,
        *,
        requested_max_new_chunks,
    ):
        _validate_positive_int_or_none(
            requested_max_new_chunks,
            "requested_max_new_chunks",
        )
        row = self._profile_row(job_id)
        limits = self.budget(job_id)
        usage = self._usage(job_id)
        metrics = self._metrics(row)
        remaining = self._remaining(
            limits,
            usage,
            metrics["elapsed_seconds"],
        )

        item = self.sleep_store.get_work_item(work_item_id)
        if item is None:
            raise ValueError(f"Unknown WorkItem: {work_item_id}")
        if item.job_id != job_id:
            raise ValueError("WorkItem does not belong to Sleep budget Job")

        reason = None
        if (
            limits.max_elapsed_seconds is not None
            and metrics["elapsed_seconds"] >= limits.max_elapsed_seconds
        ):
            reason = "elapsed_seconds"

        additional_cost = 0 if self._cost_charged(item) else COST_UNITS[item.cost_hint]
        if (
            reason is None
            and limits.max_cost_units is not None
            and usage["cost_units"] + additional_cost > limits.max_cost_units
        ):
            reason = "cost_units"

        if (
            reason is None
            and limits.max_committed_chunks is not None
            and usage["committed_chunks"] >= limits.max_committed_chunks
        ):
            reason = "committed_chunks"

        if reason is not None:
            return BudgetDecision(
                allowed_new_chunks=0,
                exhausted=True,
                reason=reason,
                usage=usage,
                remaining=remaining,
            )

        allowed = requested_max_new_chunks
        chunk_remaining = remaining["committed_chunks"]
        if chunk_remaining is not None:
            if allowed is None:
                allowed = chunk_remaining
            else:
                allowed = min(allowed, chunk_remaining)

        if allowed == 0:
            return BudgetDecision(
                allowed_new_chunks=0,
                exhausted=True,
                reason="committed_chunks",
                usage=usage,
                remaining=remaining,
            )

        return BudgetDecision(
            allowed_new_chunks=allowed,
            exhausted=False,
            reason=None,
            usage=usage,
            remaining=remaining,
        )

    def _work_item_record(self, item):
        checkpoints = self.sleep_store.list_checkpoints(item.public_id)
        latest = checkpoints[-1] if checkpoints else None
        return {
            "id": item.public_id,
            "status": item.status,
            "source": item.source_ref.to_dict(),
            "processor": item.processor,
            "processor_version": item.processor_version,
            "priority": item.priority,
            "cost_hint": item.cost_hint,
            "cost_units": COST_UNITS[item.cost_hint],
            "attempts": item.attempts,
            "checkpoint_ref": item.checkpoint_ref,
            "committed_chunks": len(checkpoints),
            "last_committed_sequence": (
                None if latest is None else latest["sequence"]
            ),
            "next_sequence": 0 if latest is None else latest["sequence"] + 1,
            "selection_reason": {
                "priority": item.priority,
                "cost_hint": item.cost_hint,
                "tie_break": [item.source_ref.kind, item.source_ref.source_id],
            },
        }

    @staticmethod
    def _current_record(records):
        for status in ("running", "checkpointed", "queued"):
            for record in records:
                if record["status"] == status:
                    return record
        return None

    def snapshot(self, job_id):
        job = self.sleep_store.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown SleepJob: {job_id}")
        row = self._profile_row(job_id)
        limits = self.budget(job_id)
        usage = self._usage(job_id)
        metrics = self._metrics(row)
        remaining = self._remaining(
            limits,
            usage,
            metrics["elapsed_seconds"],
        )
        records = [
            self._work_item_record(item)
            for item in self._work_items(job_id)
        ]
        current = self._current_record(records)
        counts = usage["counts"]

        return {
            "job_id": job_id,
            "job_status": job["status"],
            "queue": {
                "total": len(records),
                "processed": counts["completed"],
                "skipped": counts["skipped"],
                "failed": counts["failed"],
                "by_status": dict(counts),
                "selected_cost_units": usage["selected_cost_units"],
                "ordering": "priority desc, cost asc, source kind/id tie-break",
            },
            "current_work_item": current,
            "current_chunk": (
                None
                if current is None
                else {
                    "last_committed_sequence": current[
                        "last_committed_sequence"
                    ],
                    "next_sequence": current["next_sequence"],
                }
            ),
            "work_items": records,
            "budget": {
                "limits": limits.to_dict(),
                "usage": {
                    "committed_chunks": usage["committed_chunks"],
                    "cost_units": usage["cost_units"],
                    "elapsed_seconds": metrics["elapsed_seconds"],
                },
                "remaining": remaining,
                "exhausted": row["last_stop_reason"] is not None,
                "reason": row["last_stop_reason"],
            },
            "metrics": metrics,
        }
