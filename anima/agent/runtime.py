from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import uuid4

from anima.agent.choice_adapter import CandidateHistoryEntry, ProposalChoiceCoordinator
from anima.agent.contracts import Action, Observation, VerificationSpec
from anima.agent.executor import SandboxExecutor, action_request_hash, operation_kind
from anima.agent.planner import PlannerAdapter, PlannerRequest
from anima.agent.store import AgentStore
from anima.agent.tools import ToolRegistry
from anima.agent.verification import (
    DeterministicGoalVerifier,
    GoalVerificationBridge,
)


MAX_BASELINE_STEPS = 64
RECENT_RUNTIME_ITEMS = 16


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json_object(value, label):
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return dict(value)


def _observation_from_receipt(action, receipt):
    """Normalize one technical receipt into factual Observation without hidden I/O."""

    if not isinstance(action, Action):
        raise TypeError("observation normalization requires an Action")
    arguments = action.to_dict()["arguments"]
    receipt_record = receipt.to_dict()
    output = receipt_record["output"]
    observed_at = receipt.finished_at

    if receipt.status == "succeeded":
        if action.tool == "fs.read":
            kind = "file.content"
            data = dict(output)
        elif action.tool == "fs.write":
            kind = "file.write"
            data = dict(output)
        elif action.tool == "fs.list":
            kind = "directory.listing"
            data = dict(output)
        else:
            kind = "tool.result"
            data = {
                "tool": action.tool,
                "tool_version": action.tool_version,
                "output": output,
            }
    elif receipt.status == "timeout":
        kind = "tool.timeout"
        data = {
            "tool": action.tool,
            "tool_version": action.tool_version,
            "error_code": receipt.error_code,
            "message": receipt.error_message,
        }
        if isinstance(arguments.get("path"), str):
            data["path"] = arguments["path"]
    elif action.tool == "fs.read" and receipt.error_code in {
        "NOT_FOUND",
        "NOT_FILE",
        "FILE_TOO_LARGE",
        "UNSUPPORTED_ENCODING",
    }:
        kind = "file.unavailable"
        data = {
            "path": arguments["path"],
            "error_code": receipt.error_code,
            "message": receipt.error_message,
        }
    else:
        kind = "tool.failure"
        data = {
            "tool": action.tool,
            "tool_version": action.tool_version,
            "error_code": receipt.error_code,
            "message": receipt.error_message,
        }
        if isinstance(arguments.get("path"), str):
            data["path"] = arguments["path"]

    return Observation.create(
        action=action,
        receipt=receipt,
        source="sandbox_executor",
        kind=kind,
        data=data,
        observed_at=observed_at,
    )


