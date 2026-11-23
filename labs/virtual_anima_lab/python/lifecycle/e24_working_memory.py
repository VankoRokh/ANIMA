"""E2.4 research: verified egocentric Raw → Core pointer → working memory.

Full sealed view bytes + sample cursor share ONE sidecar SQLite transaction.
A separate existing CoreIngress event/outbox records the digest: replay across
these stores uses Core's native ALREADY_SEEN. Nothing in this module invents
confirmed Knowledge, authorizes world effects, or replaces production Memory.

Lab limitation: sidecar and Core are NOT one atomic DB/backup. Intended for
bounded temporary E2.x cognitive evaluation, not permanent instance E4.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from anima.core.assembly import CoreAssembly
from anima.core.belief import PropertyRule
from anima.core.ingress import CONTRACT, SourceRegistration
from .contracts import WorldContractError
from .egocentric import EgocentricView, E23ObserverPort, VIEW_SCHEMA

SOURCE = "lab.sensor.anima.vision"
PRODUCER = "lab.world.lifecycle.egocentric_adapter"
SUBJECT = "lab.actor.anima"
PREDICATE = "view_digest"
CLOCK = "lab_sample"
MAX_PENDING = 64
MAX_HISTORY = 256

_SCHEMA = """
CREATE TABLE IF NOT EXISTS e24_binding (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 core_id TEXT NOT NULL,
 source_ref TEXT NOT NULL,
 producer_ref TEXT NOT NULL,
 world_id TEXT NOT NULL,
 epoch INTEGER NOT NULL CHECK(epoch > 0),
 sample_seq INTEGER NOT NULL CHECK(sample_seq > 0),
 revision INTEGER NOT NULL CHECK(revision >= 0),
 tick INTEGER NOT NULL CHECK(tick >= 0)
);
CREATE TABLE IF NOT EXISTS e24_raw (
 sample_id TEXT PRIMARY KEY,
 world_id TEXT NOT NULL,
 epoch INTEGER NOT NULL CHECK(epoch > 0),
 sample_seq INTEGER NOT NULL CHECK(sample_seq > 0),
 revision INTEGER NOT NULL CHECK(revision >= 0),
 tick INTEGER NOT NULL CHECK(tick >= 0),
 raw_json TEXT NOT NULL,
 raw_sha256 TEXT NOT NULL CHECK(length(raw_sha256)=64),
 core_event_id TEXT,
 UNIQUE(world_id,epoch,sample_seq)
);
CREATE TABLE IF NOT EXISTS e24_processed (
 sample_id TEXT PRIMARY KEY REFERENCES e24_raw(sample_id),
 core_event_id TEXT NOT NULL,
 raw_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS e24_mentions (
 sample_id TEXT NOT NULL REFERENCES e24_processed(sample_id),
 entity_ref TEXT NOT NULL,
 category TEXT NOT NULL,
 bearing_mdeg INTEGER NOT NULL,
 range_milli_cells INTEGER NOT NULL,
 PRIMARY KEY(sample_id,entity_ref)
);
CREATE TABLE IF NOT EXISTS e24_co_seen (
 sample_id TEXT NOT NULL REFERENCES e24_processed(sample_id),
 first_ref TEXT NOT NULL,
 second_ref TEXT NOT NULL,
 PRIMARY KEY(sample_id,first_ref,second_ref),
 CHECK(first_ref < second_ref)
);
CREATE INDEX IF NOT EXISTS e24_mentions_entity ON e24_mentions(entity_ref,sample_id);
CREATE INDEX IF NOT EXISTS e24_co_seen_first ON e24_co_seen(first_ref,second_ref);
"""


class E24MemoryError(RuntimeError):
    """Invalid Raw/provenance/derived memory: refuse to present unverified facts."""


def vision_source_registration() -> SourceRegistration:
    return SourceRegistration(
        source_ref=SOURCE, producer_ref=PRODUCER, allowed_kinds=("state.property",),
    )


def vision_digest_rule() -> PropertyRule:
    return PropertyRule(
        subject_ref=SUBJECT, predicate_ref=PREDICATE, value_type="string",
        clock_domain=CLOCK, allowed_sources=(SOURCE,), freshness_ticks=0,
    )


@dataclass(frozen=True, slots=True)
class E24Recorded:
    sample_id: str
    core_event_id: str
    raw_sha256: str


class E24WorkingMemory:
    """Trusted lab composition: one existing CoreAssembly, one observer-only port.

    Working model is a *derived, rebuildable* projection. 'co_observed' is an
    associative edge, NOT proof of traversability or a global topological map.
    Cached relative locations refer ONLY to the viewpoint at last observation.
    """

    def __init__(
        self, core: CoreAssembly, observer: E23ObserverPort, *,
        fault_hook: Callable[[str, str], None] | None = None,
    ):
        if type(core) is not CoreAssembly or type(observer) is not E23ObserverPort:
            raise TypeError("E2.4 requires existing CoreAssembly and E23ObserverPort")
        if core.core_events is None or core.core_events.ingress.beliefs is None:
            raise E24MemoryError("E2.4 requires registered CoreIngress and Belief projection")
        if core.core_execution is not None or core.core_autonomy is not None:
            raise E24MemoryError("E2.4 does not authorize world effects or Core autonomy")
        if core.runtime.core_events is not core.core_events or core.runtime.identity is not core.identity:
            raise E24MemoryError("Core composition identity mismatch")
        if core.core_events.ingress.sources.get(SOURCE) != vision_source_registration():
            raise E24MemoryError("vision source must be registered exactly")
        if core.core_events.ingress.beliefs.properties.get(
            (SUBJECT, PREDICATE)
        ) != vision_digest_rule():
            raise E24MemoryError("vision digest property rule required")
        if fault_hook is not None and not callable(fault_hook):
            raise TypeError("fault_hook must be callable")
        self._core = core
        self._observer = observer
        self._fault_hook = fault_hook
        self._file = Path(core.data_dir) / "e24_working_memory.db"
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def _connect(self):
        db = sqlite3.connect(self._file, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _fault(self, stage, sample):
        if self._fault_hook is not None:
            self._fault_hook(stage, sample)

    @staticmethod
    def _json(data) -> str:
        return json.dumps(data, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)

    @staticmethod
    def _digest(original) -> str:
        return hashlib.sha256(original.encode("utf-8")).hexdigest()

    def _binding(self):
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM e24_binding WHERE singleton=1").fetchone()
        if row is None:
            return None
        if (row["core_id"] != self._core.identity.get()["instance_id"]
                or row["source_ref"] != SOURCE or row["producer_ref"] != PRODUCER):
            raise E24MemoryError("stored Core identity/source/provenance mismatch")
        return dict(row)

    @staticmethod
    def _event(snap, digest):
        sample_clock = {"domain": CLOCK, "value": snap["sample_seq"]}
        return {
            "contract": CONTRACT,
            "occurrence_id": "e24:" + snap["sample_id"],
            "occurrence_version": 1, "kind": "state.property",
            "payload": {
                "subject_ref": SUBJECT, "predicate_ref": PREDICATE,
                "observed_at": sample_clock,
                "temporal_scope": {"kind": "instant", "at": dict(sample_clock)},
                "source_revision": snap["sample_seq"],
                "value": {"type": "string", "value": digest},
            },
        }

    def _verify_row(self, row, binding):
        original = row["raw_json"]
        digest = self._digest(original)
        if digest != row["raw_sha256"]:
            raise E24MemoryError("full Raw snapshot SHA-256 mismatch")
        try:
            view = EgocentricView(json.loads(original))
        except (WorldContractError, ValueError, TypeError) as exc:
            raise E24MemoryError("captured Raw fails exact vision contract") from exc
        snap = view.as_dict()
        if (view.canonical_json != original or snap["sample_id"] != row["sample_id"]
                or snap["world_instance_id"] != row["world_id"]
                or snap["epoch"] != row["epoch"]
                or snap["sample_seq"] != row["sample_seq"]
                or snap["revision"] != row["revision"] or snap["tick"] != row["tick"]
                or snap["source_ref"] != SOURCE
                or snap["world_instance_id"] != binding["world_id"]
                or snap["epoch"] != binding["epoch"]
                or snap["sample_seq"] > binding["sample_seq"]
                or snap["revision"] > binding["revision"]
                or snap["tick"] > binding["tick"]):
            raise E24MemoryError("Raw, cursor, world or source disagree")
        return snap, digest

    def _verify_core(self, event_id, snap, digest, *, require_forwarded=False):
        claimed = self._event(snap, digest)
        existing = self._core.core_events.ingress.get_event(event_id)
        if (existing is None or existing["source_ref"] != SOURCE
                or existing["producer_ref"] != PRODUCER
                or existing["occurrence_id"] != claimed["occurrence_id"]
                or existing["occurrence_version"] != 1
                or existing["kind"] != "state.property"
                or existing["payload"] != claimed["payload"]):
            raise E24MemoryError("Core event does not attest to exact Raw pointer")
        outcome = self._core.core_events.ingress.observation_outcome(event_id)
        if outcome is None or outcome["outcome"].startswith("REJECTED_"):
            raise E24MemoryError("Core Belief refused vision source")
        if require_forwarded:
            receipt = self._core.core_events.ingress.dispatch_receipt(event_id)
            if receipt is None or receipt["disposition"] != "forwarded":
                raise E24MemoryError("Core pointer has no forwarded receipt")

    def _capture(self, view: EgocentricView):
        snap = view.as_dict()
        if snap["source_ref"] != SOURCE or snap["schema"] != VIEW_SCHEMA:
            raise E24MemoryError("incorrect sensor source/version")
        core_id = self._core.identity.get()["instance_id"]
        original = view.canonical_json
        digest = self._digest(original)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM e24_binding WHERE singleton=1").fetchone()
                binding = (core_id, SOURCE, PRODUCER, snap["world_instance_id"], snap["epoch"])
                clocks = (snap["sample_seq"], snap["revision"], snap["tick"])
                if row is None:
                    db.execute(
                        "INSERT INTO e24_binding VALUES(1,?,?,?,?,?,?,?,?)",
                        binding + clocks,
                    )
                else:
                    if tuple(row[k] for k in (
                        "core_id", "source_ref", "producer_ref", "world_id", "epoch",
                    )) != binding:
                        raise E24MemoryError("world/epoch/Core changed; explicit new instance required")
                    if (clocks[0] <= row["sample_seq"]
                            or clocks[1] < row["revision"] or clocks[2] < row["tick"]):
                        raise E24MemoryError("observation cursor/revision/tick regressed")
                    db.execute(
                        "UPDATE e24_binding SET sample_seq=?,revision=?,tick=? WHERE singleton=1",
                        clocks,
                    )
                count = db.execute("SELECT COUNT(*) AS n FROM e24_raw").fetchone()["n"]
                if count >= MAX_HISTORY:
                    raise E24MemoryError("bounded E2.4 lab history exhausted")
                db.execute(
                    "INSERT INTO e24_raw(sample_id,world_id,epoch,sample_seq,"
                    "revision,tick,raw_json,raw_sha256,core_event_id)"
                    " VALUES (?,?,?,?,?,?,?,?,NULL)",
                    (snap["sample_id"], snap["world_instance_id"], snap["epoch"],
                     *clocks, original, digest),
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        self._fault("after_raw_commit", snap["sample_id"])
        return snap["sample_id"]

    def _project(self, row, snap, digest):
        """Idempotent materialization; all projected facts derive from verified Raw."""
        sample = snap["sample_id"]
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                check = db.execute(
                    "SELECT core_event_id,raw_sha256 FROM e24_processed WHERE sample_id=?",
                    (sample,),
                ).fetchone()
                if check is not None:
                    if (check["core_event_id"] != row["core_event_id"]
                            or check["raw_sha256"] != digest):
                        raise E24MemoryError("derived memory conflicts with verified Raw")
                    db.commit()
                    return
                db.execute(
                    "INSERT INTO e24_processed(sample_id,core_event_id,raw_sha256)"
                    " VALUES (?,?,?)", (sample, row["core_event_id"], digest),
                )
                names = []
                for reading in snap["readings"]:
                    name = reading["entity_ref"]
                    names.append(name)
                    db.execute(
                        "INSERT INTO e24_mentions(sample_id,entity_ref,category,"
                        "bearing_mdeg,range_milli_cells) VALUES(?,?,?,?,?)",
                        (sample, name, reading["category"],
                         reading["bearing_mdeg"], reading["range_milli_cells"]),
                    )
                for i, a in enumerate(sorted(names)):
                    for b in sorted(names)[i + 1:]:
                        db.execute(
                            "INSERT INTO e24_co_seen(sample_id,first_ref,second_ref) "
                            "VALUES(?,?,?)", (sample, a, b),
                        )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        self._fault("after_projection_commit", sample)

    def recover(self, *, max_samples: int = MAX_PENDING) -> tuple[str, ...]:
        """Finish Core admission + outbox + working projection from exact saved Raw."""
        if type(max_samples) is not int or not 1 <= max_samples <= MAX_PENDING:
            raise ValueError("bounded recovery batch required")
        binding = self._binding()
        if binding is None:
            return ()
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM e24_raw ORDER BY sample_seq LIMIT ?", (MAX_HISTORY,),
            ).fetchall()
        # Verify every bounded lab record before further admissions or public read.
        for row in rows:
            snap, digest = self._verify_row(row, binding)
            if row["core_event_id"]:
                self._verify_core(row["core_event_id"], snap, digest)
        processed = []
        for row in rows:
            if row["core_event_id"] is not None:
                continue
            if len(processed) >= max_samples:
                break
            snap, digest = self._verify_row(row, binding)
            result = self._core.core_events.ingress.admit(
                self._event(snap, digest), source_ref=SOURCE,
            )
            if result.status not in ("ACCEPTED", "ALREADY_SEEN") or not result.event_id:
                raise E24MemoryError("Core rejected saved Raw: " + result.status)
            self._verify_core(result.event_id, snap, digest)
            self._fault("after_core_admit", snap["sample_id"])
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    current = db.execute(
                        "SELECT raw_sha256,core_event_id FROM e24_raw WHERE sample_id=?",
                        (snap["sample_id"],),
                    ).fetchone()
                    if (current is None or current["raw_sha256"] != digest
                            or current["core_event_id"] not in (None, result.event_id)):
                        raise E24MemoryError("Raw changed during Core admission")
                    db.execute(
                        "UPDATE e24_raw SET core_event_id=? WHERE sample_id=?",
                        (result.event_id, snap["sample_id"]),
                    )
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
            self._fault("after_core_link", snap["sample_id"])
            processed.append(snap["sample_id"])
        self._core.event_processing.recover()
        self._core.core_events.drain(max_events=MAX_PENDING)
        # Work only on rows with durable Core admission and dispatch.
        with closing(self._connect()) as db:
            linked = db.execute(
                "SELECT r.* FROM e24_raw r LEFT JOIN e24_processed p ON "
                "p.sample_id=r.sample_id WHERE r.core_event_id IS NOT NULL "
                "AND p.sample_id IS NULL ORDER BY r.sample_seq LIMIT ?",
                (max_samples,),
            ).fetchall()
        for row in linked:
            snap, digest = self._verify_row(row, binding)
            self._verify_core(row["core_event_id"], snap, digest, require_forwarded=True)
            self._project(row, snap, digest)
        return tuple(processed)

    def observe_and_record(self) -> E24Recorded:
        self.recover()
        view = self._observer.observe()
        sample_id = self._capture(view)
        self.recover()
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM e24_raw WHERE sample_id=?", (sample_id,)).fetchone()
            derived = db.execute(
                "SELECT * FROM e24_processed WHERE sample_id=?", (sample_id,),
            ).fetchone()
        if row is None or derived is None or row["core_event_id"] is None:
            raise E24MemoryError("view not yet durably projected")
        snap, digest = self._verify_row(row, self._binding())
        self._verify_core(row["core_event_id"], snap, digest, require_forwarded=True)
        if derived["core_event_id"] != row["core_event_id"] or derived["raw_sha256"] != digest:
            raise E24MemoryError("derived memory not bound to Core")
        return E24Recorded(sample_id, row["core_event_id"], digest)

    def world_model(self, *, memory_enabled: bool = True) -> dict:
        """Working retrieval. No false 'absent' claims from omitted view entities."""
        if type(memory_enabled) is not bool:
            raise TypeError("memory_enabled must be bool")
        binding = self._binding()
        if binding is None:
            raise E24MemoryError("no captured world binding")
        with closing(self._connect()) as db:
            raw = db.execute("SELECT * FROM e24_raw ORDER BY sample_seq").fetchall()
            processed = db.execute("SELECT * FROM e24_processed").fetchall()
        if len(raw) != len(processed) or not raw:
            raise E24MemoryError("unprocessed Raw exists: working model not available")
        # Check all evidence before exposing working projections.
        seen = {r["sample_id"]: r for r in processed}
        snapshots = []
        for row in raw:
            snap, digest = self._verify_row(row, binding)
            proof = seen.get(row["sample_id"])
            if (proof is None or proof["core_event_id"] != row["core_event_id"]
                    or proof["raw_sha256"] != digest):
                raise E24MemoryError("missing/forged derived evidence")
            self._verify_core(row["core_event_id"], snap, digest, require_forwarded=True)
            snapshots.append((snap, row["core_event_id"], digest))
        latest, _, _ = snapshots[-1]
        selected = snapshots if memory_enabled else snapshots[-1:]
        entities: dict[str, dict] = {}
        edges: dict[tuple[str, str], dict] = {}
        for snap, event_id, digest in selected:
            labels = []
            for reading in snap["readings"]:
                name = reading["entity_ref"]
                labels.append(name)
                old = entities.get(name)
                entities[name] = {
                    "entity_ref": name, "category": reading["category"],
                    "last_seen_sample": snap["sample_id"],
                    "last_seen_event_id": event_id, "last_seen_raw_sha256": digest,
                    "last_seen_view": {
                        "bearing_mdeg": reading["bearing_mdeg"],
                        "range_milli_cells": reading["range_milli_cells"],
                    },
                    "evidence_count": 1 if old is None else old["evidence_count"] + 1,
                }
            names = sorted(labels)
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    key = (a, b)
                    existing = edges.get(key)
                    edges[key] = {
                        "kind": "co_observed", "first_ref": a, "second_ref": b,
                        "evidence_count": 1 if existing is None else existing["evidence_count"] + 1,
                        "last_sample_id": snap["sample_id"], "last_event_id": event_id,
                    }
        present = {reading["entity_ref"] for reading in latest["readings"]}
        for entity in entities.values():
            entity["current_observation"] = (
                "observed" if entity["entity_ref"] in present else "not_observed"
            )
            # Past bearings are not automatically usable for CURRENT navigation.
            entity["current_relative_geometry_verified"] = (
                entity["current_observation"] == "observed"
            )
        return {
            "schema": "anima.lab.working_world_model/0.1",
            "world_instance_id": latest["world_instance_id"], "epoch": latest["epoch"],
            "latest_sample_id": latest["sample_id"], "latest_sample_seq": latest["sample_seq"],
            "coverage": latest["coverage"], "memory_enabled": memory_enabled,
            "historical_samples": len(selected),
            "entities": [entities[x] for x in sorted(entities)],
            "relations": [edges[x] for x in sorted(edges)],
            "limitations": {
                "co_observed_is_not_traversable": True,
                "not_observed_does_not_mean_absent": True,
                "previous_bearings_may_be_stale": True,
                "full_raw_is_in_sidecar_not_core": True,
            },
        }

    def raw_evidence(self, sample_id: str) -> EgocentricView:
        """Read verified original view bytes, never an unproven materialized claim."""
        if type(sample_id) is not str:
            raise TypeError("sample_id must be string")
        binding = self._binding()
        if binding is None:
            raise E24MemoryError("no trusted source binding")
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM e24_raw WHERE sample_id=?", (sample_id,)).fetchone()
            proof = db.execute(
                "SELECT * FROM e24_processed WHERE sample_id=?", (sample_id,),
            ).fetchone()
        if row is None or proof is None or row["core_event_id"] is None:
            raise E24MemoryError("Raw evidence is missing or unprocessed")
        snap, digest = self._verify_row(row, binding)
        if proof["core_event_id"] != row["core_event_id"] or proof["raw_sha256"] != digest:
            raise E24MemoryError("Raw proof mismatch")
        self._verify_core(row["core_event_id"], snap, digest, require_forwarded=True)
        return EgocentricView(snap)


__all__ = [
    "SOURCE", "PRODUCER", "SUBJECT", "PREDICATE", "E24WorkingMemory",
    "E24MemoryError", "E24Recorded", "vision_source_registration",
    "vision_digest_rule",
]
