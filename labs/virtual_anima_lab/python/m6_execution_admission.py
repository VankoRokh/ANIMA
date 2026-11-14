"""M6-A isolated, single-use execution admission for existing M4/M5 Goal.

The guard is enforceable only for this opt-in *laboratory composition*. Code
that directly constructs another executor around the same Core DB bypasses it.
No production authentication or global capability isolation is claimed.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from anima.agent.executor import SandboxHandler, SandboxToolError
from anima.core.assembly import build_core
from anima.core.door_world import (
    DOOR_PREDICATE, DOOR_PRODUCER, DOOR_SOURCE, DOOR_SUBJECT,
    DOOR_TOOL, DOOR_VERSION, VirtualDoorWorld, door_handlers,
)
from anima.core.ingress import SourceRegistration
from anima.execution.store import ExecutionStore
from labs.virtual_anima_lab.python.m5_binding_admission import (
    ACTION, CRITERION, REGISTRY_KEY, RULE,
    M5BindingAdmission, restricted_core,
)

SCHEMA = "anima.memory_v1.execution_admission_m6a/0.1"
OPERATOR = "test.operator.m6a"

DDL = """
CREATE TABLE IF NOT EXISTS m6_execution_tickets (
  ticket_id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL UNIQUE,
  m5_ticket_id TEXT NOT NULL UNIQUE,
  fingerprint TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  decision_json TEXT,
  status TEXT NOT NULL CHECK(status IN ('staged','approved','rejected','claimed')),
  operation_id TEXT UNIQUE,
  consumed_event_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK ((status='staged' AND decision_json IS NULL)
      OR (status!='staged' AND decision_json IS NOT NULL)),
  CHECK ((status='claimed' AND operation_id IS NOT NULL AND consumed_event_id IS NOT NULL)
      OR (status!='claimed' AND operation_id IS NULL AND consumed_event_id IS NULL))
);
"""


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value):
    return sha256(_canon(value).encode("utf-8")).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class OperatorExecutionDecision:
    ticket_id: str
    fingerprint: str
    decision_id: str
    operator_ref: str
    action: str

    def __post_init__(self):
        if self.action not in ("APPROVE", "REJECT"):
            raise ValueError("M6-A requires explicit APPROVE or REJECT")
        if self.operator_ref != OPERATOR:
            raise ValueError("M6-A unknown laboratory operator")
        for field in ("ticket_id", "fingerprint", "decision_id"):
            item = getattr(self, field)
            if type(item) is not str or not item or len(item) > 128:
                raise ValueError("M6-A invalid " + field)
        if (len(self.fingerprint) != 64 or
            any(x not in "0123456789abcdef" for x in self.fingerprint)):
            raise ValueError("M6-A invalid ticket fingerprint")


def observed(core, root):
    """Only a lab-owned sensor adapter may call the registered P2 ingress."""
    raw, tick = VirtualDoorWorld(Path(root) / "world").sense()
    result = core.core_events.ingress.admit(raw, source_ref=DOOR_SOURCE)
    if result.status not in ("ACCEPTED", "ALREADY_SEEN"):
        raise ValueError("M6-A registered sensor admission failed")
    return result.event_id, tick


class M6Admission:
    """M6 lab host: disabled executor until source-bound third decision."""

    def __init__(self, *, root, core, m5: M5BindingAdmission):
        if not isinstance(m5, M5BindingAdmission) or m5.core is not core:
            raise ValueError("M6-A requires the exact restricted M5 assembly")
        if core.core_execution is not None or core.core_autonomy is not None:
            raise ValueError("M6-A cannot run inside an already executable Core")
        self.root = Path(root).resolve()
        self.path = self.root / "m6_admission.db"
        self.core = core
        self.m5 = m5
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
            row = db.execute(
                "SELECT * FROM m6_execution_tickets WHERE ticket_id=?",
                (ticket_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def _bound_goal(self, m5_ticket_id):
        row = self.m5.ticket(m5_ticket_id)
        if row is None or row["status"] != "bound":
            raise ValueError("M6-A requires final M5 bound admission")
        saved = self.m5._validate(row)
        m4 = self.m5.m4.get_ticket(saved["m4_ticket_id"])
        if m4 is None or m4["status"] != "committed":
            raise ValueError("M6-A M4 approval is not committed")
        if self.m5._binding(row["origin_goal_id"]) is None:
            raise ValueError("M6-A canonical typed Core binding missing")
        goal = self.core.internal_state.goals.get_goal(row["origin_goal_id"])
        if goal is None:
            raise ValueError("M6-A original M4 Goal missing")
        return row, saved, goal

    def _fresh(self, ticket, *, active=True):
        if ticket is None:
            raise ValueError("M6-A unknown execution ticket")
        saved = json.loads(ticket["snapshot_json"])
        if (ticket["ticket_id"] != "m6_" + ticket["fingerprint"] or
                _sha(saved) != ticket["fingerprint"] or
                ticket["goal_id"] != saved["goal_id"] or
                ticket["m5_ticket_id"] != saved["m5_ticket_id"]):
            raise ValueError("M6-A execution ticket mutated")
        row, m5_saved, goal = self._bound_goal(saved["m5_ticket_id"])
        if (row["origin_goal_id"] != saved["goal_id"] or
                row["fingerprint"] != saved["m5_fingerprint"] or
                m5_saved["m4_fingerprint"] != saved["m4_fingerprint"] or
                _canon(self.m5._trusted_registry()) != _canon(saved["system"])):
            raise ValueError("M6-A upstream Goal, source or action drift")
        if active and goal["status"] != "active":
            raise ValueError("M6-A Goal is no longer active")
        original = saved["sensor"]
        current = self.core.core_events.ingress.get_event(original["event_id"])
        if (current is None or current["content_sha256"] != original["content_sha256"]):
            raise ValueError("M6-A original registered sensor changed")
        return saved

    def _sense_open(self, event_id, tick, *, after_tick=None):
        sensor = self.m5._sensor(event_id, tick)
        if after_tick is not None and sensor["tick"] <= after_tick:
            raise ValueError("M6-A requires NEW live registered sensor tick")
        return sensor

    def stage(self, *, m5_ticket_id, sensor_event_id, tick):
        m5row, m5_saved, goal = self._bound_goal(m5_ticket_id)
        if goal["status"] != "active":
            raise ValueError("M6-A requires active Goal")
        if self.core.core_decision.tasks.list_tasks() != []:
            raise ValueError("M6-A cannot stage already scheduled Goal")
        sensor = self._sense_open(
            sensor_event_id, tick, after_tick=m5_saved["sensor"]["tick"],
        )
        saved = {
            "schema": SCHEMA, "m5_ticket_id": m5_ticket_id,
            "m5_fingerprint": m5row["fingerprint"],
            "m4_fingerprint": m5_saved["m4_fingerprint"],
            "goal_id": goal["id"],
            "system": self.m5._trusted_registry(), "sensor": sensor,
        }
        if len(_canon(saved).encode("utf-8")) > 8192:
            raise ValueError("M6-A ticket budget exceeded")
        digest = _sha(saved)
        ticket_id = "m6_" + digest
        now = _now()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT OR IGNORE INTO m6_execution_tickets
                    (ticket_id,goal_id,m5_ticket_id,fingerprint,snapshot_json,
                     status,decision_json,operation_id,consumed_event_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,'staged',NULL,NULL,NULL,?,?)""",
                    (ticket_id, goal["id"], m5_ticket_id, digest,
                     _canon(saved), now, now),
                )
                row = db.execute(
                    "SELECT * FROM m6_execution_tickets WHERE goal_id=?",
                    (goal["id"],),
                ).fetchone()
                if row is None or row["ticket_id"] != ticket_id or row["snapshot_json"] != _canon(saved):
                    raise ValueError("M6-A cannot replace original execution proposal")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.ticket(ticket_id)

    def decide(self, decision: OperatorExecutionDecision):
        if not isinstance(decision, OperatorExecutionDecision):
            raise TypeError("M6-A requires typed third host decision")
        row = self.ticket(decision.ticket_id)
        if row is None or row["fingerprint"] != decision.fingerprint:
            raise ValueError("M6-A approval fingerprint does not match ticket")
        if row["decision_json"] is not None:
            if row["decision_json"] != _canon(asdict(decision)):
                raise ValueError("M6-A conflicting or altered approval receipt")
            return self.ticket(decision.ticket_id)
        self._fresh(row)
        if row["status"] != "staged":
            raise ValueError("M6-A staged ticket already terminal")
        status = "approved" if decision.action == "APPROVE" else "rejected"
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cur = db.execute(
                    """UPDATE m6_execution_tickets
                    SET status=?,decision_json=?,updated_at=?
                    WHERE ticket_id=? AND status='staged' AND decision_json IS NULL""",
                    (status, _canon(asdict(decision)), _now(), decision.ticket_id),
                )
                if cur.rowcount != 1:
                    old = db.execute(
                        "SELECT decision_json FROM m6_execution_tickets WHERE ticket_id=?",
                        (decision.ticket_id,),
                    ).fetchone()
                    if old is None or old["decision_json"] != _canon(asdict(decision)):
                        raise ValueError("M6-A concurrent conflicting decision")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.ticket(decision.ticket_id)

    def assemble(self, ticket_id, *, event_id, tick):
        """Opt-in Core executor, no P3-C; denies bad approval BEFORE assembly."""
        row = self.ticket(ticket_id)
        if row is None or row["status"] not in ("approved", "claimed"):
            raise ValueError("M6-A explicit execution APPROVE required before assembly")
        receipt = OperatorExecutionDecision(**json.loads(row["decision_json"]))
        if receipt.action != "APPROVE" or receipt.fingerprint != row["fingerprint"]:
            raise ValueError("M6-A approval receipt altered")
        saved = self._fresh(row, active=row["status"] == "approved")
        if row["status"] == "approved":
            self._sense_open(event_id, tick, after_tick=saved["sensor"]["tick"])
        else:
            # Recovery: the world may already be closed; no new effect allowed.
            if not row["operation_id"]:
                raise ValueError("M6-A claimed admission missing operation ID")
        world = VirtualDoorWorld(self.root / "world")
        wrapped = guarded_handlers(self.root, ticket_id)
        core = build_core(
            self.root / "runtime",
            sources={DOOR_SOURCE: SourceRegistration(
                source_ref=DOOR_SOURCE, producer_ref=DOOR_PRODUCER,
                allowed_kinds=("state.property",),
            )},
            properties={(DOOR_SUBJECT, DOOR_PREDICATE): RULE},
            goal_actions={REGISTRY_KEY: ACTION},
            world_port=world,
            world_handlers=wrapped,
            auto_core=False,
            enable_event_retrieval=True,
        )
        if core.core_execution is None or core.core_autonomy is not None:
            raise AssertionError("M6-A executor composition violated no-P3-C invariant")
        if core.core_decision._binding(row["goal_id"]) is None:
            raise AssertionError("M6-A lost Core typed binding")
        return core

    def execute_approved(self, ticket_id, core):
        row = self.ticket(ticket_id)
        if row is None or row["status"] not in ("approved", "claimed"):
            raise ValueError("M6-A explicit APPROVE required before Core scheduling")
        if core.core_execution is None or core.core_autonomy is not None:
            raise ValueError("M6-A requires guarded executor without P3-C")
        if row["goal_id"] != self._fresh(row, active=row["status"] == "approved")["goal_id"]:
            raise ValueError("M6-A Goal changed")
        if not isinstance(core.core_execution.world, VirtualDoorWorld):
            raise ValueError("M6-A can execute only same registered VirtualDoorWorld")
        handlers = core.core_execution.executor.handlers
        guard = handlers.get((DOOR_TOOL, DOOR_VERSION))
        if guard is None or not isinstance(guard.execute, M6GuardedDoorHandler):
            raise ValueError("M6-A refuses unguarded handler")
        if guard.execute.ticket_id != ticket_id or guard.execute.root != self.root:
            raise ValueError("M6-A handler bound to wrong execution ticket/root")
        return core.runtime.run_core_door_goal(row["goal_id"])


