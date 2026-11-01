"""Typed resolution outcomes; Canonical IR belongs to anima.ir."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from anima.ir import freeze, require_id


class ResolutionRoute(str, Enum):
    DETERMINISTIC_RESULT = "DETERMINISTIC_RESULT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    COGNITIVE_REQUIRED = "COGNITIVE_REQUIRED"


class DeterministicOutcome(str, Enum):
    VALUE = "VALUE"
    NO_ADMISSIBLE_ACTION = "NO_ADMISSIBLE_ACTION"


@dataclass(frozen=True)
class PolicyEvaluation:
    policy_id: str
    winner: str | None
    valid: bool
    reason: str


@dataclass(frozen=True)
class ResolutionResult:
    route: ResolutionRoute
    reason: str
    value: object = None
    outcome: DeterministicOutcome | None = None
    missing: tuple[str, ...] = ()
    next_source: str | None = None
    remaining: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()
    rejected: Mapping = field(default_factory=dict)
    derived: Mapping = field(default_factory=dict)
    policies: tuple[PolicyEvaluation, ...] = ()

    def __post_init__(self):
        if not isinstance(self.route, ResolutionRoute):
            raise ValueError("Resolution requires a typed route")
        require_id(self.reason, "Resolution reason")
        if self.route == ResolutionRoute.DETERMINISTIC_RESULT:
            if not isinstance(self.outcome, DeterministicOutcome):
                raise ValueError("Deterministic result requires typed outcome")
            if self.outcome == DeterministicOutcome.NO_ADMISSIBLE_ACTION and (self.value is not None or self.remaining or self.unverified):
                raise ValueError("No admissible action cannot carry a winner or possible candidates")
        elif self.value is not None or self.outcome is not None:
            raise ValueError("Unresolved result cannot contain a decision")
        if self.route == ResolutionRoute.INSUFFICIENT_DATA and not self.missing:
            raise ValueError("Insufficient data requires missing requirements")
        for name in ("value", "rejected", "derived"):
            object.__setattr__(self, name, freeze(getattr(self, name)))
        for name in ("missing", "remaining", "unverified", "policies"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def applied_policy_ids(self):
        return tuple(item.policy_id for item in self.policies if item.valid)
