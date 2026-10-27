from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from anima.agent import (
    DeterministicPlanner,
    PlannerDecision,
    PlannerRequest,
    PlannerTurn,
    ProposalDraft,
    ToolDescriptor,
    ToolInputError,
    planner_request_hash,
)


NOW = "2026-10-27T20:00:00+00:00"


def _id(prefix):
    return f"{prefix}{uuid4()}"


def _read_descriptor():
    return ToolDescriptor(
        name="fs.read",
        version="1",
        description="Read one sandbox file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
        effect_class="read_only",
        idempotency="repeat_safe",
        effort_hint="cheap",
        sandbox_scope=("workspace",),
    )


def _list_descriptor():
    return ToolDescriptor(
        name="fs.list",
        version="1",
        description="List sandbox directory",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["entries"],
            "additionalProperties": False,
        },
        effect_class="read_only",
        idempotency="repeat_safe",
        effort_hint="cheap",
        sandbox_scope=("workspace",),
    )


def _request(**overrides):
    values = {
        "run_id": _id("ar_"),
        "step_id": _id("ast_"),
        "goal_id": _id("goal_"),
        "goal_description": "Find the value in the sandbox",
        "success_criterion": "The required value has been observed",
        "context": {"knowledge": [], "memories": []},
        "tools": (_read_descriptor(), _list_descriptor()),
        "recent_steps": ({"sequence": 0, "status": "planning"},),
        "recent_observations": (),
        "constraints": {"max_tool_calls": 4},
        "remaining_budget": {"tool_calls": 4},
    }
    values.update(overrides)
    return PlannerRequest(**values)


def _read_decision(_request_value):
    return PlannerDecision(
        status="proposals_available",
        proposals=(
            ProposalDraft(
                tool="fs.read",
                tool_version="1",
                arguments={"path": "data.txt"},
                expected_observation="file content is returned",
                rationale_summary="read the most likely input file",
            ),
            ProposalDraft(
                tool="fs.list",
                tool_version="1",
                arguments={"path": "."},
                expected_observation="directory entries are returned",
                rationale_summary="inspect available files as an alternative",
            ),
        ),
        plan_summary="Try the likely file first and keep an information-gathering alternative.",
    )


def test_planner_request_is_immutable_bounded_snapshot_and_round_trips():
    context = {"knowledge": [{"id": "kn_test"}]}
    request = _request(context=context)
    context["knowledge"].append({"id": "mutated"})

    assert request.context["knowledge"][0]["id"] == "kn_test"
    assert len(request.context["knowledge"]) == 1
    with pytest.raises(TypeError):
        request.context["other"] = True
    with pytest.raises(FrozenInstanceError):
        request.goal_description = "mutated"

    record = request.to_dict()
    assert "internal_state" not in record
    restored = PlannerRequest.from_dict(record)
    assert restored.to_dict() == record
    assert planner_request_hash(restored) == planner_request_hash(request)


def test_planner_request_rejects_internal_state_or_other_unknown_fields():
    record = _request().to_dict()
    record["internal_state"] = {"fatigue": 1.0}

    with pytest.raises(ValueError, match="fields mismatch"):
        PlannerRequest.from_dict(record)


def test_planner_request_rejects_duplicate_tool_versions():
    descriptor = _read_descriptor()
    with pytest.raises(ValueError, match="duplicate tool versions"):
        _request(tools=(descriptor, descriptor))


def test_planner_request_tool_lookup_is_explicit():
    request = _request()
    assert request.tool_descriptor("fs.read", "1").name == "fs.read"

    with pytest.raises(ValueError, match="unavailable tool"):
        request.tool_descriptor("fs.write", "1")


def test_planner_decision_enforces_status_and_proposal_bound():
    draft = ProposalDraft(
        tool="fs.read",
        tool_version="1",
        arguments={"path": "data.txt"},
        expected_observation="content",
        rationale_summary="read",
    )

    with pytest.raises(ValueError, match="requires at least one"):
        PlannerDecision(status="proposals_available")
    with pytest.raises(ValueError, match="cannot contain proposals"):
        PlannerDecision(status="cannot_progress", proposals=(draft,))
    with pytest.raises(ValueError, match="max proposals"):
        PlannerDecision(
            status="proposals_available",
            proposals=(draft, draft, draft, draft),
        )


