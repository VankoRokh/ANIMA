import json
from pathlib import Path
from uuid import uuid4

import pytest

from anima.agent import (
    AgentLoop,
    AgentStore,
    DeterministicGoalVerifier,
    GoalVerificationBridge,
    LLMCallResult,
    LLMPlanner,
    LLMPlannerError,
    LLMTransport,
    PlannerRequest,
    ProposalChoiceCoordinator,
    SandboxExecutor,
    ToolInputError,
    VerificationSpec,
    build_llm_planner_prompts,
    build_sandbox_registry,
)
from anima.agent.verification import (
    DETERMINISTIC_VERIFIER_NAME,
    DETERMINISTIC_VERIFIER_VERSION,
    FILE_CONTENT_EQUALS,
)
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore


class FakeTransport(LLMTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "timeout_seconds": timeout_seconds,
            }
        )
        if not self.responses:
            raise AssertionError("FakeTransport has no response left")
        response = self.responses.pop(0)
        if isinstance(response, dict):
            response = json.dumps(response, ensure_ascii=False)
        return LLMCallResult(
            provider="fake",
            model="fake-model",
            text=response,
            latency_ms=12.5,
            input_tokens=100,
            output_tokens=25,
            estimated_cost_usd=0.001,
            finish_reason="stop",
        )


def _decision(tool="fs.read", arguments=None, *, extra_proposal=None):
    proposal = {
        "tool": tool,
        "tool_version": "1",
        "arguments": arguments or {"path": "result.txt"},
        "expected_observation": "factual sandbox observation",
        "rationale_summary": "obtain evidence for the next decision",
    }
    if extra_proposal:
        proposal.update(extra_proposal)
    return {
        "status": "proposals_available",
        "proposals": [proposal],
        "plan_summary": "one bounded next action",
    }


def _request():
    registry = build_sandbox_registry()
    return PlannerRequest(
        run_id=f"ar_{uuid4()}",
        step_id=f"ast_{uuid4()}",
        goal_id=f"goal_{uuid4()}",
        goal_description="write 42 to result.txt and verify it",
        success_criterion="result.txt content equals 42",
        context={"known_fact": "sandbox task"},
        tools=registry.list_descriptors(),
        recent_steps=(),
        recent_observations=(),
        constraints={"one_action_per_turn": True},
        remaining_budget={"steps": 4},
    )


def test_llm_planner_returns_normal_planner_turn_and_records_only_call_metadata():
    transport = FakeTransport([_decision()])
    planner = LLMPlanner(transport)
    request = _request()

    turn = planner.plan(request)

    assert turn.status == "proposals_available"
    assert len(turn.proposals) == 1
    proposal = turn.proposals[0]
    assert proposal.tool == "fs.read"
    assert proposal.to_dict()["arguments"] == {"path": "result.txt"}
    assert transport.calls[0]["timeout_seconds"] == 60.0

    call = planner.last_call
    assert call.provider == "fake"
    assert call.model == "fake-model"
    assert call.input_tokens == 100
    assert call.output_tokens == 25
    assert call.total_tokens == 125
    assert call.estimated_cost_usd == pytest.approx(0.001)
    record = call.to_dict()
    assert "text" not in record
    assert "prompt" not in record
    assert len(record["prompt_hash"]) == 64
    assert len(record["response_hash"]) == 64


def test_llm_prompt_contains_only_planner_request_contract_and_tool_metadata():
    request = _request()
    system_prompt, user_prompt = build_llm_planner_prompts(request)
    document = json.loads(user_prompt)

    assert "execute tools" not in system_prompt.lower()
    assert set(document) == {"response_contract", "planner_request"}
    planner_request = document["planner_request"]
    assert set(planner_request) == {
        "run_id",
        "step_id",
        "goal_id",
        "goal_description",
        "success_criterion",
        "context",
        "tools",
        "recent_steps",
        "recent_observations",
        "constraints",
        "remaining_budget",
    }
    assert "internal_state" not in planner_request
    assert "executor" not in planner_request
    assert "goal_store" not in planner_request
    assert planner_request["tools"]
    descriptor = planner_request["tools"][0]
    assert "effect_class" in descriptor
    assert "idempotency" in descriptor
    assert "effort_hint" in descriptor


