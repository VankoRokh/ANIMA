import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import UUID, uuid4

from anima.agent.contracts import ActionProposal
from anima.agent.tools import ToolDescriptor


PLANNER_TURN_ID_PREFIX = "pt_"
PLANNER_STATUSES = {"proposals_available", "cannot_progress"}
MAX_PROPOSALS = 3
MAX_TOOLS = 64
MAX_RECENT_STEPS = 16
MAX_RECENT_OBSERVATIONS = 16
MAX_REQUEST_JSON_CHARS = 100_000
MAX_SUMMARY_CHARS = 1_000
MAX_RATIONALE_CHARS = 1_000
MAX_EXPECTED_OBSERVATION_CHARS = 1_000


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _require_text(value, label, *, max_chars=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    value = value.strip()
    if max_chars is not None and len(value) > max_chars:
        raise ValueError(f"{label} exceeds {max_chars} characters")
    return value


def _validate_prefixed_uuid4(value, *, prefix, label):
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(f"{label} must be a {prefix}UUIDv4")
    raw = value[len(prefix):]
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a {prefix}UUIDv4") from error
    if parsed.version != 4 or str(parsed) != raw:
        raise ValueError(f"{label} must be a {prefix}UUIDv4")


def _validate_timestamp(value, label):
    value = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return value


def _json_copy(value, label):
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be JSON-compatible") from error


def _freeze_json(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value):
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_object(value, label):
    copied = _json_copy(value, label)
    if not isinstance(copied, dict):
        raise ValueError(f"{label} must be a JSON object")
    return _freeze_json(copied)


def _freeze_object_sequence(values, label, *, limit):
    values = tuple(values)
    if len(values) > limit:
        raise ValueError(f"{label} exceeds limit {limit}")
    frozen = []
    for index, value in enumerate(values):
        frozen.append(_freeze_object(value, f"{label}[{index}]"))
    return tuple(frozen)


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_exact_fields(record, expected, label):
    if not isinstance(record, dict):
        raise ValueError(f"{label} record must be an object")
    if set(record) != set(expected):
        missing = sorted(set(expected) - set(record))
        extra = sorted(set(record) - set(expected))
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("extra: " + ", ".join(extra))
        raise ValueError(f"{label} record fields mismatch ({'; '.join(details)})")


@dataclass(frozen=True, slots=True)
class PlannerRequest:
    run_id: str
    step_id: str
    goal_id: str
    goal_description: str
    success_criterion: str
    context: Mapping
    tools: tuple[ToolDescriptor, ...]
    recent_steps: tuple[Mapping, ...] = ()
    recent_observations: tuple[Mapping, ...] = ()
    constraints: Mapping = field(default_factory=dict)
    remaining_budget: Mapping = field(default_factory=dict)

    def __post_init__(self):
        _validate_prefixed_uuid4(self.run_id, prefix="ar_", label="PlannerRequest run_id")
        _validate_prefixed_uuid4(self.step_id, prefix="ast_", label="PlannerRequest step_id")
        _validate_prefixed_uuid4(self.goal_id, prefix="goal_", label="PlannerRequest goal_id")
        goal_description = _require_text(self.goal_description, "PlannerRequest goal_description")
        success_criterion = _require_text(self.success_criterion, "PlannerRequest success_criterion")
        context = _freeze_object(self.context, "PlannerRequest context")

        tools = tuple(self.tools)
        if len(tools) > MAX_TOOLS:
            raise ValueError(f"PlannerRequest tools exceeds limit {MAX_TOOLS}")
        if any(not isinstance(item, ToolDescriptor) for item in tools):
            raise TypeError("PlannerRequest tools must contain ToolDescriptor values")
        keys = [item.key for item in tools]
        if len(keys) != len(set(keys)):
            raise ValueError("PlannerRequest tools contains duplicate tool versions")

        recent_steps = _freeze_object_sequence(
            self.recent_steps,
            "PlannerRequest recent_steps",
            limit=MAX_RECENT_STEPS,
        )
        recent_observations = _freeze_object_sequence(
            self.recent_observations,
            "PlannerRequest recent_observations",
            limit=MAX_RECENT_OBSERVATIONS,
        )
        constraints = _freeze_object(self.constraints, "PlannerRequest constraints")
        remaining_budget = _freeze_object(
            self.remaining_budget,
            "PlannerRequest remaining_budget",
        )

        object.__setattr__(self, "goal_description", goal_description)
        object.__setattr__(self, "success_criterion", success_criterion)
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "recent_steps", recent_steps)
        object.__setattr__(self, "recent_observations", recent_observations)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "remaining_budget", remaining_budget)

        encoded = _canonical_json(self.to_dict())
        if len(encoded) > MAX_REQUEST_JSON_CHARS:
            raise ValueError(
                f"PlannerRequest exceeds {MAX_REQUEST_JSON_CHARS} serialized characters"
            )

    def tool_descriptor(self, name, version):
        for descriptor in self.tools:
            if descriptor.name == name and descriptor.version == version:
                return descriptor
        raise ValueError(f"Planner proposed unavailable tool: {name}@{version}")

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "step_id": self.step_id,
            "goal_id": self.goal_id,
            "goal_description": self.goal_description,
            "success_criterion": self.success_criterion,
            "context": _thaw_json(self.context),
            "tools": [descriptor.to_dict() for descriptor in self.tools],
            "recent_steps": [_thaw_json(item) for item in self.recent_steps],
            "recent_observations": [
                _thaw_json(item) for item in self.recent_observations
            ],
            "constraints": _thaw_json(self.constraints),
            "remaining_budget": _thaw_json(self.remaining_budget),
        }

    @classmethod
    def from_dict(cls, record):
        fields = {
            "run_id",
            "step_id",
            "goal_id",
            "goal_description",
            "success_criterion",
            "context",
            "tools",
            "recent_steps",
            "recent_observations",
            "constraints",
            "remaining_budget",
        }
        _validate_exact_fields(record, fields, "PlannerRequest")
        tools = record["tools"]
        if not isinstance(tools, list):
            raise ValueError("PlannerRequest tools must be an array")
        if not isinstance(record["recent_steps"], list):
            raise ValueError("PlannerRequest recent_steps must be an array")
        if not isinstance(record["recent_observations"], list):
            raise ValueError("PlannerRequest recent_observations must be an array")
        descriptors = []
        for index, item in enumerate(tools):
            if not isinstance(item, dict):
                raise ValueError(f"PlannerRequest tools[{index}] must be an object")
            descriptor_record = dict(item)
            if isinstance(descriptor_record.get("sandbox_scope"), list):
                descriptor_record["sandbox_scope"] = tuple(
                    descriptor_record["sandbox_scope"]
                )
            descriptors.append(ToolDescriptor(**descriptor_record))
        return cls(
            run_id=record["run_id"],
            step_id=record["step_id"],
            goal_id=record["goal_id"],
            goal_description=record["goal_description"],
            success_criterion=record["success_criterion"],
            context=record["context"],
            tools=tuple(descriptors),
            recent_steps=tuple(record["recent_steps"]),
            recent_observations=tuple(record["recent_observations"]),
            constraints=record["constraints"],
            remaining_budget=record["remaining_budget"],
        )


