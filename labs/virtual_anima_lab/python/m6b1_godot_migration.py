"""M6-B1: real Godot source/clock migration *review*, never executable.

Two origins remain separate. We record the old M5 virtual-source contract and
the new externally observed P6 VAL source/clock; we NEVER admit Godot samples
as an M5 virtual producer or modify Core's persisted P2 registration.

No Tool, WorldPort in Core, Task, Goal mutation, or handler can be constructed
through this module. Laboratory loopback/host identities are not authenticated.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from anima.core.door_world import (
    DOOR_SOURCE, DOOR_PRODUCER, DOOR_SUBJECT, DOOR_PREDICATE,
)
from anima.core.ingress import CONTRACT
from labs.virtual_anima_lab.python.core_port import VALDoorPort
from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from labs.virtual_anima_lab.python.contracts import (
    SOURCE as GODOT_SOURCE, PRODUCER as GODOT_PRODUCER,
    OBSERVATION_SCHEMA, validate_observation,
)
from labs.virtual_anima_lab.python.m5_binding_admission import (
    M5BindingAdmission, restricted_core,
)
from labs.virtual_anima_lab.python.m6_execution_admission import _canon, _sha

SCHEMA = "anima.memory_v1.godot_migration_m6b1/0.1"
OPERATOR = "test.operator.m6b1"
P6_PRODUCER = "adapter.val_door_port/0.1"

DDL = """
CREATE TABLE IF NOT EXISTS m6b1_mappings(
  ticket_id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL UNIQUE,
  m5_ticket_id TEXT NOT NULL UNIQUE,
  fingerprint TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  decision_json TEXT,
  status TEXT NOT NULL CHECK(status IN ('staged','approved','rejected')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK ((status='staged' AND decision_json IS NULL) OR
         (status!='staged' AND decision_json IS NOT NULL))
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha_bytes(value):
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OperatorMigrationDecision:
    ticket_id: str
    fingerprint: str
    decision_id: str
    operator_ref: str
    action: str  # APPROVE | REJECT, only via trusted lab host, NOT auth

    def __post_init__(self):
        if self.action not in ("APPROVE", "REJECT"):
            raise ValueError("M6-B1 requires explicit host APPROVE or REJECT")
        if self.operator_ref != OPERATOR:
            raise ValueError("M6-B1 unknown laboratory host operator")
        for key in ("ticket_id", "fingerprint", "decision_id"):
            value = getattr(self, key)
            if type(value) is not str or not value or len(value) > 128:
                raise ValueError("M6-B1 invalid host decision " + key)
        if len(self.fingerprint) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.fingerprint
        ):
            raise ValueError("M6-B1 invalid mapping fingerprint")


def _source_map():
    return {
        "origin": {
            "source_ref": DOOR_SOURCE,
            "producer_ref": DOOR_PRODUCER,
            "clock_domain": "lab_tick",
        },
        "godot_raw": {
            "source_ref": GODOT_SOURCE,
            "producer_ref": GODOT_PRODUCER,
            "clock_domain": "epoch_tick",
            "schema": OBSERVATION_SCHEMA,
        },
        "godot_adapter": {
            "source_ref": DOOR_SOURCE,
            "producer_ref": P6_PRODUCER,
            "clock_domain": "lab_sample",
            "contract": CONTRACT,
        },
        "same_source_authority": False,
        "clock_conversion_authorized": False,
        "target_p2_registered": False,
        "execution_permission": False,
    }


def validate_frozen_mapping(value):
    if type(value) is not dict or _canon(value) != _canon(_source_map()):
        raise ValueError("M6-B1 source/producer/clock mapping changed")
    if value["same_source_authority"] or value["clock_conversion_authorized"]:
        raise ValueError("M6-B1 cannot silently equate source authority or clocks")
    return True


class M6B1Migration:
    """A durable mapping preflight with NO executor or Goal mutation methods."""

    def __init__(self, *, root, m5: M5BindingAdmission, port: VALDoorPort):
        if not isinstance(m5, M5BindingAdmission):
            raise TypeError("M6-B1 requires M5 original source/Goal verifier")
        if not isinstance(port, VALDoorPort):
            raise TypeError("M6-B1 requires original P6 VALDoorPort")
        if m5.core.core_execution is not None or m5.core.core_autonomy is not None:
            raise ValueError("M6-B1 refuses an already executable Core")
        self.root = Path(root).resolve()
        if m5.core.data_dir.resolve() != (self.root / "runtime").resolve():
            raise ValueError("M6-B1 cannot mix Core roots")
        if port.root.resolve() != (self.root / "p6_port").resolve():
            raise ValueError("M6-B1 requires isolated P6 adapter data")
        self.m5 = m5
        self.port = port
        self.path = self.root / "m6b1_migration.db"
        with closing(self._connect()) as db:
            db.executescript(DDL)

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=10000")
        return c

    def get(self, ticket_id):
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM m6b1_mappings WHERE ticket_id=?", (ticket_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def _origin(self, m5_ticket_id):
        row = self.m5.ticket(m5_ticket_id)
        if row is None or row["status"] != "bound":
            raise ValueError("M6-B1 requires fully bound M5 ticket")
        saved = self.m5._validate(row)
        if self.m5._binding(row["origin_goal_id"]) is None:
            raise ValueError("M6-B1 missing canonical typed M5 binding")
        goal = self.m5.core.internal_state.goals.get_goal(row["origin_goal_id"])
        if goal is None or goal["status"] != "active":
            raise ValueError("M6-B1 requires active original M4 Goal")
        if self.m5.core.core_decision.tasks.list_tasks():
            raise ValueError("M6-B1 no preexisting Tasks permitted")
        return row, saved

    def _live_sample(self):
        # P6 adapter owns transport validation, Godot DTO validation, loopback
        # world-instance / epoch binding and monotonic persistent lab_sample.
        raw, seq = self.port.sense()
        if (type(seq) is not int or seq < 1
                or raw["contract"] != CONTRACT
                or raw["kind"] != "state.property"
                or raw["payload"].get("subject_ref") != DOOR_SUBJECT
                or raw["payload"].get("predicate_ref") != DOOR_PREDICATE
                or raw["payload"].get("value") != {
                    "type": "symbol", "value": "open",
                }
                or raw["payload"].get("observed_at") != {
                    "domain": "lab_sample", "value": seq,
                }):
            raise ValueError("M6-B1 Godot adapter did not observe visible open door")
        with closing(sqlite3.connect(self.port.database_file)) as db:
            detail = db.execute(
                """SELECT instance_id,lab_observation_id,epoch,world_tick,
                          world_revision,payload_json FROM sample_log
                   WHERE sample_seq=?""", (seq,),
            ).fetchone()
        if detail is None:
            raise ValueError("M6-B1 sample provenance missing")
        identity, obs_id, epoch, world_tick, revision, raw_json = detail
        original = json.loads(raw_json)
        if (original.get("schema") != OBSERVATION_SCHEMA
                or original.get("source_ref") != GODOT_SOURCE
                or original.get("producer_ref") != GODOT_PRODUCER
                or original.get("observation_id") != obs_id
                or original.get("world_revision") != revision
                or original.get("observed_at") != {
                    "epoch": epoch, "tick": world_tick,
                }
                or raw.get("occurrence_id") != f"p6:{identity}:{obs_id}"
                or self.port._binding() != (identity, epoch)):
            raise ValueError("M6-B1 raw Godot observation vs adapter sample mismatch")
        with self.port._client() as client:
            hello = client.call("hello")
        if (self.port._identity(hello["data"]) != identity
                or hello["epoch"] != epoch):
            raise ValueError("M6-B1 world identity or epoch changed mid-sample")
        # P6 adapter verified Godot's full observation against the envelope
        # in port.sense(); the log retains its validated raw provenance.
        # Do not manufacture a CoreIngress Event under the M5 producer name.
        return {
            "world_instance_id": identity,
            "epoch": epoch,
            "world_tick": world_tick,
            "world_revision": revision,
            "lab_sample": seq,
            "godot_observation_id": obs_id,
            "raw_godot_sha256": _sha(original),
            "adapter_occurrence_id": raw["occurrence_id"],
            "adapter_raw_sha256": _sha(raw),
        }

    def _validate(self, row):
        if row is None:
            raise ValueError("M6-B1 unknown migration ticket")
        saved = json.loads(row["snapshot_json"])
        if (row["ticket_id"] != "m6b1_" + row["fingerprint"]
                or _sha(saved) != row["fingerprint"]
                or row["m5_ticket_id"] != saved["m5_ticket_id"]
                or row["goal_id"] != saved["goal_id"]):
            raise ValueError("M6-B1 immutable mapping ticket changed")
        validate_frozen_mapping(saved["mapping"])
        current, m5_saved = self._origin(saved["m5_ticket_id"])
        if (current["fingerprint"] != saved["m5_fingerprint"]
                or current["origin_goal_id"] != saved["goal_id"]
                or m5_saved["m4_fingerprint"] != saved["m4_fingerprint"]):
            raise ValueError("M6-B1 historical M4/M5 origin changed")
        if self.port._binding() != (
            saved["target"]["world_instance_id"], saved["target"]["epoch"],
        ):
            raise ValueError("M6-B1 target Godot instance/epoch changed")
        initial = saved["target"]
        with closing(sqlite3.connect(self.port.database_file)) as db:
            old = db.execute(
                """SELECT instance_id,lab_observation_id,epoch,world_tick,
                          world_revision,payload_json FROM sample_log
                   WHERE sample_seq=?""",
                (initial["lab_sample"],),
            ).fetchone()
        if old is None:
            raise ValueError("M6-B1 original target sample missing")
        ident, obs_id, epoch, tick, revision, payload = old
        if (ident != initial["world_instance_id"]
                or obs_id != initial["godot_observation_id"]
                or epoch != initial["epoch"]
                or tick != initial["world_tick"]
                or revision != initial["world_revision"]
                or _sha(json.loads(payload)) != initial["raw_godot_sha256"]
                or initial["adapter_occurrence_id"] != f"p6:{ident}:{obs_id}"):
            raise ValueError("M6-B1 original raw Godot provenance changed")
        return saved

    def stage(self, m5_ticket_id):
        old, m5_saved = self._origin(m5_ticket_id)
        target = self._live_sample()
        saved = {
            "schema": SCHEMA,
            "m5_ticket_id": m5_ticket_id,
            "m5_fingerprint": old["fingerprint"],
            "m4_fingerprint": m5_saved["m4_fingerprint"],
            "goal_id": old["origin_goal_id"],
            "mapping": _source_map(), "target": target,
        }
        digest = _sha(saved)
        ticket_id = "m6b1_" + digest
        now = _now()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT OR IGNORE INTO m6b1_mappings(
                       ticket_id,goal_id,m5_ticket_id,fingerprint,snapshot_json,
                       decision_json,status,created_at,updated_at
                    ) VALUES (?,?,?,?,?,NULL,'staged',?,?)""",
                    (ticket_id, old["origin_goal_id"], m5_ticket_id,
                     digest, _canon(saved), now, now),
                )
                prev = db.execute(
                    "SELECT * FROM m6b1_mappings WHERE goal_id=?",
                    (old["origin_goal_id"],),
                ).fetchone()
                if (prev is None or prev["ticket_id"] != ticket_id
                        or prev["snapshot_json"] != _canon(saved)):
                    raise ValueError("M6-B1 cannot replace frozen reviewed migration")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.get(ticket_id)

    def decide(self, decision: OperatorMigrationDecision):
        if not isinstance(decision, OperatorMigrationDecision):
            raise TypeError("M6-B1 requires typed separate migration host decision")
        row = self.get(decision.ticket_id)
        if row is None or row["fingerprint"] != decision.fingerprint:
            raise ValueError("M6-B1 decision references unknown/different mapping")
        if row["decision_json"] is not None:
            if row["decision_json"] != _canon(asdict(decision)):
                raise ValueError("M6-B1 conflicting or altered host approval")
            return self.get(decision.ticket_id)
        self._validate(row)
        status = "approved" if decision.action == "APPROVE" else "rejected"
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cur = db.execute(
                    """UPDATE m6b1_mappings SET status=?,decision_json=?,updated_at=?
                    WHERE ticket_id=? AND status='staged' AND decision_json IS NULL""",
                    (status, _canon(asdict(decision)), _now(), decision.ticket_id),
                )
                if cur.rowcount != 1:
                    raise ValueError("M6-B1 mapping decision race or replay")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.get(decision.ticket_id)

    def revalidate(self, ticket_id):
        row = self.get(ticket_id)
        if row is None or row["status"] != "approved":
            raise ValueError("M6-B1 explicit mapping APPROVE required")
        decision = OperatorMigrationDecision(**json.loads(row["decision_json"]))
        if (decision.action != "APPROVE" or
                decision.fingerprint != row["fingerprint"]):
            raise ValueError("M6-B1 approved mapping receipt was altered")
        saved = self._validate(row)
        newer = self._live_sample()
        first = saved["target"]
        if (newer["world_instance_id"] != first["world_instance_id"]
                or newer["epoch"] != first["epoch"]
                or newer["world_revision"] != first["world_revision"]
                or newer["lab_sample"] <= first["lab_sample"]
                or newer["godot_observation_id"] == first["godot_observation_id"]):
            raise ValueError("M6-B1 world changed or stale Godot sample")
        return {
            "status": "M6B1_SOURCE_MAPPING_REVALIDATED",
            "ticket_id": ticket_id, "fingerprint": row["fingerprint"],
            "goal_id": row["goal_id"],
            "mapping": saved["mapping"],
            "world_instance_id": newer["world_instance_id"],
            "epoch": newer["epoch"],
            "world_revision": newer["world_revision"],
            "initial_lab_sample": first["lab_sample"],
            "fresh_lab_sample": newer["lab_sample"],
            "executor_installed": False, "action_authorized": False,
        }


__all__ = [
    "M6B1Migration", "OperatorMigrationDecision", "validate_frozen_mapping",
    "SCHEMA", "OPERATOR",
]
