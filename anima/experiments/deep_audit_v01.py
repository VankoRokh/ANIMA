"""Scoped revision of the comparative FAST/DEEP audit corpus.

v0 exposed a useful flaw in the benchmark itself: after removing case-specific
answer hints, many evidence items no longer stated which entity/property they
referred to. v0.1 keeps the same ground truth and general instructions but adds
explicit semantic scope. This is benchmark metadata, not an answer hint.
"""

from anima.experiments.deep_audit import (
    AuditDifficulty,
    DeepAuditCase,
    default_audit_corpus as _v0_corpus,
)
from anima.ir import plain


AUDIT_VERSION = "deep-baseline-v0.1"


class ScopedAuditCase(DeepAuditCase):
    def view_payload(self):
        payload = super().view_payload()
        payload["audit_version"] = AUDIT_VERSION
        return payload


_SCOPE = {
    "S01": ("raspberry_pi_5", "cpu_model"),
    "S02": ("bar", "closing_time"),
    "S03": ("ssd", "capacity"),
    "S04": ("door", "state"),
    "S05": ("device", "location"),
    "S06": ("device", "availability"),
    "S07": ("user", "preference"),
    "S08": ("user", "preference"),
    "S09": ("device", "capacity"),
    "S10": ("device", "location"),
    "M01": ("cpu", "temperature"),
    "M02": ("cpu", "temperature"),
    "M03": ("device", "mode"),
    "M04": ("user", "preference"),
    "M05": ("bar", "closing_time"),
    "M06": ("device", "mode"),
    "M07": ("cpu", "temperature"),
    "M08": ("door", "state"),
    "M09": ("ssd", "capacity"),
    "M10": ("raspberry_pi_5", "cpu_model"),
    "H01": ("door", "state"),
    "H02": ("cpu", "temperature"),
    "H03": ("device", "availability"),
    "H04": ("door", "state"),
    "H05": ("device", "capacity"),
    "H06": ("bar", "closing_time"),
    "H07": ("cpu", "temperature"),
    "H08": ("device", "diagnosis"),
    "H09": ("user", "preference"),
    "H10": ("device", "location"),
}


def _with_scope(case):
    entity, predicate = _SCOPE[case.case_id]
    evidence = []
    for item in case.evidence:
        scoped = dict(plain(item))
        scoped.setdefault("entity", entity)
        scoped.setdefault("predicate", predicate)
        evidence.append(scoped)

    # Explicitly preserve the identity uncertainty being tested instead of
    # accidentally implying one resolved physical device.
    if case.case_id in {"S09", "H05"}:
        evidence[0]["entity"] = "device_candidate_A"
        evidence[1]["entity"] = "device_candidate_B"
        evidence[0]["identity_status"] = "same_physical_device_unresolved"
        evidence[1]["identity_status"] = "same_physical_device_unresolved"

    # Noise cases deliberately contain evidence about other predicates/entities.
    if case.case_id == "M10":
        evidence[0].update(entity="raspberry_pi_5", predicate="cpu_model")
        evidence[1].update(entity="raspberry_pi_5", predicate="cpu_model")
        evidence[2].update(entity="raspberry_pi_5", predicate="ram")
        evidence[3].update(entity="session", predicate="location")
    elif case.case_id == "H08":
        evidence[0].update(entity="device", predicate="possible_cause")
        evidence[1].update(entity="device", predicate="temperature_state")
    elif case.case_id == "H10":
        evidence[0].update(entity="device", predicate="location")
        evidence[1].update(entity="device", predicate="location")
        evidence[2].update(entity="device", predicate="temperature")
        evidence[3].update(entity="device", predicate="availability")

    return ScopedAuditCase(
        case.case_id,
        case.difficulty,
        case.category,
        case.expected,
        case.input_text,
        tuple(evidence),
        case.notes,
    )


def default_audit_corpus():
    """Return the v0 corpus with explicit semantic scope, preserving ground truth."""
    return tuple(_with_scope(case) for case in _v0_corpus())


__all__ = [
    "AUDIT_VERSION",
    "AuditDifficulty",
    "ScopedAuditCase",
    "default_audit_corpus",
]
