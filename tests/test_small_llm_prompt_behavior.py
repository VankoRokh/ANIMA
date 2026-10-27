import json
from uuid import uuid4

from anima.agent.executor import build_sandbox_registry
from anima.agent.planner import PlannerRequest
from anima.agent.small_llm import SmallLLMPromptProfile


def _request():
    return PlannerRequest(
        run_id=f"ar_{uuid4()}",
        step_id=f"ast_{uuid4()}",
        goal_id=f"goal_{uuid4()}",
        goal_description=(
            "Create result.txt containing exactly 42, then verify it by readback."
        ),
        success_criterion="result.txt content equals 42",
        context={},
        tools=build_sandbox_registry().list_descriptors(),
        recent_steps=(),
        recent_observations=(),
        constraints={"one_action_per_turn": True},
        remaining_budget={"steps": 6},
    )


def test_small_prompt_contract_describes_arguments_without_empty_object_example():
    system_prompt, user_prompt, metrics = SmallLLMPromptProfile().build(_request())
    payload = json.loads(user_prompt)
    contract = payload["response_contract"]

    assert "proposals" not in contract
    assert contract["proposal_fields"] == [
        "tool",
        "tool_version",
        "arguments",
        "expected_observation",
        "rationale_summary",
    ]
    assert "required arguments" in contract["arguments_rule"]
    assert "empty arguments object" in contract["arguments_rule"]
    assert "Do not repeat a successful read/list action" in system_prompt
    assert "required action argument or precondition" in system_prompt
    assert metrics.total_chars <= 4_800