class M6GuardedDoorHandler:
    """Actual Tool-worker boundary: fresh P2 read, one durable claim, then effect."""

    def __init__(self, root, ticket_id):
        self.root = Path(root).resolve()
        self.ticket_id = ticket_id

    def __call__(self, handler_root, arguments, operation_id):
        if Path(handler_root).resolve() != (self.root / "world").resolve():
            raise SandboxToolError("M6_WRONG_ROOT", "wrong world root", effect_possible=False)
        if type(arguments) is not dict or arguments != {"subject_ref": DOOR_SUBJECT}:
            raise SandboxToolError("M6_WRONG_ACTION", "unexpected tool arguments", effect_possible=False)
        if type(operation_id) is not str:
            raise SandboxToolError("M6_WRONG_OPERATION", "missing operation", effect_possible=False)
        # Independently reopen restricted non-executable Core before every effect.
        core = restricted_core(self.root)
        from scripts.run_memory_v1_binding_gate import _m5
        gate = M6Admission(root=self.root, core=core, m5=_m5(core, self.root))
        row = gate.ticket(self.ticket_id)
        if row is None or row["status"] != "approved":
            raise SandboxToolError("M6_NO_PERMIT", "no unclaimed M6 permission", effect_possible=False)
        try:
            saved = gate._fresh(row)
            receipt = OperatorExecutionDecision(**json.loads(row["decision_json"]))
            if receipt.action != "APPROVE" or receipt.fingerprint != row["fingerprint"]:
                raise ValueError("M6 approval not valid")
            stored = ExecutionStore(self.root / "runtime" / "execution.db")
            operation = stored.get_operation(operation_id)
            if operation is None or operation["status"] != "executing":
                raise ValueError("No executing canonical Core operation")
            action = stored.load_action(operation_id)
            if (action.goal_id != row["goal_id"]
                or action.tool != DOOR_TOOL or action.tool_version != DOOR_VERSION
                or action.candidate_id != ACTION.candidate_id
                or action.to_dict()["arguments"] != {"subject_ref": DOOR_SUBJECT}
            ):
                raise ValueError("Core operation is not approved action")
            raw, tick = VirtualDoorWorld(self.root / "world").sense()
            accepted = core.core_events.ingress.admit(raw, source_ref=DOOR_SOURCE)
            if accepted.status != "ACCEPTED":
                raise ValueError("M6 pre-effect sensor was not fresh")
            measured = gate._sense_open(
                accepted.event_id, tick, after_tick=saved["sensor"]["tick"],
            )
            with closing(gate._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    changed = db.execute(
                        """UPDATE m6_execution_tickets SET status='claimed',
                        operation_id=?,consumed_event_id=?,updated_at=?
                        WHERE ticket_id=? AND status='approved' AND operation_id IS NULL""",
                        (operation_id, measured["event_id"], _now(), self.ticket_id),
                    )
                    if changed.rowcount != 1:
                        raise ValueError("M6 single-use permit already claimed")
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
        except (ValueError, RuntimeError, TypeError, KeyError, sqlite3.Error) as exc:
            raise SandboxToolError("M6_PRE_EFFECT_DENIED", str(exc), effect_possible=False) from exc

        # Exactly one effect invocation. If the worker crashes here, Core must
        # reconcile the canonical operation and NEVER reclaim or repeat permit.
        return door_handlers()[(DOOR_TOOL, DOOR_VERSION)].execute(
            handler_root, arguments, operation_id,
        )


def guarded_handlers(root, ticket_id):
    original = door_handlers()[(DOOR_TOOL, DOOR_VERSION)]
    return {(DOOR_TOOL, DOOR_VERSION): SandboxHandler(
        execute=M6GuardedDoorHandler(root, ticket_id),
        reconcile=original.reconcile, replay_output=original.replay_output,
    )}


__all__ = [
    "M6Admission", "OperatorExecutionDecision", "M6GuardedDoorHandler",
    "guarded_handlers", "observed", "SCHEMA", "OPERATOR",
]
