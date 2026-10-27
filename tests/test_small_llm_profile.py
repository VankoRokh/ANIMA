import json
from uuid import uuid4

import pytest

from anima.agent.llm_planner import LLMCallResult, LLMTransport, build_llm_planner_prompts
from anima.agent.planner import PlannerRequest
from anima.agent.executor import build_sandbox_registry
from anima.agent.small_llm import (
    SMALL_LLM_MAX_OUTPUT_TOKENS,
    SMALL_LLM_MAX_PROMPT_CHARS,
    SmallLLMPromptBudgetError,
    SmallLLMPromptProfile,
    SmallModelLLMPlanner,
    SmallModelOpenAICompatibleChatTransport,
)


class FakeTransport(LLMTransport):
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "timeout_seconds": timeout_seconds,
            }
        )
        return LLMCallResult(
            provider="fake",
            model="small-fake",
            text=json.dumps(self.response, ensure_ascii=False),
            latency_ms=1.0,
            input_tokens=300,
            output_tokens=40,
            finish_reason="stop",
        )


def _step(receipt, verification):
    return {
        "step_id": f"ast_{uuid4()}",
        "planner_turn_id": f"pt_{uuid4()}",
        "planner_status": "proposals_available",
        "selected_proposal_id": f"ap_{uuid4()}",
        "action_id": f"act_{uuid4()}",
        "receipt_status": receipt,
        "observation_id": f"obs_{uuid4()}",
        "verification_outcome": verification,
    }


def _observation(kind, data):
    return {
        "id": f"obs_{uuid4()}",
        "action_id": f"act_{uuid4()}",
        "receipt_id": f"er_{uuid4()}",
        "source": "sandbox_executor",
        "kind": kind,
        "data": data,
        "observed_at": "2026-10-28T00:00:00+00:00",
    }


def _request(*, context=None, steps=(), observations=()):
    return PlannerRequest(
        run_id=f"ar_{uuid4()}",
        step_id=f"ast_{uuid4()}",
        goal_id=f"goal_{uuid4()}",
        goal_description="Create result.txt containing exactly 42 and verify it by readback.",
        success_criterion="result.txt content equals 42",
        context=context or {},
        tools=build_sandbox_registry().list_descriptors(),
        recent_steps=tuple(steps),
        recent_observations=tuple(observations),
        constraints={"one_action_per_turn": True},
        remaining_budget={"steps": 3},
    )


def test_small_profile_is_additive_and_keeps_canonical_request_unchanged():
    request = _request()
    original = request.to_dict()

    system_prompt, user_prompt, metrics = SmallLLMPromptProfile().build(request)

    assert request.to_dict() == original
    assert metrics.total_chars <= SMALL_LLM_MAX_PROMPT_CHARS
    assert metrics.tool_count == 3
    assert "run_id" not in user_prompt
    assert "step_id" not in user_prompt
    assert "goal_id" not in user_prompt
    assert "input_schema" not in user_prompt
    assert "output_schema" not in user_prompt
    assert "effect_class" not in user_prompt
    assert "idempotency" not in user_prompt
    assert "one JSON object" in system_prompt


def test_small_profile_is_materially_smaller_than_full_llm_prompt():
    request = _request(
        steps=(_step("failed", "none"), _step("succeeded", "none")),
        observations=(
            _observation(
                "file.unavailable",
                {"path": "missing-input.txt", "error_code": "NOT_FOUND", "message": "missing"},
            ),
            _observation(
                "file.write",
                {"path": "result.txt", "bytes_written": 2, "sha256": "a" * 64},
            ),
        ),
    )
    full_system, full_user = build_llm_planner_prompts(request)
    _, compact_user, metrics = SmallLLMPromptProfile().build(request)

    full_chars = len(full_system) + 1 + len(full_user)
    assert metrics.total_chars < full_chars
    assert metrics.total_chars <= SMALL_LLM_MAX_PROMPT_CHARS
    compact = json.loads(compact_user)
    assert set(compact["recent_steps"][-1]) == {
        "planner_status",
        "receipt_status",
        "verification_outcome",
    }
    assert set(compact["recent_observations"][-1]) == {"kind", "data"}


