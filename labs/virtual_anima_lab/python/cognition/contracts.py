"""E2.x restricted cognition proposal DTO: validation only, never execution.

A language model may propose a *named* registered read-only operation. The
trusted Core (not this file) must still authorize, execute, verify and record
it. This module intentionally contains no action handlers, SQL, files or tools.
"""
from __future__ import annotations

import json
import re
from typing import Any

SCHEMA = "anima.cognition.step_proposal/0.1"
_REF = re.compile(r"[A-Za-z][A-Za-z0-9._:/@-]{0,127}\Z")
_ALLOWED = frozenset({
    "retrieve_memory", "lookup_raw_evidence", "inspect_current_belief",
    "inspect_goal_status", "inspect_latest_observation",
})
_MAX_JSON_BYTES = 4096


class CognitiveProposalError(ValueError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise CognitiveProposalError(message)


def _ref(value: Any, label: str) -> str:
    _require(type(value) is str and _REF.fullmatch(value) is not None,
             f"{label}: invalid ref")
    return value


def _args(op: str, value: Any) -> None:
    _require(type(value) is dict, "operation arguments must be a dict")
    if op == "retrieve_memory":
        _require(set(value) == {"query", "top_k"}, "retrieve_memory args")
        _require(type(value["query"]) is str and
                 1 <= len(value["query"].strip()) <= 512, "retrieval query")
        _require(type(value["top_k"]) is int and 1 <= value["top_k"] <= 20,
                 "retrieval top_k")
    elif op == "lookup_raw_evidence":
        _require(set(value) == {"event_ids"}, "lookup_raw_evidence args")
        ids = value["event_ids"]
        _require(type(ids) is list and 1 <= len(ids) <= 16,
                 "bounded event list required")
        for item in ids:
            _ref(item, "evidence event ID")
        _require(len(set(ids)) == len(ids), "duplicate event reference")
    elif op == "inspect_latest_observation":
        _require(not value, "latest observation takes no arguments")
    elif op == "inspect_current_belief":
        _require(set(value) == {"subject_ref", "predicate_ref"}, "belief args")
        _ref(value["subject_ref"], "subject_ref")
        _ref(value["predicate_ref"], "predicate_ref")
    elif op == "inspect_goal_status":
        _require(set(value) == {"goal_id"}, "goal args")
        _ref(value["goal_id"], "goal ID")
    else:
        raise CognitiveProposalError("no registered read-only operation")


def validate_cognitive_proposal(value: Any) -> dict:
    """Reject unknown fields, mutation-capable verbs and unbounded arguments."""
    _require(type(value) is dict, "proposal must be an object")
    _require(set(value) == {
        "schema", "proposal_id", "turn_id", "context_snapshot_id",
        "operation_kind", "arguments", "expected_information",
    }, "proposal requires exact fields")
    _require(value["schema"] == SCHEMA, "unrecognized proposal schema")
    for key in ("proposal_id", "turn_id", "context_snapshot_id"):
        _ref(value[key], key)
    op = value["operation_kind"]
    _require(type(op) is str and op in _ALLOWED,
             "operation not on read-only allowlist")
    _args(op, value["arguments"])
    _require(type(value["expected_information"]) is str and
             len(value["expected_information"]) <= 512,
             "expected information must be bounded untrusted text")
    try:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CognitiveProposalError("non-JSON proposal") from exc
    _require(len(canonical.encode("utf-8")) <= _MAX_JSON_BYTES,
             "proposal exceeds byte budget")
    return json.loads(canonical)


class CognitiveStepProposal:
    __slots__ = ("_canonical",)

    def __init__(self, value: Any):
        copy = validate_cognitive_proposal(value)
        object.__setattr__(
            self, "_canonical",
            json.dumps(copy, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        )

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("immutable cognitive proposal")

    def as_dict(self) -> dict:
        return json.loads(self._canonical)

    @property
    def canonical_json(self) -> str:
        return self._canonical


__all__ = [
    "SCHEMA", "CognitiveProposalError", "validate_cognitive_proposal",
    "CognitiveStepProposal",
]
