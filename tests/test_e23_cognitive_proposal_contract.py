"""Cognitive initiation cannot create permissions through proposal schema."""
from __future__ import annotations

from copy import deepcopy

import pytest

from labs.virtual_anima_lab.python.cognition.contracts import (
    SCHEMA, CognitiveProposalError, CognitiveStepProposal,
)


def proposal():
    return {
        "schema": SCHEMA, "proposal_id": "pr1", "turn_id": "turn1",
        "context_snapshot_id": "ctx1", "operation_kind": "retrieve_memory",
        "arguments": {"query": "last observed crate", "top_k": 6},
        "expected_information": "Find earlier evidence of crate location",
    }


def test_proposal_is_canonical_immutable_and_untrusted():
    original = proposal()
    parsed = CognitiveStepProposal(original)
    original["arguments"]["top_k"] = 100
    assert parsed.as_dict()["arguments"]["top_k"] == 6
    with pytest.raises(AttributeError):
        parsed._canonical = "{}"
    assert CognitiveStepProposal(parsed.as_dict()).canonical_json == parsed.canonical_json


@pytest.mark.parametrize("operation", [
    "world.act", "execute", "propose_world_action", "propose_knowledge_revision",
    "propose_subgoal", "delete_memory", "inspect_truth", "shell",
])
def test_no_mutating_or_secret_capabilities(operation):
    x = proposal()
    x["operation_kind"] = operation
    with pytest.raises(CognitiveProposalError, match="allowlist"):
        CognitiveStepProposal(x)


@pytest.mark.parametrize("change", [
    lambda x: x.update(auth="secret"),
    lambda x: x.update(approval=True),
    lambda x: x.update(proposal_id="../../escape"),
    lambda x: x.update(operation_kind="lookup_raw_evidence", arguments={"path": "/etc/passwd"}),
    lambda x: x.update(operation_kind="retrieve_memory", arguments={"query": "hi", "top_k": True}),
    lambda x: x.update(arguments={"query": "hi", "top_k": 21}),
    lambda x: x.update(arguments={"query": "hi", "top_k": 1, "sql": "DROP TABLE"}),
    lambda x: x.update(arguments={"query": "hi", "top_k": 0}),
    lambda x: x.update(expected_information="x" * 513),
    lambda x: x.update(schema="anima.cognition.step_proposal/99"),
    lambda x: x.update(operation_kind="lookup_raw_evidence", arguments={"event_ids": ["ev1"] * 17}),
    lambda x: x.update(operation_kind="lookup_raw_evidence", arguments={"event_ids": ["ev1", "ev1"]}),
    lambda x: x.update(operation_kind="inspect_goal_status", arguments={"goal_id": "../../tmp"}),
    lambda x: x.update(operation_kind="inspect_current_belief", arguments={"subject_ref": "a", "predicate_ref": None}),
])
def test_reject_forged_invalid_or_unbounded_requests(change):
    x = proposal()
    change(x)
    with pytest.raises(CognitiveProposalError):
        CognitiveStepProposal(x)


def test_registered_read_only_proposals_are_validated_but_never_executed():
    examples = [
        ("lookup_raw_evidence", {"event_ids": ["ev1", "ev2"]}),
        ("inspect_current_belief", {"subject_ref": "lab.item.crate", "predicate_ref": "owner"}),
        ("inspect_goal_status", {"goal_id": "goal1"}),
    ]
    for kind, arguments in examples:
        x = proposal()
        x["operation_kind"] = kind
        x["arguments"] = arguments
        assert CognitiveStepProposal(x).as_dict()["operation_kind"] == kind
