"""System-owned FAST/DEEP routing for Stage 6.

The baseline is deliberately conservative. The router decides before any model
call and never asks a model to classify its own difficulty. Action-choice
cognition remains blocked until Stage 6.3 adds Goal/Internal State/Choice.
"""

from dataclasses import dataclass
from enum import Enum

from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask
from anima.resolution import ResolutionResult, ResolutionRoute


ROUTING_POLICY_VERSION = "stage6-baseline-v1"


class CognitiveRole(str, Enum):
    FAST = "FAST"
    DEEP = "DEEP"


class CognitiveDestination(str, Enum):
    FAST = "FAST"
    DEEP = "DEEP"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CognitiveRouteDecision:
    destination: CognitiveDestination
    reason: str
    policy_version: str = ROUTING_POLICY_VERSION

    def __post_init__(self):
        if not isinstance(self.destination, CognitiveDestination):
            raise ValueError("Cognitive route requires a typed destination")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("Cognitive route reason must be non-empty")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("Cognitive route policy_version must be non-empty")

    @property
    def blocked(self):
        return self.destination == CognitiveDestination.BLOCKED

    @property
    def role(self):
        if self.destination == CognitiveDestination.FAST:
            return CognitiveRole.FAST
        if self.destination == CognitiveDestination.DEEP:
            return CognitiveRole.DEEP
        return None


class CognitiveRouter:
    """Pure, bounded Stage 6 routing policy with optional diagnostic trace."""

    def __init__(self, *, trace=None):
        if trace is not None and not isinstance(trace, DiagnosticTrace):
            raise TypeError("CognitiveRouter trace must be a DiagnosticTrace or null")
        self.trace = trace

    def route(self, task, resolution):
        if not isinstance(task, CanonicalTask):
            raise TypeError("CognitiveRouter requires a CanonicalTask")
        if not isinstance(resolution, ResolutionResult):
            raise TypeError("CognitiveRouter requires a ResolutionResult")
        if resolution.route != ResolutionRoute.COGNITIVE_REQUIRED:
            raise ValueError("CognitiveRouter requires COGNITIVE_REQUIRED")

        # Action choice is intentionally unavailable to FAST/DEEP in 6.2. The
        # system will reopen this path only after Goal + State + Choice exist in
        # the integrated loop (Stage 6.3).
        if task.operation == "CHOOSE_ACTION" or task.output_contract == "candidate":
            decision = CognitiveRouteDecision(
                CognitiveDestination.BLOCKED,
                "action_choice_reserved_for_stage_6_3",
            )
        # Conflict resolution is the only baseline reason to pay the DEEP cost.
        # This is based on system-owned IR/resolution, never model self-report.
        elif (
            task.operation == "RESOLVE_CONFLICT"
            or resolution.reason == "conflicting_or_multiple_facts"
        ):
            decision = CognitiveRouteDecision(
                CognitiveDestination.DEEP,
                "explicit_conflict_reasoning",
            )
        else:
            decision = CognitiveRouteDecision(
                CognitiveDestination.FAST,
                "bounded_fast_baseline",
            )

        self._trace(
            "cognitive_router: "
            f"canonical={task.task_id} source={task.source_id} "
            f"resolution_reason={resolution.reason} "
            f"destination={decision.destination.value} "
            f"route_reason={decision.reason} "
            f"policy={decision.policy_version}"
        )
        return decision

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)


__all__ = [
    "CognitiveDestination",
    "CognitiveRole",
    "CognitiveRouteDecision",
    "CognitiveRouter",
    "ROUTING_POLICY_VERSION",
]
