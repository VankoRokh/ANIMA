"""Dual-axis comparative FAST/DEEP audit v0.2.

Earlier audit revisions forced evidence relation and decision state into one label.
That made CONTRADICTION and UNRESOLVED compete even though a contradiction can be
correctly detected while the semantic question remains unresolved. v0.2 separates:

- relation: SUPPORT / TEMPORAL_CHANGE / CORRECTION / CONTRADICTION / INSUFFICIENT
- resolution: RESOLVED / UNRESOLVED

The corpus reuses v0.1 scoped evidence and preserves the original 30-case ground
truth while translating it into the two orthogonal axes. Production routing and
model authority are unchanged.
"""

from dataclasses import dataclass
import re
from uuid import uuid4

from anima.cognition.contracts import CognitiveView
from anima.cognition.proposals import RoutedCognitiveRequest
from anima.cognition.routing import CognitiveRole
from anima.experiments.deep_audit import AuditDifficulty
from anima.experiments.deep_audit_v01 import default_audit_corpus as _v01_corpus
from anima.ir import plain


AUDIT_VERSION = "deep-baseline-v0.2"
RELATION_LABELS = (
    "SUPPORT",
    "TEMPORAL_CHANGE",
    "CORRECTION",
    "CONTRADICTION",
    "INSUFFICIENT",
)
RESOLUTION_LABELS = ("RESOLVED", "UNRESOLVED")
CANDIDATES = (
    "SUPPORT|RESOLVED",
    "TEMPORAL_CHANGE|RESOLVED",
    "CORRECTION|RESOLVED",
    "CONTRADICTION|UNRESOLVED",
    "INSUFFICIENT|UNRESOLVED",
)

INSTRUCTION = (
    "Use only the supplied evidence. Classify two independent axes. "
    "RELATION describes the evidence relationship: SUPPORT when compatible evidence "
    "supports the same claim; TEMPORAL_CHANGE when different values are compatible at "
    "different validity times; CORRECTION when evidence explicitly shows an earlier "
    "claim was wrong for its claimed period; CONTRADICTION when incompatible evidence "
    "applies to the same entity, predicate and time; INSUFFICIENT when the evidence does "
    "not safely establish any of those relations. RESOLUTION is RESOLVED when the semantic "
    "relationship is sufficiently established, otherwise UNRESOLVED. Return exactly one "
    "candidate from candidates and no other text. Do not decide by source name, confidence, "
    "recency, or source count alone."
)


@dataclass(frozen=True, slots=True)
class DualAxisAuditCase:
    case_id: str
    difficulty: AuditDifficulty
    category: str
    expected_relation: str
    expected_resolution: str
    evidence: tuple[dict, ...]

    def __post_init__(self):
        if self.expected_relation not in RELATION_LABELS:
            raise ValueError("unsupported expected relation")
        if self.expected_resolution not in RESOLUTION_LABELS:
            raise ValueError("unsupported expected resolution")
        if self.expected_candidate not in CANDIDATES:
            raise ValueError("unsupported expected relation/resolution pair")

    @property
    def expected_candidate(self):
        return f"{self.expected_relation}|{self.expected_resolution}"

    def view_payload(self):
        return {
            "operation": "CLASSIFY_SEMANTIC_EVIDENCE",
            "output_contract": "candidate",
            "candidates": list(CANDIDATES),
            "input": INSTRUCTION,
            "audit_version": AUDIT_VERSION,
            "audit_case": self.case_id,
            "evidence": [plain(item) for item in self.evidence],
        }


def _axes(old_expected):
    if old_expected == "SUPPORT":
        return "SUPPORT", "RESOLVED"
    if old_expected == "TEMPORAL_CHANGE":
        return "TEMPORAL_CHANGE", "RESOLVED"
    if old_expected == "CORRECTION":
        return "CORRECTION", "RESOLVED"
    if old_expected == "CONTRADICTION":
        return "CONTRADICTION", "UNRESOLVED"
    if old_expected == "UNRESOLVED":
        return "INSUFFICIENT", "UNRESOLVED"
    raise ValueError(f"unsupported v0.1 expected label: {old_expected}")


def default_audit_corpus():
    result = []
    for case in _v01_corpus():
        relation, resolution = _axes(case.expected)
        result.append(
            DualAxisAuditCase(
                case_id=case.case_id,
                difficulty=case.difficulty,
                category=case.category,
                expected_relation=relation,
                expected_resolution=resolution,
                evidence=tuple(dict(plain(item)) for item in case.evidence),
            )
        )
    return tuple(result)


def make_request(case, role):
    if not isinstance(case, DualAxisAuditCase):
        raise TypeError("v0.2 audit requires DualAxisAuditCase")
    if not isinstance(role, CognitiveRole):
        raise TypeError("audit role must be CognitiveRole")
    return RoutedCognitiveRequest(
        persistent_task_id=f"task_{uuid4()}",
        canonical_task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        role=role,
        view=CognitiveView(role.value, case.view_payload()),
    )


def normalize_exact(text):
    if not isinstance(text, str):
        return None
    value = text.strip().upper()
    return value if value else None


def _first_label(text, labels):
    if not isinstance(text, str) or not text.strip():
        return None
    pattern = re.compile(
        r"(?<![A-Z0-9_])(" + "|".join(map(re.escape, labels)) + r")(?![A-Z0-9_])",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(1).upper() if match else None


def parse_semantic_axes(text):
    return (
        _first_label(text, RELATION_LABELS),
        _first_label(text, RESOLUTION_LABELS),
    )


__all__ = [
    "AUDIT_VERSION",
    "CANDIDATES",
    "INSTRUCTION",
    "RELATION_LABELS",
    "RESOLUTION_LABELS",
    "DualAxisAuditCase",
    "default_audit_corpus",
    "make_request",
    "normalize_exact",
    "parse_semantic_axes",
]