def planner_request_hash(request):
    if not isinstance(request, PlannerRequest):
        raise TypeError("planner_request_hash() requires a PlannerRequest")
    return hashlib.sha256(
        _canonical_json(request.to_dict()).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    tool: str
    tool_version: str
    arguments: Mapping
    expected_observation: str
    rationale_summary: str

    def __post_init__(self):
        tool = _require_text(self.tool, "ProposalDraft tool")
        tool_version = _require_text(self.tool_version, "ProposalDraft tool_version")
        arguments = _freeze_object(self.arguments, "ProposalDraft arguments")
        expected = _require_text(
            self.expected_observation,
            "ProposalDraft expected_observation",
            max_chars=MAX_EXPECTED_OBSERVATION_CHARS,
        )
        rationale = _require_text(
            self.rationale_summary,
            "ProposalDraft rationale_summary",
            max_chars=MAX_RATIONALE_CHARS,
        )
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "tool_version", tool_version)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "expected_observation", expected)
        object.__setattr__(self, "rationale_summary", rationale)

    def to_dict(self):
        return {
            "tool": self.tool,
            "tool_version": self.tool_version,
            "arguments": _thaw_json(self.arguments),
            "expected_observation": self.expected_observation,
            "rationale_summary": self.rationale_summary,
        }


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    status: str
    proposals: tuple[ProposalDraft, ...] = ()
    plan_summary: str | None = None

    def __post_init__(self):
        if self.status not in PLANNER_STATUSES:
            raise ValueError(f"Unknown PlannerDecision status: {self.status!r}")
        proposals = tuple(self.proposals)
        if any(not isinstance(item, ProposalDraft) for item in proposals):
            raise TypeError("PlannerDecision proposals must contain ProposalDraft values")
        if len(proposals) > MAX_PROPOSALS:
            raise ValueError(f"PlannerDecision exceeds max proposals {MAX_PROPOSALS}")
        if self.status == "proposals_available" and not proposals:
            raise ValueError("proposals_available requires at least one proposal")
        if self.status == "cannot_progress" and proposals:
            raise ValueError("cannot_progress cannot contain proposals")
        summary = self.plan_summary
        if summary is not None:
            summary = _require_text(
                summary,
                "PlannerDecision plan_summary",
                max_chars=MAX_SUMMARY_CHARS,
            )
        object.__setattr__(self, "proposals", proposals)
        object.__setattr__(self, "plan_summary", summary)

    def to_dict(self):
        return {
            "status": self.status,
            "proposals": [item.to_dict() for item in self.proposals],
            "plan_summary": self.plan_summary,
        }


