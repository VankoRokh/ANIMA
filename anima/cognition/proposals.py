"""Typed Stage 6 cognitive request/proposal boundary.

FAST/DEEP may produce proposals, but proposals do not mutate persistent state.
Only RESPOND is enabled for model-backed cognition; action choice is a separate
system-owned Stage 6.3 path and must never pass through this dispatcher.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import freeze, plain, require_id
from anima.tasks.contracts import validate_task_id
from .contracts import CognitiveView
from .fast import FastResult, ProjectedFastBackend, ProjectedFastRequest
from .projection import project
from .routing import (
    CognitiveDestination,
    CognitiveRole,
    CognitiveRouteDecision,
)


class ProposalKind(str, Enum):
    RESPOND = "RESPOND"
    PROPOSE_ACTION = "PROPOSE_ACTION"
    PROPOSE_TASK = "PROPOSE_TASK"
    REQUEST_CONTEXT = "REQUEST_CONTEXT"


@dataclass(frozen=True, slots=True)
class CognitiveProposal:
    kind: ProposalKind
    payload: Mapping

    def __post_init__(self):
        if not isinstance(self.kind, ProposalKind):
            raise ValueError("CognitiveProposal requires a typed kind")
        if not isinstance(self.payload, Mapping):
            raise ValueError("CognitiveProposal payload must be a mapping")
        object.__setattr__(self, "payload", freeze(self.payload))

    @classmethod
    def respond(cls, text):
        return cls(ProposalKind.RESPOND, {"text": text})

    def to_dict(self):
        return {
            "kind": self.kind.value,
            "payload": plain(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ProposalValidation:
    accepted: bool
    reason: str

    def __post_init__(self):
        if not isinstance(self.accepted, bool):
            raise ValueError("ProposalValidation accepted must be boolean")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("ProposalValidation reason must be non-empty")


class ProposalValidator:
    """System-owned authority gate for model proposals.

    Stage 6 currently enables only RESPOND. Action/Task/context proposals remain
    visible contract vocabulary but cannot pass this validator yet.
    """

    def validate(self, proposal):
        if not isinstance(proposal, CognitiveProposal):
            raise TypeError("ProposalValidator requires CognitiveProposal")

        if proposal.kind != ProposalKind.RESPOND:
            return ProposalValidation(False, "proposal_kind_not_enabled")

        payload = plain(proposal.payload)
        if set(payload) != {"text"}:
            return ProposalValidation(False, "invalid_response_payload")
        text = payload["text"]
        if not isinstance(text, str) or not text.strip():
            return ProposalValidation(False, "invalid_response_payload")
        return ProposalValidation(True, "accepted_response")


@dataclass(frozen=True, slots=True)
class RoutedCognitiveRequest:
    persistent_task_id: str
    canonical_task_id: str
    source_id: str
    role: CognitiveRole
    view: CognitiveView

    def __post_init__(self):
        validate_task_id(self.persistent_task_id)
        require_id(self.canonical_task_id, "Routed cognitive canonical_task_id")
        require_id(self.source_id, "Routed cognitive source_id")
        if not isinstance(self.role, CognitiveRole):
            raise ValueError("Routed cognitive request requires a typed role")
        if not isinstance(self.view, CognitiveView):
            raise TypeError("Routed cognitive request requires CognitiveView")
        if self.view.consumer != self.role.value:
            raise ValueError("Cognitive view consumer must match selected role")


@runtime_checkable
class CognitiveBackend(Protocol):
    """Replaceable Stage 6 backend; role is supplied by the system request."""

    def complete(self, request: RoutedCognitiveRequest) -> CognitiveProposal:
        ...


class ProjectedFastProposalAdapter:
    """Adapt the proven Stage 5 projected FAST backend into the Stage 6 boundary."""

    def __init__(self, backend):
        if not isinstance(backend, ProjectedFastBackend):
            raise TypeError(
                "ProjectedFastProposalAdapter requires ProjectedFastBackend"
            )
        self.backend = backend

    def complete(self, request):
        if not isinstance(request, RoutedCognitiveRequest):
            raise TypeError("FAST proposal adapter requires RoutedCognitiveRequest")
        if request.role != CognitiveRole.FAST:
            raise ValueError("FAST proposal adapter received a non-FAST request")
        result = self.backend.complete_projected(
            ProjectedFastRequest(
                input_source_id=request.source_id,
                cognitive_view=request.view,
            )
        )
        if not isinstance(result, FastResult):
            raise TypeError("Projected FAST backend must return FastResult")
        return CognitiveProposal.respond(result.response_text)


@dataclass(frozen=True, slots=True)
class CognitiveDispatchTurn:
    decision: CognitiveRouteDecision
    request: RoutedCognitiveRequest | None
    proposal: CognitiveProposal | None
    validation: ProposalValidation
    backend_called: bool

    @property
    def accepted(self):
        return self.validation.accepted


class CognitiveDispatcher:
    """Call only the system-selected model role and validate its proposal.

    The dispatcher owns no persistent state and performs no side effects. BLOCKED
    returns without a model call; CHOICE is rejected because it belongs to the
    system-owned ActionChoiceCoordinator rather than FAST/DEEP.
    """

    def __init__(
        self,
        *,
        fast_backend,
        deep_backend,
        validator=None,
        trace=None,
    ):
        if not isinstance(fast_backend, CognitiveBackend):
            raise TypeError("CognitiveDispatcher fast_backend must implement CognitiveBackend")
        if not isinstance(deep_backend, CognitiveBackend):
            raise TypeError("CognitiveDispatcher deep_backend must implement CognitiveBackend")
        if validator is not None and not isinstance(validator, ProposalValidator):
            raise TypeError("CognitiveDispatcher validator must be ProposalValidator")
        if trace is not None and not isinstance(trace, DiagnosticTrace):
            raise TypeError("CognitiveDispatcher trace must be a DiagnosticTrace or null")
        self.fast_backend = fast_backend
        self.deep_backend = deep_backend
        self.validator = validator or ProposalValidator()
        self.trace = trace

    def dispatch(self, decision, *, persistent_task_id, task, resolution):
        if not isinstance(decision, CognitiveRouteDecision):
            raise TypeError("CognitiveDispatcher requires CognitiveRouteDecision")

        if decision.destination == CognitiveDestination.BLOCKED:
            validation = ProposalValidation(False, decision.reason)
            self._trace(
                "cognitive_dispatch: blocked "
                f"task={persistent_task_id} canonical={task.task_id} "
                f"reason={decision.reason}"
            )
            return CognitiveDispatchTurn(
                decision=decision,
                request=None,
                proposal=None,
                validation=validation,
                backend_called=False,
            )

        if decision.destination == CognitiveDestination.CHOICE:
            self._trace(
                "cognitive_dispatch: system_choice_boundary "
                f"task={persistent_task_id} canonical={task.task_id}"
            )
            raise ValueError(
                "System CHOICE route must use ActionChoiceCoordinator, not model dispatcher"
            )

        role = decision.role
        view = project(task, resolution, consumer=role.value)
        request = RoutedCognitiveRequest(
            persistent_task_id=persistent_task_id,
            canonical_task_id=task.task_id,
            source_id=task.source_id,
            role=role,
            view=view,
        )
        backend = self.fast_backend if role == CognitiveRole.FAST else self.deep_backend
        self._trace(
            "cognitive_dispatch: call "
            f"task={persistent_task_id} canonical={task.task_id} "
            f"role={role.value} route_reason={decision.reason}"
        )
        try:
            proposal = backend.complete(request)
        except Exception as error:
            self._trace(
                "cognitive_dispatch: backend_failure "
                f"task={persistent_task_id} canonical={task.task_id} "
                f"role={role.value} error={type(error).__name__}"
            )
            raise
        if not isinstance(proposal, CognitiveProposal):
            raise TypeError("Cognitive backend must return CognitiveProposal")
        validation = self.validator.validate(proposal)
        self._trace(
            "cognitive_dispatch: proposal "
            f"task={persistent_task_id} canonical={task.task_id} "
            f"role={role.value} kind={proposal.kind.value} "
            f"accepted={str(validation.accepted).lower()} "
            f"validation_reason={validation.reason}"
        )
        return CognitiveDispatchTurn(
            decision=decision,
            request=request,
            proposal=proposal,
            validation=validation,
            backend_called=True,
        )

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)


__all__ = [
    "CognitiveBackend",
    "CognitiveDispatchTurn",
    "CognitiveDispatcher",
    "CognitiveProposal",
    "ProjectedFastProposalAdapter",
    "ProposalKind",
    "ProposalValidation",
    "ProposalValidator",
    "RoutedCognitiveRequest",
]