@pytest.mark.parametrize(
    ("response", "match"),
    [
        ("```json\n{}\n```", "Markdown fences"),
        ("not json", "not valid JSON"),
        (
            {
                **_decision(),
                "goal_completed": True,
            },
            "fields mismatch",
        ),
        (
            _decision(extra_proposal={"risk": 0}),
            "fields mismatch",
        ),
    ],
)
def test_llm_planner_rejects_untrusted_or_non_contract_output(response, match):
    planner = LLMPlanner(FakeTransport([response]))

    with pytest.raises(LLMPlannerError, match=match):
        planner.plan(_request())


def test_llm_planner_rejects_unknown_tool_before_choice_or_execution():
    planner = LLMPlanner(
        FakeTransport([_decision(tool="shell.exec", arguments={})])
    )

    with pytest.raises(ValueError, match="unavailable tool"):
        planner.plan(_request())


def test_llm_planner_rejects_invalid_tool_arguments_before_choice_or_execution():
    planner = LLMPlanner(
        FakeTransport([_decision(arguments={"path": "result.txt", "extra": True})])
    )

    with pytest.raises(ToolInputError, match="unexpected property"):
        planner.plan(_request())


def test_llm_planner_accepts_explicit_cannot_progress_without_proposals():
    planner = LLMPlanner(
        FakeTransport(
            [
                {
                    "status": "cannot_progress",
                    "proposals": [],
                    "plan_summary": "no allowed tool can provide the missing evidence",
                }
            ]
        )
    )

    turn = planner.plan(_request())

    assert turn.status == "cannot_progress"
    assert turn.proposals == ()


def _build_loop(tmp_path, responses):
    data_dir = Path(tmp_path)
    sandbox = data_dir / "sandbox"
    sandbox.mkdir()
    agent_store = AgentStore(data_dir / "agent.db")
    internal_store = InternalStateStore(data_dir / "internal_state.db")
    internal = InternalStateRuntime(internal_store)
    registry = build_sandbox_registry()
    transport = FakeTransport(responses)
    planner = LLMPlanner(transport, name="llm-test", version="1")
    choice = ProposalChoiceCoordinator(
        registry=registry,
        choice_engine=internal.choice_engine,
    )
    executor = SandboxExecutor(
        root=sandbox,
        registry=registry,
        store=agent_store,
    )
    verifier = DeterministicGoalVerifier()
    bridge = GoalVerificationBridge(
        agent_store=agent_store,
        recovery=internal.recovery,
    )
    loop = AgentLoop(
        store=agent_store,
        registry=registry,
        planner=planner,
        choice=choice,
        executor=executor,
        verifier=verifier,
        verification_bridge=bridge,
    )
    goal = internal.create_goal(
        source="test",
        priority=1.0,
        description="write 42 to result.txt and verify it",
        success_criterion="result.txt content equals 42",
        reason="Stage 4.12 LLM planner contract test",
    )
    run = loop.start_run(goal["id"])
    spec = VerificationSpec.create(
        run_id=run["id"],
        verifier=DETERMINISTIC_VERIFIER_NAME,
        verifier_version=DETERMINISTIC_VERIFIER_VERSION,
        criterion_kind=FILE_CONTENT_EQUALS,
        parameters={"path": "result.txt", "expected": "42"},
    )
    return sandbox, planner, loop, run, spec


def test_llm_planner_uses_same_agent_contract_for_failure_replan_write_and_readback(tmp_path):
    responses = [
        _decision(
            tool="fs.read",
            arguments={"path": "missing-input.txt"},
        ),
        _decision(
            tool="fs.write",
            arguments={"path": "result.txt", "content": "42"},
        ),
        _decision(
            tool="fs.read",
            arguments={"path": "result.txt"},
        ),
    ]
    sandbox, planner, loop, run, spec = _build_loop(tmp_path, responses)

    result = loop.run(run["id"], spec, max_steps=5)

    assert result.completed is True
    assert result.stop_reason == "goal_completed"
    assert (sandbox / "result.txt").read_text(encoding="utf-8") == "42"
    assert [turn.action.tool for turn in result.turns] == [
        "fs.read",
        "fs.write",
        "fs.read",
    ]
    assert [turn.receipt.status for turn in result.turns] == [
        "failed",
        "succeeded",
        "succeeded",
    ]
    assert [turn.verification_result.outcome for turn in result.turns] == [
        "none",
        "none",
        "success",
    ]
    assert len(planner.call_history) == 3
    second_request = json.loads(planner.transport.calls[1]["user_prompt"])[
        "planner_request"
    ]
    assert second_request["recent_observations"][-1]["kind"] == "file.unavailable"
    third_request = json.loads(planner.transport.calls[2]["user_prompt"])[
        "planner_request"
    ]
    assert third_request["recent_observations"][-1]["kind"] == "file.write"
