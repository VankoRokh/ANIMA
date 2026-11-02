"""Cross-subsystem restart recovery for Stage 6 Cognitive Integration Core.

This coordinator does not replace subsystem recovery. It normalizes only the
shared boundaries that matter after restart and records the causal result in the
persistent unified trace.
"""

from dataclasses import dataclass

from anima.diagnostics.stage6 import Stage6TraceRecorder
from anima.diagnostics.unified_trace import UnifiedTrace
from anima.execution.store import ExecutionStore
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.sleep.task_lifecycle import TaskSleepCoordinator
from anima.tasks.contracts import TERMINAL_TASK_STATUSES
from anima.tasks.store import TaskStore


@dataclass(frozen=True, slots=True)
class Stage6RecoveryTurn:
    trace_id: str
    task_id: str
    goal_id: str | None
    task_status: str
    goal_status: str | None
    executing_to_uncertain: int
    prepared_operations: int
    uncertain_operations: int
    succeeded_operations: int
    sleep_link_status: str | None
    sleep_job_status: str | None


class Stage6RecoveryCoordinator:
    """Coordinate existing Task/Execution/Sleep recovery without replaying effects."""

    def __init__(
        self,
        *,
        task_store,
        internal_state,
        execution_store,
        sleep_coordinator,
        trace,
    ):
        if not isinstance(task_store, TaskStore):
            raise TypeError("Stage6RecoveryCoordinator task_store must be TaskStore")
        if not isinstance(internal_state, InternalStateRuntime):
            raise TypeError(
                "Stage6RecoveryCoordinator internal_state must be InternalStateRuntime"
            )
        if not isinstance(execution_store, ExecutionStore):
            raise TypeError(
                "Stage6RecoveryCoordinator execution_store must be ExecutionStore"
            )
        if not isinstance(sleep_coordinator, TaskSleepCoordinator):
            raise TypeError(
                "Stage6RecoveryCoordinator sleep_coordinator must be TaskSleepCoordinator"
            )
        if not isinstance(trace, UnifiedTrace):
            raise TypeError("Stage6RecoveryCoordinator trace must be UnifiedTrace")
        self.task_store = task_store
        self.internal_state = internal_state
        self.execution_store = execution_store
        self.sleep_coordinator = sleep_coordinator
        self.trace = trace
        self.recorder = Stage6TraceRecorder(trace)

    def _goal_status(self, task):
        if task.goal_id is None:
            return None
        goal = self.internal_state.goals.get_goal(task.goal_id)
        if goal is None:
            raise ValueError(f"Unknown Goal during Stage 6 recovery: {task.goal_id}")
        return goal["status"]

    def _normalize_execution(self, task):
        executing_to_uncertain = 0
        for operation in self.execution_store.list_operations(task_id=task.public_id):
            if operation["status"] == "executing":
                self.execution_store.transition_operation(
                    operation["id"],
                    "uncertain",
                    reason="Stage 6 restart recovered executing operation as uncertain",
                )
                executing_to_uncertain += 1

        refreshed = self.execution_store.list_operations(task_id=task.public_id)
        counts = {
            "prepared": 0,
            "uncertain": 0,
            "succeeded": 0,
        }
        for operation in refreshed:
            if operation["status"] in counts:
                counts[operation["status"]] += 1
        return executing_to_uncertain, counts

    def recover(self):
        """Recover every non-terminal Task and return immutable recovery summaries.

        A committed succeeded operation is never reset. An executing operation is
        downgraded to uncertain so the existing Executor can reconcile it safely.
        Prepared operations remain prepared because no side effect has started.
        """

        tasks = [
            task
            for task in self.task_store.list_tasks()
            if task.status not in TERMINAL_TASK_STATUSES
        ]

        trace_ids = {}
        for task in tasks:
            trace_ids[task.public_id] = self.trace.resume_or_begin(
                task_id=task.public_id,
                goal_id=task.goal_id,
            )

        execution_summaries = {}
        for task in tasks:
            trace_id = trace_ids[task.public_id]
            with self.trace.bind(trace_id):
                converted, counts = self._normalize_execution(task)
                execution_summaries[task.public_id] = (converted, counts)
                self.trace.record_event(
                    component="recovery",
                    event="execution_normalized",
                    message=(
                        f"stage6: recovery execution task={task.public_id} "
                        f"executing_to_uncertain={converted} "
                        f"succeeded={counts['succeeded']}"
                    ),
                    payload={
                        "executing_to_uncertain": converted,
                        "prepared_operations": counts["prepared"],
                        "uncertain_operations": counts["uncertain"],
                        "succeeded_operations": counts["succeeded"],
                    },
                )

        sleep_summary = self.sleep_coordinator.recover()

        turns = []
        for original in tasks:
            task = self.task_store.get_task(original.public_id)
            if task is None:
                raise RuntimeError("Task disappeared during Stage 6 recovery")
            goal_status = self._goal_status(task)
            link = self.sleep_coordinator.link_store.get_open_for_task(task.public_id)
            sleep_job_status = None
            if link is not None:
                job = self.sleep_coordinator.runtime.sleep_runtime.sleep_store.get_job(
                    link.sleep_job_id
                )
                if job is None:
                    raise ValueError(
                        f"Recovered TaskSleepLink references unknown SleepJob: {link.sleep_job_id}"
                    )
                sleep_job_status = job["status"]

            converted, counts = execution_summaries[task.public_id]
            trace_id = trace_ids[task.public_id]
            with self.trace.bind(
                trace_id,
                sleep_job_id=None if link is None else link.sleep_job_id,
            ):
                self.recorder.recovery(
                    payload={
                        "task_status": task.status,
                        "goal_status": goal_status,
                        "execution": {
                            "executing_to_uncertain": converted,
                            "prepared": counts["prepared"],
                            "uncertain": counts["uncertain"],
                            "succeeded": counts["succeeded"],
                        },
                        "sleep": sleep_summary,
                        "sleep_link_status": None if link is None else link.status,
                        "sleep_job_status": sleep_job_status,
                    }
                )

            turns.append(
                Stage6RecoveryTurn(
                    trace_id=trace_id,
                    task_id=task.public_id,
                    goal_id=task.goal_id,
                    task_status=task.status,
                    goal_status=goal_status,
                    executing_to_uncertain=converted,
                    prepared_operations=counts["prepared"],
                    uncertain_operations=counts["uncertain"],
                    succeeded_operations=counts["succeeded"],
                    sleep_link_status=None if link is None else link.status,
                    sleep_job_status=sleep_job_status,
                )
            )
        return tuple(turns)


__all__ = ["Stage6RecoveryCoordinator", "Stage6RecoveryTurn"]
