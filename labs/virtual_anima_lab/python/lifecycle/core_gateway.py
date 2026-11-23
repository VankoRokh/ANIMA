"""E2.1 laboratory Core-bound *observation-only* lifecycle world gateway.

This deliberately does NOT implement an executor, scheduler, tool handler,
Goal admission, Raw ingress or FAST access. Core retains its existing Stage 6
execution authority. The gateway pins source, Core identity and world epoch,
but producer names and a self-declared TCP role are NOT authentication.

Security boundary: code consuming this API gets only immutable DTOs. It is
NOT a sandbox for arbitrary Python code with network/socket permissions.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

from anima.core.assembly import CoreAssembly
from anima.core.ingress import SourceRegistration
from labs.virtual_anima_lab.python.lab_client import (
    LabClient, LabProtocolError, LabRejected, PROTOCOL_V2,
)
from .contracts import WorldContractError, WorldObservation

SOURCE_REF = "lab.sensor.anima.proximity"
PRODUCER_REF = "lab.world.lifecycle.adapter"
WORLD_VERSION = "lifecycle-grid/0.1"
_CAPABILITIES = ("observe",)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS e21_world_binding (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    core_instance_id TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    producer_ref TEXT NOT NULL,
    world_instance_id TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK(epoch > 0),
    last_sample_seq INTEGER NOT NULL CHECK(last_sample_seq > 0),
    last_revision INTEGER NOT NULL CHECK(last_revision >= 0),
    last_tick INTEGER NOT NULL CHECK(last_tick >= 0)
);
"""

