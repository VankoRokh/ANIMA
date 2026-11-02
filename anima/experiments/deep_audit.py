"""Comparative FAST/DEEP audit corpus and scoring helpers.

This module is experimental. It does not change production routing or model authority.
The same semantic case can be presented to FAST and DEEP so role/model effects can
be measured separately before Stage 7 relies on DEEP.
"""

from dataclasses import dataclass
from enum import Enum
import math
import statistics
import time
from uuid import uuid4

from anima.cognition.contracts import CognitiveView
from anima.cognition.proposals import CognitiveProposal, ProposalKind, RoutedCognitiveRequest
from anima.cognition.routing import CognitiveRole
from anima.ir import plain


AUDIT_VERSION = "deep-baseline-v0"
ALLOWED_LABELS = (
    "SUPPORT",
    "TEMPORAL_CHANGE",
    "CORRECTION",
    "CONTRADICTION",
    "UNRESOLVED",
)


class AuditDifficulty(str, Enum):
    SIMPLE = "simple"
    INTERMEDIATE = "intermediate"
    HARD = "hard"


@dataclass(frozen=True, slots=True)
class DeepAuditCase:
    case_id: str
    difficulty: AuditDifficulty
    category: str
    expected: str
    input_text: str
    evidence: tuple[dict, ...]
    notes: str = ""

    def __post_init__(self):
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("audit case_id must be non-empty")
        if not isinstance(self.difficulty, AuditDifficulty):
            raise TypeError("audit difficulty must be AuditDifficulty")
        if not isinstance(self.category, str) or not self.category.strip():
            raise ValueError("audit category must be non-empty")
        if self.expected not in ALLOWED_LABELS:
            raise ValueError("audit expected label is unsupported")
        if not isinstance(self.input_text, str) or not self.input_text.strip():
            raise ValueError("audit input_text must be non-empty")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError("audit evidence must be a non-empty tuple")
        if not all(isinstance(item, dict) for item in self.evidence):
            raise TypeError("audit evidence items must be dictionaries")

    def view_payload(self):
        return {
            "operation": "RESOLVE_CONFLICT",
            "output_contract": "text",
            "input": self.input_text,
            "audit_version": AUDIT_VERSION,
            "audit_case": self.case_id,
            "evidence": [plain(item) for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class AuditCaseResult:
    case_id: str
    difficulty: str
    category: str
    expected: str
    response: str | None
    normalized_response: str | None
    correct: bool
    format_valid: bool
    abstention_case: bool
    abstention_correct: bool | None
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    error: str | None

    def to_dict(self):
        return {
            "case_id": self.case_id,
            "difficulty": self.difficulty,
            "category": self.category,
            "expected": self.expected,
            "response": self.response,
            "normalized_response": self.normalized_response,
            "correct": self.correct,
            "format_valid": self.format_valid,
            "abstention_case": self.abstention_case,
            "abstention_correct": self.abstention_correct,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error": self.error,
        }


def _e(value, source, *, observed_at=None, valid_from=None, valid_until=None,
       confidence=None, authority=None, relation=None):
    item = {"value": value, "source": source}
    if observed_at is not None:
        item["observed_at"] = observed_at
    if valid_from is not None:
        item["valid_from"] = valid_from
    if valid_until is not None:
        item["valid_until"] = valid_until
    if confidence is not None:
        item["confidence"] = confidence
    if authority is not None:
        item["authority"] = authority
    if relation is not None:
        item["relation"] = relation
    return item


def _instruction(extra=""):
    base = (
        "Use only the supplied evidence. Return exactly one label and no other text: "
        "SUPPORT, TEMPORAL_CHANGE, CORRECTION, CONTRADICTION, or UNRESOLVED. "
        "SUPPORT means compatible evidence for the same claim. TEMPORAL_CHANGE means "
        "both values can be true at different times. CORRECTION means earlier information "
        "is explicitly shown to have been wrong for its claimed period. CONTRADICTION means "
        "strong evidence conflicts about the same entity, property, and time. UNRESOLVED means "
        "the evidence is insufficient to classify safely."
    )
    return base + (f" {extra}" if extra else "")


def default_audit_corpus():
    """Thirty fixed, ground-truthed cases: 10 simple, 10 intermediate, 10 hard."""
    s = AuditDifficulty.SIMPLE
    m = AuditDifficulty.INTERMEDIATE
    h = AuditDifficulty.HARD
    return (
        DeepAuditCase("S01", s, "duplicate_support", "SUPPORT", _instruction(),
            (_e("BCM2712", "inventory"), _e("BCM2712", "manual"))),
        DeepAuditCase("S02", s, "explicit_temporal_change", "TEMPORAL_CHANGE",
            _instruction("The second source explicitly says the schedule changed on 2026-11-02."),
            (_e("23:00", "old_schedule", valid_until="2026-11-02"),
             _e("00:00", "new_schedule", valid_from="2026-11-02"))),
        DeepAuditCase("S03", s, "explicit_correction", "CORRECTION",
            _instruction("The second source explicitly states the first statement was an error."),
            (_e("512GB", "user_old"), _e("1TB", "user_correction", relation="corrects:user_old"))),
        DeepAuditCase("S04", s, "same_time_conflict", "CONTRADICTION", _instruction(),
            (_e("open", "sensor_A", observed_at="2026-11-02T12:00:00Z", authority="direct"),
             _e("closed", "sensor_B", observed_at="2026-11-02T12:00:00Z", authority="direct"))),
        DeepAuditCase("S05", s, "insufficient_single_claim", "UNRESOLVED",
            _instruction("One unsupported claim is not enough to decide whether a conflict or correction exists."),
            (_e("room_B", "unverified_note"),)),
        DeepAuditCase("S06", s, "nonoverlap_state", "TEMPORAL_CHANGE", _instruction(),
            (_e("offline", "telemetry", valid_until="2026-11-02T09:00:00Z"),
             _e("online", "telemetry", valid_from="2026-11-02T09:05:00Z"))),
        DeepAuditCase("S07", s, "support_different_sources", "SUPPORT", _instruction(),
            (_e("tea", "user_statement", authority="direct"),
             _e("tea", "recent_preference_record", authority="direct"))),
        DeepAuditCase("S08", s, "explicit_never_true", "CORRECTION",
            _instruction("The newer direct statement says the old interpretation was never true."),
            (_e("prefers_coffee", "behavior_inference", authority="derived"),
             _e("does_not_prefer_coffee", "user_direct", authority="direct",
                relation="old_interpretation_was_wrong"))),
        DeepAuditCase("S09", s, "entity_ambiguity", "UNRESOLVED",
            _instruction("The evidence may refer to different physical devices; identity is not established."),
            (_e("512GB", "device_seen_A"), _e("1TB", "device_seen_B"))),
        DeepAuditCase("S10", s, "weak_new_observation", "UNRESOLVED",
            _instruction("The new observation is explicitly uncertain and does not establish a conflict."),
            (_e("room_A", "inventory", authority="direct"),
             _e("possibly_room_B", "camera_guess", confidence=0.4, authority="derived"))),

        DeepAuditCase("M01", m, "direct_over_derived_same_value", "SUPPORT", _instruction(),
            (_e("76C", "hardware_sensor", authority="direct"),
             _e("76C", "thermal_estimator", authority="derived"))),
        DeepAuditCase("M02", m, "direct_vs_derived_disagreement", "CONTRADICTION",
            _instruction("Both refer to the same instant; neither item says the derived estimate is invalid."),
            (_e("76C", "hardware_sensor", observed_at="2026-11-02T12:00:00Z", authority="direct"),
             _e("60C", "thermal_estimator", observed_at="2026-11-02T12:00:00Z", authority="derived"))),
        DeepAuditCase("M03", m, "newer_not_correction", "UNRESOLVED",
            _instruction("Newer evidence alone does not prove the older claim was wrong or that the world changed."),
            (_e("A", "source_old", observed_at="2026-11-01T12:00:00Z"),
             _e("B", "source_new", observed_at="2026-11-02T12:00:00Z"))),
        DeepAuditCase("M04", m, "preference_change", "TEMPORAL_CHANGE",
            _instruction("The direct statement says the preference changed recently."),
            (_e("coffee", "user_2025", valid_until="2026-10-01"),
             _e("tea", "user_2026", valid_from="2026-10-01", relation="preference_changed"))),
        DeepAuditCase("M05", m, "retroactive_correction", "CORRECTION",
            _instruction("The newer source explicitly corrects the historical period, not merely the current state."),
            (_e("worked_until_22", "old_note", valid_from="2026-01-01", valid_until="2026-06-01"),
             _e("worked_until_23", "verified_archive", valid_from="2026-01-01",
                valid_until="2026-06-01", relation="corrects:old_note"))),
        DeepAuditCase("M06", m, "duplicate_plus_conflict", "CONTRADICTION", _instruction(),
            (_e("A", "source_1", authority="direct"), _e("A", "source_2", authority="direct"),
             _e("B", "source_3", authority="direct"))),
        DeepAuditCase("M07", m, "confidence_trap", "CONTRADICTION",
            _instruction("A numeric confidence is interpretation metadata, not permission to discard conflicting direct evidence."),
            (_e("40C", "user_guess", confidence=0.99, authority="derived"),
             _e("76C", "hardware_sensor", confidence=0.75, authority="direct"))),
        DeepAuditCase("M08", m, "temporal_gap_change", "TEMPORAL_CHANGE",
            _instruction("There is a gap between validity windows; the exact transition time is unknown, but the non-overlapping states remain temporally compatible."),
            (_e("closed", "state_A", valid_until="2026-11-02T10:00:00Z"),
             _e("open", "state_B", valid_from="2026-11-02T12:00:00Z"))),
        DeepAuditCase("M09", m, "correction_plus_support", "CORRECTION",
            _instruction("Two sources support the corrected value and one explicitly marks the old value as erroneous."),
            (_e("512GB", "old_record"),
             _e("1TB", "inventory", authority="direct"),
             _e("1TB", "user_correction", authority="direct", relation="corrects:old_record"))),
        DeepAuditCase("M10", m, "noise_irrelevant", "SUPPORT",
            _instruction("Ignore evidence about unrelated properties."),
            (_e("BCM2712", "inventory", relation="cpu_model"),
             _e("BCM2712", "manual", relation="cpu_model"),
             _e("8GB", "inventory", relation="ram"),
             _e("Batumi", "session", relation="location"))),

        DeepAuditCase("H01", h, "multi_source_conflict", "CONTRADICTION",
            _instruction("Multiple strong direct sources remain split for the same instant; do not vote by count."),
            (_e("open", "sensor_A", authority="direct"),
             _e("open", "sensor_B", authority="direct"),
             _e("closed", "sensor_C", authority="direct"),
             _e("closed", "sensor_D", authority="direct"))),
        DeepAuditCase("H02", h, "majority_is_not_truth", "CONTRADICTION",
            _instruction("Three repeated derived reports do not cancel one conflicting direct measurement; the claims still conflict."),
            (_e("60C", "derived_1", authority="derived"),
             _e("60C", "derived_2", authority="derived"),
             _e("60C", "derived_3", authority="derived"),
             _e("77C", "hardware_sensor", authority="direct"))),
        DeepAuditCase("H03", h, "temporal_sequence_many_states", "TEMPORAL_CHANGE",
            _instruction("All records form a non-overlapping sequence of states."),
            (_e("offline", "telemetry", valid_until="10:00"),
             _e("booting", "telemetry", valid_from="10:00", valid_until="10:02"),
             _e("online", "telemetry", valid_from="10:02"))),
        DeepAuditCase("H04", h, "overlapping_temporal_conflict", "CONTRADICTION",
            _instruction("The validity intervals overlap, so the incompatible claims apply to the same period."),
            (_e("door_open", "sensor_A", valid_from="10:00", valid_until="10:10", authority="direct"),
             _e("door_closed", "sensor_B", valid_from="10:05", valid_until="10:15", authority="direct"))),
        DeepAuditCase("H05", h, "partial_entity_resolution", "UNRESOLVED",
            _instruction("Model family matches but serial identity is missing; do not assume both records are the same device."),
            (_e("512GB", "pi5_record_A", relation="model:Pi5"),
             _e("1TB", "pi5_record_B", relation="model:Pi5"))),
        DeepAuditCase("H06", h, "mixed_correction_and_change", "UNRESOLVED",
            _instruction("One source claims a historical correction while another claims a later change; evidence does not establish which history is true."),
            (_e("23:00", "old_schedule", valid_from="2026-01-01"),
             _e("00:00", "manager_A", relation="old_schedule_was_wrong"),
             _e("00:00", "manager_B", valid_from="2026-11-01", relation="schedule_changed"))),
        DeepAuditCase("H07", h, "adversarial_source_name", "CONTRADICTION",
            _instruction("Source names are labels, not authority. Both claims are otherwise direct and simultaneous."),
            (_e("40C", "OFFICIAL_VERIFIED_TRUTH", authority="direct", observed_at="12:00"),
             _e("76C", "sensor_2", authority="direct", observed_at="12:00"))),
        DeepAuditCase("H08", h, "high_confidence_hypothesis", "UNRESOLVED",
            _instruction("A high-confidence hypothesis is still not direct evidence of the claimed cause."),
            (_e("fan_failure", "deep_hypothesis", confidence=0.98, authority="hypothetical"),
             _e("high_temperature", "sensor", authority="direct"))),
        DeepAuditCase("H09", h, "current_vs_historical_query", "TEMPORAL_CHANGE",
            _instruction("The old and new values have explicit non-overlapping validity periods."),
            (_e("coffee", "preference_archive", valid_until="2026-05-01", authority="direct"),
             _e("tea", "current_statement", valid_from="2026-05-01", authority="direct"),
             _e("tea", "recent_behavior", valid_from="2026-06-01", authority="derived"))),
        DeepAuditCase("H10", h, "conflict_with_noise_and_missing_time", "UNRESOLVED",
            _instruction("Conflicting values lack enough temporal identity to know whether they are simultaneous or sequential; unrelated evidence does not resolve that."),
            (_e("room_A", "inventory_old"),
             _e("room_B", "camera_new"),
             _e("65C", "sensor", relation="temperature"),
             _e("online", "network", relation="availability"))),
    )


def normalize_response(text):
    if not isinstance(text, str):
        return None
    normalized = text.strip().upper()
    if normalized.endswith("."):
        normalized = normalized[:-1].rstrip()
    return normalized or None


def make_request(case, role):
    if not isinstance(case, DeepAuditCase):
        raise TypeError("audit requires DeepAuditCase")
    if not isinstance(role, CognitiveRole):
        raise TypeError("audit role must be CognitiveRole")
    return RoutedCognitiveRequest(
        persistent_task_id=f"task_{uuid4()}",
        canonical_task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        role=role,
        view=CognitiveView(role.value, case.view_payload()),
    )


def _history(backend):
    history = getattr(backend, "call_history", None)
    if history is not None:
        return history
    wrapped = getattr(backend, "backend", None)
    return getattr(wrapped, "call_history", ())


def run_case(case, *, role, backend):
    """Run one case against an already configured Stage 6 cognitive backend."""
    request = make_request(case, role)
    before = len(_history(backend))
    started = time.perf_counter()
    response = None
    error = None
    input_tokens = None
    output_tokens = None
    try:
        proposal = backend.complete(request)
        if not isinstance(proposal, CognitiveProposal):
            raise TypeError("audit backend must return CognitiveProposal")
        if proposal.kind != ProposalKind.RESPOND:
            raise ValueError("audit backend must return RESPOND")
        payload = plain(proposal.payload)
        response = payload.get("text") if isinstance(payload, dict) else None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - started) * 1000.0

    history = _history(backend)
    if len(history) > before:
        call = history[-1]
        input_tokens = getattr(call, "input_tokens", None)
        output_tokens = getattr(call, "output_tokens", None)
        measured_latency = getattr(call, "latency_ms", None)
        if isinstance(measured_latency, (int, float)) and math.isfinite(float(measured_latency)):
            latency_ms = float(measured_latency)

    normalized = normalize_response(response)
    format_valid = normalized in ALLOWED_LABELS
    correct = error is None and normalized == case.expected
    abstention = case.expected == "UNRESOLVED"
    return AuditCaseResult(
        case_id=case.case_id,
        difficulty=case.difficulty.value,
        category=case.category,
        expected=case.expected,
        response=response,
        normalized_response=normalized,
        correct=bool(correct),
        format_valid=bool(format_valid),
        abstention_case=abstention,
        abstention_correct=(bool(correct) if abstention else None),
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error=error,
    )


def summarize_results(results):
    results = tuple(results)
    if not results:
        raise ValueError("audit summary requires results")
    latencies = [item.latency_ms for item in results if item.error is None]
    unresolved = [item for item in results if item.abstention_case]
    by_difficulty = {}
    for difficulty in AuditDifficulty:
        selected = [item for item in results if item.difficulty == difficulty.value]
        by_difficulty[difficulty.value] = {
            "passes": sum(item.correct for item in selected),
            "total": len(selected),
        }
    return {
        "audit_version": AUDIT_VERSION,
        "passes": sum(item.correct for item in results),
        "total": len(results),
        "format_valid": sum(item.format_valid for item in results),
        "errors": sum(item.error is not None for item in results),
        "abstention_passes": sum(item.correct for item in unresolved),
        "abstention_total": len(unresolved),
        "mean_latency_ms": statistics.mean(latencies) if latencies else None,
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "input_tokens": sum(item.input_tokens or 0 for item in results),
        "output_tokens": sum(item.output_tokens or 0 for item in results),
        "missing_token_rows": sum(
            item.input_tokens is None or item.output_tokens is None for item in results
        ),
        "by_difficulty": by_difficulty,
    }


__all__ = [
    "ALLOWED_LABELS",
    "AUDIT_VERSION",
    "AuditCaseResult",
    "AuditDifficulty",
    "DeepAuditCase",
    "default_audit_corpus",
    "make_request",
    "normalize_response",
    "run_case",
    "summarize_results",
]
