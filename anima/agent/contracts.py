import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import UUID, uuid4

from anima.agent.tools import TOOL_NAME_PATTERN, TOOL_VERSION_PATTERN, ToolRegistry


ACTION_PROPOSAL_ID_PREFIX = "ap_"
ACTION_ID_PREFIX = "act_"
EXECUTION_RECEIPT_ID_PREFIX = "er_"
OBSERVATION_ID_PREFIX = "obs_"
VERIFICATION_SPEC_ID_PREFIX = "vs_"
VERIFICATION_RESULT_ID_PREFIX = "vr_"

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


def _validate_timestamp(value, label):
    value = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return value


def _parse_timestamp(value, label):
    _validate_timestamp(value, label)
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _validate_tool_ref(name, version, label):
    name = _require_text(name, f"{label} tool")
    version = _require_text(version, f"{label} tool_version")
    if TOOL_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(f"{label} tool must be a lowercase dotted identifier")
    if TOOL_VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"{label} tool_version contains unsupported characters")
    return name, version


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


def _new_id(prefix):
    return f"{prefix}{uuid4()}"


def _validate_rank(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("ActionProposal rank must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class ActionProposal:
    public_id: str
    rank: int
    tool: str
    tool_version: str
    arguments: Mapping
    expected_observation: str
    rationale_summary: str

    def __post_init__(self):
        _validate_prefixed_uuid4(
            self.public_id,
            prefix=ACTION_PROPOSAL_ID_PREFIX,
            label="ActionProposal public_id",
        )
        _validate_rank(self.rank)
        tool, version = _validate_tool_ref(self.tool, self.tool_version, "ActionProposal")
        arguments = _freeze_object(self.arguments, "ActionProposal arguments")
        expected = _require_text(
            self.expected_observation,
            "ActionProposal expected_observation",
        )
        rationale = _require_text(self.rationale_summary, "ActionProposal rationale_summary")
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "tool_version", version)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "expected_observation", expected)
        object.__setattr__(self, "rationale_summary", rationale)

    @classmethod
    def create(
        cls,
        *,
        rank,
        tool,
        tool_version,
        arguments,
        expected_observation,
        rationale_summary,
        public_id=None,
    ):
        return cls(
            public_id=public_id or _new_id(ACTION_PROPOSAL_ID_PREFIX),
            rank=rank,
            tool=tool,
            tool_version=tool_version,
            arguments=arguments,
            expected_observation=expected_observation,
            rationale_summary=rationale_summary,
        )

    def validate_tool_input(self, registry):
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        registry.validate_input(self.tool, self.tool_version, _thaw_json(self.arguments))
        return self

    def to_dict(self):
        return {
            "id": self.public_id,
            "rank": self.rank,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "arguments": _thaw_json(self.arguments),
            "expected_observation": self.expected_observation,
            "rationale_summary": self.rationale_summary,
        }

    @classmethod
    def from_dict(cls, record):
        fields = {
            "id",
            "rank",
            "tool",
            "tool_version",
            "arguments",
            "expected_observation",
            "rationale_summary",
        }
        _validate_exact_fields(record, fields, "ActionProposal")
        return cls(
            public_id=record["id"],
            rank=record["rank"],
            tool=record["tool"],
            tool_version=record["tool_version"],
            arguments=record["arguments"],
            expected_observation=record["expected_observation"],
            rationale_summary=record["rationale_summary"],
        )


