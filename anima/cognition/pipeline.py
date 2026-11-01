"""ANIMA-owned Stage 5 resolution path, above the replaceable FAST ACI.

process_event retrieves bounded context once. process_task never retrieves and
requires neither a textual request nor an Event identity.
"""

from dataclasses import dataclass, replace
from enum import Enum

from anima.ir import CanonicalTask, Evidence, freeze, plain
from anima.resolution import DeterministicOutcome, ResolutionResult, ResolutionRoute, resolve
from anima.resolution.frontend import task_from_event
from .fast import ProjectedFastBackend, ProjectedFastRequest, FastResult, FastTurn
from .projection import CognitiveView, project
from .contracts import FastTransportError, FastModelOutputError


class BackendFailureClassification(str, Enum):
    TRANSPORT = "TRANSPORT"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    INVALID_BACKEND_RESULT = "INVALID_BACKEND_RESULT"
    BACKEND = "BACKEND"


@dataclass(frozen=True)
class ProjectedBackendAudit:
    """One local projected-call record; snapshots contain no exception payloads."""

    task_id: str
    source_id: str
    backend_attempts: int = 1
    backend_completions: int = 0
    terminal_failure: bool = False
    failure_classification: BackendFailureClassification | None = None


class _InvalidBackendResult(TypeError):
    pass


def _failure_classification(error):
    if isinstance(error, FastModelOutputError):
        return BackendFailureClassification.MODEL_OUTPUT
    if isinstance(error, (FastTransportError, TimeoutError, ConnectionError)):
        return BackendFailureClassification.TRANSPORT
    if isinstance(error, _InvalidBackendResult):
        return BackendFailureClassification.INVALID_BACKEND_RESULT
    return BackendFailureClassification.BACKEND


@dataclass(frozen=True)
class CognitiveTurn:
    task: CanonicalTask
    resolution: ResolutionResult
    consumer: str | None = None
    view: CognitiveView | None = None
    fast_turn: FastTurn | None = None
    model_call_count: int = 0
    final_result: object = None
    error: str | None = None
    backend_audit: ProjectedBackendAudit | None = None

    def __post_init__(self):
        object.__setattr__(self, "final_result", freeze(self.final_result))

    @property
    def backend_attempts(self):
        return self.backend_audit.backend_attempts if self.backend_audit else 0

    @property
    def backend_completions(self):
        return self.backend_audit.backend_completions if self.backend_audit else 0

    @property
    def model_called(self):
        return self.model_call_count > 0


def route_cognitive(resolution):
    if resolution.route != ResolutionRoute.COGNITIVE_REQUIRED:
        raise ValueError("Cognitive router requires COGNITIVE_REQUIRED")
    return "FAST"


class CognitivePipeline:
    def __init__(self, *, backend, context_builder=None, trace=None):
        if not isinstance(backend, ProjectedFastBackend):
            raise TypeError(
                "CognitivePipeline requires ProjectedFastBackend.complete_projected; "
                "legacy FastBackend remains supported by FastCognition"
            )
        self.backend = backend
        self.context_builder = context_builder
        self.trace = trace
        self._backend_audits = []

    @property
    def backend_audits(self):
        """Immutable snapshots of attempts, including failed calls that raised."""
        return tuple(self._backend_audits)

    def process_event(self, event):
        task = task_from_event(event)
        if self.context_builder is None:
            raise TypeError("Event path requires ContextBuilder")
        bundle = self.context_builder.build(task.raw_input, consumer="FAST")
        evidence = []
        for bucket, field in (("knowledge", "statement"), ("memories", "content")):
            for entry in bundle.get(bucket, ()):
                record = entry["record"]
                evidence.append(Evidence(record["id"], record[field], provenance=(record["id"],)))
        task = replace(task, evidence=tuple(evidence))
        return self._process(task, event_id=event.event_id, bundle=bundle)

    def process_task(self, canonical_task):
        return self._process(canonical_task)

    def _process(self, task, *, event_id=None, bundle=None):
        resolution = resolve(task)
        self._trace(
            f"resolution: task={task.task_id} route={resolution.route.value} "
            f"reason={resolution.reason} remaining={resolution.remaining} "
            f"rejected={plain(resolution.rejected)} policies={resolution.applied_policy_ids}"
        )
        if resolution.route != ResolutionRoute.COGNITIVE_REQUIRED:
            return self._finish(task, resolution, resolution.value)
        view = project(task, resolution)
        allowed = resolution.remaining if task.operation == "CHOOSE_ACTION" else task.candidates
        if (task.operation == "CHOOSE_ACTION" or task.output_contract == "candidate") and not allowed:
            # No model response could satisfy the contract. Preserve the unresolved
            # boundary for audit, without a guaranteed-failure backend invocation.
            return self._finish(task, resolution, None, view=view, error="no_admissible_candidates")
        consumer = route_cognitive(resolution)
        request = ProjectedFastRequest(
            input_source_id=task.source_id,
            cognitive_view=view,
            input_event_id=event_id,
            input_text=task.raw_input if event_id is not None else None,
            context_bundle=bundle,
        )
        audit = ProjectedBackendAudit(task.task_id, task.source_id)
        audit_index = len(self._backend_audits)
        self._backend_audits.append(audit)
        self._trace(f"cognition: task={task.task_id} source={task.source_id} consumer={consumer} "
                    f"view={view.to_dict()!r} model_calls=1 backend_attempts=1 backend_completions=0")
        try:
            result = self.backend.complete_projected(request)
            if not isinstance(result, FastResult):
                raise _InvalidBackendResult("FAST backend must return FastResult")
        except Exception as error:
            failed = replace(audit, terminal_failure=True, failure_classification=_failure_classification(error))
            self._backend_audits[audit_index] = failed
            self._trace(f"cognition: task={task.task_id} source={task.source_id} backend_attempts=1 "
                        f"backend_completions=0 terminal_failure=true "
                        f"failure_classification={failed.failure_classification.value}")
            raise
        completed = replace(audit, backend_completions=1)
        self._backend_audits[audit_index] = completed
        self._trace(f"cognition: task={task.task_id} source={task.source_id} backend_attempts=1 "
                    "backend_completions=1 terminal_failure=false")
        return self._finish(task, resolution, result.response_text, consumer=consumer,
                            view=view, fast_turn=FastTurn(request, result), model_call_count=1,
                            backend_audit=completed)

    def _finish(self, task, resolution, final, *, consumer=None, view=None,
                fast_turn=None, model_call_count=0, error=None, backend_audit=None):
        has_value = resolution.route == ResolutionRoute.COGNITIVE_REQUIRED or (
            resolution.outcome == DeterministicOutcome.VALUE)
        if error is None and has_value and (
            task.operation == "CHOOSE_ACTION" or task.output_contract == "candidate"
        ):
            allowed = resolution.remaining if task.operation == "CHOOSE_ACTION" else task.candidates
            if not isinstance(final, str) or final.strip() not in (allowed or ()):
                error = "invalid_output_candidate"
                final = None
            else:
                final = final.strip()
        turn = CognitiveTurn(task, resolution, consumer, view, fast_turn, model_call_count, final, error, backend_audit)
        self._trace(f"cognition: task={task.task_id} source={task.source_id} model_calls={model_call_count} "
                    f"backend_attempts={turn.backend_attempts} backend_completions={turn.backend_completions} "
                    f"final={final!r} error={error}")
        return turn

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)
