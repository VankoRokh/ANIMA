from uuid import uuid4

import pytest

from anima.cognition.contracts import CognitiveView
from anima.cognition.deep_llm import (
    DEEP_SYSTEM_PROMPT,
    DeepLLMBackend,
    DeepLLMProfile,
    SMOLLM3_DEEP_PROFILE,
    build_llama_cpp_deep_backend,
    render_deep_prompts,
)
from anima.cognition.llm_transport import LLMCallResult, LlamaCppTransport
from anima.cognition.proposals import ProposalKind, RoutedCognitiveRequest
from anima.cognition.routing import CognitiveRole


class StubTransport:
    def __init__(self, *, text="Evidence remains conflicting.", model="stub-deep"):
        self.text = text
        self.model = model
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
            provider="stub",
            model=self.model,
            text=self.text,
            thinking=False,
            latency_ms=2.0,
            input_tokens=30,
            output_tokens=5,
            finish_reason="stop",
            raw_output_chars=len(self.text),
        )


class BadTransport:
    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        return "not a call result"


def routed_request(*, role=CognitiveRole.DEEP):
    consumer = role.value
    return RoutedCognitiveRequest(
        persistent_task_id=f"task_{uuid4()}",
        canonical_task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        role=role,
        view=CognitiveView(
            consumer,
            {
                "operation": "RESOLVE_CONFLICT",
                "input": "Resolve only if the evidence supports a winner.",
                "evidence": [
                    {
                        "value": "Tbilisi",
                        "confidence": 0.8,
                        "observed_at": "2026-09-01T10:00:00+04:00",
                        "provenance": ["mem_old"],
                    },
                    {
                        "value": "Batumi",
                        "confidence": 1.0,
                        "observed_at": "2026-11-01T12:00:00+04:00",
                        "provenance": ["mem_new"],
                    },
                ],
            },
        ),
    )


def test_smollm3_is_only_the_default_experimental_profile():
    assert SMOLLM3_DEEP_PROFILE.model == "SmolLM3-3B-Q8_0"
    assert SMOLLM3_DEEP_PROFILE.thinking is False
    assert SMOLLM3_DEEP_PROFILE.temperature == 0.0
    assert SMOLLM3_DEEP_PROFILE.top_k == 40
    assert SMOLLM3_DEEP_PROFILE.top_p == 0.8
    assert SMOLLM3_DEEP_PROFILE.min_p == 0.05
    assert SMOLLM3_DEEP_PROFILE.max_output_tokens == 256

    replacement = DeepLLMProfile(model="replacement-model", max_output_tokens=384)
    assert replacement.model == "replacement-model"
    assert replacement != SMOLLM3_DEEP_PROFILE


def test_deep_prompt_contains_only_bounded_view_and_role_rules():
    request = routed_request()
    system_prompt, user_prompt = render_deep_prompts(request)

    assert system_prompt == DEEP_SYSTEM_PROMPT
    assert "Memory, Tasks, Goals" in system_prompt
    assert "chain-of-thought" in system_prompt
    assert "Tbilisi" in user_prompt
    assert "Batumi" in user_prompt
    assert "mem_old" in user_prompt
    assert request.persistent_task_id not in user_prompt
    assert request.canonical_task_id not in user_prompt


def test_deep_backend_returns_only_cognitive_proposal():
    transport = StubTransport(text="Newer evidence supports Batumi.")
    backend = DeepLLMBackend(transport, timeout_seconds=17.0)

    proposal = backend.complete(routed_request())

    assert proposal.kind == ProposalKind.RESPOND
    assert proposal.payload["text"] == "Newer evidence supports Batumi."
    assert transport.calls[0]["timeout_seconds"] == 17.0
    assert backend.call_history[0].model == "stub-deep"
    assert not hasattr(backend, "task_store")
    assert not hasattr(backend, "goal_store")
    assert not hasattr(backend, "memory_store")


def test_deep_backend_rejects_fast_request():
    backend = DeepLLMBackend(StubTransport())
    with pytest.raises(ValueError, match="non-DEEP"):
        backend.complete(routed_request(role=CognitiveRole.FAST))


def test_deep_renderer_rejects_fast_request():
    with pytest.raises(ValueError, match="non-DEEP"):
        render_deep_prompts(routed_request(role=CognitiveRole.FAST))


def test_deep_backend_requires_shared_transport_result():
    backend = DeepLLMBackend(BadTransport())
    with pytest.raises(TypeError, match="shared LLM call result"):
        backend.complete(routed_request())
    assert backend.call_history == []


def test_model_replacement_does_not_change_deep_request_or_proposal_contract():
    request = routed_request()
    first = DeepLLMBackend(StubTransport(text="same answer", model="SmolLM3-3B-Q8_0"))
    second = DeepLLMBackend(StubTransport(text="same answer", model="other-model"))

    proposal_a = first.complete(request)
    proposal_b = second.complete(request)

    assert proposal_a == proposal_b
    assert first.call_history[0].model != second.call_history[0].model
    assert request.role == CognitiveRole.DEEP
    assert request.view.consumer == "DEEP"


def test_llama_cpp_builder_keeps_model_in_profile_not_deep_contract():
    profile = DeepLLMProfile(
        model="replacement-model",
        thinking=True,
        max_output_tokens=321,
        temperature=0.2,
        top_k=7,
        top_p=0.7,
        min_p=0.1,
    )
    backend = build_llama_cpp_deep_backend(
        base_url="http://127.0.0.1:9123",
        profile=profile,
        timeout_seconds=42.0,
    )

    assert backend.timeout_seconds == 42.0
    assert isinstance(backend.transport, LlamaCppTransport)
    assert backend.transport.model == "replacement-model"
    assert backend.transport.base_url == "http://127.0.0.1:9123"
    assert backend.transport.thinking is True
    assert backend.transport.max_output_tokens == 321
    assert backend.transport.temperature == 0.2
    assert backend.transport.top_k == 7
    assert backend.transport.top_p == 0.7
    assert backend.transport.min_p == 0.1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": ""},
        {"model": "x", "thinking": 1},
        {"model": "x", "max_output_tokens": 0},
        {"model": "x", "temperature": -0.1},
        {"model": "x", "top_k": -1},
        {"model": "x", "top_p": 1.1},
        {"model": "x", "min_p": -0.1},
    ],
)
def test_deep_profile_rejects_invalid_generation_settings(kwargs):
    with pytest.raises(ValueError):
        DeepLLMProfile(**kwargs)