def test_deterministic_planner_returns_ranked_validated_proposals():
    request = _request()
    planner = DeterministicPlanner(_read_decision, name="baseline", version="1")

    turn = planner.plan(
        request,
        turn_id=_id("pt_"),
        created_at=NOW,
    )

    assert turn.status == "proposals_available"
    assert turn.planner_name == "baseline"
    assert turn.planner_version == "1"
    assert turn.run_id == request.run_id
    assert turn.step_id == request.step_id
    assert turn.request_hash == planner_request_hash(request)
    assert [proposal.rank for proposal in turn.proposals] == [1, 2]
    assert [proposal.tool for proposal in turn.proposals] == ["fs.read", "fs.list"]
    assert all(turn.owns_proposal(proposal.public_id) for proposal in turn.proposals)
    assert PlannerTurn.from_dict(turn.to_dict()).to_dict() == turn.to_dict()


def test_deterministic_planner_same_request_has_same_semantics():
    request = _request()
    planner = DeterministicPlanner(_read_decision)

    first = planner.plan(request, created_at=NOW)
    second = planner.plan(request, created_at=NOW)

    assert first.request_hash == second.request_hash
    first_semantics = [
        {
            "rank": proposal.rank,
            "tool": proposal.tool,
            "tool_version": proposal.tool_version,
            "arguments": dict(proposal.arguments),
            "expected_observation": proposal.expected_observation,
            "rationale_summary": proposal.rationale_summary,
        }
        for proposal in first.proposals
    ]
    second_semantics = [
        {
            "rank": proposal.rank,
            "tool": proposal.tool,
            "tool_version": proposal.tool_version,
            "arguments": dict(proposal.arguments),
            "expected_observation": proposal.expected_observation,
            "rationale_summary": proposal.rationale_summary,
        }
        for proposal in second.proposals
    ]
    assert first_semantics == second_semantics


def test_planner_adapter_rejects_unknown_tool_proposal():
    def strategy(_request_value):
        return PlannerDecision(
            status="proposals_available",
            proposals=(
                ProposalDraft(
                    tool="fs.write",
                    tool_version="1",
                    arguments={"path": "x", "content": "y"},
                    expected_observation="write output",
                    rationale_summary="write",
                ),
            ),
        )

    with pytest.raises(ValueError, match="unavailable tool"):
        DeterministicPlanner(strategy).plan(_request())


def test_planner_adapter_rejects_arguments_outside_system_tool_schema():
    def strategy(_request_value):
        return PlannerDecision(
            status="proposals_available",
            proposals=(
                ProposalDraft(
                    tool="fs.read",
                    tool_version="1",
                    arguments={"path": "data.txt", "unsafe": True},
                    expected_observation="content",
                    rationale_summary="read",
                ),
            ),
        )

    with pytest.raises(ToolInputError, match="unexpected property"):
        DeterministicPlanner(strategy).plan(_request())


def test_cannot_progress_turn_contains_no_action_proposals():
    def strategy(_request_value):
        return PlannerDecision(
            status="cannot_progress",
            proposals=(),
            plan_summary="No permitted action can produce new evidence.",
        )

    turn = DeterministicPlanner(strategy).plan(
        _request(),
        turn_id=_id("pt_"),
        created_at=NOW,
    )

    assert turn.status == "cannot_progress"
    assert turn.proposals == ()
    assert turn.plan_summary == "No permitted action can produce new evidence."


def test_planner_strategy_receives_no_execution_or_internal_state_handles():
    observed = {}

    def strategy(request):
        observed["has_store"] = hasattr(request, "store")
        observed["has_executor"] = hasattr(request, "executor")
        observed["has_internal_state"] = hasattr(request, "internal_state")
        return PlannerDecision(status="cannot_progress")

    DeterministicPlanner(strategy).plan(_request())

    assert observed == {
        "has_store": False,
        "has_executor": False,
        "has_internal_state": False,
    }


def test_planner_rejects_strategy_returning_arbitrary_object():
    planner = DeterministicPlanner(lambda request: {"status": "cannot_progress"})

    with pytest.raises(TypeError, match="PlannerDecision"):
        planner.plan(_request())


def test_planner_request_bounds_recent_history():
    too_many = tuple({"sequence": index} for index in range(17))

    with pytest.raises(ValueError, match="recent_steps exceeds limit"):
        _request(recent_steps=too_many)