@dataclass(frozen=True, slots=True)
class PlannerTurn:
    public_id: str
    run_id: str
    step_id: str
    planner_name: str
    planner_version: str
    request_hash: str
    status: str
    proposals: tuple[ActionProposal, ...]
    plan_summary: str | None
    created_at: str

    def __post_init__(self):
        _validate_prefixed_uuid4(
            self.public_id,
            prefix=PLANNER_TURN_ID_PREFIX,
            label="PlannerTurn public_id",
        )
        _validate_prefixed_uuid4(self.run_id, prefix="ar_", label="PlannerTurn run_id")
        _validate_prefixed_uuid4(self.step_id, prefix="ast_", label="PlannerTurn step_id")
        planner_name = _require_text(self.planner_name, "PlannerTurn planner_name")
        planner_version = _require_text(self.planner_version, "PlannerTurn planner_version")
        if (
            not isinstance(self.request_hash, str)
            or len(self.request_hash) != 64
            or any(char not in "0123456789abcdef" for char in self.request_hash)
        ):
            raise ValueError("PlannerTurn request_hash must be lowercase SHA-256")
        if self.status not in PLANNER_STATUSES:
            raise ValueError(f"Unknown PlannerTurn status: {self.status!r}")
        proposals = tuple(self.proposals)
        if any(not isinstance(item, ActionProposal) for item in proposals):
            raise TypeError("PlannerTurn proposals must contain ActionProposal values")
        if len(proposals) > MAX_PROPOSALS:
            raise ValueError(f"PlannerTurn exceeds max proposals {MAX_PROPOSALS}")
        if self.status == "proposals_available" and not proposals:
            raise ValueError("proposals_available PlannerTurn requires proposals")
        if self.status == "cannot_progress" and proposals:
            raise ValueError("cannot_progress PlannerTurn cannot contain proposals")
        ids = [item.public_id for item in proposals]
        if len(ids) != len(set(ids)):
            raise ValueError("PlannerTurn proposal IDs must be unique")
        ranks = [item.rank for item in proposals]
        if ranks != list(range(1, len(proposals) + 1)):
            raise ValueError("PlannerTurn proposal ranks must be consecutive from 1")
        summary = self.plan_summary
        if summary is not None:
            summary = _require_text(
                summary,
                "PlannerTurn plan_summary",
                max_chars=MAX_SUMMARY_CHARS,
            )
        created_at = _validate_timestamp(self.created_at, "PlannerTurn created_at")
        object.__setattr__(self, "planner_name", planner_name)
        object.__setattr__(self, "planner_version", planner_version)
        object.__setattr__(self, "proposals", proposals)
        object.__setattr__(self, "plan_summary", summary)
        object.__setattr__(self, "created_at", created_at)

    def owns_proposal(self, proposal_id):
        return any(item.public_id == proposal_id for item in self.proposals)

    def to_dict(self):
        return {
            "id": self.public_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "planner_name": self.planner_name,
            "planner_version": self.planner_version,
            "request_hash": self.request_hash,
            "status": self.status,
            "proposals": [item.to_dict() for item in self.proposals],
            "plan_summary": self.plan_summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, record):
        fields = {
            "id",
            "run_id",
            "step_id",
            "planner_name",
            "planner_version",
            "request_hash",
            "status",
            "proposals",
            "plan_summary",
            "created_at",
        }
        _validate_exact_fields(record, fields, "PlannerTurn")
        proposals = record["proposals"]
        if not isinstance(proposals, list):
            raise ValueError("PlannerTurn proposals must be an array")
        return cls(
            public_id=record["id"],
            run_id=record["run_id"],
            step_id=record["step_id"],
            planner_name=record["planner_name"],
            planner_version=record["planner_version"],
            request_hash=record["request_hash"],
            status=record["status"],
            proposals=tuple(ActionProposal.from_dict(item) for item in proposals),
            plan_summary=record["plan_summary"],
            created_at=record["created_at"],
        )


