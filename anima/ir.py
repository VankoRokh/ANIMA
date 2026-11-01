"""Small, model-independent ANIMA task contracts. No persistence or routing ownership."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal
import math
from types import MappingProxyType


def require_id(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty identifier")


def freeze(value):
    """Snapshot JSON-shaped data so nested caller mutations cannot alter a task."""
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Task data keys must be strings")
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal) and value.is_finite():
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("Task data must contain finite JSON values or exact decimals")


def plain(value):
    """Create detached JSON-compatible data for rendering or diagnostics."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value


class ConstraintRule(str, Enum):
    PRESERVE_ACTIVE_TASK = "PRESERVE_ACTIVE_TASK"
    CHARGER_AVAILABLE = "CHARGER_AVAILABLE"
    BATTERY_ABOVE_THRESHOLD = "BATTERY_ABOVE_THRESHOLD"


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    value: object
    subject: str | None = None
    predicate: str | None = None
    provenance: tuple[str, ...] = ()
    confidence: float | None = None
    observed_at: str | None = None

    def __post_init__(self):
        require_id(self.evidence_id, "Evidence ID")
        if (self.subject is None) != (self.predicate is None):
            raise ValueError("Structured evidence requires both subject and predicate")
        for name in ("subject", "predicate"):
            if getattr(self, name) is not None:
                require_id(getattr(self, name), name)
        if isinstance(self.provenance, str):
            raise ValueError("Provenance must be a collection of references")
        for item in self.provenance:
            require_id(item, "Provenance reference")
        if self.confidence is not None and (
            type(self.confidence) not in (int, float)
            or not 0 <= self.confidence <= 1
            or not math.isfinite(self.confidence)
        ):
            raise ValueError("Evidence confidence must be within 0..1")
        if self.observed_at is not None:
            from datetime import datetime
            timestamp = datetime.fromisoformat(self.observed_at)
            if timestamp.utcoffset() is None:
                raise ValueError("Evidence observation time must include UTC offset")
        object.__setattr__(self, "value", freeze(self.value))
        object.__setattr__(self, "provenance", tuple(self.provenance))


@dataclass(frozen=True)
class HardConstraint:
    constraint_id: str
    candidate_id: str
    rule: str

    def __post_init__(self):
        require_id(self.constraint_id, "Constraint ID")
        require_id(self.candidate_id, "Constraint candidate")
        require_id(self.rule, "Constraint rule")


@dataclass(frozen=True)
class FormalPolicy:
    """Task-local policy data; resolver validates authority before applying it.

    Incomplete/unsupported policy data remains observable rather than being dropped.
    Only ACTION_PRIORITY has production semantics.
    """

    policy_id: str
    type: str = "ACTION_PRIORITY"
    priority: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("policy_id", "type", "priority"):
            object.__setattr__(self, name, freeze(getattr(self, name)))


@dataclass(frozen=True)
class CanonicalTask:
    task_id: str
    source_id: str
    operation: str
    subject: str | None = None
    predicate: str | None = None
    arguments: Mapping = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    state: Mapping = field(default_factory=dict)
    candidates: tuple[str, ...] | None = None
    constraints: tuple[HardConstraint, ...] = ()
    policies: tuple[FormalPolicy, ...] = ()
    raw_input: str | None = None
    goal: str | None = None
    preference: str | None = None
    output_contract: str = "text"

    def __post_init__(self):
        for name in ("task_id", "source_id", "operation"):
            require_id(getattr(self, name), name)
        for name in ("subject", "predicate"):
            if getattr(self, name) is not None:
                require_id(getattr(self, name), name)
        if self.operation == "QUERY_FACT" and not (self.subject and self.predicate):
            raise ValueError("QUERY_FACT requires resolved subject and predicate")
        if self.raw_input is not None and not isinstance(self.raw_input, str):
            raise ValueError("raw_input must be text or None")
        if self.output_contract not in ("text", "candidate"):
            raise ValueError("Output contract must be text or candidate")
        for name in ("goal", "preference"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be text or None")
        for name in ("arguments", "state"):
            if not isinstance(getattr(self, name), Mapping):
                raise ValueError(f"{name} must be a mapping")
            object.__setattr__(self, name, freeze(getattr(self, name)))
        for name, item_type in (("evidence", Evidence), ("constraints", HardConstraint),
                                ("policies", FormalPolicy)):
            items = tuple(getattr(self, name))
            if not all(isinstance(item, item_type) for item in items):
                raise ValueError(f"{name} contains invalid contracts")
            object.__setattr__(self, name, items)
        if isinstance(self.candidates, str):
            raise ValueError("Candidates must be a collection of IDs")
        if self.operation != "CHOOSE_ACTION" and (self.constraints or self.policies):
            raise ValueError("Stage 5 action constraints/policies require CHOOSE_ACTION")
        candidates = None if self.candidates is None else tuple(self.candidates)
        for item in candidates or ():
            require_id(item, "Candidate ID")
        if candidates is not None and len(set(candidates)) != len(candidates):
            raise ValueError("Candidate IDs must be unique")
        object.__setattr__(self, "candidates", candidates)
        for name, ids in (
            ("evidence", [item.evidence_id for item in self.evidence]),
            ("constraints", [item.constraint_id for item in self.constraints]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {name} IDs")
        if candidates is not None and any(item.candidate_id not in candidates for item in self.constraints):
            raise ValueError("Constraint references unknown candidate")
