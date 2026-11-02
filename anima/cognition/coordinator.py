"""System-owned Stage 6 coordinator above persistent Tasks and resolution.

This slice deliberately stops before FAST/DEEP routing. It binds one persistent
Task to one supplied CanonicalTask, performs authoritative deterministic
resolution, records an observable directive, and returns control to the system.
"""

from dataclasses import dataclass
from enum import Enum

from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask
from anima.resolution import ResolutionResult, ResolutionRoute, resolve
from anima.tasks.contracts import Task
from anima.tasks.store import TaskStore


class CoordinatorDirective(str, Enum):
    FINAL = "FINAL"
    NEEDS_DATA = "NEEDS_DATA"
    ROUTE_COGNITION = "ROUTE_COGNITION"


_ROUTE_TO_DIRECTIVE = {
    ResolutionRoute.DETERMINISTIC_RESULT: CoordinatorDirective.FINAL,
    ResolutionRoute.INSUFFICIENT_DATA: CoordinatorDirective.NEEDS_DATA,
    ResolutionRoute.COGNITIVE_REQUIRED: CoordinatorDirective.ROUTE_COGNITION,
}


@dataclass(frozen=True, slots=True)
class CoordinatorTurn:
    persistent_task: Task
    canonical_task: CanonicalTask
    resolution: ResolutionResult
    directive: CoordinatorDirective

    @property
    def persistent_task_id(self):
        return self.persistent_task.public_id

    @property
    def canonical_task_id(self):
        return self.canonical_task.task_id

    @property
    def final_result(self):
        if self.directive != CoordinatorDirective.FINAL:
            return None
        return self.resolution.value


class CognitiveCoordinator:
    """Own Stage 6 orchestration boundary without owning subsystem data.

    The coordinator reads Task existence/status through TaskStore and delegates
    deterministic semantics to the Stage 5 resolver. It does not mutate Task
    lifecycle, call FAST/DEEP, retrieve Memory, update Goals/Internal State, or
    execute Actions. Those capabilities are separate later Stage 6 slices.
    """

    def __init__(self, *, task_store, trace=None):
        if not isinstance(task_store, TaskStore):
            raise TypeError("CognitiveCoordinator task_store must be a TaskStore")
        if trace is not None and not isinstance(trace, DiagnosticTrace):
            raise TypeError("CognitiveCoordinator trace must be a DiagnosticTrace or null")
        self.task_store = task_store
        self.trace = trace

    def process(self, persistent_task_id, canonical_task):
        if not isinstance(canonical_task, CanonicalTask):
            raise TypeError("CognitiveCoordinator requires a CanonicalTask")

        persistent_task = self.task_store.get_task(persistent_task_id)
        if persistent_task is None:
            raise ValueError(f"Unknown persistent Task: {persistent_task_id}")
        if persistent_task.status != "active":
            raise RuntimeError(
                "CognitiveCoordinator requires an active persistent Task, "
                f"got {persistent_task.status!r}"
            )

        self._trace(
            "coordinator: begin "
            f"task={persistent_task.public_id} "
            f"canonical={canonical_task.task_id} "
            f"source={canonical_task.source_id} "
            f"operation={canonical_task.operation}"
        )

        resolution = resolve(canonical_task)
        directive = _ROUTE_TO_DIRECTIVE[resolution.route]

        self._trace(
            "coordinator: resolved "
            f"task={persistent_task.public_id} "
            f"canonical={canonical_task.task_id} "
            f"route={resolution.route.value} "
            f"directive={directive.value} "
            f"reason={resolution.reason}"
        )

        return CoordinatorTurn(
            persistent_task=persistent_task,
            canonical_task=canonical_task,
            resolution=resolution,
            directive=directive,
        )

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)


__all__ = [
    "CognitiveCoordinator",
    "CoordinatorDirective",
    "CoordinatorTurn",
]
