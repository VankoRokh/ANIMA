import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from anima.agent.planner import PlannerTurn
from anima.agent.tools import ToolRegistry
from anima.internal_state.choice_engine import Candidate, ChoiceEngine


MAX_HISTORY_ENTRIES = 64
HISTORY_OUTCOMES = {"none", "failure", "progress", "blocked", "success"}

BASE_SCORE_FIRST = 0.70
BASE_SCORE_STEP = 0.08
BASE_SCORE_FLOOR = 0.45

EFFORT_COST = {
    "cheap": 0.15,
    "normal": 0.50,
    "expensive": 0.85,
}

INFORMATION_GAIN = {
    "read_only": 1.00,
    "reversible_write": 0.20,
    "irreversible": 0.05,
}

IRREVERSIBLE_RISK = {
    ("read_only", "repeat_safe"): 0.00,
    ("reversible_write", "repeat_safe"): 0.20,
    ("reversible_write", "keyed"): 0.30,
    ("reversible_write", "none"): 0.45,
    ("irreversible", "repeat_safe"): 0.70,
    ("irreversible", "keyed"): 0.85,
    ("irreversible", "none"): 1.00,
}


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


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


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def action_fingerprint(tool, tool_version, arguments):
    tool = _require_text(tool, "Action fingerprint tool")
    tool_version = _require_text(tool_version, "Action fingerprint tool_version")
    arguments = _json_copy(arguments, "Action fingerprint arguments")
    if not isinstance(arguments, dict):
        raise ValueError("Action fingerprint arguments must be a JSON object")
    payload = {
        "tool": tool,
        "tool_version": tool_version,
        "arguments": arguments,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CandidateHistoryEntry:
    tool: str
    tool_version: str
    arguments: Mapping
    outcome: str
    verified: bool

    def __post_init__(self):
        tool = _require_text(self.tool, "CandidateHistoryEntry tool")
        version = _require_text(
            self.tool_version,
            "CandidateHistoryEntry tool_version",
        )
        arguments = _freeze_object(
            self.arguments,
            "CandidateHistoryEntry arguments",
        )
        if self.outcome not in HISTORY_OUTCOMES:
            raise ValueError(
                f"Unknown CandidateHistoryEntry outcome: {self.outcome!r}"
            )
        if type(self.verified) is not bool:
            raise ValueError("CandidateHistoryEntry verified must be boolean")
        if self.outcome in {"progress", "success"} and not self.verified:
            raise ValueError(
                "progress/success history requires verified=true"
            )
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "tool_version", version)
        object.__setattr__(self, "arguments", arguments)

    @property
    def fingerprint(self):
        return action_fingerprint(
            self.tool,
            self.tool_version,
            _thaw_json(self.arguments),
        )