def _history_entry(action, receipt, verification_result):
    if receipt.status != "succeeded":
        outcome = "failure"
        verified = True
    else:
        outcome = verification_result.outcome
        verified = outcome != "none"
    return CandidateHistoryEntry(
        tool=action.tool,
        tool_version=action.tool_version,
        arguments=action.to_dict()["arguments"],
        outcome=outcome,
        verified=verified,
    )


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    step_id: str
    planner_turn: object
    choice: Mapping | None
    action: Action | None
    receipt: object | None
    observation: Observation | None
    verification_result: object | None
    verification_application: object | None

    def summary(self):
        return {
            "step_id": self.step_id,
            "planner_turn_id": self.planner_turn.public_id,
            "planner_status": self.planner_turn.status,
            "selected_proposal_id": (
                self.choice["selected_proposal_id"] if self.choice is not None else None
            ),
            "action_id": self.action.public_id if self.action is not None else None,
            "receipt_status": self.receipt.status if self.receipt is not None else None,
            "observation_id": (
                self.observation.public_id if self.observation is not None else None
            ),
            "verification_outcome": (
                self.verification_result.outcome
                if self.verification_result is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    run: Mapping
    goal: Mapping
    verification_spec: VerificationSpec
    turns: tuple[AgentTurnResult, ...]
    stop_reason: str

    @property
    def completed(self):
        return self.run["status"] == "completed" and self.goal["status"] == "completed"

    def snapshot(self):
        return {
            "run": dict(self.run),
            "goal": dict(self.goal),
            "verification_spec": self.verification_spec.to_dict(),
            "turns": [turn.summary() for turn in self.turns],
            "stop_reason": self.stop_reason,
        }


class AgentLoop:
    """Stage 4.8 headless one-action-per-turn orchestration baseline."""

    def __init__(
        self,
        *,
        store,
        registry,
        planner,
        choice,
        executor,
        verifier,
        verification_bridge,
        context_provider=None,
    ):
        if not isinstance(store, AgentStore):
            raise TypeError("AgentLoop store must be an AgentStore")
        if not isinstance(registry, ToolRegistry):
            raise TypeError("AgentLoop registry must be a ToolRegistry")
        if not isinstance(planner, PlannerAdapter):
            raise TypeError("AgentLoop planner must be a PlannerAdapter")
        if not isinstance(choice, ProposalChoiceCoordinator):
            raise TypeError("AgentLoop choice must be a ProposalChoiceCoordinator")
        if not isinstance(executor, SandboxExecutor):
            raise TypeError("AgentLoop executor must be a SandboxExecutor")
        if not isinstance(verifier, DeterministicGoalVerifier):
            raise TypeError("AgentLoop verifier must be a DeterministicGoalVerifier")
        if not isinstance(verification_bridge, GoalVerificationBridge):
            raise TypeError(
                "AgentLoop verification_bridge must be a GoalVerificationBridge"
            )
        if context_provider is not None and not callable(context_provider):
            raise TypeError("AgentLoop context_provider must be callable or null")
        if executor.store is not store:
            raise ValueError("AgentLoop Executor must use the same AgentStore")
        if executor.registry is not registry:
            raise ValueError("AgentLoop Executor must use the same ToolRegistry")
        if choice.registry is not registry:
            raise ValueError("AgentLoop Choice must use the same ToolRegistry")
        if verification_bridge.agent_store is not store:
            raise ValueError("AgentLoop VerificationBridge must use the same AgentStore")

        self.store = store
        self.registry = registry
        self.planner = planner
        self.choice = choice
        self.executor = executor
        self.verifier = verifier
        self.verification_bridge = verification_bridge
        self.goal_store = verification_bridge.recovery.goal_store
        self.context_provider = context_provider

    def start_run(self, goal_id):
        goal = self.goal_store.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Unknown Goal: {goal_id}")
        if goal["status"] != "active":
            raise ValueError(
                f"AgentRun requires an active Goal, got {goal['status']!r}"
            )
        run = self.store.create_run(
            goal_id=goal_id,
            planner=self.planner.name,
            planner_version=self.planner.version,
            reason="AgentLoop run created",
        )
        return self.store.transition_run(
            run["id"],
            "running",
            reason="AgentLoop started",
        )

    def _context(self, goal, observations, history):
        if self.context_provider is None:
            return {}
        value = self.context_provider(
            dict(goal),
            tuple(item.to_dict() for item in observations),
            tuple(history),
        )
        return _json_object(value, "AgentLoop context_provider result")

    @staticmethod
    def _validate_step_limit(max_steps):
        if (
            not isinstance(max_steps, int)
            or isinstance(max_steps, bool)
            or not 1 <= max_steps <= MAX_BASELINE_STEPS
        ):
            raise ValueError(
                f"AgentLoop max_steps must be within 1..{MAX_BASELINE_STEPS}"
            )

    def _planner_request(
        self,
        *,
        run,
        step,
        goal,
        observations,
        history,
        turn_results,
        max_steps,
    ):
        recent_steps = [
            turn.summary() for turn in turn_results[-RECENT_RUNTIME_ITEMS:]
        ]
        recent_observations = [
            item.to_dict() for item in observations[-RECENT_RUNTIME_ITEMS:]
        ]
        remaining = max_steps - len(turn_results)
        return PlannerRequest(
            run_id=run["id"],
            step_id=step["id"],
            goal_id=goal["id"],
            goal_description=goal["description"],
            success_criterion=goal["success_criterion"],
            context=self._context(goal, observations, history),
            tools=self.registry.list_descriptors(),
            recent_steps=tuple(recent_steps),
            recent_observations=tuple(recent_observations),
            constraints={"one_action_per_turn": True},
            remaining_budget={"steps": remaining},
        )

    def _finish_without_action(self, *, run, step, planner_turn, turns):
        self.store.transition_step(
            step["id"],
            "completed",
            reason="Planner cannot progress",
        )
        turn = AgentTurnResult(
            step_id=step["id"],
            planner_turn=planner_turn,
            choice=None,
            action=None,
            receipt=None,
            observation=None,
            verification_result=None,
            verification_application=None,
        )
        turns.append(turn)
        final_run = self.store.transition_run(
            run["id"],
            "failed",
            reason="Planner reported cannot_progress",
        )
        goal = self.goal_store.get_goal(run["goal_id"])
        return AgentLoopResult(
            run=MappingProxyType(dict(final_run)),
            goal=MappingProxyType(dict(goal)),
            verification_spec=None,
            turns=tuple(turns),
            stop_reason="planner_cannot_progress",
        )

    def run(self, run_id, verification_spec, *, max_steps=8):
        self._validate_step_limit(max_steps)
        if not isinstance(verification_spec, VerificationSpec):
            raise TypeError("AgentLoop run requires a VerificationSpec")

        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown AgentRun: {run_id}")
        if run["status"] != "running":
            raise ValueError(
                f"AgentLoop run requires running AgentRun, got {run['status']!r}"
            )
        if verification_spec.run_id != run_id:
            raise ValueError("VerificationSpec does not belong to AgentRun")
        if self.store.list_steps(run_id=run_id):
            raise ValueError(
                "Stage 4.8 baseline starts from a fresh AgentRun; persisted resume belongs to 4.11"
            )

        goal = self.goal_store.get_goal(run["goal_id"])
        if goal is None:
            raise ValueError(f"Unknown Goal: {run['goal_id']}")
        if goal["status"] != "active":
            raise ValueError(
                f"AgentLoop requires an active Goal, got {goal['status']!r}"
            )

        observations = []
        history = []
        turns = []

        for _ in range(max_steps):
            goal = self.goal_store.get_goal(run["goal_id"])
            if goal["status"] == "completed":
                final_run = self.store.transition_run(
                    run_id,
                    "completed",
                    reason="Goal already completed",
                )
                return AgentLoopResult(
                    run=MappingProxyType(dict(final_run)),
                    goal=MappingProxyType(dict(goal)),
                    verification_spec=verification_spec,
                    turns=tuple(turns),
                    stop_reason="goal_completed",
                )
            if goal["status"] == "cancelled":
                final_run = self.store.transition_run(
                    run_id,
                    "cancelled",
                    reason="Goal cancelled",
                )
                return AgentLoopResult(
                    run=MappingProxyType(dict(final_run)),
                    goal=MappingProxyType(dict(goal)),
                    verification_spec=verification_spec,
                    turns=tuple(turns),
                    stop_reason="goal_cancelled",
                )
            if goal["status"] == "blocked":
                final_run = self.store.transition_run(
                    run_id,
                    "interrupted",
                    reason="Goal blocked",
                )
                return AgentLoopResult(
                    run=MappingProxyType(dict(final_run)),
                    goal=MappingProxyType(dict(goal)),
                    verification_spec=verification_spec,
                    turns=tuple(turns),
                    stop_reason="goal_blocked",
                )

            step = self.store.create_step(
                run_id=run_id,
                reason="AgentLoop turn created",
            )
            request = self._planner_request(
                run=run,
                step=step,
                goal=goal,
                observations=observations,
                history=history,
                turn_results=turns,
                max_steps=max_steps,
            )
            planner_turn = self.planner.plan(request)
            self.store.transition_step(
                step["id"],
                "planned",
                reason=f"PlannerTurn {planner_turn.public_id} produced",
            )

            if planner_turn.status == "cannot_progress":
                self.store.transition_step(
                    step["id"],
                    "completed",
                    reason="Planner reported cannot_progress",
                )
                turns.append(
                    AgentTurnResult(
                        step_id=step["id"],
                        planner_turn=planner_turn,
                        choice=None,
                        action=None,
                        receipt=None,
                        observation=None,
                        verification_result=None,
                        verification_application=None,
                    )
                )
                final_run = self.store.transition_run(
                    run_id,
                    "failed",
                    reason="Planner reported cannot_progress",
                )
                return AgentLoopResult(
                    run=MappingProxyType(dict(final_run)),
                    goal=MappingProxyType(dict(goal)),
                    verification_spec=verification_spec,
                    turns=tuple(turns),
                    stop_reason="planner_cannot_progress",
                )

            choice_result = self.choice.choose(
                goal["id"],
                planner_turn,
                history=tuple(history),
            )
            selected = choice_result["selected_proposal"]
            operation_id = f"aop_{uuid4()}"
            action = Action.from_proposal(
                selected,
                registry=self.registry,
                run_id=run_id,
                step_id=step["id"],
                operation_id=operation_id,
                created_at=_now(),
            )
            self.store.transition_step(
                step["id"],
                "selected",
                reason=f"Choice selected {selected.public_id}",
            )
            descriptor = self.registry.get(action.tool, action.tool_version)
            self.store.create_operation(
                run_id=run_id,
                step_id=step["id"],
                action_id=action.public_id,
                operation_kind=operation_kind(action),
                request_hash=action_request_hash(action),
                idempotency_class=descriptor.idempotency,
                public_id=operation_id,
                reason="Action intent persisted before execution",
            )
            self.store.transition_step(
                step["id"],
                "executing",
                reason=f"Action {action.public_id} executing",
            )
            receipt = self.executor.execute(action)
            operation = self.store.get_operation(operation_id)

            if operation["status"] == "uncertain":
                turns.append(
                    AgentTurnResult(
                        step_id=step["id"],
                        planner_turn=planner_turn,
                        choice=choice_result,
                        action=action,
                        receipt=receipt,
                        observation=None,
                        verification_result=None,
                        verification_application=None,
                    )
                )
                final_run = self.store.transition_run(
                    run_id,
                    "interrupted",
                    reason="Tool effect is uncertain; recovery required",
                )
                return AgentLoopResult(
                    run=MappingProxyType(dict(final_run)),
                    goal=MappingProxyType(dict(goal)),
                    verification_spec=verification_spec,
                    turns=tuple(turns),
                    stop_reason="uncertain_tool_effect",
                )

            self.store.transition_step(
                step["id"],
                "executed",
                reason=f"ExecutionReceipt {receipt.public_id} recorded in runtime trace",
            )
            observation = _observation_from_receipt(action, receipt)
            observations.append(observation)
            self.store.transition_step(
                step["id"],
                "observed",
                reason=f"Observation {observation.public_id} produced",
            )
            verification_result = self.verifier.verify(
                verification_spec,
                step_id=step["id"],
                candidate_id=selected.public_id,
                observations=tuple(observations),
                timestamp=observation.observed_at,
            )
            application = self.verification_bridge.apply(
                spec=verification_spec,
                result=verification_result,
                observations=tuple(observations),
            )
            self.store.transition_step(
                step["id"],
                "verified",
                reason=(
                    f"VerificationResult {verification_result.public_id} "
                    f"outcome={verification_result.outcome}"
                ),
            )
            history.append(_history_entry(action, receipt, verification_result))
            self.store.transition_step(
                step["id"],
                "completed",
                reason="AgentLoop turn completed",
            )
            turns.append(
                AgentTurnResult(
                    step_id=step["id"],
                    planner_turn=planner_turn,
                    choice=choice_result,
                    action=action,
                    receipt=receipt,
                    observation=observation,
                    verification_result=verification_result,
                    verification_application=application,
                )
            )

            goal = self.goal_store.get_goal(run["goal_id"])
            if goal["status"] == "completed":
                final_run = self.store.transition_run(
                    run_id,
                    "completed",
                    reason="Verified Goal criterion satisfied",
                )
                return AgentLoopResult(
                    run=MappingProxyType(dict(final_run)),
                    goal=MappingProxyType(dict(goal)),
                    verification_spec=verification_spec,
                    turns=tuple(turns),
                    stop_reason="goal_completed",
                )
            if goal["status"] == "blocked":
                final_run = self.store.transition_run(
                    run_id,
                    "interrupted",
                    reason="Verified Goal blocker",
                )
                return AgentLoopResult(
                    run=MappingProxyType(dict(final_run)),
                    goal=MappingProxyType(dict(goal)),
                    verification_spec=verification_spec,
                    turns=tuple(turns),
                    stop_reason="goal_blocked",
                )

        final_run = self.store.transition_run(
            run_id,
            "interrupted",
            reason="Stage 4.8 max_steps guard reached",
        )
        goal = self.goal_store.get_goal(run["goal_id"])
        return AgentLoopResult(
            run=MappingProxyType(dict(final_run)),
            goal=MappingProxyType(dict(goal)),
            verification_spec=verification_spec,
            turns=tuple(turns),
            stop_reason="max_steps_reached",
        )


__all__ = [
    "MAX_BASELINE_STEPS",
    "AgentLoop",
    "AgentLoopResult",
    "AgentTurnResult",
]
