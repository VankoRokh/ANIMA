"""E2.5c: opt-in Stage2/Stage6 spatial action authority for experimental worlds.

This is a *neutral, reusable Core boundary*. It never imports Godot or the lab.
It owns Goal/Task/ExecutionOperation and exact CoreIngress source admission;
the caller supplies a trusted, explicitly registered ToolRegistry/handler and
sealed sensor proof. No direct model-specified tools, arbitrary OS capability,
or unregistered source. No automatic retry on uncertain effects.

Unlike the original door-only CoreGoalDecision, the spatial Goal's task is
multi-step; each admitted step owns a *new* Stage6 Task and operation. This
gateway does not claim independent physical Verification or E4 atomicity.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from anima.agent.tools import ToolRegistry
from anima.core.assembly import CoreAssembly
from anima.execution.contracts import ActionSpec, ExecutionAction, VerificationSpec
from anima.execution.store import ExecutionStore
from anima.execution.sandbox import SandboxExecutor
from anima.tasks.store import TaskStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


class CoreSpatialAdmissionError(RuntimeError):
    """An unverifiable request cannot cross the world-effect boundary."""


@dataclass(frozen=True, slots=True)
class SpatialSourceProof:
    """Full sealed Raw + Core-ingested SHA pointer; not a discretionary LLM claim."""

    sample_id: str
    raw_json: str
    core_event_id: str


@dataclass(frozen=True, slots=True)
class PreparedSpatialAction:
    goal_id: str
    task_id: str
    operation_id: str
    action: ExecutionAction
    spec: VerificationSpec
    pre_sample_id: str
    source_event_id: str


class CoreSpatialActionGateway:
    """Guarded, source-backed Stage6 preparation.

    A single process owns the scheduler and tool executor. A new Goal is never
    implicitly created here. Core GoalStore/TaskStore and ExecutionStore are
    the canonical lifecycle owners; this class has no parallel task ledger.
    """

    def __init__(
        self, *, core: CoreAssembly, store: ExecutionStore,
        registry: ToolRegistry, executor: SandboxExecutor,
        allowed_capabilities: Mapping[str, tuple[str, str]],
        source_ref: str, producer_ref: str,
        subject_ref: str, predicate_ref: str,
    ):
        if not isinstance(core, CoreAssembly) or core.core_events is None:
            raise CoreSpatialAdmissionError("CoreAssembly requires registered CoreIngress")
        if not isinstance(store, ExecutionStore) or not isinstance(registry, ToolRegistry):
            raise TypeError("Stage6 ExecutionStore and exact ToolRegistry required")
        if not isinstance(executor, SandboxExecutor) or executor.store is not store or executor.registry is not registry:
            raise CoreSpatialAdmissionError("Stage6 executor/store/registry identity mismatch")
        if (type(allowed_capabilities) is not dict
                or set(allowed_capabilities) != {"world.turn", "world.step"}):
            raise ValueError("trusted exact spatial allowlist required")
        selected = dict(allowed_capabilities)
        if any(not isinstance(v, tuple) or len(v) != 2 for v in selected.values()):
            raise ValueError("invalid fixed capability mapping")
        for name, version in selected.values():
            if registry.get(name, version) is None or (name, version) not in executor.handlers:
                raise CoreSpatialAdmissionError("allowed capability missing trusted executable")
        source = core.core_events.ingress.sources.get(source_ref)
        if source is None or source.producer_ref != producer_ref or "state.property" not in source.allowed_kinds:
            raise CoreSpatialAdmissionError("unregistered exact Core source/producer")
        rule = core.core_events.ingress.beliefs.properties.get((subject_ref, predicate_ref))
        if (rule is None or rule.value_type != "string" or source_ref not in rule.allowed_sources):
            raise CoreSpatialAdmissionError("missing registered string view digest property")
        self.core = core
        self.store = store
        self.registry = registry
        self.executor = executor
        self.capabilities = selected
        self.source_ref = source_ref
        self.producer_ref = producer_ref
        self.subject_ref = subject_ref
        self.predicate_ref = predicate_ref
        # TaskStore's canonical database is shared with CoreGoalDecision when
        # that optional decision module exists. Do not force a dummy Goal
        # action registry merely to obtain the real Stage6 Task store.
        self.tasks = (
            core.core_decision.tasks if core.core_decision is not None
            else TaskStore(core.data_dir / "tasks.db")
        )
        self.goals = core.internal_state.goals

    def _raw(self, proof: SpatialSourceProof) -> dict:
        if not isinstance(proof, SpatialSourceProof):
            raise CoreSpatialAdmissionError("typed sealed source proof required")
        if any(type(x) is not str or not x for x in (
            proof.sample_id, proof.raw_json, proof.core_event_id,
        )):
            raise CoreSpatialAdmissionError("empty evidence identities")
        try:
            snap = json.loads(proof.raw_json)
        except (ValueError, TypeError) as exc:
            raise CoreSpatialAdmissionError("Raw JSON is invalid") from exc
        if type(snap) is not dict:
            raise CoreSpatialAdmissionError("Raw is not an object")
        digest = hashlib.sha256(proof.raw_json.encode("utf-8")).hexdigest()
        ingress = self.core.core_events.ingress
        event = ingress.get_event(proof.core_event_id)
        if event is None:
            raise CoreSpatialAdmissionError("unknown canonical Core event")
        expected_value = {"type": "string", "value": digest}
        expected_clock = snap.get("sample_seq")
        if (
            event["source_ref"] != self.source_ref
            or event["producer_ref"] != self.producer_ref
            or event["kind"] != "state.property"
            or event["occurrence_id"] != "e24:" + proof.sample_id
            or event["payload"].get("subject_ref") != self.subject_ref
            or event["payload"].get("predicate_ref") != self.predicate_ref
            or event["payload"].get("source_revision") != expected_clock
            or event["payload"].get("value") != expected_value
            or snap.get("sample_id") != proof.sample_id
            or snap.get("source_ref") != self.source_ref
            or type(expected_clock) is not int or expected_clock < 1
        ):
            raise CoreSpatialAdmissionError("Core event does not attest to supplied full Raw")
        receipt = ingress.dispatch_receipt(proof.core_event_id)
        if receipt is None or receipt["disposition"] != "forwarded":
            raise CoreSpatialAdmissionError("Core event missing forward receipt")
        belief = ingress.read_belief(
            self.subject_ref, self.predicate_ref, as_of_tick=expected_clock,
        )
        if (belief["status"] != "known" or belief["freshness"] != "fresh"
                or belief["value"] != expected_value
                or proof.core_event_id not in belief["evidence_event_ids"]):
            raise CoreSpatialAdmissionError("stale or contradicted Core Belief")
        required = {"world_instance_id", "epoch", "revision", "tick", "sample_seq"}
        if any(type(snap.get(k)) is not int for k in required - {"world_instance_id"}):
            raise CoreSpatialAdmissionError("invalid sensor clock")
        if type(snap.get("world_instance_id")) is not str:
            raise CoreSpatialAdmissionError("invalid sensor world")
        return snap

    def prepare(
        self, *, goal_id: str, proof: SpatialSourceProof,
        tool_kind: str, direction: str, reason: str,
    ) -> PreparedSpatialAction:
        """Persist a typed, *nonexecuting* Stage6 operation + VerificationSpec.

        Any previous Task/Operation from the same Goal must be already
        verified and terminal. An orphan or ambiguous effect blocks new work.
        """
        snap = self._raw(proof)
        goal = self.goals.get_goal(goal_id)
        if goal is None or goal["status"] != "active" or goal["source"] != "lab.visual":
            raise CoreSpatialAdmissionError("spatial action requires active registered Goal")
        if type(reason) is not str or not reason or len(reason) > 128:
            raise CoreSpatialAdmissionError("bounded action reason required")
        if type(tool_kind) is not str or tool_kind not in self.capabilities:
            raise CoreSpatialAdmissionError("unregistered world action")
        if ((tool_kind == "world.turn" and direction not in ("left", "right"))
                or (tool_kind == "world.step" and direction != "forward")):
            raise CoreSpatialAdmissionError("invalid egocentric capability arguments")
        # Fail closed on any previously issued incomplete Stage6 Task under this
        # Goal. Our caller must complete/verify the prior action before another.
        existing_tasks = self.tasks.list_tasks(goal_id=goal_id)
        if any(task.status != "completed" for task in existing_tasks):
            raise CoreSpatialAdmissionError("existing spatial Task not terminally verified")
        for task in existing_tasks:
            operations = self.store.list_operations(task_id=task.public_id)
            if len(operations) != 1 or operations[0]["status"] != "succeeded":
                raise CoreSpatialAdmissionError("prior Stage6 operation not succeeded")
        tool, version = self.capabilities[tool_kind]
        arguments = {
            "world_instance_id": snap["world_instance_id"],
            "epoch": snap["epoch"],
            "observation_id": snap["sample_id"],
            "expected_revision": snap["revision"],
            "pre_tick": snap["tick"],
            "direction": direction,
        }
        candidate = ActionSpec(
            candidate_id="spatial." + tool_kind + "." + direction,
            tool=tool, tool_version=version, arguments=arguments,
        )
        candidate.validate_tool_input(self.registry)
        task = self.tasks.create_task(
            source="core.spatial", source_id=goal_id,
            goal_id=goal_id,
            description="One bounded egocentric action from verified Core view",
            reason=reason,
        )
        self.tasks.transition_task(
            task.public_id, "active", reason="Core admitted typed spatial action",
        )
        action = ExecutionAction.from_spec(
            candidate, registry=self.registry,
            persistent_task_id=task.public_id, goal_id=goal_id,
            created_at=_now(),
        )
        spec = VerificationSpec.create(
            goal_id=goal_id, criterion_kind="world.egocentric_transition",
            parameters={
                "before_sample_id": proof.sample_id,
                "source_event_id": proof.core_event_id,
                "raw_sha256": hashlib.sha256(proof.raw_json.encode("utf-8")).hexdigest(),
                "world_instance_id": snap["world_instance_id"],
                "epoch": snap["epoch"],
                "expected_revision": snap["revision"],
                "expected_tick": snap["tick"],
                "action_type": tool_kind,
                "direction": direction,
            },
        )
        self.store.create_operation(
            action, registry=self.registry, verification_spec=spec,
            reason="Core: source-bound spatial Task and staged VerificationSpec",
        )
        return PreparedSpatialAction(
            goal_id, task.public_id, action.operation_id, action, spec,
            proof.sample_id, proof.core_event_id,
        )

    def before_effect(self, prepared: PreparedSpatialAction,
                      *, proof: SpatialSourceProof) -> None:
        """Refuse execution if Goal, Task, Core pointer or plan was altered."""
        if not isinstance(prepared, PreparedSpatialAction):
            raise CoreSpatialAdmissionError("prepared Stage6 action required")
        snap = self._raw(proof)
        goal = self.goals.get_goal(prepared.goal_id)
        task = self.tasks.get_task(prepared.task_id)
        operation = self.store.get_operation(prepared.operation_id)
        stored_action = self.store.load_action(prepared.operation_id)
        spec = self.store.load_verification_spec(prepared.operation_id)
        if (goal is None or goal["status"] != "active"
                or task is None or task.goal_id != prepared.goal_id
                or task.status != "active" or task.source != "core.spatial"
                or operation is None or operation["status"] != "prepared"
                or stored_action.to_dict() != prepared.action.to_dict()
                or spec != prepared.spec
                or proof.sample_id != prepared.pre_sample_id
                or proof.core_event_id != prepared.source_event_id
                or snap["revision"] != prepared.action.to_dict()["arguments"]["expected_revision"]):
            raise CoreSpatialAdmissionError("Stage2/Stage6 binding drifted before effect")

    def execute_once(
        self, prepared: PreparedSpatialAction, *, proof: SpatialSourceProof,
    ):
        """The only trusted Stage6 route into the world effect handler."""
        self.before_effect(prepared, proof=proof)
        return self.executor.execute(prepared.action)

    def finish_verified(self, prepared: PreparedSpatialAction, *,
                        verified: bool, outcome: str) -> None:
        """Only after independent world receipt+new Raw verified by caller.

        Do NOT turn Goal into completed here. It is a multi-step goal with
        independent criterion; caller separately verifies and reports success.
        """
        if type(verified) is not bool or not verified:
            raise CoreSpatialAdmissionError("unverified action cannot complete Task")
        if outcome not in ("VERIFIED_EFFECT", "VERIFIED_BLOCKED"):
            raise CoreSpatialAdmissionError("invalid spatial verification result")
        operation = self.store.get_operation(prepared.operation_id)
        task = self.tasks.get_task(prepared.task_id)
        if (operation is None or operation["status"] != "succeeded"
                or task is None or task.status != "active"
                or self.goals.get_goal(prepared.goal_id)["status"] != "active"):
            raise CoreSpatialAdmissionError("Stage2/Stage6 state does not allow verification")
        self.tasks.transition_task(
            prepared.task_id, "completed",
            reason="Godot readback and new Core Raw corroborate result: " + outcome,
        )


__all__ = [
    "CoreSpatialActionGateway", "SpatialSourceProof", "PreparedSpatialAction",
    "CoreSpatialAdmissionError",
]
