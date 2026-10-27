import json
from uuid import uuid4

from anima.agent.executor import build_sandbox_registry
from anima.agent.llm_planner import LLMCallResult, LLMTransport
from anima.agent.planner import PlannerRequest
from anima.agent.small_llm import (
    SmallModelLLMPlanner,
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


def _variant(schema, tool_name):
    variants = schema["properties"]["proposals"]["items"]["oneOf"]
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
    assert transport.response_schema is not None
    write = _variant(transport.response_schema, "fs.write")
    assert write["properties"]["arguments"]["required"] == ["path", "content"]
