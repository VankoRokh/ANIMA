"""P2-B: deterministic typed observations and versioned Core working beliefs.

Not Stage 7 Knowledge authority, model inference, or virtual-world ground truth.
The caller owns the SQLite transaction; project() never commits independently.
"""

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


_REF = re.compile(r"[A-Za-z][A-Za-z0-9._/@-]{0,127}\Z")
_VALUE_TYPES = {"symbol", "string", "boolean", "integer"}
_OBSERVATION_KINDS = {"state.property", "sensor.unavailable"}
MAX_TICK = 2**63 - 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS core_observations (
    event_id TEXT PRIMARY KEY REFERENCES core_events(event_id),
    source_ref TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    predicate_ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    observed_tick INTEGER NOT NULL,
    value_json TEXT,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_core_obs_lookup
ON core_observations(subject_ref, predicate_ref, source_ref, source_revision);
CREATE TABLE IF NOT EXISTS core_observation_outcomes (
    event_id TEXT PRIMARY KEY REFERENCES core_events(event_id),
    outcome TEXT NOT NULL,
    reason_code TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS core_beliefs (
    subject_ref TEXT NOT NULL,
    predicate_ref TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('known', 'unknown', 'disputed')),
    value_json TEXT,
    last_known_json TEXT,
    observed_tick INTEGER NOT NULL,
    last_known_tick INTEGER,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY(subject_ref, predicate_ref)
);
CREATE TABLE IF NOT EXISTS core_belief_revisions (
    row_id INTEGER PRIMARY KEY,
    subject_ref TEXT NOT NULL,
    predicate_ref TEXT NOT NULL,
    revision INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE REFERENCES core_events(event_id),
    status TEXT NOT NULL,
    value_json TEXT,
    observed_tick INTEGER NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    UNIQUE(subject_ref, predicate_ref, revision)
);
"""


def _ref(text):
    return isinstance(text, str) and _REF.fullmatch(text) is not None


def _nonneg(value):
    return type(value) is int and 0 <= value <= MAX_TICK


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _from_json(value):
    return None if value is None else json.loads(value)


@dataclass(frozen=True, slots=True)
class PropertyRule:
    """Explicit single-valued exact property in one registered logical clock."""

    subject_ref: str
    predicate_ref: str
    value_type: str
    clock_domain: str
    allowed_sources: tuple[str, ...]
    freshness_ticks: int
    allowed_symbols: tuple[str, ...] = ()

    def __post_init__(self):
        if not all(_ref(x) for x in (self.subject_ref, self.predicate_ref, self.clock_domain)):
            raise ValueError("Invalid property identity or clock domain")
        if self.value_type not in _VALUE_TYPES:
            raise ValueError("P2-B supports only exact atomic values")
        if not _nonneg(self.freshness_ticks):
            raise ValueError("Freshness budget must be nonnegative logical ticks")
        if (
            type(self.allowed_sources) is not tuple or not self.allowed_sources
            or any(not _ref(source) for source in self.allowed_sources)
            or len(set(self.allowed_sources)) != len(self.allowed_sources)
        ):
            raise ValueError("PropertyRule requires unique registered sources")
        if (
            type(self.allowed_symbols) is not tuple
            or any(not _ref(symbol) for symbol in self.allowed_symbols)
            or len(set(self.allowed_symbols)) != len(self.allowed_symbols)
        ):
            raise ValueError("Invalid symbol vocabulary")
        if self.value_type != "symbol" and self.allowed_symbols:
            raise ValueError("Only symbols support enumerated vocabulary")


class BeliefProjection:
    """A narrow authorized observation projection on the Core SQLite connection.

    Observation acceptance is separate from raw event admission; accepted
    raw events with invalid world payload remain auditable but cannot update
    Core Belief. The caller must have authenticated the adapter identity.
    """

    def __init__(self, properties: Mapping[tuple[str, str], PropertyRule]):
        if not isinstance(properties, Mapping):
            raise TypeError("properties must be a registry mapping")
        copied = dict(properties)
        if any(
            not isinstance(rule, PropertyRule)
            or key != (rule.subject_ref, rule.predicate_ref)
            for key, rule in copied.items()
        ):
            raise ValueError("PropertyRule registry must be keyed by entity and predicate")
        self.properties = MappingProxyType(copied)

    @staticmethod
    def initialize(connection):
        connection.executescript(SCHEMA)

    @staticmethod
    def _atomic_value(value, rule):
        if type(value) is not dict or set(value) != {"type", "value"}:
            return False
        kind = value["type"]
        if kind != rule.value_type:
            return False
        datum = value["value"]
        if kind == "boolean":
            return type(datum) is bool
        if kind == "integer":
            return _nonneg(datum) or (type(datum) is int and -MAX_TICK <= datum < 0)
        if kind == "string":
            return isinstance(datum, str) and len(datum) <= 4096
        if kind == "symbol":
            return _ref(datum) and (
                not rule.allowed_symbols or datum in rule.allowed_symbols
            )
        return False

    def _normalize(self, record):
        """Return (normalized, error). No inference from untrusted strings."""
        kind = record["kind"]
        if kind not in _OBSERVATION_KINDS:
            return None, "UNSUPPORTED_KIND"
        payload = record["payload"]
        if type(payload) is not dict:
            return None, "INVALID_OBSERVATION"
        required = {"subject_ref", "predicate_ref", "observed_at", "temporal_scope", "source_revision"}
        if kind == "state.property":
            required.add("value")
        else:
            required.add("reason")
        if set(payload) != required:
            return None, "INVALID_OBSERVATION"
        subject, predicate = payload["subject_ref"], payload["predicate_ref"]
        if not _ref(subject) or not _ref(predicate):
            return None, "INVALID_OBSERVATION"
        rule = self.properties.get((subject, predicate))
        if rule is None:
            return None, "UNREGISTERED_PROPERTY"
        if record["source_ref"] not in rule.allowed_sources:
            return None, "SOURCE_NOT_AUTHORIZED"
        observed = payload["observed_at"]
        if (
            type(observed) is not dict
            or set(observed) != {"domain", "value"}
            or observed["domain"] != rule.clock_domain
            or not _nonneg(observed["value"])
            or not _nonneg(payload["source_revision"])
        ):
            return None, "INVALID_OBSERVATION"
        scope = payload["temporal_scope"]
        if (
            type(scope) is not dict
            or set(scope) != {"kind", "at"}
            or scope["kind"] != "instant"
            or scope["at"] != observed
        ):
            return None, "INVALID_OBSERVATION"
        value = None
        if kind == "state.property":
            if not self._atomic_value(payload["value"], rule):
                return None, "INVALID_OBSERVATION"
            value = _json(payload["value"])
        else:
            if (
                not isinstance(payload["reason"], str)
                or not 1 <= len(payload["reason"]) <= 128
            ):
                return None, "INVALID_OBSERVATION"
        return {
            "source_ref": record["source_ref"],
            "subject_ref": subject,
            "predicate_ref": predicate,
            "kind": kind,
            "source_revision": payload["source_revision"],
            "observed_tick": observed["value"],
            "value_json": value,
            "reason": payload.get("reason"),
        }, None

    @staticmethod
    def _save_outcome(connection, event_id, outcome, reason):
        connection.execute(
            "INSERT INTO core_observation_outcomes(event_id, outcome, reason_code)"
            " VALUES (?, ?, ?)",
            (event_id, outcome, reason),
        )
        return outcome

    @staticmethod
    def _snapshot(connection, subject, predicate):
        return connection.execute(
            "SELECT * FROM core_beliefs WHERE subject_ref=? AND predicate_ref=?",
            (subject, predicate),
        ).fetchone()

    def project(self, connection, record, event_id):
        """Validate + persist evidence + project revision in caller's transaction."""
        obs, error = self._normalize(record)
        if error is not None:
            outcome = (
                "REJECTED_UNAUTHORIZED"
                if error == "SOURCE_NOT_AUTHORIZED"
                else "REJECTED_INVALID"
            )
            return self._save_outcome(connection, event_id, outcome, error)

        subject, predicate = obs["subject_ref"], obs["predicate_ref"]
        connection.execute(
            "INSERT INTO core_observations("
            "event_id, source_ref, subject_ref, predicate_ref, kind,"
            " source_revision, observed_tick, value_json, reason"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id, obs["source_ref"], subject, predicate, obs["kind"],
                obs["source_revision"], obs["observed_tick"],
                obs["value_json"], obs["reason"],
            ),
        )
        # Source-local revision monotonicity is independent of global tick order.
        max_source = connection.execute(
            "SELECT MAX(source_revision) FROM core_observations"
            " WHERE subject_ref=? AND predicate_ref=? AND source_ref=?"
            " AND event_id != ?",
            (subject, predicate, obs["source_ref"], event_id),
        ).fetchone()[0]
        if max_source is not None and obs["source_revision"] <= max_source:
            return self._save_outcome(
                connection, event_id, "HISTORY_ONLY", "SOURCE_REVISION_NOT_NEWER"
            )

        previous = self._snapshot(connection, subject, predicate)
        tick = obs["observed_tick"]
        value = obs["value_json"]
        if previous is not None and tick < previous["observed_tick"]:
            return self._save_outcome(connection, event_id, "HISTORY_ONLY", "OLDER_TICK")

        if previous is None:
            status = "known" if value is not None else "unknown"
            current = value
            last_known = value
            last_known_tick = tick if value is not None else None
            evidence = [event_id]
            outcome = "ACCEPTED_NEW" if value is not None else "MARKED_UNKNOWN"
        else:
            evidence = json.loads(previous["evidence_json"])
            if event_id not in evidence:
                evidence.append(event_id)
            last_known = previous["last_known_json"]
            last_known_tick = previous["last_known_tick"]
            if tick > previous["observed_tick"]:
                status = "known" if value is not None else "unknown"
                current = value
                if value is not None:
                    last_known, last_known_tick = value, tick
                outcome = "UPDATED_LATER" if value is not None else "MARKED_UNKNOWN"
                evidence = [event_id]  # new time scope, previous provenance in history
            elif value is None:
                status, current = "unknown", None
                outcome = "MARKED_UNKNOWN"
            elif previous["status"] == "disputed" or (
                previous["status"] == "known" and previous["value_json"] != value
            ):
                status, current = "disputed", None
                outcome = "MARKED_DISPUTED"
            elif previous["status"] == "unknown":
                status, current = "unknown", None
                outcome = "MARKED_UNKNOWN"
            else:
                status, current = "known", previous["value_json"]
                outcome = "ACCEPTED_SUPPORT"
            if status == "known" and current is not None and tick >= previous["observed_tick"]:
                last_known, last_known_tick = current, tick
        revision = 1 if previous is None else previous["revision"] + 1
        reason = outcome
        connection.execute(
            "INSERT INTO core_beliefs("
            "subject_ref, predicate_ref, revision, status, value_json,"
            " last_known_json, observed_tick, last_known_tick, evidence_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(subject_ref, predicate_ref) DO UPDATE SET"
            " revision=excluded.revision, status=excluded.status,"
            " value_json=excluded.value_json, last_known_json=excluded.last_known_json,"
            " observed_tick=excluded.observed_tick, last_known_tick=excluded.last_known_tick,"
            " evidence_json=excluded.evidence_json",
            (
                subject, predicate, revision, status, current, last_known,
                tick, last_known_tick, _json(evidence),
            ),
        )
        connection.execute(
            "INSERT INTO core_belief_revisions("
            "subject_ref, predicate_ref, revision, event_id, status,"
            " value_json, observed_tick, reason, evidence_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                subject, predicate, revision, event_id, status, current, tick,
                reason, _json(evidence),
            ),
        )
        return self._save_outcome(connection, event_id, outcome, reason)

    def read(self, connection, subject_ref, predicate_ref, *, as_of_tick=None):
        """Read-only working snapshot, with freshness derived from caller clock."""
        rule = self.properties.get((subject_ref, predicate_ref))
        if rule is None:
            raise ValueError("Unregistered Core property")
        if as_of_tick is not None and not _nonneg(as_of_tick):
            raise ValueError("as_of_tick must be a nonnegative logical tick")
        row = self._snapshot(connection, subject_ref, predicate_ref)
        if row is None:
            return {
                "subject_ref": subject_ref, "predicate_ref": predicate_ref,
                "revision": 0, "status": "unknown", "freshness": "undetermined",
                "value": None, "last_known": None, "evidence_event_ids": (),
            }
        freshness = "undetermined"
        if as_of_tick is not None and as_of_tick >= row["observed_tick"]:
            freshness = (
                "fresh"
                if as_of_tick - row["observed_tick"] <= rule.freshness_ticks
                else "stale"
            )
        return {
            "subject_ref": subject_ref,
            "predicate_ref": predicate_ref,
            "revision": row["revision"],
            "status": row["status"],
            "freshness": freshness,
            "value": _from_json(row["value_json"]),
            "last_known": _from_json(row["last_known_json"]),
            "observed_tick": row["observed_tick"],
            "last_known_tick": row["last_known_tick"],
            "evidence_event_ids": tuple(json.loads(row["evidence_json"])),
            "clock_domain": rule.clock_domain,
        }

    @staticmethod
    def history(connection, subject_ref, predicate_ref):
        rows = connection.execute(
            "SELECT revision, event_id, status, reason, observed_tick"
            " FROM core_belief_revisions"
            " WHERE subject_ref=? AND predicate_ref=? ORDER BY revision",
            (subject_ref, predicate_ref),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    @staticmethod
    def observation_outcome(connection, event_id):
        row = connection.execute(
            "SELECT outcome, reason_code FROM core_observation_outcomes"
            " WHERE event_id=?", (event_id,)
        ).fetchone()
        return None if row is None else dict(row)


__all__ = ["BeliefProjection", "PropertyRule", "SCHEMA"]