@dataclass(frozen=True, slots=True)
class Action:
    public_id: str
    proposal_id: str
    run_id: str
    step_id: str
    operation_id: str
    tool: str
    tool_version: str
    arguments: Mapping
    created_at: str

    def __post_init__(self):
        _validate_prefixed_uuid4(self.public_id, prefix=ACTION_ID_PREFIX, label="Action public_id")
        _validate_prefixed_uuid4(
            self.proposal_id,
            prefix=ACTION_PROPOSAL_ID_PREFIX,
            label="Action proposal_id",
        )
        _validate_prefixed_uuid4(self.run_id, prefix="ar_", label="Action run_id")
        _validate_prefixed_uuid4(self.step_id, prefix="ast_", label="Action step_id")
        _validate_prefixed_uuid4(self.operation_id, prefix="aop_", label="Action operation_id")
        tool, version = _validate_tool_ref(self.tool, self.tool_version, "Action")
        arguments = _freeze_object(self.arguments, "Action arguments")
        created_at = _validate_timestamp(self.created_at, "Action created_at")
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "tool_version", version)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "created_at", created_at)

    @classmethod
    def from_proposal(
        cls,
        proposal,
        *,
        registry,
        run_id,
        step_id,
        operation_id,
        created_at,
        public_id=None,
    ):
        if not isinstance(proposal, ActionProposal):
            raise TypeError("Action.from_proposal() requires an ActionProposal")
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        arguments = _thaw_json(proposal.arguments)
        registry.validate_input(proposal.tool, proposal.tool_version, arguments)
        return cls(
            public_id=public_id or _new_id(ACTION_ID_PREFIX),
            proposal_id=proposal.public_id,
            run_id=run_id,
            step_id=step_id,
            operation_id=operation_id,
            tool=proposal.tool,
            tool_version=proposal.tool_version,
            arguments=arguments,
            created_at=created_at,
        )

    def to_dict(self):
        return {
            "id": self.public_id,
            "proposal_id": self.proposal_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "operation_id": self.operation_id,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "arguments": _thaw_json(self.arguments),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, record):
        fields = {
            "id",
            "proposal_id",
            "run_id",
            "step_id",
            "operation_id",
            "tool",
            "tool_version",
            "arguments",
            "created_at",
        }
        _validate_exact_fields(record, fields, "Action")
        return cls(
            public_id=record["id"],
            proposal_id=record["proposal_id"],
            run_id=record["run_id"],
            step_id=record["step_id"],
            operation_id=record["operation_id"],
            tool=record["tool"],
            tool_version=record["tool_version"],
            arguments=record["arguments"],
            created_at=record["created_at"],
        )


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
        _validate_prefixed_uuid4(
            self.public_id,
            prefix=EXECUTION_RECEIPT_ID_PREFIX,
            label="ExecutionReceipt public_id",
        )
        _validate_prefixed_uuid4(self.action_id, prefix=ACTION_ID_PREFIX, label="ExecutionReceipt action_id")
        _validate_prefixed_uuid4(self.operation_id, prefix="aop_", label="ExecutionReceipt operation_id")
        if self.status not in RECEIPT_STATUSES:
            raise ValueError(f"Unknown ExecutionReceipt status: {self.status!r}")
        output = None if self.output is None else _freeze_json(_json_copy(self.output, "ExecutionReceipt output"))
        started = _validate_timestamp(self.started_at, "ExecutionReceipt started_at")
        finished = _validate_timestamp(self.finished_at, "ExecutionReceipt finished_at")
        if _parse_timestamp(finished, "ExecutionReceipt finished_at") < _parse_timestamp(
            started,
            "ExecutionReceipt started_at",
        ):
            raise ValueError("ExecutionReceipt finished_at cannot precede started_at")

        error_code = self.error_code
        error_message = self.error_message
        if self.status == "succeeded":
            if error_code is not None or error_message is not None:
                raise ValueError("Succeeded ExecutionReceipt cannot contain an error")
        else:
            error_code = _require_text(error_code, "ExecutionReceipt error_code")
            error_message = _require_text(error_message, "ExecutionReceipt error_message")

        object.__setattr__(self, "output", output)
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "error_message", error_message)
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)

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
        if not isinstance(action, Action):
            raise TypeError("ExecutionReceipt.create() requires an Action")
        return cls(
            public_id=public_id or _new_id(EXECUTION_RECEIPT_ID_PREFIX),
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
            "output": _thaw_json(self.output),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, record):
        fields = {
            "id",
            "action_id",
            "operation_id",
            "status",
            "output",
            "error_code",
            "error_message",
            "started_at",
            "finished_at",
        }
        _validate_exact_fields(record, fields, "ExecutionReceipt")
        return cls(
            public_id=record["id"],
            action_id=record["action_id"],
            operation_id=record["operation_id"],
            status=record["status"],
            output=record["output"],
            error_code=record["error_code"],
            error_message=record["error_message"],
            started_at=record["started_at"],
            finished_at=record["finished_at"],
        )


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
        _validate_prefixed_uuid4(self.public_id, prefix=OBSERVATION_ID_PREFIX, label="Observation public_id")
        _validate_prefixed_uuid4(self.action_id, prefix=ACTION_ID_PREFIX, label="Observation action_id")
        _validate_prefixed_uuid4(
            self.receipt_id,
            prefix=EXECUTION_RECEIPT_ID_PREFIX,
            label="Observation receipt_id",
        )
        source = _require_text(self.source, "Observation source")
        kind = _require_text(self.kind, "Observation kind")
        if TOOL_NAME_PATTERN.fullmatch(kind) is None:
            raise ValueError("Observation kind must be a lowercase dotted identifier")
        data = _freeze_object(self.data, "Observation data")
        observed_at = _validate_timestamp(self.observed_at, "Observation observed_at")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "observed_at", observed_at)

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
        if not isinstance(action, Action):
            raise TypeError("Observation.create() requires an Action")
        if not isinstance(receipt, ExecutionReceipt):
            raise TypeError("Observation.create() requires an ExecutionReceipt")
        if receipt.action_id != action.public_id or receipt.operation_id != action.operation_id:
            raise ValueError("Observation receipt does not belong to the supplied Action")
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
            "data": _thaw_json(self.data),
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, record):
        fields = {"id", "action_id", "receipt_id", "source", "kind", "data", "observed_at"}
        _validate_exact_fields(record, fields, "Observation")
        return cls(
            public_id=record["id"],
            action_id=record["action_id"],
            receipt_id=record["receipt_id"],
            source=record["source"],
            kind=record["kind"],
            data=record["data"],
            observed_at=record["observed_at"],
        )