@dataclass(frozen=True, slots=True)
class CandidateFeatureTrace:
    proposal_id: str
    tool: str
    tool_version: str
    action_fingerprint: str
    base_score: float
    effort_cost: float
    information_gain: float
    irreversible_risk: float
    repeated_failure: float
    alternative_value: float
    verified_continuation: float
    planner_rank: int
    matching_failures: int
    latest_matching_outcome: str | None
    latest_failed_fingerprint: str | None

    def to_dict(self):
        return {
            "proposal_id": self.proposal_id,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "action_fingerprint": self.action_fingerprint,
            "base_score": self.base_score,
            "effort_cost": self.effort_cost,
            "information_gain": self.information_gain,
            "irreversible_risk": self.irreversible_risk,
            "repeated_failure": self.repeated_failure,
            "alternative_value": self.alternative_value,
            "verified_continuation": self.verified_continuation,
            "planner_rank": self.planner_rank,
            "matching_failures": self.matching_failures,
            "latest_matching_outcome": self.latest_matching_outcome,
            "latest_failed_fingerprint": self.latest_failed_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class CandidateAdaptation:
    candidates: tuple[Candidate, ...]
    traces: tuple[CandidateFeatureTrace, ...]

    def trace_for(self, proposal_id):
        proposal_id = _require_text(proposal_id, "CandidateAdaptation proposal_id")
        for trace in self.traces:
            if trace.proposal_id == proposal_id:
                return trace
        raise ValueError(f"Unknown adapted proposal: {proposal_id}")


class CandidateAdapter:
    """Convert Planner proposals into system-owned Stage 2 Candidate features."""

    def __init__(self, registry):
        if not isinstance(registry, ToolRegistry):
            raise TypeError("CandidateAdapter registry must be a ToolRegistry")
        self.registry = registry

    @staticmethod
    def _base_score(rank):
        value = BASE_SCORE_FIRST - (rank - 1) * BASE_SCORE_STEP
        return max(BASE_SCORE_FLOOR, min(1.0, value))

    @staticmethod
    def _normalize_history(history):
        history = tuple(history)
        if len(history) > MAX_HISTORY_ENTRIES:
            raise ValueError(
                f"Candidate history exceeds limit {MAX_HISTORY_ENTRIES}"
            )
        if any(not isinstance(item, CandidateHistoryEntry) for item in history):
            raise TypeError(
                "Candidate history must contain CandidateHistoryEntry values"
            )
        return history

    @staticmethod
    def _history_features(fingerprint, history):
        matching = [item for item in history if item.fingerprint == fingerprint]
        matching_failures = sum(
            1
            for item in matching
            if item.verified and item.outcome == "failure"
        )
        repeated_failure = min(1.0, matching_failures * 0.50)

        latest_matching = matching[-1] if matching else None
        verified_continuation = (
            1.0
            if latest_matching is not None
            and latest_matching.verified
            and latest_matching.outcome == "progress"
            else 0.0
        )

        latest_failed = next(
            (
                item
                for item in reversed(history)
                if item.verified and item.outcome == "failure"
            ),
            None,
        )
        latest_failed_fingerprint = (
            latest_failed.fingerprint if latest_failed is not None else None
        )
        alternative_value = (
            1.0
            if latest_failed_fingerprint is not None
            and latest_failed_fingerprint != fingerprint
            else 0.0
        )
        return (
            matching_failures,
            repeated_failure,
            alternative_value,
            verified_continuation,
            latest_matching.outcome if latest_matching is not None else None,
            latest_failed_fingerprint,
        )

    def adapt(self, planner_turn, *, history=()):
        if not isinstance(planner_turn, PlannerTurn):
            raise TypeError("CandidateAdapter requires a PlannerTurn")
        if planner_turn.status != "proposals_available":
            raise ValueError(
                "CandidateAdapter requires proposals_available PlannerTurn"
            )

        history = self._normalize_history(history)
        candidates = []
        traces = []
        for proposal in planner_turn.proposals:
            descriptor = self.registry.get(
                proposal.tool,
                proposal.tool_version,
            )
            arguments = proposal.to_dict()["arguments"]
            descriptor.validate_input(arguments)
            fingerprint = action_fingerprint(
                proposal.tool,
                proposal.tool_version,
                arguments,
            )

            base_score = self._base_score(proposal.rank)
            effort_cost = EFFORT_COST[descriptor.effort_hint]
            information_gain = INFORMATION_GAIN[descriptor.effect_class]
            try:
                irreversible_risk = IRREVERSIBLE_RISK[
                    (descriptor.effect_class, descriptor.idempotency)
                ]
            except KeyError as error:
                raise ValueError(
                    "Tool effect/idempotency combination has no Candidate risk mapping"
                ) from error

            (
                matching_failures,
                repeated_failure,
                alternative_value,
                verified_continuation,
                latest_matching_outcome,
                latest_failed_fingerprint,
            ) = self._history_features(fingerprint, history)

            values = {
                "base_score": base_score,
                "effort_cost": effort_cost,
                "information_gain": information_gain,
                "irreversible_risk": irreversible_risk,
                "repeated_failure": repeated_failure,
                "alternative_value": alternative_value,
                "verified_continuation": verified_continuation,
            }
            if any(
                not math.isfinite(value) or not 0.0 <= value <= 1.0
                for value in values.values()
            ):
                raise ValueError("CandidateAdapter produced an invalid normalized feature")

            candidate = Candidate(
                candidate_id=proposal.public_id,
                **values,
            )
            trace = CandidateFeatureTrace(
                proposal_id=proposal.public_id,
                tool=proposal.tool,
                tool_version=proposal.tool_version,
                action_fingerprint=fingerprint,
                planner_rank=proposal.rank,
                matching_failures=matching_failures,
                latest_matching_outcome=latest_matching_outcome,
                latest_failed_fingerprint=latest_failed_fingerprint,
                **values,
            )
            candidates.append(candidate)
            traces.append(trace)

        return CandidateAdaptation(
            candidates=tuple(candidates),
            traces=tuple(traces),
        )


class ProposalChoiceCoordinator:
    """Apply system Candidate adaptation before the existing Stage 2 ChoiceEngine."""

    def __init__(self, *, registry, choice_engine, adapter=None):
        if not isinstance(registry, ToolRegistry):
            raise TypeError("ProposalChoiceCoordinator registry must be a ToolRegistry")
        if not isinstance(choice_engine, ChoiceEngine):
            raise TypeError(
                "ProposalChoiceCoordinator choice_engine must be a ChoiceEngine"
            )
        if adapter is None:
            adapter = CandidateAdapter(registry)
        if not isinstance(adapter, CandidateAdapter):
            raise TypeError(
                "ProposalChoiceCoordinator adapter must be a CandidateAdapter"
            )
        if adapter.registry is not registry:
            raise ValueError(
                "ProposalChoiceCoordinator adapter must use the same ToolRegistry"
            )
        self.registry = registry
        self.choice_engine = choice_engine
        self.adapter = adapter

    def choose(self, goal_id, planner_turn, *, history=()):
        adaptation = self.adapter.adapt(planner_turn, history=history)
        choice = self.choice_engine.choose(
            goal_id,
            list(adaptation.candidates),
        )
        selected_id = choice["selected_candidate_id"]
        selected = next(
            proposal
            for proposal in planner_turn.proposals
            if proposal.public_id == selected_id
        )
        return {
            "goal_id": goal_id,
            "planner_turn_id": planner_turn.public_id,
            "selected_proposal_id": selected.public_id,
            "selected_proposal": selected,
            "candidate_traces": tuple(
                trace.to_dict() for trace in adaptation.traces
            ),
            "choice": choice,
        }
