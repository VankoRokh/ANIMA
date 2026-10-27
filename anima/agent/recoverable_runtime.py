from types import MappingProxyType
from uuid import uuid4

from anima.agent.contracts import Action, VerificationSpec
from anima.agent.executor import UncertainOperationError, action_request_hash, operation_kind
from anima.agent.recovery import AgentRecoveryJournal
from anima.agent.runtime import (
    AgentLoop,
    AgentLoopResult,
    AgentTurnResult,
    _history_entry,
    _now,
    _observation_from_receipt,
)


class RecoverableAgentLoop(AgentLoop):
    """Stage 4.11 AgentLoop with durable artifacts and deterministic resume."""

    def __init__(
        self,
        *,
        recovery_journal=None,
        fault_hook=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if recovery_journal is None:
            recovery_journal = AgentRecoveryJournal(self.store)
        if not isinstance(recovery_journal, AgentRecoveryJournal):
            raise TypeError(
                "RecoverableAgentLoop recovery_journal must be an AgentRecoveryJournal"
            )
        if recovery_journal.store is not self.store:
            raise ValueError("Recovery journal must use the same AgentStore")
        if fault_hook is not None and not callable(fault_hook):
            raise TypeError("RecoverableAgentLoop fault_hook must be callable or null")
        self.recovery_journal = recovery_journal
        self.fault_hook = fault_hook

    def _checkpoint(self, name, *, run_id, step_id=None):
        if self.fault_hook is None:
            return
        self.fault_hook(
            name,
            {
                "run_id": run_id,
                "step_id": step_id,
            },
        )

    @staticmethod
    def _choice_for_recovered_turn(planner_turn, action):
        if action is None:
            return None
        selected = next(
            (
                proposal
                for proposal in planner_turn.proposals
                if proposal.public_id == action.proposal_id
            ),
            None,
        )
        if selected is None:
            raise ValueError(
                "Recovered Action proposal_id is not owned by persisted PlannerTurn"
            )
        return {
            "selected_proposal_id": selected.public_id,
            "selected_proposal": selected,
            "candidate_traces": (),
            "choice": {},
        }

    def _restore_completed_trace(self, run_id):
        observations = []
        history = []
        turns = []
        for step in self.store.list_steps(run_id=run_id):
            if step["status"] != "completed":
                continue
            artifacts = self.recovery_journal.load_step(step["id"])
            if artifacts is None or artifacts.planner_turn is None:
                raise ValueError(
                    f"Completed recoverable AgentStep lacks persisted PlannerTurn: {step['id']}"
                )
            choice = self._choice_for_recovered_turn(
                artifacts.planner_turn,
                artifacts.action,
            )
            if artifacts.observation is not None:
                observations.append(artifacts.observation)
            if (
                artifacts.action is not None
                and artifacts.receipt is not None
                and artifacts.verification_result is not None
            ):
                history.append(
                    _history_entry(
                        artifacts.action,
                        artifacts.receipt,
                        artifacts.verification_result,
                    )
                )
            turns.append(
                AgentTurnResult(
                    step_id=step["id"],
                    planner_turn=artifacts.planner_turn,
                    choice=choice,
                    action=artifacts.action,
                    receipt=artifacts.receipt,
                    observation=artifacts.observation,
                    verification_result=artifacts.verification_result,
                    verification_application=None,
                )
            )
        return observations, history, turns

    def _result(self, run_id, verification_spec, turns, stop_reason):
        run = self.store.get_run(run_id)
        goal = self.goal_store.get_goal(run["goal_id"])
        return AgentLoopResult(
            run=MappingProxyType(dict(run)),
            goal=MappingProxyType(dict(goal)),
            verification_spec=verification_spec,
            turns=tuple(turns),
            stop_reason=stop_reason,
        )

    def _reconcile_terminal_goal(self, run_id, verification_spec, turns):
        run = self.store.get_run(run_id)
        goal = self.goal_store.get_goal(run["goal_id"])
        if goal["status"] == "completed":
            if run["status"] in {"running", "interrupted"}:
                run = self.store.transition_run(
                    run_id,
                    "completed",
                    reason="Recovered verified Goal completion",
                )
            return self._result(
                run_id,
                verification_spec,
                turns,
                "goal_completed",
            )
        if goal["status"] == "cancelled":
            if run["status"] in {"running", "interrupted"}:
                run = self.store.transition_run(
                    run_id,
                    "cancelled",
                    reason="Recovered cancelled Goal",
                )
            return self._result(
                run_id,
                verification_spec,
                turns,
                "goal_cancelled",
            )
        if goal["status"] == "blocked":
            if run["status"] == "running":
                self.store.transition_run(
                    run_id,
                    "interrupted",
                    reason="Recovered blocked Goal",
                )
            return self._result(
                run_id,
                verification_spec,
                turns,
                "goal_blocked",
            )
        return None

    def _recover_active_step(self, run_id, verification_spec, prior_observations):
        active = [
            step
            for step in self.store.list_steps(run_id=run_id)
            if step["status"] not in {"completed", "failed", "cancelled"}
        ]
        if len(active) > 1:
            raise ValueError("AgentRun contains more than one non-terminal AgentStep")
        if not active:
            return

        step = active[0]
        artifacts = self.recovery_journal.load_step(step["id"])
        if artifacts is None:
            self.recovery_journal.ensure_step(run_id, step["id"])
            artifacts = self.recovery_journal.load_step(step["id"])

        status = step["status"]
        if status in {"planning", "planned"}:
            self.store.transition_step(
                step["id"],
                "failed",
                reason="Recovery abandoned pre-selection Step with no side effect",
            )
            return

        action = artifacts.action
        if action is None:
            raise ValueError(
                f"Recoverable {status} AgentStep lacks persisted Action: {step['id']}"
            )
        operation = self.store.get_operation(action.operation_id)
        if operation is None:
            raise ValueError(
                f"Recovered Action lacks AgentOperation: {action.operation_id}"
            )

        if status == "selected":
            self.store.transition_step(
                step["id"],
                "executing",
                reason="Recovery resumes persisted selected Action",
            )
            status = "executing"

        receipt = artifacts.receipt
        if status == "executing":
            if receipt is None:
                try:
                    receipt = self.executor.execute(action)
                except UncertainOperationError:
                    run = self.store.get_run(run_id)
                    if run["status"] == "running":
                        self.store.transition_run(
                            run_id,
                            "interrupted",
                            reason="Recovery requires external side-effect reconciliation",
                        )
                    return
                operation = self.store.get_operation(action.operation_id)
                if operation["status"] == "uncertain":
                    run = self.store.get_run(run_id)
                    if run["status"] == "running":
                        self.store.transition_run(
                            run_id,
                            "interrupted",
                            reason="Recovered Tool effect remains uncertain",
                        )
                    return
                self.recovery_journal.save_receipt(step["id"], receipt)
                self._checkpoint(
                    "recovery_after_receipt_persisted",
                    run_id=run_id,
                    step_id=step["id"],
                )
            self.store.transition_step(
                step["id"],
                "executed",
                reason=f"Recovered ExecutionReceipt {receipt.public_id}",
            )
            status = "executed"

        artifacts = self.recovery_journal.load_step(step["id"])
        receipt = artifacts.receipt
        if status == "executed":
            if receipt is None:
                raise ValueError("Executed recovery Step lacks persisted Receipt")
            observation = artifacts.observation
            if observation is None:
                observation = _observation_from_receipt(action, receipt)
                self.recovery_journal.save_observation(step["id"], observation)
                self._checkpoint(
                    "recovery_after_observation_persisted",
                    run_id=run_id,
                    step_id=step["id"],
                )
            self.store.transition_step(
                step["id"],
                "observed",
                reason=f"Recovered Observation {observation.public_id}",
            )
            status = "observed"

        artifacts = self.recovery_journal.load_step(step["id"])
        observation = artifacts.observation
        if status == "observed":
            if observation is None:
                raise ValueError("Observed recovery Step lacks persisted Observation")
            verification_result = artifacts.verification_result
            evidence = tuple(prior_observations) + (observation,)
            if verification_result is None:
                verification_result = self.verifier.verify(
                    verification_spec,
                    step_id=step["id"],
                    candidate_id=action.proposal_id,
                    observations=evidence,
                    timestamp=observation.observed_at,
                )
                self.recovery_journal.save_verification_result(
                    step["id"],
                    verification_result,
                )
                self._checkpoint(
                    "recovery_after_verification_persisted",
                    run_id=run_id,
                    step_id=step["id"],
                )
            artifacts = self.recovery_journal.load_step(step["id"])
            if not artifacts.goal_applied:
                self.verification_bridge.apply(
                    spec=verification_spec,
                    result=verification_result,
                    observations=evidence,
                )
                self.recovery_journal.mark_goal_applied(step["id"])
                self._checkpoint(
                    "recovery_after_goal_applied",
                    run_id=run_id,
                    step_id=step["id"],
                )
            self.store.transition_step(
                step["id"],
                "verified",
                reason=(
                    f"Recovered VerificationResult {verification_result.public_id} "
                    f"outcome={verification_result.outcome}"
                ),
            )
            status = "verified"

        if status == "verified":
            artifacts = self.recovery_journal.load_step(step["id"])
            if artifacts.verification_result is None:
                raise ValueError("Verified recovery Step lacks VerificationResult")
            if not artifacts.goal_applied:
                evidence = tuple(prior_observations)
                if artifacts.observation is not None:
                    evidence += (artifacts.observation,)
                self.verification_bridge.apply(
                    spec=verification_spec,
                    result=artifacts.verification_result,
                    observations=evidence,
                )
                self.recovery_journal.mark_goal_applied(step["id"])
            self.store.transition_step(
                step["id"],
                "completed",
                reason="Recovered AgentLoop turn completed",
            )

    def _continue(self, run_id, verification_spec, *, max_steps, observations, history, turns):
        run = self.store.get_run(run_id)
        while len(turns) < max_steps:
            goal = self.goal_store.get_goal(run["goal_id"])
            terminal = self._reconcile_terminal_goal(
                run_id,
                verification_spec,
                turns,
            )
            if terminal is not None:
                return terminal

            step = self.store.create_step(
                run_id=run_id,
                reason="RecoverableAgentLoop turn created",
            )
            self.recovery_journal.ensure_step(run_id, step["id"])
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
            self.recovery_journal.save_planner_turn(step["id"], planner_turn)
            self._checkpoint(
                "after_planner_persisted",
                run_id=run_id,
                step_id=step["id"],
            )
            self.store.transition_step(
                step["id"],
                "planned",
                reason=f"PlannerTurn {planner_turn.public_id} persisted",
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
                self.store.transition_run(
                    run_id,
                    "failed",
                    reason="Planner reported cannot_progress",
                )
                return self._result(
                    run_id,
                    verification_spec,
                    turns,
                    "planner_cannot_progress",
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
            self.recovery_journal.save_action(step["id"], action)
            self._checkpoint(
                "after_action_persisted",
                run_id=run_id,
                step_id=step["id"],
            )

            self.store.transition_step(
                step["id"],
                "executing",
                reason=f"Action {action.public_id} executing",
            )
            receipt = self.executor.execute(action)
            self._checkpoint(
                "after_tool_execution",
                run_id=run_id,
                step_id=step["id"],
            )
            operation = self.store.get_operation(operation_id)
            if operation["status"] == "uncertain":
                self.store.transition_run(
                    run_id,
                    "interrupted",
                    reason="Tool effect is uncertain; recovery required",
                )
                return self._result(
                    run_id,
                    verification_spec,
                    turns,
                    "uncertain_tool_effect",
                )

            self.recovery_journal.save_receipt(step["id"], receipt)
            self._checkpoint(
                "after_receipt_persisted",
                run_id=run_id,
                step_id=step["id"],
            )
            self.store.transition_step(
                step["id"],
                "executed",
                reason=f"ExecutionReceipt {receipt.public_id} persisted",
            )

            observation = _observation_from_receipt(action, receipt)
            self.recovery_journal.save_observation(step["id"], observation)
            self._checkpoint(
                "after_observation_persisted",
                run_id=run_id,
                step_id=step["id"],
            )
            observations.append(observation)
            self.store.transition_step(
                step["id"],
                "observed",
                reason=f"Observation {observation.public_id} persisted",
            )

            verification_result = self.verifier.verify(
                verification_spec,
                step_id=step["id"],
                candidate_id=selected.public_id,
                observations=tuple(observations),
                timestamp=observation.observed_at,
            )
            self.recovery_journal.save_verification_result(
                step["id"],
                verification_result,
            )
            self._checkpoint(
                "after_verification_persisted",
                run_id=run_id,
                step_id=step["id"],
            )
            application = self.verification_bridge.apply(
                spec=verification_spec,
                result=verification_result,
                observations=tuple(observations),
            )
            self.recovery_journal.mark_goal_applied(step["id"])
            self._checkpoint(
                "after_goal_applied",
                run_id=run_id,
                step_id=step["id"],
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
                reason="RecoverableAgentLoop turn completed",
            )
            self._checkpoint(
                "after_step_completed",
                run_id=run_id,
                step_id=step["id"],
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

            terminal = self._reconcile_terminal_goal(
                run_id,
                verification_spec,
                turns,
            )
            if terminal is not None:
                return terminal

        run = self.store.get_run(run_id)
        if run["status"] == "running":
            self.store.transition_run(
                run_id,
                "interrupted",
                reason="Stage 4.11 max_steps guard reached",
            )
        return self._result(
            run_id,
            verification_spec,
            turns,
            "max_steps_reached",
        )

    def run(self, run_id, verification_spec, *, max_steps=8):
        self._validate_step_limit(max_steps)
        if not isinstance(verification_spec, VerificationSpec):
            raise TypeError("RecoverableAgentLoop run requires a VerificationSpec")
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown AgentRun: {run_id}")
        if run["status"] != "running":
            raise ValueError(
                f"RecoverableAgentLoop requires running AgentRun, got {run['status']!r}"
            )
        if verification_spec.run_id != run_id:
            raise ValueError("VerificationSpec does not belong to AgentRun")
        if self.store.list_steps(run_id=run_id):
            raise ValueError("run() requires a fresh AgentRun; use resume() after interruption")
        self.recovery_journal.ensure_run(verification_spec)
        return self._continue(
            run_id,
            verification_spec,
            max_steps=max_steps,
            observations=[],
            history=[],
            turns=[],
        )

    def resume(self, run_id, verification_spec=None, *, max_steps=8):
        self._validate_step_limit(max_steps)
        persisted_spec = self.recovery_journal.get_verification_spec(run_id)
        if verification_spec is None:
            verification_spec = persisted_spec
        if not isinstance(verification_spec, VerificationSpec):
            raise ValueError("Recoverable AgentRun has no persisted VerificationSpec")
        if verification_spec.run_id != run_id:
            raise ValueError("VerificationSpec does not belong to AgentRun")
        self.recovery_journal.ensure_run(verification_spec)

        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown AgentRun: {run_id}")
        goal = self.goal_store.get_goal(run["goal_id"])
        if goal is None:
            raise ValueError(f"Unknown Goal: {run['goal_id']}")

        observations, history, turns = self._restore_completed_trace(run_id)
        if run["status"] in {"completed", "failed", "cancelled"}:
            reason = {
                "completed": "goal_completed",
                "failed": "run_failed",
                "cancelled": "goal_cancelled",
            }[run["status"]]
            return self._result(run_id, verification_spec, turns, reason)

        if run["status"] == "interrupted" and goal["status"] == "active":
            self.store.transition_run(
                run_id,
                "running",
                reason="Stage 4.11 recovery resumed AgentRun",
            )

        self._recover_active_step(
            run_id,
            verification_spec,
            observations,
        )
        observations, history, turns = self._restore_completed_trace(run_id)

        terminal = self._reconcile_terminal_goal(
            run_id,
            verification_spec,
            turns,
        )
        if terminal is not None:
            return terminal

        run = self.store.get_run(run_id)
        if run["status"] == "interrupted":
            return self._result(
                run_id,
                verification_spec,
                turns,
                "recovery_interrupted",
            )
        if run["status"] != "running":
            raise ValueError(
                f"Recovered AgentRun cannot continue from status {run['status']!r}"
            )
        return self._continue(
            run_id,
            verification_spec,
            max_steps=max_steps,
            observations=observations,
            history=history,
            turns=turns,
        )


__all__ = ["RecoverableAgentLoop"]