@dataclass(frozen=True, slots=True)
class VerificationSpec:
    public_id: str
    run_id: str
    verifier: str
    verifier_version: str
    criterion_kind: str
    parameters: Mapping

    def __post_init__(self):
        _validate_prefixed_uuid4(
            self.public_id,
            prefix=VERIFICATION_SPEC_ID_PREFIX,
            label="VerificationSpec public_id",
        )
        _validate_prefixed_uuid4(self.run_id, prefix="ar_", label="VerificationSpec run_id")
        verifier = _require_text(self.verifier, "VerificationSpec verifier")
        verifier_version = _require_text(self.verifier_version, "VerificationSpec verifier_version")
        criterion_kind = _require_text(self.criterion_kind, "VerificationSpec criterion_kind")
        if TOOL_NAME_PATTERN.fullmatch(criterion_kind) is None:
            raise ValueError("VerificationSpec criterion_kind must be a lowercase dotted identifier")
        parameters = _freeze_object(self.parameters, "VerificationSpec parameters")
        object.__setattr__(self, "verifier", verifier)
        object.__setattr__(self, "verifier_version", verifier_version)
        object.__setattr__(self, "criterion_kind", criterion_kind)
        object.__setattr__(self, "parameters", parameters)

    @classmethod
    def create(
        cls,
        *,
        run_id,
        verifier,
        verifier_version,
        criterion_kind,
        parameters,
        public_id=None,
    ):
        return cls(
            public_id=public_id or _new_id(VERIFICATION_SPEC_ID_PREFIX),
            run_id=run_id,
            verifier=verifier,
            verifier_version=verifier_version,
            criterion_kind=criterion_kind,
            parameters=parameters,
        )

    def to_dict(self):
        return {
            "id": self.public_id,
            "run_id": self.run_id,
            "verifier": self.verifier,
            "verifier_version": self.verifier_version,
            "criterion_kind": self.criterion_kind,
            "parameters": _thaw_json(self.parameters),
        }

    @classmethod
    def from_dict(cls, record):
        fields = {"id", "run_id", "verifier", "verifier_version", "criterion_kind", "parameters"}
        _validate_exact_fields(record, fields, "VerificationSpec")
        return cls(
            public_id=record["id"],
            run_id=record["run_id"],
            verifier=record["verifier"],
            verifier_version=record["verifier_version"],
            criterion_kind=record["criterion_kind"],
            parameters=record["parameters"],
        )


