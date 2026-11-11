"""P3-B: narrow authorized door action, Stage6 ledger, independent verification.

This is NOT a generic agent scheduler. Caller explicitly invokes one bounded
run for a pre-existing, typed Goal. No LLM, hidden policy or world ground truth
is injected into Belief; all observations pass through registered CoreIngress.
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone

from anima.agent.tools import ToolRegistry
from anima.core.door_world import (
    DOOR_PREDICATE, DOOR_SOURCE, DOOR_SUBJECT, DOOR_TOOL, DOOR_VERSION,
    DoorWorldPort,
)
from anima.core.goal_decision import CoreGoalDecision
from anima.execution.contracts import (
    ExecutionAction, Observation, VerificationResult, VerificationSpec, thaw,
)
from anima.execution.sandbox import SandboxExecutor
from anima.execution.store import ExecutionStore
from anima.internal_state.goal_progress import (
    GoalObservation, GoalObservationKind, VerificationKind,
)
from anima.internal_state.runtime_integration import InternalStateRuntime


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


_VERIFY_SQL = """
CREATE TABLE IF NOT EXISTS core_world_proofs (
    goal_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    operation_id TEXT,
    candidate_id TEXT NOT NULL,
    verified_at TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class CoreDoorTurn:
    goal_id: str
    task_id: str | None
    outcome: str
    reason_code: str
    operation_id: str | None
    evidence_event_id: str | None
    receipt_status: str | None


class CoreDoorExecution:
    """One single-process trust boundary for the Stage6 door fixture.

    The trusted adapter owns the world file. The driver owns Goal verification,
    never the capability itself. No operations without an explicit Goal binding,
    registered active Task and a policy-fresh observation.
    """

    def __init__(
        self, *, decisions: CoreGoalDecision, internal_state: InternalStateRuntime,
        world: DoorWorldPort, execution_store: ExecutionStore,
        registry: ToolRegistry, executor: SandboxExecutor,
        after_effect_hook=None, before_execute_hook=None,
    ):
        if not isinstance(decisions, CoreGoalDecision):
            raise TypeError("CoreDoorExecution requires CoreGoalDecision")
        if not isinstance(internal_state, InternalStateRuntime):
            raise TypeError("CoreDoorExecution requires InternalStateRuntime")
        if not isinstance(world, DoorWorldPort):
            raise TypeError("CoreDoorExecution requires VirtualDoorWorld")
        if not isinstance(execution_store, ExecutionStore):
            raise TypeError("CoreDoorExecution requires ExecutionStore")
        if not isinstance(registry, ToolRegistry) or not isinstance(executor, SandboxExecutor):
            raise TypeError("CoreDoorExecution requires a Stage6 registry and executor")
        if executor.store is not execution_store or executor.registry is not registry:
            raise ValueError("ExecutionStore and ToolRegistry must be shared with Executor")
        if executor.root != world.root:
            raise ValueError("Executor must operate within the registered virtual world")
        if decisions.goals is not internal_state.goals:
            raise ValueError("Core GoalStore authority must be shared")
        source = decisions.ingress.sources.get(DOOR_SOURCE)
        rule = decisions.ingress.beliefs.properties.get((DOOR_SUBJECT, DOOR_PREDICATE))
        if source is None or rule is None or DOOR_SOURCE not in rule.allowed_sources:
            raise ValueError("Virtual door observer must be registered in Core Belief")
        if "state.property" not in source.allowed_kinds:
            raise ValueError("Virtual door source must admit property observations")
        descriptor = registry.get(DOOR_TOOL, DOOR_VERSION)
        if descriptor.idempotency != "keyed" or descriptor.effect_class != "reversible_write":
            raise ValueError("P3-B door requires keyed reversible-write admission")
        for hook in (after_effect_hook, before_execute_hook):
            if hook is not None and not callable(hook):
                raise TypeError("Fault-injection hooks must be callable")
        self.decisions = decisions
        self.internal_state = internal_state
        self.world = world
        self.store = execution_store
        self.registry = registry
        self.executor = executor
        self.after_effect_hook = after_effect_hook
        self.before_execute_hook = before_execute_hook
        # This table is only a durable verification receipt, not another GoalStore.
        with closing(self.decisions._connect()) as connection:
            connection.executescript(_VERIFY_SQL)

    def _proof(self, goal_id):
        with closing(self.decisions._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM core_world_proofs WHERE goal_id=?", (goal_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def _remember_proof(self, goal_id, task_id, event_id, operation_id, candidate_id):
        with closing(self.decisions._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                old = connection.execute(
                    "SELECT * FROM core_world_proofs WHERE goal_id=?", (goal_id,)
                ).fetchone()
                if old is None:
                    connection.execute(
                        "INSERT INTO core_world_proofs("
                        "goal_id,task_id,event_id,operation_id,candidate_id,verified_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (goal_id, task_id, event_id, operation_id, candidate_id, _now()),
                    )
                elif (
                    old["task_id"] != task_id
                    or old["event_id"] != event_id
                    or old["operation_id"] != operation_id
                    or old["candidate_id"] != candidate_id
                ):
                    raise ValueError("Core proof conflict for existing Goal")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _observe(self):
        raw, tick = self.world.sense()
        admitted = self.decisions.ingress.admit(raw, source_ref=DOOR_SOURCE)
        if admitted.status not in {"ACCEPTED", "ALREADY_SEEN"}:
            raise RuntimeError(f"Trusted world sensor failed admission: {admitted.status}")
        outcome = self.decisions.ingress.observation_outcome(admitted.event_id)
        if outcome is None or outcome["outcome"].startswith("REJECTED_"):
            raise RuntimeError("Trusted world sensor did not produce valid evidence")
        snapshot = self.decisions.ingress.read_belief(
            DOOR_SUBJECT, DOOR_PREDICATE, as_of_tick=tick
        )
        return admitted.event_id, tick, snapshot

    def _verified(self, goal_id, event_id, tick, snapshot):
        """Only Core Belief + the exact accepted sensor event can satisfy Goal."""
        binding = self.decisions._binding(goal_id)
        if binding is None:
            return False
        event = self.decisions.ingress.get_event(event_id)
        outcome = self.decisions.ingress.observation_outcome(event_id)
        if (
            event is None or outcome is None
            or event["source_ref"] != DOOR_SOURCE
            or event["kind"] != "state.property"
            or outcome["outcome"].startswith("REJECTED_")
            or outcome["outcome"] == "HISTORY_ONLY"
            or event_id not in snapshot["evidence_event_ids"]
            or snapshot["status"] != "known"
            or snapshot["freshness"] != "fresh"
            or snapshot["observed_tick"] != tick
            or binding["subject_ref"] != DOOR_SUBJECT
            or binding["predicate_ref"] != DOOR_PREDICATE
        ):
            return False
        return _json(snapshot["value"]) == binding["expected_json"]

    def _finish_task(self, task_id):
        task = self.decisions.tasks.get_task(task_id)
        if task is None:
            raise ValueError("Verified Task missing")
        if task.status == "completed":
            return
        if task.status in {"queued", "interrupted"}:
            self.decisions.tasks.transition_task(
                task_id, "active", reason="P3-B verified Goal recovery"
            )
            task = self.decisions.tasks.get_task(task_id)
        if task.status != "active":
            raise ValueError(f"Cannot finish Task in status {task.status}")
        self.decisions.tasks.transition_task(
            task_id, "completed", reason="P3-B independent world verification"
        )

    def _complete(self, goal_id, *, task_id, event_id, operation_id, candidate_id):
        """Persist verified evidence before separate Goal and Task commits."""
        goal = self.decisions.goals.get_goal(goal_id)
        task = self.decisions.tasks.get_task(task_id)
        if goal is None or goal["status"] not in {"active", "completed"}:
            raise ValueError("Verified Goal is not active/completed")
        if task is None or task.goal_id != goal_id or task.status in {"failed", "cancelled"}:
            raise ValueError("Verified Task no longer belongs to an eligible Goal")
        self._remember_proof(goal_id, task_id, event_id, operation_id, candidate_id)
        proof = self._proof(goal_id)
        # Stage2 source request identity must remain byte-for-byte stable.
        # Recover an interrupted Stage2 source operation even without a cold
        # Core reconstruction before reissuing the original observation.
        if goal["status"] == "active":
            self.internal_state.recovery.recover_pending()
            goal = self.decisions.goals.get_goal(goal_id)
        if goal["status"] == "active":
            self.internal_state.observe_goal(GoalObservation(
                goal_id=goal_id,
                kind=GoalObservationKind.SUCCESS,
                source_id=f"core.verify.{event_id}",
                reason="registered world readback satisfied typed ensure_once criterion",
                verification=VerificationKind.OBSERVATION,
                candidate_id=candidate_id,
                importance=1,
                criterion_satisfied=True,
                timestamp=proof["verified_at"],
            ))
        elif goal["status"] != "completed":
            raise ValueError("Cannot apply verified Goal success to inactive Goal")
        self._finish_task(task_id)

    def _authorize(self, decision, *, target):
        """Non-bypassable P3-B pre-effect guard, separate from Goal decision."""
        goal = self.decisions.goals.get_goal(decision.goal_id)
        task = None if decision.task_id is None else self.decisions.tasks.get_task(decision.task_id)
        if goal is None or goal["status"] != "active":
            return False, "GOAL_NOT_ACTIVE"
        if task is None or task.status != "active" or task.goal_id != decision.goal_id:
            return False, "TASK_NOT_ACTIVE"
        if decision.kind != "PROPOSE_ACTION" or decision.candidate is None:
            return False, "NO_ACTION_PROPOSAL"
        binding = self.decisions._binding(decision.goal_id)
        if binding is None:
            return False, "UNBOUND_GOAL"
        if (binding["subject_ref"], binding["predicate_ref"]) != (DOOR_SUBJECT, DOOR_PREDICATE):
            return False, "UNREGISTERED_TARGET"
        if binding["expected_json"] != _json({"type": "symbol", "value": target}):
            return False, "TARGET_MISMATCH"
        action = decision.candidate
        if (
            action.tool != DOOR_TOOL or action.tool_version != DOOR_VERSION
            or thaw(action.arguments) != {"subject_ref": DOOR_SUBJECT}
        ):
            return False, "UNREGISTERED_CAPABILITY"
        if decision.belief_revision is None:
            return False, "MISSING_BELIEF_REVISION"
        snapshot = self.decisions.ingress.read_belief(
            DOOR_SUBJECT, DOOR_PREDICATE, as_of_tick=decision.as_of_tick
        )
        if (
            snapshot["revision"] != decision.belief_revision
            or snapshot["status"] != "known"
            or snapshot["freshness"] != "fresh"
            or snapshot["value"] != {"type": "symbol", "value": "open"}
        ):
            return False, "STALE_ACTION_PRECONDITION"
        # Only trusted, explicitly bound tool schema may authorize this operation.
        self.registry.validate_input(action.tool, action.tool_version, thaw(action.arguments))
        return True, "ADMITTED"

    def _evidence_result(self, spec, action, receipt, event_id, tick, snapshot, verified):
        """Reuse Stage6 trace contracts, but derive outcome only from sensor data."""
        observation = Observation.create(
            action=action, receipt=receipt, source=DOOR_SOURCE,
            kind="world.property",
            data={
                "subject_ref": DOOR_SUBJECT,
                "predicate_ref": DOOR_PREDICATE,
                "core_event_id": event_id,
                "observed_tick": tick,
                "value": snapshot["value"],
            },
            observed_at=_now(),
        )
        result = VerificationResult.create(
            spec=spec,
            candidate_id=action.candidate_id,
            observations=(observation,),
            outcome="success" if verified else "failure",
            criterion_satisfied=verified,
            reason=(
                "independent virtual-world readback satisfies Goal"
                if verified else "post-action readback does not satisfy Goal"
            ),
            timestamp=_now(),
        )
        return observation, result

    def _postcheck(self, goal_id, task_id, *, action, receipt):
        event_id, tick, snapshot = self._observe()
        verified = self._verified(goal_id, event_id, tick, snapshot)
        spec = self.store.load_verification_spec(action.operation_id)
        observations, result = self._evidence_result(
            spec, action, receipt, event_id, tick, snapshot, verified
        )
        if verified:
            # Proof first. Stage2 Goal and Stage6 Task commits are independently
            # idempotent/recoverable through this one immutable proof record.
            self._complete(
                goal_id, task_id=task_id, event_id=event_id,
                operation_id=action.operation_id,
                candidate_id=action.candidate_id,
            )
            return CoreDoorTurn(
                goal_id, task_id, "VERIFIED_SUCCESS", "GOAL_SATISFIED",
                action.operation_id, event_id, receipt.status,
            )
        # Stage6 verification data is still produced for audited failure
        # but never applied as Goal success.
        return CoreDoorTurn(
            goal_id, task_id, "UNVERIFIED", result.reason,
            action.operation_id, event_id, receipt.status,
        )

    def _recover_proof(self, goal_id):
        proof = self._proof(goal_id)
        if proof is None:
            return None
        goal = self.decisions.goals.get_goal(goal_id)
        task = self.decisions.tasks.get_task(proof["task_id"])
        if goal is None or task is None or task.goal_id != goal_id:
            raise ValueError("Persisted Core proof references missing/mismatched identity")
        if goal["status"] == "cancelled" or task.status in {"cancelled", "failed"}:
            # A valid historical proof must not reverse a terminal cancellation.
            return CoreDoorTurn(
                goal_id, proof["task_id"], "DEFERRED",
                "PROOF_SUPERSEDED_BY_TERMINAL_STATE",
                proof["operation_id"], proof["event_id"], None,
            )
        if goal["status"] == "blocked":
            return CoreDoorTurn(
                goal_id, proof["task_id"], "DEFERRED",
                "GOAL_BLOCKED_WITH_VERIFIED_PROOF",
                proof["operation_id"], proof["event_id"], None,
            )
        # Never invent a new success; only resume a proof already persisted
        # after a verified accepted sensor observation.
        existing = self.decisions.ingress.get_event(proof["event_id"])
        if existing is None or existing["source_ref"] != DOOR_SOURCE:
            raise ValueError("Core verified Goal proof lacks original sensor event")
        self._complete(
            goal_id, task_id=proof["task_id"], event_id=proof["event_id"],
            operation_id=proof["operation_id"], candidate_id=proof["candidate_id"],
        )
        return CoreDoorTurn(
            goal_id, proof["task_id"], "RECOVERED_VERIFIED_SUCCESS",
            "PERSISTED_VERIFICATION_PROOF", proof["operation_id"],
            proof["event_id"], None
        )

    def recover_proofs(self, *, limit=4):
        """Finish persisted Goal/Task transitions without executing an effect."""
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError("Recovery limit must be 1..32")
        with closing(self.decisions._connect()) as connection:
            rows = connection.execute(
                "SELECT goal_id,task_id FROM core_world_proofs"
                " ORDER BY rowid"
            ).fetchall()
        if not rows:
            return ()
        # Historical successful proofs are revisited on every scheduler drain.
        # Load Goal/Task status once per batch instead of opening two separate
        # SQLite connections for each historical proof. This preserves
        # exhaustive identity checks and the existing proof ordering.
        goals = {
            goal["id"]: goal for goal in self.decisions.goals.list_goals()
        }
        tasks = {
            task.public_id: task for task in self.decisions.tasks.list_tasks()
        }
        recovered = []
        for row in rows:
            goal = goals.get(row["goal_id"])
            task = tasks.get(row["task_id"])
            if goal is None or task is None:
                raise ValueError("Persisted proof references missing Goal or Task")
            if goal["status"] == "completed" and task.status == "completed":
                continue
            # Proof is durable evidence, not authority to complete a
            # terminally cancelled Task or Goal or to unblock a paused Goal.
            # Skip these records and continue recovering unrelated Goals.
            if goal["status"] in {"blocked", "cancelled"}:
                continue
            if task.status in {"cancelled", "failed"}:
                continue
            if goal["status"] not in {"active", "completed"}:
                raise ValueError("Persisted proof references invalid Goal state")
            recovered.append(self._recover_proof(row["goal_id"]))
            if len(recovered) == limit:
                break
        return tuple(recovered)

    def _safe_load_verification_spec(self, operation_id):
        """Quarantine legacy incomplete intent without executing or poisoning other Goals.

        No action can be inferred from a prepared operation lacking a bound
        VerificationSpec. A later explicit operator repair is required.
        """
        try:
            return self.store.load_verification_spec(operation_id)
        except ValueError as error:
            if "has no persisted VerificationSpec" not in str(error):
                raise
            return None

    def run(self, goal_id):
        """One bounded explicit turn; never auto-create Goals or run in background."""
        recovered = self._recover_proof(goal_id)
        if recovered is not None:
            return recovered
        goal = self.decisions.goals.get_goal(goal_id)
        if goal is None:
            raise ValueError("Unknown Goal")
        binding = self.decisions._binding(goal_id)
        if goal["status"] != "active" or binding is None:
            return CoreDoorTurn(
                goal_id, None, "DEFERRED",
                "GOAL_NOT_ACTIVE" if goal["status"] != "active" else "UNBOUND_GOAL",
                None, None, None,
            )
        if (
            binding["mode"] != "ensure_once"
            or binding["criterion_kind"] != "world.property_equals"
            or binding["subject_ref"] != DOOR_SUBJECT
            or binding["predicate_ref"] != DOOR_PREDICATE
            or binding["expected_json"] != _json({"type": "symbol", "value": "closed"})
        ):
            return CoreDoorTurn(
                goal_id, None, "DENIED", "UNSUPPORTED_WORLD_GOAL", None, None, None
            )
        event_id, tick, snapshot = self._observe()
        decision = self.decisions.step(goal_id, as_of_tick=tick)
        if decision.kind in {"REQUEST_OBSERVATION", "DEFER"}:
            return CoreDoorTurn(
                goal_id, decision.task_id, "DEFERRED", decision.reason_code,
                None, event_id, None,
            )
        if decision.kind == "NOOP":
            # A prior effect may have committed just before a crash. Consult
            # the durable ledger before declaring that no operation occurred.
            operations = self.store.list_operations(task_id=decision.task_id)
            if len(operations) > 1:
                raise ValueError("Multiple operations for one ensure_once Task")
            recovered_operation_id = None
            recovered_candidate_id = "world.noop"
            if operations:
                operation = operations[0]
                action = self.store.load_action(operation["id"])
                persisted_spec = self._safe_load_verification_spec(operation["id"])
                if persisted_spec is None:
                    return CoreDoorTurn(
                        goal_id, decision.task_id, "DEFERRED",
                        "INCOMPLETE_EXECUTION_INTENT",
                        action.operation_id, event_id, None,
                    )
                if (
                    action.goal_id != goal_id
                    or action.persistent_task_id != decision.task_id
                    or action.tool != DOOR_TOOL or action.tool_version != DOOR_VERSION
                    or action.to_dict()["arguments"] != {"subject_ref": DOOR_SUBJECT}
                ):
                    raise ValueError("Recovered NOOP operation identity mismatch")
                recovered_operation_id = action.operation_id
                recovered_candidate_id = action.candidate_id
                if operation["status"] == "executing":
                    self.store.transition_operation(
                        action.operation_id, "uncertain",
                        reason="P3-B recovery: executing may have applied its effect",
                    )
                    operation = self.store.get_operation(action.operation_id)
                if operation["status"] == "uncertain":
                    outcome, _ = self.world.reconcile(
                        action.to_dict()["arguments"], action.operation_id
                    )
                    if outcome == "succeeded":
                        self.store.transition_operation(
                            action.operation_id, "succeeded",
                            reason="P3-B read-only keyed effect reconciliation",
                        )
                    # If world is closed but effect absent, the Goal can still
                    # succeed via independent observation. Ledger remains
                    # uncertain; no implicit tool retry or fabricated receipt.
            confirm_id, confirm_tick, confirmed = self._observe()
            if self._verified(goal_id, confirm_id, confirm_tick, confirmed):
                if operations and operation["status"] == "prepared":
                    self.store.transition_operation(
                        operation["id"], "cancelled",
                        reason="P3-B independent readback makes prepared effect unnecessary",
                    )
                self._complete(
                    goal_id, task_id=decision.task_id, event_id=confirm_id,
                    operation_id=recovered_operation_id,
                    candidate_id=recovered_candidate_id,
                )
                return CoreDoorTurn(
                    goal_id, decision.task_id, "VERIFIED_SUCCESS",
                    "NO_EFFECT_REQUIRED", recovered_operation_id, confirm_id, None,
                )
            return CoreDoorTurn(
                goal_id, decision.task_id, "UNVERIFIED", "NOOP_READBACK_CHANGED",
                None, confirm_id, None,
            )

        # Reobserve then recompute the decision. An observation can go stale
        # or change between the first proposal and the side-effect boundary.
        guard_id, guard_tick, _ = self._observe()
        guarded = self.decisions.step(goal_id, as_of_tick=guard_tick)
        allowed, reason = self._authorize(guarded, target="closed")
        if not allowed:
            return CoreDoorTurn(
                goal_id, guarded.task_id, "DENIED", reason, None, guard_id, None
            )

        task_id = guarded.task_id
        ops = self.store.list_operations(task_id=task_id)
        if len(ops) > 1:
            raise ValueError("Multiple operations for single P3-B ensure_once Task")
        if ops:
            operation = ops[0]
            action = self.store.load_action(operation["id"])
            spec = self._safe_load_verification_spec(operation["id"])
            if spec is None:
                return CoreDoorTurn(
                    goal_id, task_id, "DEFERRED",
                    "INCOMPLETE_EXECUTION_INTENT",
                    action.operation_id, guard_id, None,
                )
            if (
                action.goal_id != goal_id or action.persistent_task_id != task_id
                or action.tool != DOOR_TOOL or action.tool_version != DOOR_VERSION
                or action.to_dict()["arguments"] != {"subject_ref": DOOR_SUBJECT}
                or spec.goal_id != goal_id
                or spec.criterion_kind != "world.property_equals"
            ):
                raise ValueError("Recovered ExecutionAction/VerificationSpec mismatch")
            status = operation["status"]
            if status == "executing":
                self.store.transition_operation(
                    action.operation_id, "uncertain",
                    reason="P3-B crash recovery: executing is ambiguous",
                )
                status = "uncertain"
            if status == "uncertain":
                # Reconcile ONLY; do not call SandboxExecutor, which is allowed
                # to retry keyed operations when it finds a missing effect.
                state, _ = self.world.reconcile(
                    action.to_dict()["arguments"], action.operation_id
                )
                if state == "succeeded":
                    self.store.transition_operation(
                        action.operation_id, "succeeded",
                        reason="P3-B read-only keyed side-effect reconciliation",
                    )
                    status = "succeeded"
                else:
                    return CoreDoorTurn(
                        goal_id, task_id, "DEFERRED", "UNCERTAIN_EFFECT_NOT_RETRIED",
                        action.operation_id, guard_id, None,
                    )
            if status in {"failed", "cancelled"}:
                return CoreDoorTurn(
                    goal_id, task_id, "DEFERRED", "PREVIOUS_OPERATION_TERMINAL",
                    action.operation_id, guard_id, None,
                )
            if status == "succeeded":
                # Never run a completed effect again. Verify current state.
                event_id, tick, snapshot = self._observe()
                if self._verified(goal_id, event_id, tick, snapshot):
                    self._complete(
                        goal_id, task_id=task_id, event_id=event_id,
                        operation_id=action.operation_id,
                        candidate_id=action.candidate_id,
                    )
                    return CoreDoorTurn(
                        goal_id, task_id, "VERIFIED_SUCCESS", "RECOVERED_READBACK",
                        action.operation_id, event_id, None,
                    )
                return CoreDoorTurn(
                    goal_id, task_id, "UNVERIFIED", "RECOVERED_EFFECT_NOT_SUFFICIENT",
                    action.operation_id, event_id, None,
                )
            if status != "prepared":
                raise ValueError("Unknown recovered ExecutionOperation state")
        else:
            action = ExecutionAction.from_spec(
                guarded.candidate, registry=self.registry,
                persistent_task_id=task_id, goal_id=goal_id, created_at=_now(),
            )
            spec = VerificationSpec.create(
                goal_id=goal_id,
                criterion_kind="world.property_equals",
                parameters={
                    "subject_ref": DOOR_SUBJECT, "predicate_ref": DOOR_PREDICATE,
                    "expected": {"type": "symbol", "value": "closed"},
                },
            )
            # Operation, Action and VerificationSpec commit atomically in
            # the existing Stage6 SQLite DB. No partial new Core intent.
            self.store.create_operation(
                action, registry=self.registry, verification_spec=spec,
                reason="P3-B admitted typed Goal action",
            )

        # Boundary check again: Task/Goal could be cancelled after preparation.
        if self.before_execute_hook is not None:
            self.before_execute_hook(goal_id)
        allowed, reason = self._authorize(guarded, target="closed")
        if not allowed:
            return CoreDoorTurn(
                goal_id, task_id, "DENIED", reason, action.operation_id, guard_id, None
            )

        receipt = self.executor.execute(action)
        if self.after_effect_hook is not None:
            self.after_effect_hook(goal_id)
        return self._postcheck(
            goal_id, task_id, action=action, receipt=receipt
        )


__all__ = ["CoreDoorExecution", "CoreDoorTurn"]