class PlannerAdapter(ABC):
    """Provider-neutral proposal boundary. It cannot execute tools or mutate ANIMA state."""

    def __init__(self, *, name, version):
        self.name = _require_text(name, "PlannerAdapter name")
        self.version = _require_text(version, "PlannerAdapter version")

    @abstractmethod
    def _decide(self, request):
        """Return PlannerDecision from a read-only PlannerRequest."""

    def plan(self, request, *, turn_id=None, created_at=None):
        if not isinstance(request, PlannerRequest):
            raise TypeError("PlannerAdapter.plan() requires a PlannerRequest")
        decision = self._decide(request)
        if not isinstance(decision, PlannerDecision):
            raise TypeError("PlannerAdapter must return PlannerDecision")

        proposals = []
        for rank, draft in enumerate(decision.proposals, start=1):
            descriptor = request.tool_descriptor(draft.tool, draft.tool_version)
            arguments = _thaw_json(draft.arguments)
            descriptor.validate_input(arguments)
            proposals.append(
                ActionProposal.create(
                    rank=rank,
                    tool=draft.tool,
                    tool_version=draft.tool_version,
                    arguments=arguments,
                    expected_observation=draft.expected_observation,
                    rationale_summary=draft.rationale_summary,
                )
            )

        return PlannerTurn(
            public_id=turn_id or f"{PLANNER_TURN_ID_PREFIX}{uuid4()}",
            run_id=request.run_id,
            step_id=request.step_id,
            planner_name=self.name,
            planner_version=self.version,
            request_hash=planner_request_hash(request),
            status=decision.status,
            proposals=tuple(proposals),
            plan_summary=decision.plan_summary,
            created_at=created_at or _now(),
        )


class DeterministicPlanner(PlannerAdapter):
    """Deterministic baseline whose strategy has no execution or writable-state handle."""

    def __init__(
        self,
        strategy: Callable[[PlannerRequest], PlannerDecision],
        *,
        name="deterministic",
        version="1",
    ):
        if not callable(strategy):
            raise TypeError("DeterministicPlanner strategy must be callable")
        super().__init__(name=name, version=version)
        self._strategy = strategy

    def _decide(self, request):
        return self._strategy(request)


__all__ = [
    "MAX_PROPOSALS",
    "PLANNER_STATUSES",
    "PLANNER_TURN_ID_PREFIX",
    "DeterministicPlanner",
    "PlannerAdapter",
    "PlannerDecision",
    "PlannerRequest",
    "PlannerTurn",
    "ProposalDraft",
    "planner_request_hash",
]