def test_small_profile_bounds_large_context_and_raw_observation_content():
    request = _request(
        context={"memory": "m" * 20_000},
        observations=(
            _observation(
                "file.content",
                {"path": "large.txt", "content": "x" * 20_000, "bytes": 20_000},
            ),
        ),
    )

    _, user_prompt, metrics = SmallLLMPromptProfile().build(request)
    payload = json.loads(user_prompt)

    assert metrics.total_chars <= SMALL_LLM_MAX_PROMPT_CHARS
    assert len(payload["context"]["memory"]) < 300
    content = payload["recent_observations"][-1]["data"]["content"]
    assert len(content) <= 384
    assert content.endswith("…[truncated]")


def test_small_profile_keeps_only_recent_history():
    steps = tuple(_step("succeeded", "none") for _ in range(8))
    observations = tuple(
        _observation("file.write", {"path": f"file-{index}.txt"})
        for index in range(8)
    )
    request = _request(steps=steps, observations=observations)

    _, user_prompt, metrics = SmallLLMPromptProfile().build(request)
    payload = json.loads(user_prompt)

    assert metrics.recent_steps <= 3
    assert metrics.recent_observations <= 3
    assert len(payload["recent_steps"]) == metrics.recent_steps
    assert len(payload["recent_observations"]) == metrics.recent_observations
    assert payload["recent_observations"][-1]["data"]["path"] == "file-7.txt"


def test_small_profile_refuses_excessive_tool_set_instead_of_silently_hiding_tools():
    request = _request()
    profile = SmallLLMPromptProfile(max_tools=2)

    with pytest.raises(SmallLLMPromptBudgetError, match="at most 2 tools"):
        profile.build(request)


def test_small_model_planner_uses_compact_projection_and_tracks_prompt_metrics():
    response = {
        "status": "proposals_available",
        "proposals": [
            {
                "tool": "fs.read",
                "tool_version": "1",
                "arguments": {"path": "result.txt"},
                "expected_observation": "file content",
                "rationale_summary": "verify result",
            }
        ],
        "plan_summary": "verify by readback",
    }
    transport = FakeTransport(response)
    planner = SmallModelLLMPlanner(transport)

    turn = planner.plan(_request())

    assert turn.status == "proposals_available"
    assert turn.proposals[0].tool == "fs.read"
    assert len(planner.call_history) == 1
    assert len(planner.prompt_metrics) == 1
    assert planner.prompt_metrics[0].total_chars <= SMALL_LLM_MAX_PROMPT_CHARS
    sent = transport.calls[0]["user_prompt"]
    assert "input_schema" not in sent
    assert "run_id" not in sent


def test_small_transport_sends_explicit_completion_budget(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "status": "cannot_progress",
                                        "proposals": [],
                                        "plan_summary": "no action",
                                    }
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 200, "completion_tokens": 20},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("anima.agent.small_llm.urllib.request.urlopen", fake_urlopen)
    transport = SmallModelOpenAICompatibleChatTransport(
        base_url="http://127.0.0.1:1234/v1",
        model="small-model",
        max_output_tokens=SMALL_LLM_MAX_OUTPUT_TOKENS,
    )

    result = transport.complete(
        system_prompt="system",
        user_prompt="{}",
        timeout_seconds=10,
    )

    assert result.output_tokens == 20
    assert captured["payload"]["temperature"] == 0
    assert captured["payload"]["max_tokens"] == SMALL_LLM_MAX_OUTPUT_TOKENS
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_canonical_three_turn_profile_stays_within_character_budget():
    profile = SmallLLMPromptProfile()
    scenarios = [
        _request(),
        _request(
            steps=(_step("failed", "none"),),
            observations=(
                _observation(
                    "file.unavailable",
                    {"path": "missing-input.txt", "error_code": "NOT_FOUND", "message": "missing"},
                ),
            ),
        ),
        _request(
            steps=(
                _step("failed", "none"),
                _step("succeeded", "none"),
            ),
            observations=(
                _observation(
                    "file.unavailable",
                    {"path": "missing-input.txt", "error_code": "NOT_FOUND", "message": "missing"},
                ),
                _observation(
                    "file.write",
                    {"path": "result.txt", "bytes_written": 2, "sha256": "a" * 64},
                ),
            ),
        ),
    ]

    metrics = [profile.build(request)[2] for request in scenarios]

    assert all(item.total_chars <= SMALL_LLM_MAX_PROMPT_CHARS for item in metrics)
    assert metrics[-1].recent_observations == 2
