"""Strict wire validation for the Stage 7 ``classify_relation/0.1`` profile.

This module intentionally uses only the standard library. It validates the frozen
Stage 7 renderer contract and referential integrity, but it does not own lifecycle,
Knowledge writes, routing, model dispatch, or source authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from typing import Any, Mapping


SUPPORTED_PROFILE = "classify_relation/0.1"
_SUPPORTED_PROFILES = (SUPPORTED_PROFILE,)
_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/@-]{0,95}$")
_INTEGER_RE = re.compile(r"^-?(0|[1-9][0-9]*)$")
_DECIMAL_RE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


@dataclass(frozen=True)
class ProcessFailure(ValueError):
    """A request failure outside semantic CONTENT/REVISION outcomes."""

    stage: str
    code: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - diagnostic convenience
        return f"{self.stage}:{self.code}"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": "process_error",
            "stage": self.stage,
            "code": self.code,
            "backend_calls_expected": 0,
        }
        result.update(self.details)
        return result


class _DuplicateKey(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def parse_json_strict(raw: str) -> Any:
    """Parse JSON while rejecting duplicate object keys before object construction."""

    if not isinstance(raw, str):
        raise ProcessFailure("parse", "invalid_input_type")
    try:
        return json.loads(raw, object_pairs_hook=_object_no_duplicates)
    except _DuplicateKey as exc:
        raise ProcessFailure("parse", "duplicate_key", {"key": exc.key}) from exc
    except json.JSONDecodeError as exc:
        raise ProcessFailure(
            "parse",
            "malformed_json",
            {"line": exc.lineno, "column": exc.colno},
        ) from exc


def parse_and_validate_request(raw: str) -> dict[str, Any]:
    data = parse_json_strict(raw)
    if not isinstance(data, dict):
        raise ProcessFailure("schema_validation", "invalid_shape", {"field": "$"})
    profile = data.get("profile")
    if profile != SUPPORTED_PROFILE:
        raise ProcessFailure(
            "preflight",
            "unsupported_profile",
            {
                "requested_profile": profile,
                "supported_profiles": list(_SUPPORTED_PROFILES),
            },
        )
    validate_request(data)
    return data


def _fail_shape(path: str) -> None:
    raise ProcessFailure("schema_validation", "invalid_shape", {"field": path or "$"})


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail_shape(path)
    return value


def _closed(obj: Mapping[str, Any], allowed: set[str], path: str) -> None:
    for key in obj:
        if key not in allowed:
            field = f"{path}.{key}" if path else key
            raise ProcessFailure(
                "schema_validation", "unknown_semantic_field", {"field": field}
            )


def _required(obj: Mapping[str, Any], names: set[str], path: str) -> None:
    for name in names:
        if name not in obj:
            field = f"{path}.{name}" if path else name
            raise ProcessFailure("schema_validation", "missing_required_field", {"field": field})


def _string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        _fail_shape(path)
    return value


def _ref(value: Any, path: str) -> str:
    text = _string(value, path)
    if not _REF_RE.fullmatch(text):
        _fail_shape(path)
    return text


def _array(value: Any, path: str, *, min_items: int, max_items: int) -> list[Any]:
    if not isinstance(value, list) or not min_items <= len(value) <= max_items:
        _fail_shape(path)
    return value


def _enum(value: Any, allowed: set[str], path: str) -> str:
    if value not in allowed:
        _fail_shape(path)
    return value


def _unique_strings(values: list[Any], path: str, *, ref: bool = False) -> list[str]:
    parsed = [
        (_ref(item, f"{path}[{i}]") if ref else _string(item, f"{path}[{i}]"))
        for i, item in enumerate(values)
    ]
    if len(set(parsed)) != len(parsed):
        raise ProcessFailure("schema_validation", "duplicate_value", {"field": path})
    return parsed


def _validate_timepoint(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    _closed(obj, {"value", "clock"}, path)
    _required(obj, {"value", "clock"}, path)
    text = _string(obj["value"], f"{path}.value")
    _ref(obj["clock"], f"{path}.clock")
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProcessFailure(
            "schema_validation", "invalid_rfc3339", {"field": f"{path}.value"}
        ) from exc
    if stamp.utcoffset() is None or "T" not in text:
        raise ProcessFailure(
            "schema_validation", "invalid_rfc3339", {"field": f"{path}.value"}
        )


def _validate_time_marker(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    kind = obj.get("kind")
    if kind == "unknown":
        _closed(obj, {"kind"}, path)
        _required(obj, {"kind"}, path)
        return
    if kind == "known":
        _closed(obj, {"kind", "at"}, path)
        _required(obj, {"kind", "at"}, path)
        _validate_timepoint(obj["at"], f"{path}.at")
        return
    _fail_shape(f"{path}.kind")


def _validate_temporal_bound(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    kind = obj.get("kind")
    if kind in {"unknown", "unbounded"}:
        _closed(obj, {"kind"}, path)
        _required(obj, {"kind"}, path)
        return
    if kind == "known":
        _closed(obj, {"kind", "at"}, path)
        _required(obj, {"kind", "at"}, path)
        _validate_timepoint(obj["at"], f"{path}.at")
        return
    _fail_shape(f"{path}.kind")


def _point_key(point: Mapping[str, Any]) -> tuple[str, datetime]:
    stamp = datetime.fromisoformat(point["value"].replace("Z", "+00:00"))
    return point["clock"], stamp


def _validate_temporal_scope(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    kind = obj.get("kind")
    if kind == "unknown":
        _closed(obj, {"kind"}, path)
        _required(obj, {"kind"}, path)
        return
    if kind == "instant":
        _closed(obj, {"kind", "at"}, path)
        _required(obj, {"kind", "at"}, path)
        _validate_timepoint(obj["at"], f"{path}.at")
        return
    if kind == "interval":
        _closed(obj, {"kind", "from", "until"}, path)
        _required(obj, {"kind", "from", "until"}, path)
        _validate_temporal_bound(obj["from"], f"{path}.from")
        _validate_temporal_bound(obj["until"], f"{path}.until")
        start = obj["from"]
        end = obj["until"]
        if start["kind"] == "known" and end["kind"] == "known":
            start_clock, start_time = _point_key(start["at"])
            end_clock, end_time = _point_key(end["at"])
            if start_clock == end_clock and start_time >= end_time:
                raise ProcessFailure(
                    "semantic_validation", "invalid_interval", {"field": path}
                )
        return
    _fail_shape(f"{path}.kind")


def _validate_entity_ref(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    kind = obj.get("kind")
    if kind == "resolved":
        _closed(obj, {"kind", "ref", "semantic_revision"}, path)
        _required(obj, {"kind", "ref", "semantic_revision"}, path)
        _ref(obj["ref"], f"{path}.ref")
        _string(obj["semantic_revision"], f"{path}.semantic_revision")
        return
    if kind == "unresolved":
        _closed(obj, {"kind", "mention", "evidence_ref"}, path)
        _required(obj, {"kind", "mention", "evidence_ref"}, path)
        _string(obj["mention"], f"{path}.mention")
        _ref(obj["evidence_ref"], f"{path}.evidence_ref")
        return
    _fail_shape(f"{path}.kind")


def _validate_predicate_ref(value: Any, path: str) -> None:
    _validate_entity_ref(value, path)


def _validate_value(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    value_type = obj.get("type")
    if value_type == "quantity":
        _closed(obj, {"type", "value", "unit"}, path)
        _required(obj, {"type", "value", "unit"}, path)
        number = _string(obj["value"], f"{path}.value")
        if not _DECIMAL_RE.fullmatch(number):
            _fail_shape(f"{path}.value")
        _ref(obj["unit"], f"{path}.unit")
        return
    if value_type == "entity":
        _closed(obj, {"type", "value"}, path)
        _required(obj, {"type", "value"}, path)
        _validate_entity_ref(obj["value"], f"{path}.value")
        return
    _closed(obj, {"type", "value"}, path)
    _required(obj, {"type", "value"}, path)
    if value_type == "string":
        if not isinstance(obj["value"], str):
            _fail_shape(f"{path}.value")
    elif value_type == "symbol":
        _ref(obj["value"], f"{path}.value")
    elif value_type == "boolean":
        if type(obj["value"]) is not bool:
            _fail_shape(f"{path}.value")
    elif value_type == "integer":
        text = _string(obj["value"], f"{path}.value")
        if not _INTEGER_RE.fullmatch(text):
            _fail_shape(f"{path}.value")
    elif value_type == "decimal":
        text = _string(obj["value"], f"{path}.value")
        if not _DECIMAL_RE.fullmatch(text):
            _fail_shape(f"{path}.value")
    else:
        _fail_shape(f"{path}.type")


def _validate_qualifier(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    _closed(obj, {"key", "value"}, path)
    _required(obj, {"key", "value"}, path)
    _ref(obj["key"], f"{path}.key")
    _validate_value(obj["value"], f"{path}.value")


def _validate_predicate_definition(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    allowed = {
        "ref",
        "semantic_revision",
        "value_type",
        "cardinality",
        "temporal_behavior",
        "comparison",
        "description",
    }
    _closed(obj, allowed, path)
    _required(
        obj,
        {
            "ref",
            "semantic_revision",
            "value_type",
            "cardinality",
            "temporal_behavior",
            "comparison",
        },
        path,
    )
    _ref(obj["ref"], f"{path}.ref")
    _string(obj["semantic_revision"], f"{path}.semantic_revision")
    _enum(
        obj["value_type"],
        {"string", "symbol", "boolean", "integer", "decimal", "quantity", "entity"},
        f"{path}.value_type",
    )
    _enum(obj["cardinality"], {"single", "multi", "unknown"}, f"{path}.cardinality")
    _enum(
        obj["temporal_behavior"],
        {"changeable", "invariant", "unspecified"},
        f"{path}.temporal_behavior",
    )
    if obj["comparison"] != "exact":
        _fail_shape(f"{path}.comparison")
    if "description" in obj:
        _string(obj["description"], f"{path}.description")


def _validate_claim(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    allowed = {
        "ref",
        "subject_ref",
        "predicate_ref",
        "value",
        "polarity",
        "qualifiers",
        "qualifier_completeness",
        "validity",
    }
    _closed(obj, allowed, path)
    _required(obj, allowed, path)
    _ref(obj["ref"], f"{path}.ref")
    _validate_entity_ref(obj["subject_ref"], f"{path}.subject_ref")
    _validate_predicate_ref(obj["predicate_ref"], f"{path}.predicate_ref")
    _validate_value(obj["value"], f"{path}.value")
    _enum(obj["polarity"], {"positive", "negative"}, f"{path}.polarity")
    qualifiers = _array(obj["qualifiers"], f"{path}.qualifiers", min_items=0, max_items=8)
    for index, qualifier in enumerate(qualifiers):
        _validate_qualifier(qualifier, f"{path}.qualifiers[{index}]")
    _enum(
        obj["qualifier_completeness"],
        {"complete", "partial", "unknown"},
        f"{path}.qualifier_completeness",
    )
    _validate_temporal_scope(obj["validity"], f"{path}.validity")


def _validate_evidence_content(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    kind = obj.get("kind")
    if kind == "text":
        _closed(obj, {"kind", "text", "completeness"}, path)
        _required(obj, {"kind", "text", "completeness"}, path)
        _string(obj["text"], f"{path}.text")
        _enum(
            obj["completeness"],
            {"complete", "truncated", "unknown"},
            f"{path}.completeness",
        )
        return
    if kind == "structured":
        _closed(obj, {"kind", "declaration_status"}, path)
        _required(obj, {"kind", "declaration_status"}, path)
        _enum(
            obj["declaration_status"],
            {"present", "absent", "unknown"},
            f"{path}.declaration_status",
        )
        return
    _fail_shape(f"{path}.kind")


def _validate_correction_link(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    _closed(obj, {"correcting_claim_ref", "corrected_claim_ref"}, path)
    _required(obj, {"correcting_claim_ref", "corrected_claim_ref"}, path)
    _ref(obj["correcting_claim_ref"], f"{path}.correcting_claim_ref")
    _ref(obj["corrected_claim_ref"], f"{path}.corrected_claim_ref")


def _validate_evidence(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    required = {
        "ref",
        "claim_refs",
        "form",
        "stance",
        "source_ref",
        "content",
        "observed_at",
        "identity",
        "provenance_root_refs",
        "producer_ref",
        "asserted_at",
        "received_at",
        "created_at",
    }
    allowed = required | {"correction_link", "premise_evidence_refs", "derivation_method_ref"}
    _closed(obj, allowed, path)
    _required(obj, required, path)
    _ref(obj["ref"], f"{path}.ref")
    claim_refs = _array(obj["claim_refs"], f"{path}.claim_refs", min_items=1, max_items=2)
    _unique_strings(claim_refs, f"{path}.claim_refs", ref=True)
    form = _enum(obj["form"], {"observation", "report", "derivation"}, f"{path}.form")
    _enum(obj["stance"], {"asserted", "hypothesized"}, f"{path}.stance")
    if obj["source_ref"] is not None:
        _ref(obj["source_ref"], f"{path}.source_ref")
    elif form in {"observation", "report"}:
        raise ProcessFailure(
            "semantic_validation", "missing_source", {"field": f"{path}.source_ref"}
        )
    _validate_evidence_content(obj["content"], f"{path}.content")
    for name in ("observed_at", "asserted_at", "received_at", "created_at"):
        _validate_time_marker(obj[name], f"{path}.{name}")
    identity = _mapping(obj["identity"], f"{path}.identity")
    _closed(identity, {"occurrence_ref", "version_ref"}, f"{path}.identity")
    _required(identity, {"occurrence_ref", "version_ref"}, f"{path}.identity")
    _ref(identity["occurrence_ref"], f"{path}.identity.occurrence_ref")
    _ref(identity["version_ref"], f"{path}.identity.version_ref")
    roots = _array(
        obj["provenance_root_refs"], f"{path}.provenance_root_refs", min_items=1, max_items=8
    )
    _unique_strings(roots, f"{path}.provenance_root_refs", ref=True)
    _ref(obj["producer_ref"], f"{path}.producer_ref")
    if "correction_link" in obj:
        _validate_correction_link(obj["correction_link"], f"{path}.correction_link")
    if "premise_evidence_refs" in obj:
        refs = _array(
            obj["premise_evidence_refs"], f"{path}.premise_evidence_refs", min_items=1, max_items=8
        )
        _unique_strings(refs, f"{path}.premise_evidence_refs", ref=True)
    if "derivation_method_ref" in obj:
        _ref(obj["derivation_method_ref"], f"{path}.derivation_method_ref")
    if form == "derivation":
        if "premise_evidence_refs" not in obj or "derivation_method_ref" not in obj:
            raise ProcessFailure("semantic_validation", "invalid_derivation", {"field": path})
    elif "premise_evidence_refs" in obj or "derivation_method_ref" in obj:
        raise ProcessFailure("semantic_validation", "invalid_derivation", {"field": path})


def _validate_coverage(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    _closed(obj, {"completeness", "limitations"}, path)
    _required(obj, {"completeness", "limitations"}, path)
    _enum(
        obj["completeness"],
        {"complete_for_declared_scope", "partial", "unknown"},
        f"{path}.completeness",
    )
    limitations = _array(obj["limitations"], f"{path}.limitations", min_items=0, max_items=7)
    parsed = [
        _enum(
            item,
            {
                "retrieval_truncated",
                "fragment_truncated",
                "unresolved_binding",
                "missing_time",
                "missing_source",
                "unknown_dependency",
                "other_selection_limit",
            },
            f"{path}.limitations[{index}]",
        )
        for index, item in enumerate(limitations)
    ]
    if len(set(parsed)) != len(parsed):
        raise ProcessFailure(
            "schema_validation", "duplicate_value", {"field": f"{path}.limitations"}
        )


def _validate_scope_comparison(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    _closed(obj, {"entity", "predicate", "context"}, path)
    _required(obj, {"entity", "predicate", "context"}, path)
    _enum(obj["entity"], {"same", "different", "unknown"}, f"{path}.entity")
    _enum(obj["predicate"], {"same", "different", "unknown"}, f"{path}.predicate")
    _enum(obj["context"], {"same", "disjoint", "overlap", "unknown"}, f"{path}.context")


def validate_request(data: Mapping[str, Any]) -> None:
    obj = _mapping(data, "")
    allowed = {
        "profile",
        "kind",
        "aspects",
        "required_features",
        "predicate_defs",
        "claims",
        "evidence",
        "coverage",
        "scope_comparison",
    }
    _closed(obj, allowed, "")
    _required(obj, allowed, "")
    if obj["profile"] != SUPPORTED_PROFILE or obj["kind"] != "request":
        _fail_shape("profile" if obj["profile"] != SUPPORTED_PROFILE else "kind")

    aspects = _array(obj["aspects"], "aspects", min_items=1, max_items=2)
    parsed_aspects = [
        _enum(item, {"content", "revision"}, f"aspects[{i}]")
        for i, item in enumerate(aspects)
    ]
    if len(set(parsed_aspects)) != len(parsed_aspects):
        raise ProcessFailure("schema_validation", "duplicate_value", {"field": "aspects"})

    required_features = _array(
        obj["required_features"], "required_features", min_items=0, max_items=16
    )
    _unique_strings(required_features, "required_features", ref=True)

    predicate_defs = _array(obj["predicate_defs"], "predicate_defs", min_items=0, max_items=2)
    for index, definition in enumerate(predicate_defs):
        _validate_predicate_definition(definition, f"predicate_defs[{index}]")
    predicate_ids = [definition["ref"] for definition in predicate_defs]
    if len(set(predicate_ids)) != len(predicate_ids):
        raise ProcessFailure(
            "schema_validation", "duplicate_predicate_ref", {"field": "predicate_defs"}
        )

    claims = _array(obj["claims"], "claims", min_items=2, max_items=2)
    for index, claim in enumerate(claims):
        _validate_claim(claim, f"claims[{index}]")
    claim_ids = [claim["ref"] for claim in claims]
    if len(set(claim_ids)) != len(claim_ids):
        raise ProcessFailure("semantic_validation", "duplicate_claim_ref", {"ref": claim_ids[0]})

    evidence = _array(obj["evidence"], "evidence", min_items=1, max_items=8)
    for index, item in enumerate(evidence):
        _validate_evidence(item, f"evidence[{index}]")
    evidence_ids = [item["ref"] for item in evidence]
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ProcessFailure(
            "semantic_validation", "duplicate_evidence_ref", {"ref": evidence_ids[0]}
        )

    _validate_coverage(obj["coverage"], "coverage")
    _validate_scope_comparison(obj["scope_comparison"], "scope_comparison")

    claim_set = set(claim_ids)
    evidence_set = set(evidence_ids)
    for item in evidence:
        for ref in item["claim_refs"]:
            if ref not in claim_set:
                raise ProcessFailure(
                    "referential_integrity", "dangling_claim_ref", {"ref": ref}
                )
        link = item.get("correction_link")
        if link:
            for key in ("correcting_claim_ref", "corrected_claim_ref"):
                ref = link[key]
                if ref not in claim_set:
                    raise ProcessFailure(
                        "referential_integrity", "dangling_claim_ref", {"ref": ref}
                    )
            if link["correcting_claim_ref"] == link["corrected_claim_ref"]:
                raise ProcessFailure(
                    "semantic_validation",
                    "invalid_correction_direction",
                    {"ref": link["correcting_claim_ref"]},
                )
        for ref in item.get("premise_evidence_refs", []):
            if ref not in evidence_set:
                raise ProcessFailure(
                    "referential_integrity", "dangling_evidence_ref", {"ref": ref}
                )

    for claim in claims:
        for field_name in ("subject_ref", "predicate_ref"):
            ref_obj = claim[field_name]
            if (
                ref_obj["kind"] == "unresolved"
                and ref_obj["evidence_ref"] not in evidence_set
            ):
                raise ProcessFailure(
                    "referential_integrity",
                    "dangling_evidence_ref",
                    {"ref": ref_obj["evidence_ref"]},
                )
        value = claim["value"]
        if (
            value["type"] == "entity"
            and value["value"]["kind"] == "unresolved"
            and value["value"]["evidence_ref"] not in evidence_set
        ):
            raise ProcessFailure(
                "referential_integrity",
                "dangling_evidence_ref",
                {"ref": value["value"]["evidence_ref"]},
            )

    definitions = {definition["ref"]: definition for definition in predicate_defs}
    for claim in claims:
        predicate_ref = claim["predicate_ref"]
        if predicate_ref["kind"] != "resolved":
            continue
        definition = definitions.get(predicate_ref["ref"])
        if definition and definition["value_type"] != claim["value"]["type"]:
            raise ProcessFailure(
                "semantic_validation",
                "predicate_value_type_mismatch",
                {"ref": predicate_ref["ref"]},
            )


def _validate_evidence_refs(
    refs: Any,
    request: Mapping[str, Any],
    path: str,
    *,
    allow_empty: bool = False,
) -> None:
    values = _array(refs, path, min_items=0 if allow_empty else 1, max_items=8)
    parsed = _unique_strings(values, path, ref=True)
    known = {item["ref"] for item in request["evidence"]}
    for ref in parsed:
        if ref not in known:
            raise ProcessFailure(
                "referential_integrity", "dangling_evidence_ref", {"ref": ref}
            )


def _validate_feature_refs(value: Any, path: str) -> None:
    refs = _array(value, path, min_items=1, max_items=16)
    _unique_strings(refs, path, ref=True)


def _validate_content_result(value: Any, request: Mapping[str, Any], path: str) -> None:
    obj = _mapping(value, path)
    kind = obj.get("kind")
    if kind == "not_requested":
        _closed(obj, {"kind"}, path)
        return
    if kind == "unsupported":
        _closed(obj, {"kind", "required_features"}, path)
        _required(obj, {"kind", "required_features"}, path)
        _validate_feature_refs(obj["required_features"], f"{path}.required_features")
        return
    if kind == "relation":
        relation = obj.get("relation")
        if relation == "TEMPORAL_SUCCESSION":
            _closed(
                obj,
                {
                    "kind",
                    "relation",
                    "earlier_claim_ref",
                    "later_claim_ref",
                    "evidence_refs",
                },
                path,
            )
            _required(
                obj,
                {
                    "kind",
                    "relation",
                    "earlier_claim_ref",
                    "later_claim_ref",
                    "evidence_refs",
                },
                path,
            )
            claim_ids = {claim["ref"] for claim in request["claims"]}
            for key in ("earlier_claim_ref", "later_claim_ref"):
                ref = _ref(obj[key], f"{path}.{key}")
                if ref not in claim_ids:
                    raise ProcessFailure(
                        "referential_integrity", "dangling_claim_ref", {"ref": ref}
                    )
            _validate_evidence_refs(
                obj["evidence_refs"], request, f"{path}.evidence_refs"
            )
            return
        _closed(obj, {"kind", "relation", "evidence_refs"}, path)
        _required(obj, {"kind", "relation", "evidence_refs"}, path)
        _enum(
            relation,
            {"SUPPORT", "CONTRADICTION", "COMPATIBLE_DISTINCT"},
            f"{path}.relation",
        )
        _validate_evidence_refs(obj["evidence_refs"], request, f"{path}.evidence_refs")
        return
    if kind == "not_comparable":
        _closed(obj, {"kind", "reason", "evidence_refs"}, path)
        _required(obj, {"kind", "reason", "evidence_refs"}, path)
        _enum(
            obj["reason"],
            {"DIFFERENT_ENTITY", "DIFFERENT_PREDICATE", "DISJOINT_CONTEXT"},
            f"{path}.reason",
        )
        _validate_evidence_refs(obj["evidence_refs"], request, f"{path}.evidence_refs")
        return
    if kind == "insufficient":
        _closed(obj, {"kind", "missing", "considered_evidence_refs"}, path)
        _required(obj, {"kind", "missing", "considered_evidence_refs"}, path)
        missing = _array(obj["missing"], f"{path}.missing", min_items=1, max_items=8)
        allowed = {
            "entity_binding",
            "predicate_binding",
            "context_scope",
            "temporal_scope",
            "evidence_for_claim",
            "value_semantics",
            "cardinality",
            "temporal_behavior",
        }
        parsed = [
            _enum(item, allowed, f"{path}.missing[{i}]")
            for i, item in enumerate(missing)
        ]
        if len(set(parsed)) != len(parsed):
            raise ProcessFailure(
                "schema_validation", "duplicate_value", {"field": f"{path}.missing"}
            )
        _validate_evidence_refs(
            obj["considered_evidence_refs"],
            request,
            f"{path}.considered_evidence_refs",
            allow_empty=True,
        )
        return
    _fail_shape(f"{path}.kind")


def _validate_revision_result(value: Any, request: Mapping[str, Any], path: str) -> None:
    obj = _mapping(value, path)
    kind = obj.get("kind")
    if kind == "not_requested":
        _closed(obj, {"kind"}, path)
        return
    if kind == "unsupported":
        _closed(obj, {"kind", "required_features"}, path)
        _required(obj, {"kind", "required_features"}, path)
        _validate_feature_refs(obj["required_features"], f"{path}.required_features")
        return
    if kind == "correction":
        _closed(
            obj,
            {
                "kind",
                "correcting_claim_ref",
                "corrected_claim_ref",
                "evidence_refs",
            },
            path,
        )
        _required(
            obj,
            {
                "kind",
                "correcting_claim_ref",
                "corrected_claim_ref",
                "evidence_refs",
            },
            path,
        )
        claim_ids = {claim["ref"] for claim in request["claims"]}
        for key in ("correcting_claim_ref", "corrected_claim_ref"):
            ref = _ref(obj[key], f"{path}.{key}")
            if ref not in claim_ids:
                raise ProcessFailure(
                    "referential_integrity", "dangling_claim_ref", {"ref": ref}
                )
        _validate_evidence_refs(obj["evidence_refs"], request, f"{path}.evidence_refs")
        return
    if kind == "no_declaration_in_scope":
        _closed(obj, {"kind", "evidence_refs"}, path)
        _required(obj, {"kind", "evidence_refs"}, path)
        _validate_evidence_refs(obj["evidence_refs"], request, f"{path}.evidence_refs")
        return
    if kind == "insufficient":
        _closed(obj, {"kind", "missing", "considered_evidence_refs"}, path)
        _required(obj, {"kind", "missing", "considered_evidence_refs"}, path)
        missing = _array(obj["missing"], f"{path}.missing", min_items=1, max_items=4)
        allowed = {
            "correction_target",
            "correction_intent",
            "source_attribution",
            "evidence_fragment",
        }
        parsed = [
            _enum(item, allowed, f"{path}.missing[{i}]")
            for i, item in enumerate(missing)
        ]
        if len(set(parsed)) != len(parsed):
            raise ProcessFailure(
                "schema_validation", "duplicate_value", {"field": f"{path}.missing"}
            )
        _validate_evidence_refs(
            obj["considered_evidence_refs"],
            request,
            f"{path}.considered_evidence_refs",
            allow_empty=True,
        )
        return
    _fail_shape(f"{path}.kind")


def validate_assessment(data: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    obj = _mapping(data, "")
    allowed = {"profile", "kind", "content", "revision"}
    _closed(obj, allowed, "")
    _required(obj, allowed, "")
    if obj["profile"] != SUPPORTED_PROFILE or obj["kind"] != "assessment":
        _fail_shape("profile" if obj["profile"] != SUPPORTED_PROFILE else "kind")
    _validate_content_result(obj["content"], request, "content")
    _validate_revision_result(obj["revision"], request, "revision")
    aspects = set(request["aspects"])
    if "content" not in aspects and obj["content"].get("kind") != "not_requested":
        raise ProcessFailure("semantic_validation", "unexpected_content_result")
    if "revision" not in aspects and obj["revision"].get("kind") != "not_requested":
        raise ProcessFailure("semantic_validation", "unexpected_revision_result")
