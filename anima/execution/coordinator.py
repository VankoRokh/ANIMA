"""Bind a verified Stage 6 Choice result to one trusted executable ActionSpec."""

from dataclasses import dataclass

from anima.agent.tools import ToolRegistry
from anima.cognition.action_choice import ActionChoiceTurn
from anima.diagnostics.trace import DiagnosticTrace
from anima.tasks.store import TaskStore
from .contracts import ActionSpec, ExecutionAction, ExecutionReceipt
from .sandbox import SandboxExecutor
from .store import ExecutionStore


@dataclass(frozen=True, slots=True)
class ExecutionTurn:
    action: ExecutionAction
    receipt: ExecutionReceipt


class ExecutionCoordinator:
    """System-owned bridge from ActionChoiceTurn to bounded Executor.

    It does not verify Goal success and never treats a successful receipt as a
    completed Goal. Independent observation/verification is a separate boundary.
    """

    def __init__(
        self,
        *,
        task_store,
        execution_store,
        registry,
        executor,
        trace=None,
    ):
        if not isinstance(task_store, TaskStore):
            raise TypeError("ExecutionCoordinator task_store must be TaskStore")
        if not isinstance(execution_store, ExecutionStore):
            raise TypeError("ExecutionCoordinator execution_store must be ExecutionStore")
        if not isinstance(registry, ToolRegistry):
            raise TypeError("ExecutionCoordinator registry must be ToolRegistry")
        if not isinstance(executor, SandboxExecutor):
            raise TypeError("ExecutionCoordinator executor must be SandboxExecutor")
        if executor.store is not execution_store or executor.registry is not registry:
            raise ValueError("ExecutionCoordinator and Executor must share store/registry")
        if trace is not None and not isinstance(trace, DiagnosticTrace):
            raise TypeError("ExecutionCoordinator trace must be DiagnosticTrace or null")
        self.task_store = task_store
        self.execution_store = execution_store
        self.registry = registry
        self.executor = executor
        self.trace = trace

    def _validate_specs(self, choice_turn, specs):
        if not isinstance(choice_turn, ActionChoiceTurn):
            raise TypeError("ExecutionCoordinator requires ActionChoiceTurn")
        if not isinstance(specs, (list, tuple)) or not specs:
            raise ValueError("ExecutionCoordinator requires ActionSpec values")
        if not all(isinstance(spec, ActionSpec) for spec in specs):
            raise TypeError("ExecutionCoordinator requires ActionSpec values")
        ids = [spec.candidate_id for spec in specs]
        if len(ids) != len(set(ids)):
            raise ValueError("ActionSpec candidate IDs must be unique")
        expected = {
            item["candidate_id"]
            for item in choice_turn.choice["evaluations"]
        }
        if set(ids) != expected:
            raise ValueError(
                "ActionSpec candidate IDs must exactly match Choice evaluations"
            )
        return {spec.candidate_id: spec for spec in specs}

    def prepare(self, choice_turn, specs, *, created_at):
        mapping = self._validate_specs(choice_turn, specs)
        persistent = self.task_store.get_task(choice_turn.persistent_task_id)
        if persistent is None:
            raise ValueError(f"Unknown Task: {choice_turn.persistent_task_id}")
        if persistent.status != "active":
            raise ValueError(
                f"Execution requires active Task, got {persistent.status!r}"
            )
        if persistent.goal_id != choice_turn.goal_id:
            raise ValueError("Execution Task/Choice Goal mismatch")
        selected = mapping[choice_turn.selected_candidate_id]
        action = ExecutionAction.from_spec(
            selected,
            registry=self.registry,
            persistent_task_id=persistent.public_id,
            goal_id=choice_turn.goal_id,
            created_at=created_at,
        )
        self.execution_store.create_operation(
            action,
            registry=self.registry,
            reason="selected Stage 6 action prepared",
        )
        self._trace(
            "execution: prepared "
            f"task={persistent.public_id} goal={choice_turn.goal_id} "
            f"candidate={action.candidate_id} action={action.public_id} "
            f"operation={action.operation_id} tool={action.tool}@{action.tool_version}"
        )
        return action

    def execute(self, action):
        if not isinstance(action, ExecutionAction):
            raise TypeError("ExecutionCoordinator.execute requires ExecutionAction")
        receipt = self.executor.execute(action)
        self._trace(
            "execution: receipt "
            f"task={action.persistent_task_id} goal={action.goal_id} "
            f"action={action.public_id} operation={action.operation_id} "
            f"status={receipt.status}"
        )
        return ExecutionTurn(action=action, receipt=receipt)

    def prepare_and_execute(self, choice_turn, specs, *, created_at):
        return self.execute(self.prepare(choice_turn, specs, created_at=created_at))

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)


__all__ = ["ExecutionCoordinator", "ExecutionTurn"]
