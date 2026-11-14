"""M6-B2 opt-in Godot admission. Not a global Core capability firewall.

One canonical M4 GoalStore, entirely separate P6-facing P2/P3/Task/Operation
files, and an extra action-scoped lab approval. M6-A's virtual permission
cannot be reused. No change to production anima/ is required.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import sqlite3

from anima.agent.executor import SandboxHandler, SandboxToolError
from anima.core.belief import PropertyRule
from anima.core.door_execution import CoreDoorExecution
from anima.core.door_world import (
    DOOR_PREDICATE, DOOR_SOURCE, DOOR_SUBJECT, DOOR_TOOL, DOOR_VERSION,
    door_tool_registry,
)
from anima.core.goal_decision import CoreGoalDecision, GoalCriterion
from anima.core.ingress import CoreIngress, SourceRegistration
from anima.execution.sandbox import SandboxExecutor
from anima.execution.store import ExecutionStore
from anima.execution.contracts import thaw
from anima.tasks.store import TaskStore
from labs.virtual_anima_lab.python.core_port import VALDoorPort
from labs.virtual_anima_lab.python.contracts import (
    SOURCE as GODOT_SOURCE, PRODUCER as GODOT_PRODUCER, OBSERVATION_SCHEMA,
)
from labs.virtual_anima_lab.python.m5_binding_admission import (
    ACTION, CRITERION, REGISTRY_KEY, M5BindingAdmission, restricted_core,
)
from labs.virtual_anima_lab.python.m6b1_godot_migration import (
    M6B1Migration, OperatorMigrationDecision, P6_PRODUCER,
    validate_frozen_mapping,
)
from labs.virtual_anima_lab.python.m6_execution_admission import _canon, _sha, _now

SCHEMA = "anima.memory_v1.godot_execution_m6b2/0.1"
OPERATOR = "test.operator.m6b2"

DDL = """
CREATE TABLE IF NOT EXISTS m6b2_tickets(
  ticket_id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL UNIQUE,
  b1_ticket_id TEXT NOT NULL UNIQUE,
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
  CHECK ((status='claimed' AND operation_id IS NOT NULL
      AND consumed_event_id IS NOT NULL)
      OR (status!='claimed' AND operation_id IS NULL
      AND consumed_event_id IS NULL))
);
"""


@dataclass(frozen=True, slots=True)
class OperatorGodotExecutionDecision:
    ticket_id: str
    fingerprint: str
    decision_id: str
    operator_ref: str
    action: str

    def __post_init__(self):
        if self.action not in ("APPROVE", "REJECT"):
            raise ValueError("M6-B2 requires separate APPROVE or REJECT")
        if self.operator_ref != OPERATOR:
            raise ValueError("M6-B2 unknown laboratory operator")
        for key in ("ticket_id", "fingerprint", "decision_id"):
            value = getattr(self, key)
            if type(value) is not str or not value or len(value) > 128:
                raise ValueError("M6-B2 invalid " + key)
        if len(self.fingerprint) != 64 or any(
            x not in "0123456789abcdef" for x in self.fingerprint
        ):
            raise ValueError("M6-B2 invalid ticket fingerprint")


@dataclass(frozen=True, slots=True)
class B2Target:
    ingress: CoreIngress
    decision: CoreGoalDecision
    operations: ExecutionStore
    execution: CoreDoorExecution | None


class M6B2Admission:
    """Trusted *laboratory composition* only. No production identity security."""

    def __init__(self, *, root, b1: M6B1Migration):
        if not isinstance(b1, M6B1Migration):
            raise TypeError("M6-B2 requires the exact B1 migration gate")
        self.root = Path(root).resolve()
        if b1.root != self.root or b1.port.root != self.root / "p6_port":
            raise ValueError("M6-B2 root/port mismatch")
        if (b1.m5.core.core_execution is not None
                or b1.m5.core.core_autonomy is not None):
            raise ValueError("M6-B2 origin must remain non-executable")
        self.b1 = b1
        self.port = b1.port
        self.target_root = self.root / "m6b2_target"
        self.path = self.root / "m6b2_admission.db"
        with closing(self._connect()) as db:
            db.executescript(DDL)

    @classmethod
    def reopen(cls, root, *, port_num):
        """Worker/recovery process opens fresh DB handles, not parent handles."""
        from scripts.run_memory_v1_binding_gate import _m5
        root = Path(root).resolve()
        core = restricted_core(root)
        m5 = _m5(core, root)
        port = VALDoorPort(root / "p6_port", port=port_num)
        return cls(root=root, b1=M6B1Migration(root=root, m5=m5, port=port))

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def get(self, ticket_id):
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM m6b2_tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def _target(self, *, ticket_id=None):
        """Target-only P2/P3/Task/Execution; original GoalStore is shared."""
        self.target_root.mkdir(parents=True, exist_ok=True)
        ing = CoreIngress(
            self.target_root / "core_state.db",
            sources={DOOR_SOURCE: SourceRegistration(
                source_ref=DOOR_SOURCE, producer_ref=P6_PRODUCER,
                allowed_kinds=("state.property", "sensor.unavailable"),
            )},
            properties={(DOOR_SUBJECT, DOOR_PREDICATE): PropertyRule(
                subject_ref=DOOR_SUBJECT, predicate_ref=DOOR_PREDICATE,
                value_type="symbol", clock_domain="lab_sample",
                allowed_sources=(DOOR_SOURCE,), freshness_ticks=2,
                allowed_symbols=("open", "closed"),
            )},
        )
        decision = CoreGoalDecision(
            database_file=self.target_root / "core_work.db",
            goals=self.b1.m5.core.internal_state.goals,
            tasks=TaskStore(self.target_root / "tasks.db"),
            ingress=ing, actions={REGISTRY_KEY: ACTION},
        )
        store = ExecutionStore(self.target_root / "execution.db")
        executor = None
        if ticket_id is not None:
            port_handler = self.port.handlers()[(DOOR_TOOL, DOOR_VERSION)]
            guarded = SandboxHandler(
                execute=M6B2GuardedHandler(self.root, ticket_id, self.port.port),
                reconcile=port_handler.reconcile,
                replay_output=port_handler.replay_output,
            )
            registry = door_tool_registry()
            sandbox = SandboxExecutor(
                root=self.port.root, registry=registry, store=store,
                handlers={(DOOR_TOOL, DOOR_VERSION): guarded},
            )
            executor = CoreDoorExecution(
                decisions=decision, internal_state=self.b1.m5.core.internal_state,
                world=self.port, execution_store=store,
                registry=registry, executor=sandbox,
            )
        return B2Target(ing, decision, store, executor)

    def _history(self, saved, *, active):
        """Immutable ancestry, without B1's pre-action OPEN rule in recovery."""
        b1row = self.b1.get(saved["b1_ticket_id"])
        if b1row is None or b1row["status"] != "approved":
            raise ValueError("M6-B2 missing approved B1 origin")
        b1_saved = json.loads(b1row["snapshot_json"])
        if (b1row["fingerprint"] != saved["b1_fingerprint"]
                or b1row["ticket_id"] != "m6b1_" + b1row["fingerprint"]
                or _sha(b1_saved) != b1row["fingerprint"]
                or b1_saved["goal_id"] != saved["goal_id"]):
            raise ValueError("M6-B2 B1 mapping was changed")
        validate_frozen_mapping(b1_saved["mapping"])
        b1dec = OperatorMigrationDecision(**json.loads(b1row["decision_json"]))
        if b1dec.action != "APPROVE" or b1dec.fingerprint != b1row["fingerprint"]:
            raise ValueError("M6-B2 invalid B1 decision")
        m5row = self.b1.m5.ticket(b1_saved["m5_ticket_id"])
        if m5row is None or m5row["status"] != "bound":
            raise ValueError("M6-B2 historical M5 binding missing")
        m5_saved = json.loads(m5row["snapshot_json"])
        if (m5row["fingerprint"] != b1_saved["m5_fingerprint"]
                or _sha(m5_saved) != m5row["fingerprint"]
                or m5_saved["goal_id"] != saved["goal_id"]
                or m5_saved["m4_fingerprint"] != b1_saved["m4_fingerprint"]):
            raise ValueError("M6-B2 M5 provenance changed")
        m4row = self.b1.m5.m4.get_ticket(m5_saved["m4_ticket_id"])
        if (m4row is None or m4row["status"] != "committed"
                or m4row["fingerprint"] != m5_saved["m4_fingerprint"]
                or m4row["goal_id"] != saved["goal_id"]
                or not m4row["decision_json"]):
            raise ValueError("M6-B2 M4 Goal provenance changed")
        # M4's source review is independent of Goal lifecycle, so it must
        # also be checked after an already-applied effect on recovery.
        self.b1.m5.m4._ensure_fresh(m4row)
        initial = b1_saved["target"]
        with closing(sqlite3.connect(self.port.database_file)) as db:
            raw_first = db.execute(
                "SELECT payload_json,instance_id,epoch,world_revision "
                "FROM sample_log WHERE sample_seq=?",
                (initial["lab_sample"],),
            ).fetchone()
        if (raw_first is None
                or _sha(json.loads(raw_first[0])) != initial["raw_godot_sha256"]
                or raw_first[1] != initial["world_instance_id"]
                or raw_first[2] != initial["epoch"]
                or raw_first[3] != initial["world_revision"]):
            raise ValueError("M6-B2 original B1 Godot sample changed")
        event_ref = m5_saved["sensor"]
        original = self.b1.m5.core.core_events.ingress.get_event(event_ref["event_id"])
        if original is None or original["content_sha256"] != event_ref["content_sha256"]:
            raise ValueError("M6-B2 original M5 P2 Event changed")
        if self.b1.m5._binding(saved["goal_id"]) is None:
            raise ValueError("M6-B2 original P3-A binding missing")
        goals = self.b1.m5.core.internal_state.goals
        goal = goals.get_goal(saved["goal_id"])
        if (goal is None or goals.goal_count() != 1
                or (active and goal["status"] != "active")
                or (not active and goal["status"] not in ("active", "completed"))):
            raise ValueError("M6-B2 canonical Goal lifecycle invalid")
        if active:
            # Strong original Memory/Event-index validation before every effect.
            self.b1._validate(b1row)
        return b1_saved

    def _read_target(self, ing, *, later_than, world, open_required=True):
        """P6 port -> provenance ledger -> distinct registered target P2."""
        raw, seq = self.port.sense()
        if type(seq) is not int or seq <= later_than:
            raise ValueError("M6-B2 stale Godot sample")
        if (self.port._binding()
                != (world["world_instance_id"], world["epoch"])):
            raise ValueError("M6-B2 Godot world instance/epoch changed")
        with closing(sqlite3.connect(self.port.database_file)) as db:
            sample = db.execute(
                "SELECT instance_id,lab_observation_id,epoch,world_tick,"
                "world_revision,payload_json FROM sample_log WHERE sample_seq=?",
                (seq,),
            ).fetchone()
        if sample is None:
            raise ValueError("M6-B2 P6 source sample missing")
        identity, obs_id, epoch, tick, revision, payload = sample
        original = json.loads(payload)
        if (identity != world["world_instance_id"]
                or epoch != world["epoch"]
                or revision != world["world_revision"]
                or original.get("schema") != OBSERVATION_SCHEMA
                or original.get("source_ref") != GODOT_SOURCE
                or original.get("producer_ref") != GODOT_PRODUCER
                or original.get("world_revision") != revision
                or original.get("observed_at") != {"epoch": epoch, "tick": tick}
                or original.get("observation_id") != obs_id
                or raw.get("occurrence_id") != f"p6:{identity}:{obs_id}"
                or raw.get("payload", {}).get("observed_at")
                   != {"domain": "lab_sample", "value": seq}):
            raise ValueError("M6-B2 stale/corrupt P6 provenance or changed revision")
        admitted = ing.admit(raw, source_ref=DOOR_SOURCE)
        if admitted.status != "ACCEPTED":
            raise ValueError("M6-B2 target P2 requires new authoritative Event")
        event = ing.get_event(admitted.event_id)
        outcome = ing.observation_outcome(admitted.event_id)
        belief = ing.read_belief(DOOR_SUBJECT, DOOR_PREDICATE, as_of_tick=seq)
        if (event is None or event["producer_ref"] != P6_PRODUCER
                or event["source_ref"] != DOOR_SOURCE
                or outcome is None or outcome["outcome"].startswith("REJECTED_")
                or outcome["outcome"] == "HISTORY_ONLY"
                or belief["freshness"] != "fresh"
                or belief["observed_tick"] != seq
                or admitted.event_id not in belief["evidence_event_ids"]):
            raise ValueError("M6-B2 target P2 observation not authoritative")
        if open_required and (belief["status"] != "known" or
                              belief["value"] != {"type": "symbol", "value": "open"}):
            raise ValueError("M6-B2 Godot door is not open")
        return {
            "event_id": admitted.event_id, "content_sha256": event["content_sha256"],
            "lab_sample": seq, "sample_hash": _sha(original),
            "world_instance_id": identity, "epoch": epoch,
            "world_revision": revision, "belief_revision": belief["revision"],
        }

    def _validate(self, row, *, active):
        if row is None:
            raise ValueError("M6-B2 execution ticket absent")
        saved = json.loads(row["snapshot_json"])
        if (row["ticket_id"] != "m6b2_" + row["fingerprint"]
                or _sha(saved) != row["fingerprint"]
                or row["goal_id"] != saved["goal_id"]
                or row["b1_ticket_id"] != saved["b1_ticket_id"]
                or saved["schema"] != SCHEMA
                or saved["action"] != ACTION.to_dict()
                or saved["target"] != {
                    "source": DOOR_SOURCE, "producer": P6_PRODUCER,
                    "clock": "lab_sample", "criterion": CRITERION,
                }):
            raise ValueError("M6-B2 frozen execution ticket changed")
        self._history(saved, active=active)
        target = self._target()
        bound = target.decision._binding(saved["goal_id"])
        if (bound is None or bound["mode"] != CRITERION["mode"]
                or bound["criterion_kind"] != CRITERION["kind"]
                or bound["subject_ref"] != DOOR_SUBJECT
                or bound["predicate_ref"] != DOOR_PREDICATE
                or bound["expected_json"] != _canon(CRITERION["expected"])):
            raise ValueError("M6-B2 target P3-A binding changed")
        with closing(sqlite3.connect(self.port.database_file)) as db:
            stored = db.execute(
                "SELECT payload_json,instance_id,epoch,world_revision "
                "FROM sample_log WHERE sample_seq=?",
                (saved["admission_sample"]["lab_sample"],),
            ).fetchone()
        if (stored is None or _sha(json.loads(stored[0]))
                != saved["admission_sample"]["sample_hash"]
                or stored[1] != saved["world"]["world_instance_id"]
                or stored[2] != saved["world"]["epoch"]
                or stored[3] != saved["world"]["world_revision"]):
            raise ValueError("M6-B2 original P6 sample ledger changed")
        original = target.ingress.get_event(saved["admission_sample"]["event_id"])
        if (original is None or original["content_sha256"]
                != saved["admission_sample"]["content_sha256"]
                or original["producer_ref"] != P6_PRODUCER
                or original["payload"]["observed_at"] != {
                    "domain": "lab_sample",
                    "value": saved["admission_sample"]["lab_sample"],
                }):
            raise ValueError("M6-B2 immutable target P2 sample changed")
        world = saved["world"]
        if self.port._binding() != (world["world_instance_id"], world["epoch"]):
            raise ValueError("M6-B2 world identity changed")
        return saved

    def stage(self, b1_ticket_id):
        b1row = self.b1.get(b1_ticket_id)
        if b1row is None:
            raise ValueError("M6-B2 unknown B1 source map")
        with closing(self._connect()) as db:
            old = db.execute(
                "SELECT ticket_id FROM m6b2_tickets WHERE goal_id=?",
                (b1row["goal_id"],),
            ).fetchone()
        if old is not None:
            row = self.get(old["ticket_id"])
            self._validate(row, active=row["status"] != "claimed")
            return row
        proof = self.b1.revalidate(b1_ticket_id)
        target = self._target()
        if (target.decision.tasks.list_tasks()
                or target.operations.list_operations()
                or target.decision._binding(proof["goal_id"]) is not None):
            raise ValueError("M6-B2 nonempty target P3/Task/Operation store")
        world = {
            "world_instance_id": proof["world_instance_id"],
            "epoch": proof["epoch"], "world_revision": proof["world_revision"],
        }
        sample = self._read_target(
            target.ingress, later_than=proof["fresh_lab_sample"], world=world,
        )
        target.decision.bind(GoalCriterion(
            goal_id=proof["goal_id"], subject_ref=DOOR_SUBJECT,
            predicate_ref=DOOR_PREDICATE, expected=dict(CRITERION["expected"]),
        ))
        b1saved = json.loads(b1row["snapshot_json"])
        saved = {
            "schema": SCHEMA, "goal_id": proof["goal_id"],
            "b1_ticket_id": b1_ticket_id, "b1_fingerprint": b1row["fingerprint"],
            "m5_ticket_id": b1saved["m5_ticket_id"],
            "m5_fingerprint": b1saved["m5_fingerprint"],
            "world": world, "admission_sample": sample,
            "action": ACTION.to_dict(),
            "target": {
                "source": DOOR_SOURCE, "producer": P6_PRODUCER,
                "clock": "lab_sample", "criterion": CRITERION,
            },
        }
        digest = _sha(saved)
        ticket_id = "m6b2_" + digest
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "INSERT INTO m6b2_tickets("
                    "ticket_id,goal_id,b1_ticket_id,fingerprint,snapshot_json,"
                    "status,created_at,updated_at) VALUES(?,?,?,?,?,'staged',?,?)",
                    (ticket_id, proof["goal_id"], b1_ticket_id,
                     digest, _canon(saved), _now(), _now()),
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.get(ticket_id)

    def decide(self, receipt: OperatorGodotExecutionDecision):
        if not isinstance(receipt, OperatorGodotExecutionDecision):
            raise TypeError("M6-B2 requires typed separate host decision")
        row = self.get(receipt.ticket_id)
        if row is None or row["fingerprint"] != receipt.fingerprint:
            raise ValueError("M6-B2 unknown/changed approval fingerprint")
        if row["decision_json"] is not None:
            if row["decision_json"] != _canon(asdict(receipt)):
                raise ValueError("M6-B2 conflicting host decision")
            return row
        self._validate(row, active=True)
        status = "approved" if receipt.action == "APPROVE" else "rejected"
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                changed = db.execute(
                    "UPDATE m6b2_tickets SET status=?,decision_json=?,"
                    "updated_at=? WHERE ticket_id=? AND status='staged'",
                    (status, _canon(asdict(receipt)), _now(), receipt.ticket_id),
                )
                if changed.rowcount != 1:
                    raise ValueError("M6-B2 decision race")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.get(receipt.ticket_id)

    def _approved(self, row, *, active):
        if row is None or row["status"] not in ("approved", "claimed"):
            raise ValueError("M6-B2 explicit new execution APPROVE required")
        rec = OperatorGodotExecutionDecision(**json.loads(row["decision_json"]))
        if (rec.action != "APPROVE" or rec.fingerprint != row["fingerprint"]
                or rec.ticket_id != row["ticket_id"]):
            raise ValueError("M6-B2 approval receipt changed")
        if active and row["status"] != "approved":
            raise ValueError("M6-B2 execution permit already claimed")
        return self._validate(row, active=active)

    def assemble(self, ticket_id):
        row = self.get(ticket_id)
        saved = self._approved(
            row, active=(row is not None and row["status"] == "approved"),
        )
        if row["status"] == "approved":
            target = self._target()
            self._read_target(
                target.ingress, later_than=saved["admission_sample"]["lab_sample"],
                world=saved["world"],
            )
        else:
            operation = self._target().operations.get_operation(row["operation_id"])
            if operation is None or operation["goal_id"] != saved["goal_id"]:
                raise ValueError("M6-B2 claimed operation missing on recovery")
        return self._target(ticket_id=ticket_id)

    def execute_approved(self, ticket_id, target: B2Target):
        row = self.get(ticket_id)
        self._approved(
            row, active=(row is not None and row["status"] == "approved"),
        )
        if not isinstance(target, B2Target) or target.execution is None:
            raise ValueError("M6-B2 requires action-capable guarded target")
        executor = target.execution.executor
        guard = executor.handlers.get((DOOR_TOOL, DOOR_VERSION))
        if (not isinstance(guard, SandboxHandler)
                or not isinstance(guard.execute, M6B2GuardedHandler)
                or guard.execute.ticket_id != ticket_id
                or guard.execute.root != self.root
                or guard.execute.port_num != self.port.port
                or target.decision.goals is not self.b1.m5.core.internal_state.goals
                or target.decision.ingress.database_file
                   != self.target_root / "core_state.db"
                or target.decision.database_file != self.target_root / "core_work.db"
                or target.execution.store.database_file
                   != self.target_root / "execution.db"):
            raise ValueError("M6-B2 unguarded/mixed Core target denied")
        return target.execution.run(row["goal_id"])

    def claim_and_effect(self, ticket_id, handler_root, arguments, operation_id):
        """Called ONLY in the sandbox Tool worker; claim precedes any effect."""
        if Path(handler_root).resolve() != self.port.root:
            raise ValueError("M6-B2 wrong Godot Tool root")
        if arguments != {"subject_ref": DOOR_SUBJECT} or type(operation_id) is not str:
            raise ValueError("M6-B2 wrong Tool invocation")
        row = self.get(ticket_id)
        saved = self._approved(row, active=True)
        target = self._target()
        op = target.operations.get_operation(operation_id)
        if (op is None or op["status"] != "executing"
                or op["goal_id"] != saved["goal_id"]
                or op["task_id"] is None):
            raise ValueError("M6-B2 no executing canonical operation")
        action = target.operations.load_action(operation_id)
        spec = target.operations.load_verification_spec(operation_id)
        task = target.decision.tasks.get_task(op["task_id"])
        if (action.goal_id != saved["goal_id"]
                or action.persistent_task_id != op["task_id"]
                or action.candidate_id != ACTION.candidate_id
                or action.tool != DOOR_TOOL or action.tool_version != DOOR_VERSION
                or action.to_dict()["arguments"] != {"subject_ref": DOOR_SUBJECT}
                or spec.goal_id != saved["goal_id"]
                or spec.criterion_kind != "world.property_equals"
                or thaw(spec.parameters) != {
                    "subject_ref": DOOR_SUBJECT,
                    "predicate_ref": DOOR_PREDICATE,
                    "expected": {"type": "symbol", "value": "closed"},
                }
                or task is None or task.status != "active"
                or task.goal_id != saved["goal_id"]):
            raise ValueError("M6-B2 operation/Task/VerificationSpec mismatch")
        ops = target.operations.list_operations(task_id=op["task_id"])
        if len(ops) != 1 or ops[0]["id"] != operation_id:
            raise ValueError("M6-B2 duplicate or mismatched operations")
        measured = self._read_target(
            target.ingress, later_than=saved["admission_sample"]["lab_sample"],
            world=saved["world"],
        )
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                changed = db.execute(
                    "UPDATE m6b2_tickets SET status='claimed',operation_id=?,"
                    "consumed_event_id=?,updated_at=? WHERE ticket_id=?"
                    " AND status='approved' AND operation_id IS NULL",
                    (operation_id, measured["event_id"], _now(), ticket_id),
                )
                if changed.rowcount != 1:
                    raise ValueError("M6-B2 permit already consumed")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        # The adapter must NOT silently rebase onto a newer world revision.
        return self.port.execute(
            handler_root, arguments, operation_id,
            expected_world_instance=saved["world"]["world_instance_id"],
            expected_epoch=saved["world"]["epoch"],
            expected_revision=saved["world"]["world_revision"],
        )


@dataclass(frozen=True, slots=True)
class M6B2GuardedHandler:
    root: Path
    ticket_id: str
    port_num: int

    def __call__(self, handler_root, arguments, operation_id):
        try:
            gate = M6B2Admission.reopen(self.root, port_num=self.port_num)
            return gate.claim_and_effect(
                self.ticket_id, handler_root, arguments, operation_id,
            )
        except (ValueError, TypeError, KeyError, sqlite3.Error, RuntimeError) as exc:
            raise SandboxToolError(
                "M6B2_PRE_EFFECT_DENIED", str(exc), effect_possible=False,
            ) from exc


__all__ = [
    "M6B2Admission", "M6B2GuardedHandler", "OperatorGodotExecutionDecision",
    "B2Target", "SCHEMA", "OPERATOR",
]
