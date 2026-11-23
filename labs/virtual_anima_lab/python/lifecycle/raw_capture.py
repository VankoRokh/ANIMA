"""E2.2 laboratory Raw capture → existing CoreIngress/Dispatcher, no second Core.

The exact WorldObservation bytes are captured atomically with E2.1's cursor
before this service sees them. A typed Core Raw *reference* event stores the
SHA-256 pointer and sample identity; the full immutable sensor snapshot remains
in the colocated capture SQLite. It is NOT claimed to be a standalone full
WorldObservation inside CoreIngress or EventLog.

Crash cuts: snapshot/pin commit → CoreIngress accept → capture link →
CoreEventDispatcher durable legacy projection. Every boundary is replayable.
No action, Goal, Task, executor, FAST, Knowledge or unregistered source.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Callable

from anima.core.assembly import CoreAssembly
from anima.core.belief import PropertyRule
from anima.core.ingress import CONTRACT
from .contracts import WorldObservation
from .core_gateway import (
    CoreBoundObservationGateway, PRODUCER_REF, SOURCE_REF,
    WorldBoundaryError, lifecycle_source_registration,
)

SUBJECT = "lab.actor.anima"
PREDICATE = "snapshot_digest"
CLOCK = "lab_sample"
MAX_PENDING = 64


class RawCaptureError(WorldBoundaryError):
    """A capture is pending or inconsistent: fail closed, never invent history."""


def lifecycle_snapshot_rule() -> PropertyRule:
    return PropertyRule(
        subject_ref=SUBJECT,
        predicate_ref=PREDICATE,
        value_type="string",
        clock_domain=CLOCK,
        allowed_sources=(SOURCE_REF,),
        freshness_ticks=0,
    )


@dataclass(frozen=True, slots=True)
class CapturedObservation:
    observation: WorldObservation
    core_event_id: str
    raw_digest: str
    core_dispatch_receipt: str


class E22RawCaptureService:
    """A lab host that owns the gateway and *existing* Core assembly.

    The CoreIngress/core_state.db and CoreDispatcher/EventLog keep their normal
    idempotent ledgers. The e22 capture table stores original sensor bytes and
    stable links. An accepted Core reference event cannot replace those bytes.
    """

    __slots__ = ("_core", "_gateway", "_fault_hook")

    def __init__(
        self,
        core: CoreAssembly,
        gateway: CoreBoundObservationGateway,
        *,
        fault_hook: Callable[[str, str], None] | None = None,
    ):
        if type(core) is not CoreAssembly or type(gateway) is not CoreBoundObservationGateway:
            raise TypeError("E2.2 requires exact CoreAssembly and CoreBoundObservationGateway")
        if gateway._core is not core or not gateway._capture_raw:
            raise RawCaptureError("E2.2 requires same Core and atomic full-Raw capture mode")
        if core.core_events is None or core.core_events.ingress.sources.get(SOURCE_REF) != lifecycle_source_registration():
            raise RawCaptureError("E2.2 requires exact trusted Core source registration")
        if core.core_events.ingress.beliefs is None:
            raise RawCaptureError("E2.2 requires Core Belief projection and dispatcher")
        property_rule = core.core_events.ingress.beliefs.properties.get((SUBJECT, PREDICATE))
        if property_rule != lifecycle_snapshot_rule():
            raise RawCaptureError("E2.2 requires exact snapshot digest property rule")
        if fault_hook is not None and not callable(fault_hook):
            raise TypeError("fault_hook must be callable")
        self._core = core
        self._gateway = gateway
        self._fault_hook = fault_hook

    def _fault(self, stage: str, sample_id: str):
        if self._fault_hook is not None:
            self._fault_hook(stage, sample_id)

    def _db(self):
        db = sqlite3.connect(self._gateway._dbfile, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _occurrence(snapshot: dict) -> str:
        # Bound by CoreIngress 128-character occurrence_id length. Every
        # sample and world epoch receives exactly one stable event identity.
        return "e22:" + snapshot["sample_id"]

    @staticmethod
    def _raw_event(snapshot: dict, digest: str) -> dict:
        clock = {"domain": CLOCK, "value": snapshot["sample_seq"]}
        return {
            "contract": CONTRACT,
            "occurrence_id": E22RawCaptureService._occurrence(snapshot),
            "occurrence_version": 1,
            "kind": "state.property",
            "payload": {
                "subject_ref": SUBJECT,
                "predicate_ref": PREDICATE,
                "observed_at": clock,
                "temporal_scope": {"kind": "instant", "at": dict(clock)},
                "source_revision": snapshot["sample_seq"],
                "value": {"type": "string", "value": digest},
            },
        }

    @staticmethod
    def _validate_capture(row: sqlite3.Row, binding: dict) -> tuple[dict, str]:
        original = row["snapshot_json"]
        calculated = hashlib.sha256(original.encode("utf-8")).hexdigest()
        if calculated != row["snapshot_sha256"]:
            raise RawCaptureError("captured Raw bytes do not match stored digest")
        observation = WorldObservation(json.loads(original))
        snap = observation.as_dict()
        if (observation.canonical_json != original
                or snap["sample_id"] != row["sample_id"]
                or snap["world_instance_id"] != row["world_instance_id"]
                or snap["epoch"] != row["epoch"]
                or snap["sample_seq"] != row["sample_seq"]
                or snap["revision"] != row["revision"]
                or snap["tick"] != row["tick"]
                or snap["source_ref"] != SOURCE_REF
                or snap["observer_ref"] != SUBJECT
                or snap["world_instance_id"] != binding["world_instance_id"]
                or snap["epoch"] != binding["epoch"]
                or snap["sample_seq"] > binding["sample_seq"]
                or snap["tick"] > binding["tick"]
                or snap["revision"] > binding["revision"]):
            raise RawCaptureError("captured Raw provenance conflicts with pinned Core/world")
        return snap, calculated

    def _verify_core(self, event_id: str, event: dict, digest: str):
        existing = self._core.core_events.ingress.get_event(event_id)
        if (existing is None
                or existing["source_ref"] != SOURCE_REF
                or existing["producer_ref"] != PRODUCER_REF
                or existing["occurrence_id"] != event["occurrence_id"]
                or existing["occurrence_version"] != 1
                or existing["kind"] != "state.property"
                or existing["payload"] != event["payload"]
                or existing["payload"]["value"]["value"] != digest):
            raise RawCaptureError("Core event does not attest to captured Raw digest")
        outcome = self._core.core_events.ingress.observation_outcome(event_id)
        if (outcome is None
                or outcome["outcome"].startswith("REJECTED_")
                or outcome["outcome"] == "HISTORY_ONLY"):
            raise RawCaptureError("Core Belief rejected captured sensor provenance")

    def recover(self, *, max_samples: int = MAX_PENDING) -> tuple[str, ...]:
        """Replay each pending capture into Core, then existing Core dispatcher.

        A crash after Core commit but before sidecar link returns ALREADY_SEEN
        with the same event_id; a crash after link but before dispatcher is
        recovered by Core's native durable outbox. No new Godot observation
        or effect is issued here.
        """
        if type(max_samples) is not int or not 1 <= max_samples <= MAX_PENDING:
            raise ValueError("bounded positive recovery batch required")
        binding = self._gateway.binding_snapshot()
        if binding is None:
            return ()
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT * FROM e22_raw_capture WHERE event_id IS NULL"
                " ORDER BY sample_seq LIMIT ?",
                (max_samples,),
            ).fetchall()
        linked_ids = []
        for row in rows:
            snap, digest = self._validate_capture(row, binding)
            event = self._raw_event(snap, digest)
            result = self._core.core_events.ingress.admit(event, source_ref=SOURCE_REF)
            if result.status not in {"ACCEPTED", "ALREADY_SEEN"} or not result.event_id:
                raise RawCaptureError("Core refused canonical Raw reference: " + result.status)
            self._verify_core(result.event_id, event, digest)
            self._fault("after_core_admit", row["sample_id"])
            with closing(self._db()) as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    existing = db.execute(
                        "SELECT snapshot_sha256,event_id FROM e22_raw_capture"
                        " WHERE sample_id=?", (row["sample_id"],),
                    ).fetchone()
                    if existing is None or existing["snapshot_sha256"] != digest:
                        raise RawCaptureError("Raw changed during ingress")
                    if existing["event_id"] not in (None, result.event_id):
                        raise RawCaptureError("Raw already linked to conflicting Core event")
                    db.execute(
                        "UPDATE e22_raw_capture SET event_id=? WHERE sample_id=?",
                        (result.event_id, row["sample_id"]),
                    )
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
            linked_ids.append(result.event_id)
            self._fault("after_capture_link", row["sample_id"])
        # CoreEventDispatcher is the ONLY path to legacy EventLog/processing.
        self._core.event_processing.recover()
        self._core.core_events.drain(max_events=MAX_PENDING)
        return tuple(linked_ids)

    def observe_and_record(self) -> CapturedObservation:
        """Never expose newly sensed data unless Core dispatch is durable."""
        self.recover()
        observation = self._gateway.observe()  # atomic snapshot+cursor
        sample_id = observation.sample_id
        self._fault("after_snapshot_commit", sample_id)
        self.recover()
        with closing(self._db()) as db:
            row = db.execute(
                "SELECT * FROM e22_raw_capture WHERE sample_id=?", (sample_id,),
            ).fetchone()
        if row is None or row["event_id"] is None:
            raise RawCaptureError("Raw still pending; not exposing observation")
        snap, digest = self._validate_capture(
            row, self._gateway.binding_snapshot(),
        )
        event = self._raw_event(snap, digest)
        self._verify_core(row["event_id"], event, digest)
        receipt = self._core.core_events.ingress.dispatch_receipt(row["event_id"])
        if receipt is None or receipt["disposition"] != "forwarded":
            raise RawCaptureError("Raw not yet durably dispatched to EventLog")
        return CapturedObservation(
            observation=observation, core_event_id=row["event_id"],
            raw_digest=digest, core_dispatch_receipt=receipt["disposition"],
        )

    def capture_snapshot(self, sample_id: str) -> WorldObservation:
        """Inspect exact locally persisted Raw bytes, never a model assertion."""
        if type(sample_id) is not str:
            raise TypeError("sample_id must be string")
        with closing(self._db()) as db:
            row = db.execute(
                "SELECT * FROM e22_raw_capture WHERE sample_id=?", (sample_id,),
            ).fetchone()
        if row is None:
            raise RawCaptureError("unknown Raw sensor sample")
        snap, _digest = self._validate_capture(
            row, self._gateway.binding_snapshot(),
        )
        return WorldObservation(snap)


__all__ = [
    "E22RawCaptureService", "RawCaptureError", "CapturedObservation",
    "lifecycle_snapshot_rule", "SUBJECT", "PREDICATE", "CLOCK",
]
