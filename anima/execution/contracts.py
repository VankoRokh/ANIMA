"""Neutral Stage 6 execution contracts owned by Task/Goal, not AgentRun/Planner."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID, uuid4

from anima.agent.tools import TOOL_NAME_PATTERN, TOOL_VERSION_PATTERN, ToolRegistry
from anima.tasks.contracts import validate_goal_id, validate_task_id


ACTION_ID_PREFIX = "xact_"
OPERATION_ID_PREFIX = "xop_"
RECEIPT_ID_PREFIX = "xrec_"
OBSERVATION_ID_PREFIX = "xobs_"
VERIFICATION_SPEC_ID_PREFIX = "xvs_"
VERIFICATION_RESULT_ID_PREFIX = "xvr_"

RECEIPT_STATUSES = {"succeeded", "failed", "timeout"}
VERIFICATION_OUTCOMES = {"none", "failure", "progress", "blocked", "success"}


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


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
    return value


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


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def _freeze_object(value, label):
    copied = _json_copy(value, label)
    if not isinstance(copied, dict):
        raise ValueError(f"{label} must be a JSON object")
    return _freeze(copied)


def _validate_tool(tool, version, label):
    tool = _require_text(tool, f"{label} tool")
    version = _require_text(version, f"{label} tool_version")
    if TOOL_NAME_PATTERN.fullmatch(tool) is None:
        raise ValueError(f"{label} tool must be a lowercase dotted identifier")
    if TOOL_VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"{label} tool_version contains unsupported characters")
    return tool, version


def _new_id(prefix):
    return f"{prefix}{uuid4()}"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """Trusted system mapping from a Choice candidate ID to one tool invocation."""

    candidate_id: str
    tool: str
    tool_version: str
    arguments: Mapping

    def __post_init__(self):
        candidate_id = _require_text(self.candidate_id, "ActionSpec candidate_id")
        tool, version = _validate_tool(self.tool, self.tool_version, "ActionSpec")
        arguments = _freeze_object(self.arguments, "ActionSpec arguments")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "tool_version", version)
        object.__setattr__(self, "arguments", arguments)

    def validate_tool_input(self, registry):
        if not isinstance(registry, ToolRegistry):
            raise TypeError("ActionSpec registry must be ToolRegistry")
        registry.validate_input(self.tool, self.tool_version, thaw(self.arguments))
        return self

    def to_dict(self):
        return {
            "candidate_id": self.candidate_id,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "arguments": thaw(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class ExecutionAction:
    public_id: str
    operation_id: str
    persistent_task_id: str
    goal_id: str
    candidate_id: str
    tool: str
    tool_version: str
    arguments: Mapping
    created_at: str

    def __post_init__(self):
        object.__setattr__(
            self,
            "public_id",
            _validate_prefixed_uuid4(
                self.public_id,
                prefix=ACTION_ID_PREFIX,
                label="ExecutionAction public_id",
            ),
        )
        object.__setattr__(
            self,
            "operation_id",
            _validate_prefixed_uuid4(
                self.operation_id,
                prefix=OPERATION_ID_PREFIX,
                label="ExecutionAction operation_id",
            ),
        )
        validate_task_id(self.persistent_task_id)
        validate_goal_id(self.goal_id)
        object.__setattr__(
            self,
            "candidate_id",
            _require_text(self.candidate_id, "ExecutionAction candidate_id"),
        )
        tool, version = _validate_tool(self.tool, self.tool_version, "ExecutionAction")
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "tool_version", version)
        object.__setattr__(
            self,
            "arguments",
            _freeze_object(self.arguments, "ExecutionAction arguments"),
        )
        object.__setattr__(
            self,
            "created_at",
            _validate_timestamp(self.created_at, "ExecutionAction created_at"),
        )

    @classmethod
    def from_spec(
        cls,
        spec,
        *,
        registry,
        persistent_task_id,
        goal_id,
        created_at,
        public_id=None,
        operation_id=None,
    ):
        if not isinstance(spec, ActionSpec):
            raise TypeError("ExecutionAction.from_spec() requires ActionSpec")
        spec.validate_tool_input(registry)
        return cls(
            public_id=public_id or _new_id(ACTION_ID_PREFIX),
            operation_id=operation_id or _new_id(OPERATION_ID_PREFIX),
            persistent_task_id=persistent_task_id,
            goal_id=goal_id,
            candidate_id=spec.candidate_id,
            tool=spec.tool,
            tool_version=spec.tool_version,
            arguments=thaw(spec.arguments),
            created_at=created_at,
        )

    def to_dict(self):
        return {
            "id": self.public_id,
            "operation_id": self.operation_id,
            "persistent_task_id": self.persistent_task_id,
            "goal_id": self.goal_id,
            "candidate_id": self.candidate_id,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "arguments": thaw(self.arguments),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    public_id: str
    action_id: str
    operation_id: str
    status: str
    output: object | None
    error_code: str | None
    error_message: str | None
    started_at: str
    finished_at: str

    def __post_init__(self):
        object.__setattr__(
            self,
            "public_id",
            _validate_prefixed_uuid4(
                self.public_id,
                prefix=RECEIPT_ID_PREFIX,
                label="ExecutionReceipt public_id",
            ),
        )
        _validate_prefixed_uuid4(
            self.action_id,
            prefix=ACTION_ID_PREFIX,
            label="ExecutionReceipt action_id",
        )
        _validate_prefixed_uuid4(
            self.operation_id,
            prefix=OPERATION_ID_PREFIX,
            label="ExecutionReceipt operation_id",
        )
        if self.status not in RECEIPT_STATUSES:
            raise ValueError(f"Unknown ExecutionReceipt status: {self.status!r}")
        output = None if self.output is None else _freeze(_json_copy(self.output, "ExecutionReceipt output"))
        started_at = _validate_timestamp(self.started_at, "ExecutionReceipt started_at")
        finished_at = _validate_timestamp(self.finished_at, "ExecutionReceipt finished_at")
        if datetime.fromisoformat(finished_at) < datetime.fromisoformat(started_at):
            raise ValueError("ExecutionReceipt finished_at cannot precede started_at")
        if self.status == "succeeded":
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("Succeeded ExecutionReceipt cannot contain an error")
        else:
            object.__setattr__(
                self,
                "error_code",
                _require_text(self.error_code, "ExecutionReceipt error_code"),
            )
            object.__setattr__(
                self,
                "error_message",
                _require_text(self.error_message, "ExecutionReceipt error_message"),
            )
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)

    @classmethod
    def create(
        cls,
        *,
        action,
        status,
        started_at,
        finished_at,
        output=None,
        error_code=None,
        error_message=None,
        public_id=None,
    ):
        if not isinstance(action, ExecutionAction):
            raise TypeError("ExecutionReceipt.create() requires ExecutionAction")
        return cls(
            public_id=public_id or _new_id(RECEIPT_ID_PREFIX),
            action_id=action.public_id,
            operation_id=action.operation_id,
            status=status,
            output=output,
            error_code=error_code,
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
        )

    def to_dict(self):
        return {
            "id": self.public_id,
            "action_id": self.action_id,
            "operation_id": self.operation_id,
            "status": self.status,
            "output": thaw(self.output),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True, slots=True)
class Observation:
    public_id: str
    action_id: str
    receipt_id: str
    source: str
    kind: str
    data: Mapping
    observed_at: str

    def __post_init__(self):
        object.__setattr__(
            self,
            "public_id",
            _validate_prefixed_uuid4(
                self.public_id,
                prefix=OBSERVATION_ID_PREFIX,
                label="Observation public_id",
            ),
        )
        _validate_prefixed_uuid4(
            self.action_id,
            prefix=ACTION_ID_PREFIX,
            label="Observation action_id",
        )
        _validate_prefixed_uuid4(
            self.receipt_id,
            prefix=RECEIPT_ID_PREFIX,
            label="Observation receipt_id",
        )
        object.__setattr__(self, "source", _require_text(self.source, "Observation source"))
        kind = _require_text(self.kind, "Observation kind")
        if TOOL_NAME_PATTERN.fullmatch(kind) is None:
            raise ValueError("Observation kind must be a lowercase dotted identifier")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "data",
            _freeze_object(self.data, "Observation data"),
        )
        object.__setattr__(
            self,
            "observed_at",
            _validate_timestamp(self.observed_at, "Observation observed_at"),
        )

    @classmethod
    def create(
        cls,
        *,
        action,
        receipt,
        source,
        kind,
        data,
        observed_at,
        public_id=None,
    ):
        if not isinstance(action, ExecutionAction):
            raise TypeError("Observation.create() requires ExecutionAction")
        if not isinstance(receipt, ExecutionReceipt):
            raise TypeError("Observation.create() requires ExecutionReceipt")
        if receipt.action_id != action.public_id or receipt.operation_id != action.operation_id:
            raise ValueError("Observation receipt does not belong to ExecutionAction")
        return cls(
            public_id=public_id or _new_id(OBSERVATION_ID_PREFIX),
            action_id=action.public_id,
            receipt_id=receipt.public_id,
            source=source,
            kind=kind,
            data=data,
            observed_at=observed_at,
        )

    def to_dict(self):
        return {
            "id": self.public_id,
            "action_id": self.action_id,
            "receipt_id": self.receipt_id,
            "source": self.source,
            "kind": self.kind,
            "data": thaw(self.data),
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class VerificationSpec:
    public_id: str
    goal_id: str
    criterion_kind: str
    parameters: Mapping

    def __post_init__(self):
        object.__setattr__(
            self,
            "public_id",
            _validate_prefixed_uuid4(
                self.public_id,
                prefix=VERIFICATION_SPEC_ID_PREFIX,
                label="VerificationSpec public_id",
            ),
        )
        validate_goal_id(self.goal_id)
        criterion = _require_text(self.criterion_kind, "VerificationSpec criterion_kind")
        if TOOL_NAME_PATTERN.fullmatch(criterion) is None:
            raise ValueError("VerificationSpec criterion_kind must be a lowercase dotted identifier")
        object.__setattr__(self, "criterion_kind", criterion)
        object.__setattr__(
            self,
            "parameters",
            _freeze_object(self.parameters, "VerificationSpec parameters"),
        )

    @classmethod
    def create(cls, *, goal_id, criterion_kind, parameters, public_id=None):
        return cls(
            public_id=public_id or _new_id(VERIFICATION_SPEC_ID_PREFIX),
            goal_id=goal_id,
            criterion_kind=criterion_kind,
            parameters=parameters,
        )


@dataclass(frozen=True, slots=True)
class VerificationResult:
    public_id: str
    verification_spec_id: str
    goal_id: str
    candidate_id: str
    observation_ids: tuple[str, ...]
    outcome: str
    criterion_satisfied: bool
    reason: str
    timestamp: str

    def __post_init__(self):
        object.__setattr__(
            self,
            "public_id",
            _validate_prefixed_uuid4(
                self.public_id,
                prefix=VERIFICATION_RESULT_ID_PREFIX,
                label="VerificationResult public_id",
            ),
        )
        _validate_prefixed_uuid4(
            self.verification_spec_id,
            prefix=VERIFICATION_SPEC_ID_PREFIX,
            label="VerificationResult verification_spec_id",
        )
        validate_goal_id(self.goal_id)
        object.__setattr__(
            self,
            "candidate_id",
            _require_text(self.candidate_id, "VerificationResult candidate_id"),
        )
        if not isinstance(self.observation_ids, tuple):
            raise ValueError("VerificationResult observation_ids must be a tuple")
        for public_id in self.observation_ids:
            _validate_prefixed_uuid4(
                public_id,
                prefix=OBSERVATION_ID_PREFIX,
                label="VerificationResult observation_id",
            )
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("VerificationResult observation_ids must be unique")
        if self.outcome not in VERIFICATION_OUTCOMES:
            raise ValueError(f"Unknown VerificationResult outcome: {self.outcome!r}")
        if type(self.criterion_satisfied) is not bool:
            raise ValueError("VerificationResult criterion_satisfied must be boolean")
        if self.criterion_satisfied != (self.outcome == "success"):
            raise ValueError("criterion_satisfied must be true exactly for success")
        if self.outcome != "none" and not self.observation_ids:
            raise ValueError("Verified non-none outcome requires Observation evidence")
        object.__setattr__(self, "reason", _require_text(self.reason, "VerificationResult reason"))
        object.__setattr__(
            self,
            "timestamp",
            _validate_timestamp(self.timestamp, "VerificationResult timestamp"),
        )

    @classmethod
    def create(
        cls,
        *,
        spec,
        candidate_id,
        observations,
        outcome,
        criterion_satisfied,
        reason,
        timestamp,
        public_id=None,
    ):
        if not isinstance(spec, VerificationSpec):
            raise TypeError("VerificationResult.create() requires VerificationSpec")
        observations = tuple(observations)
        if any(not isinstance(item, Observation) for item in observations):
            raise TypeError("VerificationResult observations must contain Observation values")
        return cls(
            public_id=public_id or _new_id(VERIFICATION_RESULT_ID_PREFIX),
            verification_spec_id=spec.public_id,
            goal_id=spec.goal_id,
            candidate_id=candidate_id,
            observation_ids=tuple(item.public_id for item in observations),
            outcome=outcome,
            criterion_satisfied=criterion_satisfied,
            reason=reason,
            timestamp=timestamp,
        )


__all__ = [
    "ActionSpec",
    "ExecutionAction",
    "ExecutionReceipt",
    "Observation",
    "VerificationResult",
    "VerificationSpec",
    "thaw",
]