# E2.2: optional additive capture journal. Full original sensor snapshots are
# committed in the SAME SQLite transaction as the monotonic sample cursor.
# This table is NOT a competing Core event log or Belief/Knowledge authority.
_CAPTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS e22_raw_capture (
    sample_id TEXT PRIMARY KEY,
    world_instance_id TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK(epoch > 0),
    sample_seq INTEGER NOT NULL CHECK(sample_seq > 0),
    revision INTEGER NOT NULL CHECK(revision >= 0),
    tick INTEGER NOT NULL CHECK(tick >= 0),
    snapshot_json TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    event_id TEXT,
    UNIQUE(world_instance_id,epoch,sample_seq),
    CHECK (length(snapshot_sha256) = 64)
);
"""


class WorldBoundaryError(RuntimeError):
    """Fail closed. Do not retry effects or silently rebind another world."""


def lifecycle_source_registration() -> SourceRegistration:
    """Registration intent; it does not authenticate a remote sensor."""
    return SourceRegistration(
        source_ref=SOURCE_REF,
        producer_ref=PRODUCER_REF,
        allowed_kinds=("state.property", "sensor.unavailable"),
    )


class CoreBoundObservationGateway:
    """Read-only adapter owned by one registered Core assembly.

    No public call to act, operation_status, operator commands or a raw client.
    The source identity is fixed at composition, not copied from the response.
    An observed incarnation/epoch is persistently pinned and never auto-reset.
    """

    __slots__ = ("_core", "_port", "_timeout", "_client_factory", "_dbfile", "_observer_key", "_capture_raw")

    def __init__(
        self, core: CoreAssembly, *, observer_key: str,
        port: int = 46029, timeout: float = 3.0,
        client_factory: Callable = LabClient, capture_raw: bool = False,
    ) -> None:
        if type(core) is not CoreAssembly:
            raise TypeError("E2.1 requires a CoreAssembly from the existing composition root")
        if (core.runtime.identity is not core.identity
                or core.runtime.core_events is not core.core_events
                or core.runtime.core_decision is not core.core_decision
                or core.runtime.core_execution is not core.core_execution):
            raise WorldBoundaryError("Core assembly/runtime identity mismatch")
        if core.core_execution is not None or core.core_autonomy is not None:
            raise WorldBoundaryError("E2.1 cannot create a parallel execution authority")
        if core.core_events is None:
            raise WorldBoundaryError("E2.1 requires a registered CoreIngress")
        registration = core.core_events.ingress.sources.get(SOURCE_REF)
        if (type(registration) is not SourceRegistration
                or registration != lifecycle_source_registration()):
            raise WorldBoundaryError("Lifecycle sensor registration must be explicit and exact")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("invalid loopback port")
        if type(timeout) not in (float, int) or type(timeout) is bool or timeout <= 0:
            raise ValueError("invalid timeout")
        if (type(observer_key) is not str or
                re.fullmatch(r"[A-Za-z0-9_-]{32,128}", observer_key) is None):
            raise ValueError("guarded E2.1 requires a strong observer-only bearer key")
        if type(capture_raw) is not bool:
            raise TypeError("capture_raw must be boolean")
        if not callable(client_factory):
            raise TypeError("client factory must be callable")
        self._core = core
        self._port = port
        self._timeout = timeout
        self._observer_key = observer_key
        self._capture_raw = capture_raw
        # Only the trusted composition root may provide an alternate factory,
        # e.g. an in-process test double. This is not a plugin extension point.
        self._client_factory = client_factory
        self._dbfile = Path(core.data_dir).resolve() / "e21_world_binding.db"
        self._dbfile.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)
            if capture_raw:
                db.executescript(_CAPTURE_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._dbfile, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _client(self):
        # Never returns to a model, FAST, a plugin or the observation caller.
        return self._client_factory(
            self._port, role="agent", protocol=PROTOCOL_V2, timeout=self._timeout,
        )

    @staticmethod
    def _validate_hello(data: dict) -> tuple[str, int]:
        if (type(data) is not dict
                or set(data) != {
                    "ready", "world_version", "world_instance_id",
                    "epoch", "capabilities", "auth_mode",
                }
                or data["ready"] is not True
                or data["auth_mode"] != "guarded"
                or data["world_version"] != WORLD_VERSION
                or type(data["world_instance_id"]) is not str
                or re.fullmatch(r"[a-f0-9]{32}", data["world_instance_id"]) is None
                or type(data["epoch"]) is not int or data["epoch"] < 1
                or type(data["capabilities"]) is not list
                or data["capabilities"] != list(_CAPABILITIES)):
            raise WorldBoundaryError(
                "untrusted/mismatched lifecycle world handshake or capabilities"
            )
        return data["world_instance_id"], data["epoch"]

    @staticmethod
    def _validate_sample(
        observed: WorldObservation, hello: tuple[str, int], envelope: dict,
    ) -> dict:
        data = observed.as_dict()
        if (data["world_instance_id"] != hello[0]
                or data["epoch"] != hello[1]
                or data["source_ref"] != SOURCE_REF
                or data["observer_ref"] != "lab.actor.anima"
                or type(envelope) is not dict
                or envelope.get("epoch") != data["epoch"]
                or envelope.get("revision") != data["revision"]
                or envelope.get("tick") != data["tick"]):
            raise WorldBoundaryError("world handshake, envelope and sensor disagree")
        return data

    def _pin(self, data: dict) -> None:
        core_id = self._core.identity.get()["instance_id"]
        if type(core_id) is not str or not core_id:
            raise WorldBoundaryError("Core identity invalid")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT core_instance_id,source_ref,producer_ref,"
                    " world_instance_id,epoch,last_sample_seq,last_revision,last_tick"
                    " FROM e21_world_binding WHERE singleton=1"
                ).fetchone()
                fixed = (core_id, SOURCE_REF, PRODUCER_REF,
                         data["world_instance_id"], data["epoch"])
                observed = (data["sample_seq"], data["revision"], data["tick"])
                if row is None:
                    db.execute(
                        "INSERT INTO e21_world_binding VALUES (1,?,?,?,?,?,?,?,?)",
                        fixed + observed,
                    )
                else:
                    if tuple(row[:5]) != fixed:
                        raise WorldBoundaryError(
                            "Core/source/world binding changed; explicit new instance required"
                        )
                    if (observed[0] <= row[5] or observed[1] < row[6]
                            or observed[2] < row[7]):
                        raise WorldBoundaryError(
                            "observation sequence/revision/tick regressed or replayed"
                        )
                    db.execute(
                        "UPDATE e21_world_binding SET "
                        "last_sample_seq=?,last_revision=?,last_tick=? WHERE singleton=1",
                        observed,
                    )
                if self._capture_raw:
                    # Canonical bytes are durable BEFORE sample cursor commit.
                    # Any failure aborts both records, so no observation can
                    # be consumed without its complete original Raw snapshot.
                    snapshot = json.dumps(
                        data, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False,
                    )
                    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
                    db.execute(
                        "INSERT INTO e22_raw_capture("
                        "sample_id,world_instance_id,epoch,sample_seq,revision,tick,"
                        "snapshot_json,snapshot_sha256,event_id"
                        ") VALUES (?,?,?,?,?,?,?,?,NULL)",
                        (
                            data["sample_id"], data["world_instance_id"],
                            data["epoch"], data["sample_seq"],
                            data["revision"], data["tick"],
                            snapshot, digest,
                        ),
                    )
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def observe(self) -> WorldObservation:
        """Return only a sealed local observation; never creates WorldAction.

        With capture_raw=True, full evidence and the cursor commit together.
        That pending snapshot is not a Core Event until the E2.2 outbox
        service admits it through the existing CoreIngress/EventLog.
        """
        try:
            with self._client() as client:
                hello = self._validate_hello(client.call("hello", auth=self._observer_key)["data"])
                response = client.call("observe", auth=self._observer_key)
            observed = WorldObservation(response["data"])
            self._pin(self._validate_sample(observed, hello, response))
            return observed
        except (OSError, TimeoutError, ConnectionError,
                LabProtocolError, LabRejected, WorldContractError) as error:
            raise WorldBoundaryError("world observation rejected; no state admitted") from error

    def binding_snapshot(self) -> dict | None:
        """Return a COPY of the pinned identity and clock, never a socket."""
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT world_instance_id,epoch,last_sample_seq,last_revision,last_tick"
                " FROM e21_world_binding WHERE singleton=1"
            ).fetchone()
        if row is None:
            return None
        return dict(zip(
            ("world_instance_id", "epoch", "sample_seq", "revision", "tick"), row
        ))


__all__ = [
    "CoreBoundObservationGateway", "WorldBoundaryError",
    "lifecycle_source_registration", "SOURCE_REF", "PRODUCER_REF",
]
