"""Structured Stage 6 causal-trace recorder over subsystem results.

This module records evidence about decisions already made elsewhere. It owns no
routing, Task, Goal, Internal State, execution, verification, or Sleep authority.
"""

from contextlib import contextmanager

from anima.cognition.action_choice import ActionChoiceTurn
from anima.cognition.coordinator import CoordinatorTurn
from anima.cognition.proposals import CognitiveDispatchTurn
from anima.cognition.routing import CognitiveRouteDecision
from anima.execution.contracts import ExecutionAction, Observation, VerificationResult
from anima.execution.coordinator import ExecutionTurn
from anima.sleep.task_lifecycle import TaskSleepTurn
from anima.tasks.contracts import Task
from .unified_trace import UnifiedTrace


class Stage6TraceRecorder:
    def __init__(self, trace):
        if not isinstance(trace, UnifiedTrace):
            raise TypeError("Stage6TraceRecorder trace must be UnifiedTrace")
        self.trace = trace

    @contextmanager
    def task_scope(self, task, *, goal_status=None):
        if not isinstance(task, Task):
            raise TypeError("Stage6TraceRecorder task_scope requires Task")
        trace_id = self.trace.resume_or_begin(task_id=task.public_id, goal_id=task.goal_id)
        with self.trace.bind(trace_id):
            self.trace.record_event(
                component="stage6",
                event="task_scope",
                message=(
                    f"stage6: task_scope task={task.public_id} goal={task.goal_id or 'none'} "
                    f"task_status={task.status} goal_status={goal_status or 'unknown'}"
                ),
                payload={
                    "task_status": task.status,
                    "goal_status": goal_status,
                },
            )
            yield trace_id

    def resolution(self, turn):
        if not isinstance(turn, CoordinatorTurn):
            raise TypeError("resolution trace requires CoordinatorTurn")
        task = turn.canonical_task
        return self.trace.record_event(
            component="coordinator",
            event="resolution",
            message=(
                f"stage6: resolution canonical={task.task_id} source={task.source_id} "
                f"route={turn.resolution.route.value} reason={turn.resolution.reason}"
            ),
            canonical_task_id=task.task_id,
            source_id=task.source_id,
            payload={
                "operation": task.operation,
                "resolution_route": turn.resolution.route.value,
                "resolution_reason": turn.resolution.reason,
                "directive": turn.directive.value,
                "remaining_candidates": list(turn.resolution.remaining),
                "unverified_candidates": list(turn.resolution.unverified),
            },
        )

    def route(self, task, decision):
        if not isinstance(decision, CognitiveRouteDecision):
            raise TypeError("route trace requires CognitiveRouteDecision")
        return self.trace.record_event(
            component="cognitive_router",
            event="route",
            message=(
                f"stage6: route canonical={task.task_id} destination={decision.destination.value} "
                f"reason={decision.reason} policy={decision.policy_version}"
            ),
            canonical_task_id=task.task_id,
            source_id=task.source_id,
            payload={
                "destination": decision.destination.value,
                "route_reason": decision.reason,
                "policy_version": decision.policy_version,
                "role": None if decision.role is None else decision.role.value,
            },
        )

    @staticmethod
    def _context_summary(dispatch_turn):
        if dispatch_turn.request is None:
            return {
                "consumer": None,
                "evidence_count": 0,
                "provenance_ref_count": 0,
            }
        data = dispatch_turn.request.view.to_dict()
        evidence = data.get("evidence", [])
        provenance_count = 0
        for item in evidence:
            provenance = item.get("provenance", []) if isinstance(item, dict) else []
            if isinstance(provenance, list):
                provenance_count += len(provenance)
        return {
            "consumer": dispatch_turn.request.role.value,
            "evidence_count": len(evidence),
            "provenance_ref_count": provenance_count,
            "has_input": "input" in data,
            "has_goal": "goal" in data,
            "has_state": bool(data.get("state")),
        }

    def dispatch(self, turn):
        if not isinstance(turn, CognitiveDispatchTurn):
            raise TypeError("dispatch trace requires CognitiveDispatchTurn")
        request = turn.request
        canonical_task_id = None if request is None else request.canonical_task_id
        source_id = None if request is None else request.source_id
        proposal_kind = None if turn.proposal is None else turn.proposal.kind.value
        context_summary = self._context_summary(turn)
        return self.trace.record_event(
            component="cognitive_dispatch",
            event="completion",
            message=(
                "stage6: cognitive_dispatch "
                f"destination={turn.decision.destination.value} "
                f"backend_called={str(turn.backend_called).lower()} "
                f"accepted={str(turn.validation.accepted).lower()}"
            ),
            canonical_task_id=canonical_task_id,
            source_id=source_id,
            payload={
                "destination": turn.decision.destination.value,
                "role": None if turn.decision.role is None else turn.decision.role.value,
                "backend_called": turn.backend_called,
                "proposal_kind": proposal_kind,
                "proposal_validation": {
                    "accepted": turn.validation.accepted,
                    "reason": turn.validation.reason,
                },
                "context": context_summary,
            },
        )

    def choice(self, turn):
        if not isinstance(turn, ActionChoiceTurn):
            raise TypeError("choice trace requires ActionChoiceTurn")
        choice = dict(turn.choice)
        evaluations = []
        for item in choice.get("evaluations", ()):  # frozen mappings are iterable mappings
            record = dict(item)
            evaluations.append(
                {
                    "candidate_id": record["candidate_id"],
                    "base_score": record["base_score"],
                    "score": record.get("score"),
                    "modifiers": [dict(modifier) for modifier in record.get("modifiers", ())],
                }
            )
        return self.trace.record_event(
            component="action_choice",
            event="selected",
            message=(
                f"stage6: choice canonical={turn.canonical_task_id} "
                f"baseline={turn.baseline_selected_candidate_id} "
                f"selected={turn.selected_candidate_id}"
            ),
            canonical_task_id=turn.canonical_task_id,
            payload={
                "baseline_selected_candidate_id": turn.baseline_selected_candidate_id,
                "selected_candidate_id": turn.selected_candidate_id,
                "state_changed_selection": turn.state_changed_selection,
                "ruleset_version": choice.get("ruleset_version"),
                "state_snapshot": dict(choice.get("state_snapshot", {})),
                "evaluations": evaluations,
            },
        )

    def execution(self, turn):
        if not isinstance(turn, ExecutionTurn):
            raise TypeError("execution trace requires ExecutionTurn")
        action = turn.action
        receipt = turn.receipt
        return self.trace.record_event(
            component="execution",
            event="receipt",
            message=(
                f"stage6: execution action={action.public_id} operation={action.operation_id} "
                f"candidate={action.candidate_id} status={receipt.status}"
            ),
            action_id=action.public_id,
            operation_id=action.operation_id,
            payload={
                "candidate_id": action.candidate_id,
                "tool": action.tool,
                "tool_version": action.tool_version,
                "receipt_id": receipt.public_id,
                "receipt_status": receipt.status,
                "error_code": receipt.error_code,
            },
        )

    def observation(self, action, observation):
        if not isinstance(action, ExecutionAction):
            raise TypeError("observation trace requires ExecutionAction")
        if not isinstance(observation, Observation):
            raise TypeError("observation trace requires Observation")
        if observation.action_id != action.public_id:
            raise ValueError("Observation trace Action mismatch")
        return self.trace.record_event(
            component="observation",
            event="observed",
            message=(
                f"stage6: observation action={action.public_id} "
                f"observation={observation.public_id} kind={observation.kind}"
            ),
            action_id=action.public_id,
            operation_id=action.operation_id,
            observation_id=observation.public_id,
            payload={
                "source": observation.source,
                "kind": observation.kind,
            },
        )

    def verification(self, action, result):
        if not isinstance(action, ExecutionAction):
            raise TypeError("verification trace requires ExecutionAction")
        if not isinstance(result, VerificationResult):
            raise TypeError("verification trace requires VerificationResult")
        if result.goal_id != action.goal_id or result.candidate_id != action.candidate_id:
            raise ValueError("Verification trace Action/Goal mismatch")
        return self.trace.record_event(
            component="verification",
            event="result",
            message=(
                f"stage6: verification action={action.public_id} result={result.public_id} "
                f"outcome={result.outcome} satisfied={str(result.criterion_satisfied).lower()}"
            ),
            action_id=action.public_id,
            operation_id=action.operation_id,
            verification_id=result.public_id,
            payload={
                "verification_spec_id": result.verification_spec_id,
                "observation_ids": list(result.observation_ids),
                "outcome": result.outcome,
                "criterion_satisfied": result.criterion_satisfied,
                "reason": result.reason,
            },
        )

    def sleep(self, turn, *, event):
        if not isinstance(turn, TaskSleepTurn):
            raise TypeError("sleep trace requires TaskSleepTurn")
        if event not in {"entered", "wake", "recovered"}:
            raise ValueError("Unknown Stage 6 Sleep trace event")
        return self.trace.record_event(
            component="task_sleep",
            event=event,
            message=(
                f"stage6: sleep {event} job={turn.link.sleep_job_id} "
                f"link={turn.link.public_id} task_status={turn.task_status} "
                f"job_status={turn.sleep_job_status}"
            ),
            sleep_job_id=turn.link.sleep_job_id,
            payload={
                "link_id": turn.link.public_id,
                "link_status": turn.link.status,
                "task_status": turn.task_status,
                "goal_status": turn.goal_status,
                "sleep_job_status": turn.sleep_job_status,
                "anima_status": turn.anima_status,
            },
        )

    def recovery(self, *, payload):
        return self.trace.record_event(
            component="recovery",
            event="normalized",
            message="stage6: recovery normalized persistent subsystem state",
            payload=payload,
        )

    def finish(self, trace_id, *, task, goal_status=None, success, reason):
        if not isinstance(task, Task):
            raise TypeError("Stage6TraceRecorder finish requires Task")
        with self.trace.bind(trace_id):
            self.trace.record_event(
                component="stage6",
                event="outcome",
                message=(
                    f"stage6: outcome task={task.public_id} task_status={task.status} "
                    f"goal_status={goal_status or 'none'}"
                ),
                payload={
                    "task_status": task.status,
                    "goal_status": goal_status,
                    "success": success,
                    "reason": reason,
                },
            )
        return self.trace.close(
            trace_id,
            success=success,
            task_status=task.status,
            goal_status=goal_status,
            reason=reason,
        )


__all__ = ["Stage6TraceRecorder"]