@dataclass(frozen=True, slots=True)
class VerificationResult:
    public_id: str
    run_id: str
    step_id: str
    verification_spec_id: str
    observation_ids: tuple[str, ...]
    outcome: str
    criterion_satisfied: bool
    reason: str
    importance: int
    candidate_id: str | None
    timestamp: str

    def __post_init__(self):
        _validate_prefixed_uuid4(
            self.public_id,
            prefix=VERIFICATION_RESULT_ID_PREFIX,
            label="VerificationResult public_id",
        )
        _validate_prefixed_uuid4(self.run_id, prefix="ar_", label="VerificationResult run_id")
        _validate_prefixed_uuid4(self.step_id, prefix="ast_", label="VerificationResult step_id")
        _validate_prefixed_uuid4(
            self.verification_spec_id,
            prefix=VERIFICATION_SPEC_ID_PREFIX,
            label="VerificationResult verification_spec_id",
        )
        if not isinstance(self.observation_ids, tuple):
            raise ValueError("VerificationResult observation_ids must be a tuple")
        for observation_id in self.observation_ids:
            _validate_prefixed_uuid4(
                observation_id,
                prefix=OBSERVATION_ID_PREFIX,
                label="VerificationResult observation_id",
            )
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("VerificationResult observation_ids must not contain duplicates")
        if self.outcome not in VERIFICATION_OUTCOMES:
            raise ValueError(f"Unknown VerificationResult outcome: {self.outcome!r}")
        if type(self.criterion_satisfied) is not bool:
            raise ValueError("VerificationResult criterion_satisfied must be boolean")
        if self.criterion_satisfied != (self.outcome == "success"):
            raise ValueError(
                "VerificationResult criterion_satisfied must be true exactly for success"
            )
        if self.outcome == "none":
            if self.candidate_id is not None:
                _validate_prefixed_uuid4(
                    self.candidate_id,
                    prefix=ACTION_PROPOSAL_ID_PREFIX,
                    label="VerificationResult candidate_id",
                )
        else:
            if not self.observation_ids:
                raise ValueError("Verified non-none outcome requires at least one Observation")
            _validate_prefixed_uuid4(
                self.candidate_id,
                prefix=ACTION_PROPOSAL_ID_PREFIX,
                label="VerificationResult candidate_id",
            )
        if (
            not isinstance(self.importance, int)
            or isinstance(self.importance, bool)
            or self.importance not in range(4)
        ):
            raise ValueError("VerificationResult importance must be an integer from 0 to 3")
        reason = _require_text(self.reason, "VerificationResult reason")
        timestamp = _validate_timestamp(self.timestamp, "VerificationResult timestamp")
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "timestamp", timestamp)

    @classmethod
    def create(
        cls,
        *,
        run_id,
        step_id,
        verification_spec_id,
        observation_ids,
        outcome,
        criterion_satisfied,
        reason,
        importance=1,
        candidate_id=None,
        timestamp,
        public_id=None,
    ):
        return cls(
            public_id=public_id or _new_id(VERIFICATION_RESULT_ID_PREFIX),
            run_id=run_id,
            step_id=step_id,
            verification_spec_id=verification_spec_id,
            observation_ids=tuple(observation_ids),
            outcome=outcome,
            criterion_satisfied=criterion_satisfied,
            reason=reason,
            importance=importance,
            candidate_id=candidate_id,
            timestamp=timestamp,
        )

    def to_dict(self):
        return {
            "id": self.public_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "verification_spec_id": self.verification_spec_id,
            "observation_ids": list(self.observation_ids),
            "outcome": self.outcome,
            "criterion_satisfied": self.criterion_satisfied,
            "reason": self.reason,
            "importance": self.importance,
            "candidate_id": self.candidate_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, record):
        fields = {
            "id",
            "run_id",
            "step_id",
            "verification_spec_id",
            "observation_ids",
            "outcome",
            "criterion_satisfied",
            "reason",
            "importance",
            "candidate_id",
            "timestamp",
        }
        _validate_exact_fields(record, fields, "VerificationResult")
        if not isinstance(record["observation_ids"], list):
            raise ValueError("VerificationResult observation_ids record field must be an array")
        return cls(
            public_id=record["id"],
            run_id=record["run_id"],
            step_id=record["step_id"],
            verification_spec_id=record["verification_spec_id"],
            observation_ids=tuple(record["observation_ids"]),
            outcome=record["outcome"],
            criterion_satisfied=record["criterion_satisfied"],
            reason=record["reason"],
            importance=record["importance"],
            candidate_id=record["candidate_id"],
            timestamp=record["timestamp"],
        )


def validate_execution_trace(*, proposal, action, receipt, observation):
    if not isinstance(proposal, ActionProposal):
        raise TypeError("proposal must be an ActionProposal")
    if not isinstance(action, Action):
        raise TypeError("action must be an Action")
    if not isinstance(receipt, ExecutionReceipt):
        raise TypeError("receipt must be an ExecutionReceipt")
    if not isinstance(observation, Observation):
        raise TypeError("observation must be an Observation")

    if action.proposal_id != proposal.public_id:
        raise ValueError("Dangling Action proposal_id")
    if action.tool != proposal.tool or action.tool_version != proposal.tool_version:
        raise ValueError("Action tool does not match ActionProposal")
    if _json_copy(_thaw_json(action.arguments), "Action arguments") != _json_copy(
        _thaw_json(proposal.arguments),
        "ActionProposal arguments",
    ):
        raise ValueError("Action arguments do not match ActionProposal")
    if receipt.action_id != action.public_id:
        raise ValueError("Dangling ExecutionReceipt action_id")
    if receipt.operation_id != action.operation_id:
        raise ValueError("ExecutionReceipt operation_id does not match Action")
    if observation.action_id != action.public_id:
        raise ValueError("Dangling Observation action_id")
    if observation.receipt_id != receipt.public_id:
        raise ValueError("Dangling Observation receipt_id")
    return True


def validate_verification_trace(*, spec, result, observations):
    if not isinstance(spec, VerificationSpec):
        raise TypeError("spec must be a VerificationSpec")
    if not isinstance(result, VerificationResult):
        raise TypeError("result must be a VerificationResult")
    observations = tuple(observations)
    if any(not isinstance(item, Observation) for item in observations):
        raise TypeError("observations must contain Observation values")

    if result.verification_spec_id != spec.public_id:
        raise ValueError("Dangling VerificationResult verification_spec_id")
    if result.run_id != spec.run_id:
        raise ValueError("VerificationResult run_id does not match VerificationSpec")

    supplied_ids = tuple(item.public_id for item in observations)
    if supplied_ids != result.observation_ids:
        raise ValueError("VerificationResult observation_ids do not match supplied evidence")
    return True
