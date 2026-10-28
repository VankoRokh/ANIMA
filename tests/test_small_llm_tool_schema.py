import json
from uuid import uuid4

import pytest

from anima.agent.tools import ToolInputError

from anima.agent.executor import build_sandbox_registry
from anima.agent.llm_planner import (
    LLMCallResult,
    LLMPlannerError,
    LLMTransport,
    parse_llm_planner_decision,
)
from anima.agent.planner import PlannerRequest
from anima.agent.small_llm import (
    SmallModelLLMPlanner,
    SmallLLMPromptProfile,
    build_small_llm_response_schema,
)


class StructuredFakeTransport(LLMTransport):
    def __init__(self):
        self.response_schema = None

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        raise AssertionError("structured Planner path should be used")

    def complete_structured(
        self,
        *,
        system_prompt,
        user_prompt,
        timeout_seconds,
        response_schema,
    ):
        del system_prompt, user_prompt, timeout_seconds
        self.response_schema = response_schema
        return LLMCallResult(
            provider="fake-structured",
            model="small-fake",
            text=json.dumps(
                {
                    "status": "proposals_available",
                    "proposals": [
                        {
                            "tool": "fs.write",
                            "tool_version": "1",
                            "arguments": {"path": "result.txt", "content": "42"},
                            "expected_observation": "result.txt written",
                            "rationale_summary": "create requested file",
                        }
                    ],
                    "plan_summary": "write result",
                }
            ),
            latency_ms=1.0,
            input_tokens=100,
            output_tokens=30,
            finish_reason="stop",
        )


def _request():
    return PlannerRequest(
        run_id=f"ar_{uuid4()}",
        step_id=f"ast_{uuid4()}",
        goal_id=f"goal_{uuid4()}",
        goal_description="Create result.txt containing exactly 42.",
        success_criterion="result.txt content equals 42",
        context={},
        tools=build_sandbox_registry().list_descriptors(),
        recent_steps=(),
        recent_observations=(),
        constraints={"one_action_per_turn": True},
        remaining_budget={"steps": 3},
    )


def _branch(schema, status):
    return next(
        item for item in schema["oneOf"]
        if item["properties"]["status"]["const"] == status
    )


def _variant(schema, tool_name):
    available = _branch(schema, "proposals_available")
    variants = available["properties"]["proposals"]["items"]["oneOf"]
    return next(
        item for item in variants
        if item["properties"]["tool"]["const"] == tool_name
    )


def test_small_model_response_schema_binds_arguments_to_selected_tool():
    request = _request()
    schema = build_small_llm_response_schema(request.tools)

    write = _variant(schema, "fs.write")
    read = _variant(schema, "fs.read")
    listing = _variant(schema, "fs.list")

    assert write["properties"]["tool_version"] == {"const": "1"}
    assert write["properties"]["arguments"]["required"] == ["path", "content"]
    assert set(write["properties"]["arguments"]["properties"]) == {"path", "content"}
    assert read["properties"]["arguments"]["required"] == ["path"]
    assert listing["properties"]["arguments"]["required"] == []


def test_small_model_planner_passes_tool_aware_schema_to_capable_transport():
    transport = StructuredFakeTransport()
    planner = SmallModelLLMPlanner(transport)

    turn = planner.plan(_request())

    assert turn.proposals[0].arguments == {"path": "result.txt", "content": "42"}
    assert transport.response_schema == build_small_llm_response_schema(_request().tools)
    write = _variant(transport.response_schema, "fs.write")
    assert write["properties"]["arguments"]["required"] == ["path", "content"]


@pytest.mark.parametrize("tool", ["fs.list", "fs.read", "fs.write"])
def test_authoritative_path_pattern_and_dynamic_schema_remain_enforced(tool):
    registry = build_sandbox_registry()
    descriptor = registry.get(tool, "1")
    path = descriptor.to_dict()["input_schema"]["properties"]["path"]
    assert path["pattern"] == r"^[^/].*$"
    schema = build_small_llm_response_schema(registry.list_descriptors())
    arguments = _variant(schema, tool)["properties"]["arguments"]
    assert arguments["properties"]["path"] == path
    values = {"path": "/outside.txt"}
    if tool == "fs.write":
        values["content"] = "payload"
    with pytest.raises(ToolInputError, match="does not match pattern"):
        descriptor.validate_input(values)


@pytest.mark.parametrize("tool", ["fs.list", "fs.read", "fs.write"])
def test_compact_tool_metadata_keeps_authoritative_path_guidance(tool):
    request = _request()
    _, user_prompt, _ = SmallLLMPromptProfile().build(request)
    metadata = next(item for item in json.loads(user_prompt)["tools"] if item["tool"] == tool)
    path = next(item for item in metadata["arguments"] if item["name"] == "path")
    authoritative = request.tool_descriptor(tool, "1").to_dict()["input_schema"]["properties"]["path"]
    assert path["pattern"] == authoritative["pattern"] == r"^[^/].*$"
    assert path["description"] == authoritative["description"]
    assert "Sandbox-relative path" in path["description"]
    assert "Never prefix" in path["description"]


def test_small_model_schema_discriminates_status_and_proposal_cardinality():
    tools = build_sandbox_registry().list_descriptors()
    schema = build_small_llm_response_schema(iter(tools))
    assert set(schema) == {"oneOf"}
    assert len(schema["oneOf"]) == 2
    available = _branch(schema, "proposals_available")
    cannot = _branch(schema, "cannot_progress")
    for branch in (available, cannot):
        assert branch["type"] == "object"
        assert set(branch["properties"]) == {"status", "proposals", "plan_summary"}
        assert branch["required"] == ["status", "proposals", "plan_summary"]
        assert branch["additionalProperties"] is False
        assert branch["properties"]["plan_summary"] == {"type": "string"}
    proposals = available["properties"]["proposals"]
    assert proposals["type"] == "array"
    assert proposals["minItems"] == 1
    assert proposals["maxItems"] == 3
    assert len(proposals["items"]["oneOf"]) == len(tools)
    for tool in tools:
        proposal = _variant(schema, tool.name)
        assert proposal["additionalProperties"] is False
        assert proposal["properties"]["arguments"] == tool.to_dict()["input_schema"]
        assert proposal["properties"]["expected_observation"] == {"type": "string"}
        assert proposal["properties"]["rationale_summary"] == {"type": "string"}
    assert cannot["properties"]["proposals"] == {
        "type": "array", "minItems": 0, "maxItems": 0,
        "items": {"type": "object"},
    }


def test_small_model_schema_with_no_tools_only_exposes_cannot_progress():
    schema = build_small_llm_response_schema(iter(()))
    assert len(schema["oneOf"]) == 1
    branch = _branch(schema, "cannot_progress")
    assert branch["properties"]["proposals"]["maxItems"] == 0
    assert branch["additionalProperties"] is False
    assert branch["required"] == ["status", "proposals", "plan_summary"]
    assert branch["properties"]["plan_summary"] == {"type": "string"}


@pytest.mark.parametrize("status, count, message", [
    ("proposals_available", 0, "requires at least one proposal"),
    ("cannot_progress", 1, "cannot contain proposals"),
])
def test_python_planner_validation_independently_rejects_contradictions(status, count, message):
    proposal = {
        "tool": "fs.read", "tool_version": "1", "arguments": {"path": "answer.txt"},
        "expected_observation": "file content", "rationale_summary": "check content",
    }
    response = json.dumps({
        "status": status, "proposals": [proposal] * count, "plan_summary": "next action",
    })
    with pytest.raises(LLMPlannerError, match=message):
        parse_llm_planner_decision(response)
