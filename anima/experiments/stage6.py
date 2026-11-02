"""Stage 6 mini experiments kept outside production cognitive authority.

These helpers answer bounded research questions without changing production
CognitiveRouter, ProposalValidator, Memory ownership, or Choice rules. A positive
experiment result is evidence for a later decision, not an automatic production
feature toggle.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from anima.cognition.proposals import CognitiveProposal, ProposalKind
from anima.cognition.routing import CognitiveDestination, CognitiveRouter
from anima.internal_state.choice_engine import Candidate
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore
from anima.ir import CanonicalTask, Evidence, plain
from anima.memory.context_builder import ContextBuilder
from anima.resolution import resolve


FAST_BENCHMARK_V2_LATENCY_MS = 2054.0
DEEP_BENCHMARK_V2_LATENCY_MS = 12753.0
BENCHMARK_V2_CASES = 8
BENCHMARK_V2_FAST_PASSES = 8
BENCHMARK_V2_DEEP_PASSES = 8

REQUEST_CONTEXT_MAX_ADDITIONAL_RETRIEVALS = 1
REQUEST_CONTEXT_MAX_ITEMS = 16
REQUEST_CONTEXT_MAX_CHARS = 4000
REQUEST_CONTEXT_MAX_QUERY_CHARS = 256
REQUEST_CONTEXT_MAX_NEED_CHARS = 256


class ExperimentVerdict(str, Enum):
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    INCONCLUSIVE = "Inconclusive"


def _require_text(value, label, *, max_chars=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    value = value.strip()
    if max_chars is not None and len(value) > max_chars:
        raise ValueError(f"{label} exceeds {max_chars} characters")
    return value


def _require_positive_int(value, label, *, maximum=None):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} exceeds experiment cap {maximum}")
    return value


def _score(value, label):
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{label} must be a finite number")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be within 0.0..1.0")
    return value


def _context_source_ids(bundle):
    source_ids = []
    for bucket in ("knowledge", "memories", "events"):
        for item in bundle.get(bucket, ()):  # ContextBuilder returns dict entries.
            if not isinstance(item, Mapping):
                continue
            record = item.get("record")
            if isinstance(record, Mapping):
                source_id = record.get("id")
                if isinstance(source_id, str) and source_id:
                    source_ids.append(source_id)
    return tuple(source_ids)


@dataclass(frozen=True, slots=True)
class ContextExperimentTurn:
    round_index: int
    initial_query: str
    consumer: str
    context: Mapping


@runtime_checkable
class ExperimentalContextBackend(Protocol):
    def complete(self, turn: ContextExperimentTurn) -> CognitiveProposal:
        ...


@dataclass(frozen=True, slots=True)
class RequestMoreContextResult:
    mechanism_verdict: ExperimentVerdict
    quality_verdict: ExperimentVerdict
    initial_coverage: float
    final_coverage: float
    coverage_delta: float
    backend_calls: int
    additional_retrievals: int
    cycle_blocked: bool
    final_proposal_kind: str | None
    final_response: str | None
    initial_source_ids: tuple[str, ...]
    final_source_ids: tuple[str, ...]
    requested_query: str | None
    requested_need: str | None
    requested_max_items: int | None
    requested_max_chars: int | None

    def to_dict(self):
        return {
            "mechanism_verdict": self.mechanism_verdict.value,
            "quality_verdict": self.quality_verdict.value,
            "initial_coverage": self.initial_coverage,
            "final_coverage": self.final_coverage,
            "coverage_delta": self.coverage_delta,
            "backend_calls": self.backend_calls,
            "additional_retrievals": self.additional_retrievals,
            "cycle_blocked": self.cycle_blocked,
            "final_proposal_kind": self.final_proposal_kind,
            "final_response": self.final_response,
            "initial_source_ids": list(self.initial_source_ids),
            "final_source_ids": list(self.final_source_ids),
            "request": {
                "query": self.requested_query,
                "need": self.requested_need,
                "max_items": self.requested_max_items,
                "max_chars": self.requested_max_chars,
            },
        }


def _validate_request_context_payload(proposal):
    if not isinstance(proposal, CognitiveProposal):
        raise TypeError("request_more_context experiment requires CognitiveProposal")
    if proposal.kind != ProposalKind.REQUEST_CONTEXT:
        raise ValueError("proposal is not REQUEST_CONTEXT")
    payload = plain(proposal.payload)
    allowed = {"query", "need", "max_items", "max_chars"}
    required = {"query", "need"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - allowed:
        raise ValueError(
            "REQUEST_CONTEXT payload must contain query/need and optional max_items/max_chars"
        )
    query = _require_text(
        payload["query"],
        "REQUEST_CONTEXT query",
        max_chars=REQUEST_CONTEXT_MAX_QUERY_CHARS,
    )
    need = _require_text(
        payload["need"],
        "REQUEST_CONTEXT need",
        max_chars=REQUEST_CONTEXT_MAX_NEED_CHARS,
    )
    max_items = _require_positive_int(
        payload.get("max_items", REQUEST_CONTEXT_MAX_ITEMS),
        "REQUEST_CONTEXT max_items",
        maximum=REQUEST_CONTEXT_MAX_ITEMS,
    )
    max_chars = _require_positive_int(
        payload.get("max_chars", REQUEST_CONTEXT_MAX_CHARS),
        "REQUEST_CONTEXT max_chars",
        maximum=REQUEST_CONTEXT_MAX_CHARS,
    )
    return {
        "query": query,
        "need": need,
        "max_items": max_items,
        "max_chars": max_chars,
    }


def run_request_more_context_experiment(
    *,
    context_builder,
    backend,
    initial_query,
    coverage_score,
    consumer="FAST",
    initial_max_items=1,
    initial_max_chars=256,
):
    """Run one bounded system-mediated context request.

    This deliberately allows at most one extra retrieval. A second REQUEST_CONTEXT
    is observed and blocked rather than recursively followed.
    """

    if not isinstance(context_builder, ContextBuilder):
        raise TypeError("context_builder must be ContextBuilder")
    if not isinstance(backend, ExperimentalContextBackend):
        raise TypeError("backend must implement ExperimentalContextBackend")
    if not callable(coverage_score):
        raise TypeError("coverage_score must be callable")
    initial_query = _require_text(initial_query, "initial_query")
    consumer = _require_text(consumer, "consumer").upper()
    if consumer not in {"FAST", "DEEP"}:
        raise ValueError("consumer must be FAST or DEEP")
    initial_max_items = _require_positive_int(
        initial_max_items,
        "initial_max_items",
        maximum=REQUEST_CONTEXT_MAX_ITEMS,
    )
    initial_max_chars = _require_positive_int(
        initial_max_chars,
        "initial_max_chars",
        maximum=REQUEST_CONTEXT_MAX_CHARS,
    )

    initial = context_builder.build(
        initial_query,
        consumer=consumer,
        max_items=initial_max_items,
        max_chars=initial_max_chars,
    )
    initial_coverage = _score(coverage_score(initial), "initial coverage")
    first = backend.complete(
        ContextExperimentTurn(
            round_index=0,
            initial_query=initial_query,
            consumer=consumer,
            context=initial,
        )
    )
    if not isinstance(first, CognitiveProposal):
        raise TypeError("experimental context backend must return CognitiveProposal")

    if first.kind != ProposalKind.REQUEST_CONTEXT:
        response = None
        if first.kind == ProposalKind.RESPOND:
            payload = plain(first.payload)
            response = payload.get("text") if isinstance(payload, dict) else None
        return RequestMoreContextResult(
            mechanism_verdict=ExperimentVerdict.INCONCLUSIVE,
            quality_verdict=ExperimentVerdict.INCONCLUSIVE,
            initial_coverage=initial_coverage,
            final_coverage=initial_coverage,
            coverage_delta=0.0,
            backend_calls=1,
            additional_retrievals=0,
            cycle_blocked=False,
            final_proposal_kind=first.kind.value,
            final_response=response,
            initial_source_ids=_context_source_ids(initial),
            final_source_ids=_context_source_ids(initial),
            requested_query=None,
            requested_need=None,
            requested_max_items=None,
            requested_max_chars=None,
        )

    request = _validate_request_context_payload(first)
    expanded = context_builder.build(
        request["query"],
        consumer=consumer,
        max_items=request["max_items"],
        max_chars=request["max_chars"],
    )
    final_coverage = _score(coverage_score(expanded), "final coverage")
    second = backend.complete(
        ContextExperimentTurn(
            round_index=1,
            initial_query=initial_query,
            consumer=consumer,
            context=expanded,
        )
    )
    if not isinstance(second, CognitiveProposal):
        raise TypeError("experimental context backend must return CognitiveProposal")

    cycle_blocked = second.kind == ProposalKind.REQUEST_CONTEXT
    response = None
    if second.kind == ProposalKind.RESPOND:
        payload = plain(second.payload)
        if isinstance(payload, dict):
            response = payload.get("text")

    mechanism_accepted = (
        not cycle_blocked
        and second.kind == ProposalKind.RESPOND
        and final_coverage > initial_coverage
    )
    return RequestMoreContextResult(
        mechanism_verdict=(
            ExperimentVerdict.ACCEPTED
            if mechanism_accepted
            else ExperimentVerdict.INCONCLUSIVE
        ),
        # Coverage is a retrieval-ground-truth proxy, not measured LLM answer quality.
        quality_verdict=ExperimentVerdict.INCONCLUSIVE,
        initial_coverage=initial_coverage,
        final_coverage=final_coverage,
        coverage_delta=final_coverage - initial_coverage,
        backend_calls=2,
        additional_retrievals=REQUEST_CONTEXT_MAX_ADDITIONAL_RETRIEVALS,
        cycle_blocked=cycle_blocked,
        final_proposal_kind=second.kind.value,
        final_response=response,
        initial_source_ids=_context_source_ids(initial),
        final_source_ids=_context_source_ids(expanded),
        requested_query=request["query"],
        requested_need=request["need"],
        requested_max_items=request["max_items"],
        requested_max_chars=request["max_chars"],
    )


@dataclass(frozen=True, slots=True)
class RoutingCase:
    name: str
    task: CanonicalTask
    expected_baseline: CognitiveDestination


@dataclass(frozen=True, slots=True)
class RoutingExperimentResult:
    baseline_verdict: ExperimentVerdict
    adaptive_verdict: ExperimentVerdict
    deep_value_verdict: ExperimentVerdict
    cases: tuple[dict, ...]
    baseline_deep_calls: int
    adaptive_deep_calls: int
    baseline_estimated_mean_ms: float
    adaptive_estimated_mean_ms: float
    all_fast_estimated_mean_ms: float
    all_deep_estimated_mean_ms: float
    fast_benchmark_passes: int
    deep_benchmark_passes: int
    benchmark_cases: int
    fast_latency_ms: float
    deep_latency_ms: float
    deep_latency_ratio: float

    def to_dict(self):
        return {
            "baseline_verdict": self.baseline_verdict.value,
            "adaptive_verdict": self.adaptive_verdict.value,
            "deep_value_verdict": self.deep_value_verdict.value,
            "cases": [dict(item) for item in self.cases],
            "baseline_deep_calls": self.baseline_deep_calls,
            "adaptive_deep_calls": self.adaptive_deep_calls,
            "estimated_mean_latency_ms": {
                "baseline": self.baseline_estimated_mean_ms,
                "adaptive": self.adaptive_estimated_mean_ms,
                "all_fast": self.all_fast_estimated_mean_ms,
                "all_deep": self.all_deep_estimated_mean_ms,
            },
            "benchmark_v2": {
                "cases": self.benchmark_cases,
                "fast_passes": self.fast_benchmark_passes,
                "deep_passes": self.deep_benchmark_passes,
                "fast_latency_ms": self.fast_latency_ms,
                "deep_latency_ms": self.deep_latency_ms,
                "deep_latency_ratio": self.deep_latency_ratio,
            },
        }


def default_routing_cases():
    subject = "device"
    predicate = "mode"
    conflict = (
        Evidence(
            evidence_id=f"evd_{uuid4()}",
            value="A",
            subject=subject,
            predicate=predicate,
            provenance=(f"mem_{uuid4()}",),
        ),
        Evidence(
            evidence_id=f"evd_{uuid4()}",
            value="B",
            subject=subject,
            predicate=predicate,
            provenance=(f"mem_{uuid4()}",),
        ),
    )
    return (
        RoutingCase(
            "open_fast",
            CanonicalTask(
                task_id=f"ct_{uuid4()}",
                source_id=f"src_{uuid4()}",
                operation="OPEN_TEXT",
                raw_input="Summarize a bounded note.",
            ),
            CognitiveDestination.FAST,
        ),
        RoutingCase(
            "high_uncertainty_open",
            CanonicalTask(
                task_id=f"ct_{uuid4()}",
                source_id=f"src_{uuid4()}",
                operation="OPEN_TEXT",
                raw_input="Answer a bounded question.",
                state={"uncertainty": 0.9},
            ),
            CognitiveDestination.FAST,
        ),
        RoutingCase(
            "conflicting_fact",
            CanonicalTask(
                task_id=f"ct_{uuid4()}",
                source_id=f"src_{uuid4()}",
                operation="QUERY_FACT",
                subject=subject,
                predicate=predicate,
                evidence=conflict,
            ),
            CognitiveDestination.DEEP,
        ),
        RoutingCase(
            "explicit_conflict_reasoning",
            CanonicalTask(
                task_id=f"ct_{uuid4()}",
                source_id=f"src_{uuid4()}",
                operation="RESOLVE_CONFLICT",
                subject=subject,
                predicate=predicate,
                evidence=conflict,
            ),
            CognitiveDestination.DEEP,
        ),
    )


def _estimated_mean_latency(destinations, *, fast_latency_ms, deep_latency_ms):
    if not destinations:
        return 0.0
    total = 0.0
    for destination in destinations:
        if destination == CognitiveDestination.DEEP:
            total += deep_latency_ms
        elif destination == CognitiveDestination.FAST:
            total += fast_latency_ms
        else:
            raise ValueError("routing experiment latency supports FAST/DEEP only")
    return total / len(destinations)


def run_routing_policy_experiment(
    cases=None,
    *,
    fast_latency_ms=FAST_BENCHMARK_V2_LATENCY_MS,
    deep_latency_ms=DEEP_BENCHMARK_V2_LATENCY_MS,
    fast_benchmark_passes=BENCHMARK_V2_FAST_PASSES,
    deep_benchmark_passes=BENCHMARK_V2_DEEP_PASSES,
    benchmark_cases=BENCHMARK_V2_CASES,
):
    cases = tuple(default_routing_cases() if cases is None else cases)
    if not cases or not all(isinstance(case, RoutingCase) for case in cases):
        raise ValueError("routing experiment requires RoutingCase values")
    for value, label in (
        (fast_latency_ms, "fast_latency_ms"),
        (deep_latency_ms, "deep_latency_ms"),
    ):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or value <= 0
        ):
            raise ValueError(f"{label} must be a positive finite number")
    for value, label in (
        (fast_benchmark_passes, "fast_benchmark_passes"),
        (deep_benchmark_passes, "deep_benchmark_passes"),
        (benchmark_cases, "benchmark_cases"),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{label} must be a non-negative integer")
    if fast_benchmark_passes > benchmark_cases or deep_benchmark_passes > benchmark_cases:
        raise ValueError("benchmark passes cannot exceed benchmark_cases")

    router = CognitiveRouter()
    rows = []
    baseline_destinations = []
    adaptive_destinations = []
    for case in cases:
        resolution = resolve(case.task)
        decision = router.route(case.task, resolution)
        if decision.destination not in {CognitiveDestination.FAST, CognitiveDestination.DEEP}:
            raise ValueError("routing experiment cases must resolve to FAST or DEEP")
        uncertainty = case.task.state.get("uncertainty", 0.0)
        adaptive = (
            CognitiveDestination.DEEP
            if decision.destination == CognitiveDestination.DEEP
            or (
                isinstance(uncertainty, (int, float))
                and not isinstance(uncertainty, bool)
                and float(uncertainty) >= 0.75
            )
            else CognitiveDestination.FAST
        )
        baseline_destinations.append(decision.destination)
        adaptive_destinations.append(adaptive)
        rows.append(
            {
                "name": case.name,
                "resolution_reason": resolution.reason,
                "expected_baseline": case.expected_baseline.value,
                "baseline": decision.destination.value,
                "baseline_reason": decision.reason,
                "adaptive": adaptive.value,
                "uncertainty": float(uncertainty),
            }
        )

    baseline_matches = all(
        actual == case.expected_baseline
        for actual, case in zip(baseline_destinations, cases)
    )
    baseline_deep = sum(item == CognitiveDestination.DEEP for item in baseline_destinations)
    adaptive_deep = sum(item == CognitiveDestination.DEEP for item in adaptive_destinations)
    quality_parity = fast_benchmark_passes == deep_benchmark_passes
    adaptive_adds_cost = adaptive_deep > baseline_deep

    baseline_verdict = (
        ExperimentVerdict.ACCEPTED if baseline_matches else ExperimentVerdict.REJECTED
    )
    adaptive_verdict = (
        ExperimentVerdict.REJECTED
        if quality_parity and adaptive_adds_cost
        else ExperimentVerdict.INCONCLUSIVE
    )
    deep_value_verdict = (
        ExperimentVerdict.INCONCLUSIVE
        if quality_parity
        else ExperimentVerdict.ACCEPTED
        if deep_benchmark_passes > fast_benchmark_passes
        else ExperimentVerdict.REJECTED
    )

    all_fast = (CognitiveDestination.FAST,) * len(cases)
    all_deep = (CognitiveDestination.DEEP,) * len(cases)
    return RoutingExperimentResult(
        baseline_verdict=baseline_verdict,
        adaptive_verdict=adaptive_verdict,
        deep_value_verdict=deep_value_verdict,
        cases=tuple(rows),
        baseline_deep_calls=baseline_deep,
        adaptive_deep_calls=adaptive_deep,
        baseline_estimated_mean_ms=_estimated_mean_latency(
            baseline_destinations,
            fast_latency_ms=float(fast_latency_ms),
            deep_latency_ms=float(deep_latency_ms),
        ),
        adaptive_estimated_mean_ms=_estimated_mean_latency(
            adaptive_destinations,
            fast_latency_ms=float(fast_latency_ms),
            deep_latency_ms=float(deep_latency_ms),
        ),
        all_fast_estimated_mean_ms=_estimated_mean_latency(
            all_fast,
            fast_latency_ms=float(fast_latency_ms),
            deep_latency_ms=float(deep_latency_ms),
        ),
        all_deep_estimated_mean_ms=_estimated_mean_latency(
            all_deep,
            fast_latency_ms=float(fast_latency_ms),
            deep_latency_ms=float(deep_latency_ms),
        ),
        fast_benchmark_passes=fast_benchmark_passes,
        deep_benchmark_passes=deep_benchmark_passes,
        benchmark_cases=benchmark_cases,
        fast_latency_ms=float(fast_latency_ms),
        deep_latency_ms=float(deep_latency_ms),
        deep_latency_ratio=float(deep_latency_ms) / float(fast_latency_ms),
    )


@dataclass(frozen=True, slots=True)
class InternalStateChoiceExperimentResult:
    verdict: ExperimentVerdict
    baseline_selected: str
    elevated_uncertainty_selected: str
    repeated_selected: str
    uncertainty_before: float
    uncertainty_after: float
    selection_changed: bool
    deterministic_repeat: bool
    modifier_bounds_ok: bool
    baseline_evaluations: tuple[dict, ...]
    elevated_evaluations: tuple[dict, ...]

    def to_dict(self):
        return {
            "verdict": self.verdict.value,
            "baseline_selected": self.baseline_selected,
            "elevated_uncertainty_selected": self.elevated_uncertainty_selected,
            "repeated_selected": self.repeated_selected,
            "uncertainty_before": self.uncertainty_before,
            "uncertainty_after": self.uncertainty_after,
            "selection_changed": self.selection_changed,
            "deterministic_repeat": self.deterministic_repeat,
            "modifier_bounds_ok": self.modifier_bounds_ok,
            "baseline_evaluations": [dict(item) for item in self.baseline_evaluations],
            "elevated_evaluations": [dict(item) for item in self.elevated_evaluations],
        }


def _detached_evaluations(choice):
    rows = []
    for item in choice["evaluations"]:
        record = dict(item)
        record["modifiers"] = [dict(modifier) for modifier in record["modifiers"]]
        rows.append(record)
    return tuple(rows)


def run_internal_state_choice_experiment(database_file):
    database_file = Path(database_file)
    store = InternalStateStore(database_file)
    runtime = InternalStateRuntime(store)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    goal = runtime.goals.create_goal(
        source="stage6-experiment",
        priority=1.0,
        description="Compare bounded Internal State influence on one candidate set",
        success_criterion="Selection change is traceable to configured modifiers",
        reason="Stage 6.7 Internal State experiment",
        timestamp=timestamp,
    )
    candidates = (
        Candidate(
            "CONTINUE",
            0.62,
            information_gain=0.0,
            irreversible_risk=1.0,
        ),
        Candidate(
            "INSPECT",
            0.58,
            information_gain=1.0,
            irreversible_risk=0.0,
        ),
    )

    before = float(store.get_state("uncertainty")["value"])
    baseline = runtime.choice_engine.choose(goal["id"], candidates)
    delta = 1.0 - before
    if delta > 0:
        store.apply_state_transition(
            state_name="uncertainty",
            delta=delta,
            cause_type="experiment",
            rule_id="EXP-009",
            reason="raise uncertainty to configured maximum for paired comparison",
            source_id="stage6-exp-internal-state",
            goal_id=goal["id"],
            timestamp=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        )
    after = float(store.get_state("uncertainty")["value"])
    elevated = runtime.choice_engine.choose(goal["id"], candidates)
    repeated = runtime.choice_engine.choose(goal["id"], candidates)

    elevated_rows = _detached_evaluations(elevated)
    bounds_ok = all(
        abs(float(modifier["contribution"])) <= float(modifier["bound"]) + 1e-12
        for row in elevated_rows
        for modifier in row["modifiers"]
    )
    changed = baseline["selected_candidate_id"] != elevated["selected_candidate_id"]
    repeat_ok = elevated["selected_candidate_id"] == repeated["selected_candidate_id"]
    expected = (
        baseline["selected_candidate_id"] == "CONTINUE"
        and elevated["selected_candidate_id"] == "INSPECT"
    )
    verdict = (
        ExperimentVerdict.ACCEPTED
        if changed and repeat_ok and bounds_ok and expected
        else ExperimentVerdict.REJECTED
    )
    return InternalStateChoiceExperimentResult(
        verdict=verdict,
        baseline_selected=baseline["selected_candidate_id"],
        elevated_uncertainty_selected=elevated["selected_candidate_id"],
        repeated_selected=repeated["selected_candidate_id"],
        uncertainty_before=before,
        uncertainty_after=after,
        selection_changed=changed,
        deterministic_repeat=repeat_ok,
        modifier_bounds_ok=bounds_ok,
        baseline_evaluations=_detached_evaluations(baseline),
        elevated_evaluations=elevated_rows,
    )


__all__ = [
    "BENCHMARK_V2_CASES",
    "BENCHMARK_V2_DEEP_PASSES",
    "BENCHMARK_V2_FAST_PASSES",
    "ContextExperimentTurn",
    "DEEP_BENCHMARK_V2_LATENCY_MS",
    "ExperimentVerdict",
    "ExperimentalContextBackend",
    "FAST_BENCHMARK_V2_LATENCY_MS",
    "InternalStateChoiceExperimentResult",
    "REQUEST_CONTEXT_MAX_ADDITIONAL_RETRIEVALS",
    "REQUEST_CONTEXT_MAX_CHARS",
    "REQUEST_CONTEXT_MAX_ITEMS",
    "RequestMoreContextResult",
    "RoutingCase",
    "RoutingExperimentResult",
    "default_routing_cases",
    "run_internal_state_choice_experiment",
    "run_request_more_context_experiment",
    "run_routing_policy_experiment",
]
