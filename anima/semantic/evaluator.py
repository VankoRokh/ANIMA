"""Deterministic Stage 7 reference evaluator for ``classify_relation/0.1``.

The evaluator is deliberately read-only. It classifies CONTENT/REVISION facets
that are decidable from typed records and returns a residual plan for facets that
still require language semantics. It never writes Knowledge or invokes a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import re
from typing import Any, Mapping

from .validation import SUPPORTED_PROFILE, ProcessFailure, parse_and_validate_request


NOT_REQUESTED = {"kind": "not_requested"}
_RFC3339_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<zone>Z|[+-]\d{2}:\d{2})$"
)


def fingerprint_request(request: Mapping[str, Any]) -> str:
    """Return a stable system-owned digest for one exact validated request."""

    payload = json.dumps(
        request,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ExactUnitRegistry:
    """Explicit exact unit normalization table used by the reference evaluator."""

    units: Mapping[str, tuple[str, Decimal]] = field(default_factory=dict)

    @classmethod
    def reference_defaults(cls) -> "ExactUnitRegistry":
        return cls(
            {
                "unit.m": ("length", Decimal("1")),
                "unit.cm": ("length", Decimal("0.01")),
            }
        )

    def compare(self, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool | None:
        left_unit = left["unit"]
        right_unit = right["unit"]
        left_value = Decimal(left["value"])
        right_value = Decimal(right["value"])
        if left_unit == right_unit:
            return left_value == right_value
        left_def = self.units.get(left_unit)
        right_def = self.units.get(right_unit)
        if not left_def or not right_def or left_def[0] != right_def[0]:
            return None
        left_exact = Fraction(left_value) * Fraction(left_def[1])
        right_exact = Fraction(right_value) * Fraction(right_def[1])
        return left_exact == right_exact


@dataclass(frozen=True)
class EvaluationPlan:
    profile: str
    content: Mapping[str, Any] | None
    revision: Mapping[str, Any] | None
    residual_facets: tuple[str, ...] = ()
    request_fingerprint: str | None = None

    @property
    def backend_calls_required(self) -> int:
        return 1 if self.residual_facets else 0

    @property
    def complete(self) -> bool:
        return not self.residual_facets

    def assessment(self) -> dict[str, Any]:
        if not self.complete:
            raise ValueError("Residual facets must be completed before producing an Assessment")
        assert self.content is not None and self.revision is not None
        return {
            "profile": self.profile,
            "kind": "assessment",
            "content": dict(self.content),
            "revision": dict(self.revision),
        }

    def determined_facets(self) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        if self.content is not None:
            result["content"] = self.content
        if self.revision is not None:
            result["revision"] = self.revision
        return result


@dataclass(frozen=True)
class _Boundary:
    point: Mapping[str, Any] | None = None
    infinity: int = 0  # -1 = -inf, +1 = +inf
    inclusive: bool = True
    unknown: bool = False


class DeterministicRelationEvaluator:
    """Reference, not production, evaluator for frozen Stage 7 root semantics."""

    def __init__(
        self,
        *,
        unit_registry: ExactUnitRegistry | None = None,
        supported_features: frozenset[str] | None = None,
    ) -> None:
        self._units = unit_registry or ExactUnitRegistry.reference_defaults()
        self._supported_features = supported_features or frozenset()

    def evaluate(self, request: Mapping[str, Any]) -> EvaluationPlan:
        aspects = set(request["aspects"])
        unsupported = [
            feature
            for feature in request["required_features"]
            if feature not in self._supported_features
        ]

        content: Mapping[str, Any] | None = NOT_REQUESTED if "content" not in aspects else None
        revision: Mapping[str, Any] | None = NOT_REQUESTED if "revision" not in aspects else None
        residual: list[str] = []

        if "content" in aspects:
            content_features = [feature for feature in unsupported if feature.startswith("content.")]
            if content_features:
                content = {"kind": "unsupported", "required_features": content_features}
            else:
                content = self._evaluate_content(request)

        if "revision" in aspects:
            revision_features = [feature for feature in unsupported if feature.startswith("revision.")]
            if revision_features:
                revision = {"kind": "unsupported", "required_features": revision_features}
            else:
                revision = self._evaluate_revision(request)
                if revision is None:
                    residual.append("revision")

        return EvaluationPlan(
            profile=SUPPORTED_PROFILE,
            content=content,
            revision=revision,
            residual_facets=tuple(residual),
            request_fingerprint=fingerprint_request(request),
        )

    def _evidence_refs(self, request: Mapping[str, Any]) -> list[str]:
        """Return terminal facet grounds, not transitive derivation premises.

        Premise Evidence remains addressable through ``premise_evidence_refs`` and
        provenance. Repeating it in a facet result would flatten the dependency
        graph and make one lineage look like multiple independent grounds.
        """

        premise_refs = {
            premise_ref
            for item in request["evidence"]
            for premise_ref in item.get("premise_evidence_refs", ())
        }
        terminal_refs = [
            item["ref"]
            for item in request["evidence"]
            if item["ref"] not in premise_refs
        ]
        return terminal_refs or [item["ref"] for item in request["evidence"]]

    def _content_relation(self, relation: str, request: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "kind": "relation",
            "relation": relation,
            "evidence_refs": self._evidence_refs(request),
        }

    def _content_insufficient(self, missing: str, request: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "kind": "insufficient",
            "missing": [missing],
            "considered_evidence_refs": self._evidence_refs(request),
        }

    def _evaluate_content(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        scope = request["scope_comparison"]
        evidence_refs = self._evidence_refs(request)
        if scope["entity"] == "different":
            return {
                "kind": "not_comparable",
                "reason": "DIFFERENT_ENTITY",
                "evidence_refs": evidence_refs,
            }
        if scope["predicate"] == "different":
            return {
                "kind": "not_comparable",
                "reason": "DIFFERENT_PREDICATE",
                "evidence_refs": evidence_refs,
            }
        if scope["context"] == "disjoint":
            return {
                "kind": "not_comparable",
                "reason": "DISJOINT_CONTEXT",
                "evidence_refs": evidence_refs,
            }
        if scope["entity"] == "unknown":
            return self._content_insufficient("entity_binding", request)
        if scope["predicate"] == "unknown":
            return self._content_insufficient("predicate_binding", request)
        if scope["context"] == "unknown":
            return self._content_insufficient("context_scope", request)
        if scope["context"] == "overlap":
            return {
                "kind": "unsupported",
                "required_features": ["content.partial_context_overlap/1"],
            }

        left, right = request["claims"]
        if left["subject_ref"]["kind"] == "unresolved" or right["subject_ref"]["kind"] == "unresolved":
            return self._content_insufficient("entity_binding", request)
        if left["predicate_ref"]["kind"] == "unresolved" or right["predicate_ref"]["kind"] == "unresolved":
            return self._content_insufficient("predicate_binding", request)

        value_equal = self._values_equal(left["value"], right["value"])
        if value_equal is None:
            return self._content_insufficient("value_semantics", request)

        predicate = self._predicate_definition(request, left)
        cardinality = predicate["cardinality"] if predicate else "unknown"
        temporal_behavior = predicate["temporal_behavior"] if predicate else "unspecified"

        if value_equal and left["polarity"] == right["polarity"]:
            local = "equivalent"
        elif value_equal:
            local = "incompatible"
        elif left["polarity"] == right["polarity"] == "positive":
            if cardinality == "unknown":
                return self._content_insufficient("cardinality", request)
            local = "incompatible" if cardinality == "single" else "compatible"
        else:
            local = "compatible"

        if local == "compatible":
            return self._content_relation("COMPATIBLE_DISTINCT", request)

        temporal = self._temporal_relation(left["validity"], right["validity"])
        if local == "equivalent":
            if temporal == "same":
                return self._content_relation("SUPPORT", request)
            if temporal == "unknown":
                return self._content_insufficient("temporal_scope", request)
            return self._content_relation("COMPATIBLE_DISTINCT", request)

        if temporal in {"same", "overlap"}:
            return self._content_relation("CONTRADICTION", request)
        if temporal in {"left_before", "right_before"}:
            if temporal_behavior == "unspecified":
                return self._content_insufficient("temporal_behavior", request)
            if temporal_behavior == "invariant":
                return {
                    "kind": "unsupported",
                    "required_features": ["content.cross_time_invariance/1"],
                }
            earlier = left["ref"] if temporal == "left_before" else right["ref"]
            later = right["ref"] if temporal == "left_before" else left["ref"]
            return {
                "kind": "relation",
                "relation": "TEMPORAL_SUCCESSION",
                "earlier_claim_ref": earlier,
                "later_claim_ref": later,
                "evidence_refs": evidence_refs,
            }
        return self._content_insufficient("temporal_scope", request)

    def _evaluate_revision(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None:
        evidence = request["evidence"]

        correction_evidence = [
            item
            for item in evidence
            if item["content"]["kind"] == "structured"
            and item["content"]["declaration_status"] == "present"
            and item.get("correction_link")
        ]
        if correction_evidence:
            item = correction_evidence[0]
            link = item["correction_link"]
            return {
                "kind": "correction",
                "correcting_claim_ref": link["correcting_claim_ref"],
                "corrected_claim_ref": link["corrected_claim_ref"],
                "evidence_refs": [item["ref"]],
            }

        present_without_target = [
            item
            for item in evidence
            if item["content"]["kind"] == "structured"
            and item["content"]["declaration_status"] == "present"
        ]
        if present_without_target:
            return {
                "kind": "insufficient",
                "missing": ["correction_target"],
                "considered_evidence_refs": [item["ref"] for item in present_without_target],
            }

        truncated = [
            item
            for item in evidence
            if item["content"]["kind"] == "text"
            and item["content"]["completeness"] != "complete"
        ]
        if truncated:
            return {
                "kind": "insufficient",
                "missing": ["evidence_fragment"],
                "considered_evidence_refs": [item["ref"] for item in truncated],
            }

        complete_text = [
            item
            for item in evidence
            if item["content"]["kind"] == "text"
            and item["content"]["completeness"] == "complete"
        ]
        if complete_text:
            return None

        structured = [
            item for item in evidence if item["content"]["kind"] == "structured"
        ]
        if structured and all(
            item["content"]["declaration_status"] == "absent" for item in structured
        ):
            if request["coverage"]["completeness"] == "complete_for_declared_scope":
                return {
                    "kind": "no_declaration_in_scope",
                    "evidence_refs": [item["ref"] for item in structured],
                }
            return {
                "kind": "insufficient",
                "missing": ["evidence_fragment"],
                "considered_evidence_refs": [item["ref"] for item in structured],
            }

        return {
            "kind": "insufficient",
            "missing": ["correction_intent"],
            "considered_evidence_refs": [item["ref"] for item in evidence],
        }

    def _predicate_definition(
        self, request: Mapping[str, Any], claim: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        predicate_ref = claim["predicate_ref"]
        if predicate_ref["kind"] != "resolved":
            return None
        for definition in request["predicate_defs"]:
            if definition["ref"] == predicate_ref["ref"]:
                return definition
        return None

    def _values_equal(
        self, left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> bool | None:
        if left["type"] != right["type"]:
            return False
        value_type = left["type"]
        if value_type == "integer":
            return int(left["value"]) == int(right["value"])
        if value_type == "decimal":
            return Decimal(left["value"]) == Decimal(right["value"])
        if value_type == "quantity":
            return self._units.compare(left, right)
        if value_type == "entity":
            left_ref = left["value"]
            right_ref = right["value"]
            if left_ref["kind"] != "resolved" or right_ref["kind"] != "resolved":
                return None
            return (left_ref["ref"], left_ref["semantic_revision"]) == (
                right_ref["ref"],
                right_ref["semantic_revision"],
            )
        return left["value"] == right["value"]

    @staticmethod
    def _rfc3339_value(text: str) -> Fraction:
        match = _RFC3339_RE.fullmatch(text)
        if match is None:
            raise ValueError(f"Unsupported RFC3339 timestamp: {text!r}")

        day = date.fromisoformat(match.group("date"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        second = int(match.group("second"))
        whole_seconds = ((day.toordinal() * 24 + hour) * 60 + minute) * 60 + second

        fraction_text = match.group("fraction") or ""
        fraction = (
            Fraction(int(fraction_text), 10 ** len(fraction_text))
            if fraction_text
            else Fraction(0, 1)
        )

        zone = match.group("zone")
        offset_seconds = 0
        if zone != "Z":
            sign = 1 if zone[0] == "+" else -1
            offset_hours = int(zone[1:3])
            offset_minutes = int(zone[4:6])
            offset_seconds = sign * (offset_hours * 3600 + offset_minutes * 60)

        return Fraction(whole_seconds - offset_seconds, 1) + fraction

    def _timepoint_cmp(
        self, left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> int | None:
        if left["clock"] != right["clock"]:
            return None
        left_time = self._rfc3339_value(left["value"])
        right_time = self._rfc3339_value(right["value"])
        return (left_time > right_time) - (left_time < right_time)

    def _start_boundary(self, scope: Mapping[str, Any]) -> _Boundary:
        if scope["kind"] == "unknown":
            return _Boundary(unknown=True)
        if scope["kind"] == "instant":
            return _Boundary(point=scope["at"], inclusive=True)
        bound = scope["from"]
        if bound["kind"] == "unknown":
            return _Boundary(unknown=True)
        if bound["kind"] == "unbounded":
            return _Boundary(infinity=-1, inclusive=False)
        return _Boundary(point=bound["at"], inclusive=True)

    def _end_boundary(self, scope: Mapping[str, Any]) -> _Boundary:
        if scope["kind"] == "unknown":
            return _Boundary(unknown=True)
        if scope["kind"] == "instant":
            return _Boundary(point=scope["at"], inclusive=True)
        bound = scope["until"]
        if bound["kind"] == "unknown":
            return _Boundary(unknown=True)
        if bound["kind"] == "unbounded":
            return _Boundary(infinity=1, inclusive=False)
        return _Boundary(point=bound["at"], inclusive=False)

    def _bound_cmp(self, left: _Boundary, right: _Boundary) -> int | None:
        if left.unknown or right.unknown:
            return None
        if left.infinity or right.infinity:
            if left.infinity == right.infinity:
                return 0
            if left.infinity == -1 or right.infinity == 1:
                return -1
            return 1
        assert left.point is not None and right.point is not None
        return self._timepoint_cmp(left.point, right.point)

    def _scope_same(self, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        if left["kind"] != right["kind"] or left["kind"] == "unknown":
            return False
        if left["kind"] == "instant":
            return self._timepoint_cmp(left["at"], right["at"]) == 0
        for key in ("from", "until"):
            left_bound = left[key]
            right_bound = right[key]
            if (
                left_bound["kind"] != right_bound["kind"]
                or left_bound["kind"] == "unknown"
            ):
                return False
            if (
                left_bound["kind"] == "known"
                and self._timepoint_cmp(left_bound["at"], right_bound["at"]) != 0
            ):
                return False
        return True

    def _provably_before(
        self, left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> bool:
        end = self._end_boundary(left)
        start = self._start_boundary(right)
        comparison = self._bound_cmp(end, start)
        if comparison is None:
            return False
        if comparison < 0:
            return True
        if comparison > 0:
            return False
        return not (end.inclusive and start.inclusive)

    def _provably_overlap(
        self, left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> bool | None:
        left_start = self._start_boundary(left)
        right_start = self._start_boundary(right)
        left_end = self._end_boundary(left)
        right_end = self._end_boundary(right)
        if any(
            bound.unknown
            for bound in (left_start, right_start, left_end, right_end)
        ):
            return None

        start_cmp = self._bound_cmp(left_start, right_start)
        end_cmp = self._bound_cmp(left_end, right_end)
        if start_cmp is None or end_cmp is None:
            return None
        latest_start = left_start if start_cmp >= 0 else right_start
        earliest_end = left_end if end_cmp <= 0 else right_end
        cross = self._bound_cmp(latest_start, earliest_end)
        if cross is None:
            return None
        if cross < 0:
            return True
        if cross > 0:
            return False
        return latest_start.inclusive and earliest_end.inclusive

    def _temporal_relation(
        self, left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> str:
        if self._scope_same(left, right):
            return "same"
        if self._provably_before(left, right):
            return "left_before"
        if self._provably_before(right, left):
            return "right_before"
        overlap = self._provably_overlap(left, right)
        if overlap is True:
            return "overlap"
        return "unknown"


def evaluate_document(
    raw: str, *, evaluator: DeterministicRelationEvaluator | None = None
) -> EvaluationPlan | dict[str, Any]:
    """Strictly parse/validate a request, then return a process error or evaluation plan."""

    try:
        request = parse_and_validate_request(raw)
    except ProcessFailure as failure:
        return failure.as_dict()
    return (evaluator or DeterministicRelationEvaluator()).evaluate(request)
