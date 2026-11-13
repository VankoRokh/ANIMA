"""M5 experimental second approval -> exact typed Core binding, with NO executor.

CAUTION: This laboratory binding is latent capability. A future runtime that
installs CoreDoorExecution against the same Core DB could act. Never deploy the
M5 DB with an execution-capable assembler without a separate M6 authorization.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from anima.core.assembly import CoreAssembly, build_core
from anima.core.belief import PropertyRule
from anima.core.door_world import (
    DOOR_PREDICATE, DOOR_PRODUCER, DOOR_SOURCE, DOOR_SUBJECT,
    DOOR_TOOL, DOOR_VERSION,
)
from anima.core.goal_decision import GoalCriterion
from anima.core.ingress import SourceRegistration
from anima.execution.contracts import ActionSpec
from .m4_approval_bridge import M4ApprovalBridge, OperatorDecision as M4Decision

SCHEMA = "anima.memory_v1.binding_admission_m5/0.1"
OPERATOR = "test.operator.m5"
CRITERION = {
    "kind": "world.property_equals", "mode": "ensure_once",
    "subject_ref": DOOR_SUBJECT, "predicate_ref": DOOR_PREDICATE,
    "expected": {"type": "symbol", "value": "closed"},
}
REGISTRY_KEY = (
    DOOR_SUBJECT, DOOR_PREDICATE,
    json.dumps(CRITERION["expected"], sort_keys=True, separators=(",", ":")),
)
ACTION = ActionSpec(
    candidate_id="door_close_01", tool=DOOR_TOOL,
    tool_version=DOOR_VERSION, arguments={"subject_ref": DOOR_SUBJECT},
)
RULE = PropertyRule(
    subject_ref=DOOR_SUBJECT, predicate_ref=DOOR_PREDICATE,
    value_type="symbol", clock_domain="lab_tick",
    allowed_sources=(DOOR_SOURCE,), freshness_ticks=2,
    allowed_symbols=("open", "closed"),
)
DDL = """
CREATE TABLE IF NOT EXISTS m5_binding_tickets (
    ticket_id TEXT PRIMARY KEY,
    origin_goal_id TEXT UNIQUE NOT NULL,
    fingerprint TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    decision_json TEXT,
    status TEXT NOT NULL CHECK(status IN ('staged','approved','rejected','bound')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((status='staged' AND decision_json IS NULL)
       OR (status!='staged' AND decision_json IS NOT NULL))
);
"""


def _canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value):
    return sha256(_canon(value).encode("utf-8")).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def restricted_core(root):
    """Real P2/P3-A and registered action spec; no WorldPort/Executor/P3-C."""
    core = build_core(
        Path(root) / "runtime",
        sources={
            DOOR_SOURCE: SourceRegistration(
                source_ref=DOOR_SOURCE, producer_ref=DOOR_PRODUCER,
                allowed_kinds=("state.property",),
            ),
        },
        properties={(DOOR_SUBJECT, DOOR_PREDICATE): RULE},
        goal_actions={REGISTRY_KEY: ACTION},
        auto_core=False, enable_event_retrieval=True,
    )
    assert core.core_decision is not None
    assert core.core_execution is None and core.core_autonomy is None
    return core


@dataclass(frozen=True, slots=True)
class OperatorBindingDecision:
    ticket_id: str
    fingerprint: str
    decision_id: str
    operator_ref: str
    action: str  # APPROVE | REJECT (lab host, NOT authentication)

    def __post_init__(self):
        if self.action not in ("APPROVE", "REJECT"):
            raise ValueError("M5 binding decision must be explicit APPROVE or REJECT")
        if self.operator_ref != OPERATOR:
            raise ValueError("M5 operator is not in laboratory allowlist")
        for k in ("ticket_id", "fingerprint", "decision_id"):
            v = getattr(self, k)
            if type(v) is not str or not v or len(v) > 128:
                raise ValueError("M5 invalid " + k)
        if len(self.fingerprint) != 64 or any(
            c not in "0123456789abcdef" for c in self.fingerprint
        ):
            raise ValueError("M5 invalid proposal fingerprint")


class M5BindingAdmission:
    """No executor, no task scheduler, no tool handlers, no user data write."""

    def __init__(self, *, database_file, core: CoreAssembly, m4: M4ApprovalBridge):
        if not isinstance(core, CoreAssembly):
            raise TypeError("M5 requires a CoreAssembly")
        if core.core_decision is None or core.core_events is None:
            raise ValueError("M5 requires registered Core P2/P3-A")
        if core.core_execution is not None or core.core_autonomy is not None:
            raise ValueError("M5 refuses executor or autonomous Core configurations")
        if not isinstance(m4, M4ApprovalBridge):
            raise TypeError("M5 requires real M4 lab approval ledger")
        if m4.goals.database_file.resolve() != core.internal_state.goals.database_file.resolve():
            raise ValueError("M5 and M4 must share canonical GoalStore")
        if m4.gate.index.event_log.log_file.resolve() != core.event_log.log_file.resolve():
            raise ValueError("M5 and M4 must share canonical EventLog")
        self.core = core
        self.m4 = m4
        self.path = Path(database_file).resolve()
        if self.path in (m4.path.resolve(), core.internal_state_store.database_file.resolve()):
            raise ValueError("M5 admission ledger must be a distinct file")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(DDL)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def ticket(self, ticket_id):
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM m5_binding_tickets WHERE ticket_id=?",
                             (ticket_id,)).fetchone()
        return None if row is None else dict(row)

    def _trusted_registry(self):
        core = self.core
        if dict(core.core_decision.actions) != {REGISTRY_KEY: ACTION}:
            raise ValueError("M5 system action registry was changed")
        if core.core_events.ingress.beliefs.properties != {
            (DOOR_SUBJECT, DOOR_PREDICATE): RULE
        }:
            raise ValueError("M5 registered property rule was changed")
        if core.core_events.ingress.sources != {
            DOOR_SOURCE: SourceRegistration(
                source_ref=DOOR_SOURCE, producer_ref=DOOR_PRODUCER,
                allowed_kinds=("state.property",),
            ),
        }:
            raise ValueError("M5 registered observation source was changed")
        return {
            "criterion": CRITERION,
            "action": ACTION.to_dict(),
            "property": asdict(RULE),
            "source": DOOR_SOURCE, "producer": DOOR_PRODUCER,
        }

    def _sensor(self, event_id, tick):
        if type(event_id) is not str or not event_id or type(tick) is not int:
            raise ValueError("M5 requires typed live registered observation reference")
        ingress = self.core.core_events.ingress
        event = ingress.get_event(event_id)
        if event is None:
            raise ValueError("M5 sensor event not found in registered Core ingress")
        if (event["source_ref"] != DOOR_SOURCE
                or event["producer_ref"] != DOOR_PRODUCER
                or event["kind"] != "state.property"
                or event["payload"].get("subject_ref") != DOOR_SUBJECT
                or event["payload"].get("predicate_ref") != DOOR_PREDICATE
                or event["payload"].get("observed_at") != {
                    "domain": "lab_tick", "value": tick,
                }
                or event["payload"].get("value") != {
                    "type": "symbol", "value": "open",
                }):
            raise ValueError("M5 sensor event does not match registered door/open criterion")
        outcome = ingress.observation_outcome(event_id)
        if (outcome is None or outcome["outcome"].startswith("REJECTED_")
                or outcome["outcome"] == "HISTORY_ONLY"):
            raise ValueError("M5 sensor event was not admitted as authoritative observation")
        belief = ingress.read_belief(
            DOOR_SUBJECT, DOOR_PREDICATE, as_of_tick=tick,
        )
        if (belief["status"] != "known"
                or belief["freshness"] != "fresh"
                or belief["observed_tick"] != tick
                or event_id not in belief["evidence_event_ids"]
                or belief["value"] != {"type": "symbol", "value": "open"}):
            raise ValueError("M5 requires current trusted fresh open-world sensor evidence")
        return {"event_id": event_id, "tick": tick,
                "content_sha256": event["content_sha256"],
                "revision": belief["revision"]}

    def _m4_goal(self, m4_ticket_id):
        row = self.m4.get_ticket(m4_ticket_id)
        if row is None or row["status"] != "committed":
            raise ValueError("M5 requires already committed M4 Goal")
        if row["decision_json"] is None:
            raise ValueError("M5 missing M4 operator receipt")
        decision = M4Decision(**json.loads(row["decision_json"]))
        if decision.action != "APPROVE" or decision.fingerprint != row["fingerprint"]:
            raise ValueError("M5 previous Goal approval is not valid")
        # Committed M4 tickets otherwise skip this important fresh-source check.
        self.m4._ensure_fresh(row)
        if not self.m4._check_created_goal(row):
            raise ValueError("M5 missing canonical M4 Goal")
        goal = self.core.internal_state.goals.get_goal(row["goal_id"])
        if goal is None or goal["status"] != "active":
            raise ValueError("M5 requires active unbound canonical Goal")
        return row

    def _binding(self, goal_id):
        stored = self.core.core_decision._binding(goal_id)
        if stored is None:
            return None
        expected = {
            "goal_id": goal_id, "mode": CRITERION["mode"],
            "criterion_kind": CRITERION["kind"],
            "subject_ref": DOOR_SUBJECT, "predicate_ref": DOOR_PREDICATE,
            "expected_json": _canon(CRITERION["expected"]),
        }
        if any(stored.get(k) != v for k, v in expected.items()):
            raise ValueError("M5 existing Core binding is different from admitted criterion")
        return stored

    def _validate(self, row):
        if row is None:
            raise ValueError("Unknown M5 binding ticket")
        saved = json.loads(row["snapshot_json"])
        if row["ticket_id"] != "m5_" + row["fingerprint"] or _sha(saved) != row["fingerprint"]:
            raise ValueError("M5 immutable binding snapshot changed")
        if row["origin_goal_id"] != saved["goal_id"]:
            raise ValueError("M5 goal binding identity changed")
        m4 = self._m4_goal(saved["m4_ticket_id"])
        if (m4["goal_id"] != saved["goal_id"]
                or m4["fingerprint"] != saved["m4_fingerprint"]):
            raise ValueError("M5 source M4 proposal fingerprint changed")
        if self._trusted_registry() != saved["system"]:
            raise ValueError("M5 trusted action or registered property changed")
        before = saved["sensor"]
        old = self.core.core_events.ingress.get_event(before["event_id"])
        if old is None or old["content_sha256"] != before["content_sha256"]:
            raise ValueError("M5 original sensor Event changed")
        return saved

    def stage(self, *, m4_ticket_id, sensor_event_id, tick):
        m4 = self._m4_goal(m4_ticket_id)
        if self._binding(m4["goal_id"]) is not None:
            raise ValueError("M5 refuses staging a previously bound Goal")
        system = self._trusted_registry()
        evidence = self._sensor(sensor_event_id, tick)
        saved = {
            "schema": SCHEMA, "goal_id": m4["goal_id"],
            "m4_ticket_id": m4_ticket_id,
            "m4_fingerprint": m4["fingerprint"],
            "system": system, "sensor": evidence,
        }
        raw = _canon(saved)
        if len(raw.encode("utf-8")) > 8192:
            raise ValueError("M5 admission ticket exceeds data budget")
        fingerprint = _sha(saved)
        ticket_id = "m5_" + fingerprint
        now = _now()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT OR IGNORE INTO m5_binding_tickets(
                        ticket_id,origin_goal_id,fingerprint,snapshot_json,
                        decision_json,status,created_at,updated_at
                    ) VALUES (?,?,?,?,NULL,'staged',?,?)""",
                    (ticket_id, m4["goal_id"], fingerprint, raw, now, now),
                )
                existing = db.execute(
                    "SELECT * FROM m5_binding_tickets WHERE origin_goal_id=?",
                    (m4["goal_id"],),
                ).fetchone()
                if existing is None or (existing["ticket_id"] != ticket_id
                    or existing["fingerprint"] != fingerprint
                    or existing["snapshot_json"] != raw):
                    raise ValueError("M5 cannot replace previously reviewed binding")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.ticket(ticket_id)

    def decide(self, decision: OperatorBindingDecision):
        if not isinstance(decision, OperatorBindingDecision):
            raise TypeError("M5 requires typed separate host binding decision")
        row = self.ticket(decision.ticket_id)
        if row is None:
            raise ValueError("Unknown M5 admission ticket")
        if decision.fingerprint != row["fingerprint"]:
            raise ValueError("M5 receipt does not match exact binding fingerprint")
        if row["decision_json"] is not None:
            if row["decision_json"] != _canon(asdict(decision)):
                raise ValueError("M5 changed or contradictory decision is not replay")
            return self.ticket(decision.ticket_id)
        self._validate(row)
        if row["status"] != "staged" or self._binding(row["origin_goal_id"]) is not None:
            raise ValueError("M5 binding admission already used")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                status = "approved" if decision.action == "APPROVE" else "rejected"
                cursor = db.execute(
                    """UPDATE m5_binding_tickets
                    SET status=?,decision_json=?,updated_at=?
                    WHERE ticket_id=? AND status='staged' AND decision_json IS NULL""",
                    (status, _canon(asdict(decision)), _now(), decision.ticket_id),
                )
                if cursor.rowcount != 1:
                    current = db.execute(
                        "SELECT decision_json FROM m5_binding_tickets WHERE ticket_id=?",
                        (decision.ticket_id,),
                    ).fetchone()
                    if current is None or current["decision_json"] != _canon(asdict(decision)):
                        raise ValueError("M5 concurrent conflicting operator decision")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.ticket(decision.ticket_id)

    def apply(self, ticket_id, *, sensor_event_id, tick, cut=None):
        """Persist CoreGoalDecision.bind ONLY in non-executable Core P3-A."""
        if cut not in (None, "before_bind", "after_bind"):
            raise ValueError("M5 unsupported crash cut")
        if self.core.core_execution is not None or self.core.core_autonomy is not None:
            raise ValueError("M5 refuses execution-enabled Core")
        row = self.ticket(ticket_id)
        if row is None or row["status"] not in ("approved", "bound"):
            raise ValueError("M5 binding requires a separate explicit APPROVE")
        saved = self._validate(row)
        receipt = OperatorBindingDecision(**json.loads(row["decision_json"]))
        if receipt.action != "APPROVE" or receipt.fingerprint != row["fingerprint"]:
            raise ValueError("M5 binding approval receipt is invalid")
        present = self._binding(row["origin_goal_id"])
        live = self._sensor(sensor_event_id, tick)
        if live["tick"] < saved["sensor"]["tick"]:
            raise ValueError("M5 live sensor went backward")
        if row["status"] == "bound":
            if present is None:
                raise ValueError("M5 bound ledger missing canonical Core binding")
            return present
        if cut == "before_bind":
            import os
            os._exit(74)
        if present is None:
            self.core.runtime.bind_core_goal(GoalCriterion(
                goal_id=row["origin_goal_id"],
                subject_ref=DOOR_SUBJECT, predicate_ref=DOOR_PREDICATE,
                expected=dict(CRITERION["expected"]),
            ))
        present = self._binding(row["origin_goal_id"])
        if present is None:
            raise AssertionError("M5 CoreGoalDecision binding is missing")
        if cut == "after_bind":
            import os
            os._exit(73)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                changed = db.execute(
                    """UPDATE m5_binding_tickets SET status='bound',updated_at=?
                       WHERE ticket_id=? AND status='approved'""",
                    (_now(), ticket_id),
                )
                if changed.rowcount != 1:
                    row2 = db.execute(
                        "SELECT status FROM m5_binding_tickets WHERE ticket_id=?",
                        (ticket_id,),
                    ).fetchone()
                    if row2 is None or row2["status"] != "bound":
                        raise ValueError("M5 binding ledger changed during finalize")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return present


__all__ = [
    "M5BindingAdmission", "OperatorBindingDecision", "restricted_core",
    "SCHEMA", "OPERATOR", "RULE", "ACTION", "CRITERION",
]
