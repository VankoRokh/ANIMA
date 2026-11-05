"""P2-A durable ingress for trusted, registered Core event adapters.

This is a narrow event receipt boundary, NOT an Observation validator, Belief
writer, or replacement for the legacy EventLog / MemoryProcessor.
"""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4


CONTRACT = "core.event/0.1"
SCHEMA_VERSION = 1
MAX_PAYLOAD_BYTES = 16_384
_REF = re.compile(r"[a-zA-Z][a-zA-Z0-9._/@-]{0,127}\Z")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS core_events (
    event_id TEXT PRIMARY KEY,
    source_ref TEXT NOT NULL,
    producer_ref TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    occurrence_version INTEGER NOT NULL CHECK (occurrence_version > 0),
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE (source_ref, occurrence_id, occurrence_version)
);
CREATE TABLE IF NOT EXISTS core_outbox (
    event_id TEXT PRIMARY KEY REFERENCES core_events(event_id),
    destination TEXT NOT NULL CHECK (destination = 'core.dispatch'),
    status TEXT NOT NULL CHECK (status = 'pending')
);
CREATE TABLE IF NOT EXISTS ingress_rejections (
    row_id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    source_ref TEXT,
    reason_code TEXT NOT NULL
);
"""


def _ref(value):
    return isinstance(value, str) and _REF.fullmatch(value) is not None


def _json_safe(value, depth=0):
    """Limit exact JSON input; do not coerce floats or serialize arbitrary objects."""
    if depth > 12:
        return False
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is list:
        return len(value) <= 1024 and all(_json_safe(v, depth + 1) for v in value)
    if type(value) is dict:
        return len(value) <= 1024 and all(
            isinstance(k, str) and _json_safe(v, depth + 1)
            for k, v in value.items()
        )
    return False


def _canonical(data):
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


@dataclass(frozen=True, slots=True)
class SourceRegistration:
    """System-owned adapter binding. Not a transport authentication protocol."""

    source_ref: str
    producer_ref: str
    allowed_kinds: tuple[str, ...]

    def __post_init__(self):
        if not _ref(self.source_ref) or not _ref(self.producer_ref):
            raise ValueError("Source and Producer refs must be registered identifiers")
        if (
            type(self.allowed_kinds) is not tuple
            or not self.allowed_kinds
            or any(not _ref(kind) for kind in self.allowed_kinds)
            or len(set(self.allowed_kinds)) != len(self.allowed_kinds)
        ):
            raise ValueError("allowed_kinds must be a nonempty unique identifier tuple")


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    status: str
    event_id: str | None
    reason_code: str | None = None


class CoreIngress:
    """Admission uses a system-owned SourceRegistration registry.

    Call admit() only from a trusted adapter boundary that has already bound
    the caller to source_ref. Registry names alone are NOT authentication.
    A single SQLite transaction inserts the immutable event and dispatch intent.
    P2-B will add validated Observation/Belief writes to this same boundary.
    """

    def __init__(
        self,
        database_file: str | Path,
        *,
        sources: Mapping[str, SourceRegistration],
        fault_hook: Callable[[str], None] | None = None,
    ):
        if not isinstance(sources, Mapping):
            raise TypeError("sources must be a trusted registration mapping")
        self.sources = dict(sources)
        if any(
            not isinstance(entry, SourceRegistration) or key != entry.source_ref
            for key, entry in self.sources.items()
        ):
            raise ValueError("Source registry key must match a SourceRegistration")
        if fault_hook is not None and not callable(fault_hook):
            raise TypeError("fault_hook must be callable")
        self.fault_hook = fault_hook
        self.database_file = Path(database_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row["value"] != str(SCHEMA_VERSION):
                    raise ValueError("Unsupported Core ingress schema version")

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _audit(connection, received_at, source_ref, reason):
        safe_ref = source_ref if isinstance(source_ref, str) and len(source_ref) <= 128 else None
        connection.execute(
            "INSERT INTO ingress_rejections(received_at, source_ref, reason_code) "
            "VALUES (?, ?, ?)",
            (received_at, safe_ref, reason),
        )

    def _reject(self, source_ref, reason, received_at):
        with closing(self._connect()) as connection:
            with connection:
                self._audit(connection, received_at, source_ref, reason)
        return AdmissionResult("REJECTED", None, reason)

    @staticmethod
    def _validated(raw, registration):
        if type(raw) is not dict or set(raw) != {
            "contract", "occurrence_id", "occurrence_version", "kind", "payload"
        }:
            return None
        if raw["contract"] != CONTRACT:
            return None
        occurrence_id = raw["occurrence_id"]
        if not isinstance(occurrence_id, str) or not 1 <= len(occurrence_id) <= 128:
            return None
        if type(raw["occurrence_version"]) is not int or raw["occurrence_version"] < 1:
            return None
        if raw["kind"] not in registration.allowed_kinds or type(raw["payload"]) is not dict:
            return None
        if not _json_safe(raw["payload"]):
            return None
        try:
            payload = _canonical(raw["payload"])
            if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                return None
            record = {
                "contract": CONTRACT,
                "source_ref": registration.source_ref,
                "producer_ref": registration.producer_ref,
                "occurrence_id": occurrence_id,
                "occurrence_version": raw["occurrence_version"],
                "kind": raw["kind"],
                "payload": json.loads(payload),
            }
            fingerprint = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
        except (TypeError, ValueError, RecursionError, OverflowError):
            return None
        return record, payload, fingerprint

    def admit(self, raw, *, source_ref):
        """Return ACCEPTED / ALREADY_SEEN / IDENTITY_CONFLICT / REJECTED.

        Duplicate deliveries return the originally committed system event_id.
        Rejection audit has reason codes but never stores untrusted raw payload.
        SQLite I/O failures deliberately propagate instead of faking rejection.
        """
        received_at = self._now()
        registration = self.sources.get(source_ref) if isinstance(source_ref, str) else None
        if registration is None:
            return self._reject(source_ref, "UNKNOWN_SOURCE", received_at)
        checked = self._validated(raw, registration)
        if checked is None:
            return self._reject(source_ref, "INVALID_ENVELOPE", received_at)
        record, payload, digest = checked

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = connection.execute(
                    "SELECT event_id, content_sha256 FROM core_events "
                    "WHERE source_ref=? AND occurrence_id=? AND occurrence_version=?",
                    (
                        source_ref, record["occurrence_id"], record["occurrence_version"]
                    ),
                ).fetchone()
                if previous is not None:
                    if previous["content_sha256"] == digest:
                        result = AdmissionResult("ALREADY_SEEN", previous["event_id"])
                    else:
                        self._audit(connection, received_at, source_ref, "IDENTITY_CONFLICT")
                        result = AdmissionResult(
                            "IDENTITY_CONFLICT", previous["event_id"], "IDENTITY_CONFLICT"
                        )
                else:
                    event_id = f"ev_{uuid4()}"
                    connection.execute(
                        "INSERT INTO core_events("
                        "event_id, source_ref, producer_ref, occurrence_id, "
                        "occurrence_version, kind, payload_json, content_sha256, received_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            event_id, source_ref, record["producer_ref"],
                            record["occurrence_id"], record["occurrence_version"],
                            record["kind"], payload, digest, received_at,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO core_outbox(event_id, destination, status) "
                        "VALUES (?, 'core.dispatch', 'pending')",
                        (event_id,),
                    )
                    if self.fault_hook is not None:
                        self.fault_hook(event_id)
                    result = AdmissionResult("ACCEPTED", event_id)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return result

    def get_event(self, event_id):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM core_events WHERE event_id=?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "event_id": row["event_id"],
            "source_ref": row["source_ref"],
            "producer_ref": row["producer_ref"],
            "occurrence_id": row["occurrence_id"],
            "occurrence_version": row["occurrence_version"],
            "kind": row["kind"],
            "payload": json.loads(row["payload_json"]),
            "received_at": row["received_at"],
            "content_sha256": row["content_sha256"],
        }

    def pending_event_ids(self):
        """Read-only; P2-C will define dispatch acknowledgements/reconciliation."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT event_id FROM core_outbox WHERE status='pending' ORDER BY rowid"
            ).fetchall()
        return tuple(row["event_id"] for row in rows)

    def rejection_count(self):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM ingress_rejections"
            ).fetchone()
        return row["n"]


__all__ = ["AdmissionResult", "CONTRACT", "CoreIngress", "SourceRegistration"]
