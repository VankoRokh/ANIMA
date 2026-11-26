"""R9.3-C RED: canonical consumers must not promote incomplete generations.

Use real transport implementations with synthetic server responses. These tests
do not exercise a model, write files through an executor, or attest a backend.
"""
import json

import pytest

from anima.agent.llm_planner import (
    LLMPlanner, LLMPlannerError, OpenAICompatibleChatTransport,
)
from anima.agent.small_llm import (
    SmallModelLLMPlanner, SmallModelOpenAICompatibleChatTransport,
)
from anima.agent.llama_cpp_transport import LlamaCppSmallModelTransport
from anima.cognition.fast_llm import FastLLMBackend, FastLLMModelOutputError, LlamaCppFastTransport
from anima.cognition.deep_llm import DeepLLMBackend
from anima.cognition.llm_transport import LlamaCppTransport, LLMModelOutputError
from tests.test_agent_llm_planner import _decision, _request
from tests.test_fast_llm_backend import fast_request
from tests.test_deep_llm_backend import routed_request


def canonical_consumer(role, *, wire):
    config = {"base_url": "http://127.0.0.1:8085", "model": "test"}
    if role in ("planner", "small_planner"):
        if wire == "native":
            transport = LlamaCppSmallModelTransport(**config)
        elif role == "planner":
            transport = OpenAICompatibleChatTransport(**config)
        else:
            transport = SmallModelOpenAICompatibleChatTransport(**config)
        planner_type = LLMPlanner if role == "planner" else SmallModelLLMPlanner
        consumer = planner_type(transport)
        return (transport, consumer, lambda: consumer.plan(_request()),
                json.dumps(_decision()), LLMPlannerError)
    if role == "fast":
        transport = LlamaCppFastTransport(**config)
        consumer = FastLLMBackend(transport)
        return (transport, consumer, lambda: consumer.complete(fast_request()),
                "Captured observation is available.", FastLLMModelOutputError)
    if role == "deep":
        transport = LlamaCppTransport(**config)
        consumer = DeepLLMBackend(transport)
        return (transport, consumer, lambda: consumer.complete(routed_request()),
                "Evidence supports a bounded conclusion.", LLMModelOutputError)
    raise AssertionError("unknown test role")


def assert_success(role, result):
    if role in ("planner", "small_planner"):
        assert result.status == "proposals_available"
        assert result.proposals[0].tool == "fs.read"
    elif role == "fast":
        assert result.response_text == "Captured observation is available."
    else:
        assert result.payload["text"] == "Evidence supports a bounded conclusion."


@pytest.mark.parametrize("role", ["planner", "small_planner", "fast", "deep"])
@pytest.mark.parametrize("metadata,accepted", [
    ({"stop_type": "eos", "stop": True}, True),
    ({"stop_type": "word", "stop": True}, True),
    ({"stop_type": "limit", "stop": True}, False),
    ({"stop_type": "none", "stop": False}, False),
    ({"stop": True}, False),
    ({"stop": False}, False),
    ({"stop_type": "stop", "stop": True}, False),
])
def test_canonical_native_completion_requires_explicit_termination(
        monkeypatch, role, metadata, accepted):
    transport, consumer, invoke, text, error_type = canonical_consumer(role, wire="native")
    calls = []

    def post(endpoint, payload, *, timeout_seconds):
        calls.append(endpoint)
        if endpoint.endswith("/apply-template"):
            return {"prompt": "rendered"}
        assert endpoint.endswith("/completion")
        return {"content": text, "tokens_evaluated": 20,
                "tokens_predicted": 8, **metadata}

    monkeypatch.setattr(transport, "_post_json", post)
    if accepted:
        assert_success(role, invoke())
        assert len(consumer.call_history) == 1
    else:
        with pytest.raises(error_type):
            invoke()
        if role in ("planner", "small_planner"):
            assert consumer.last_call.input_tokens == 20
            assert consumer.last_call.output_tokens == 8
        else:
            # Existing FAST/DEEP history is explicitly successful calls only.
            assert not consumer.call_history
    assert len(calls) == 2


@pytest.mark.parametrize("role", ["planner", "small_planner"])
@pytest.mark.parametrize("finish", ["stop", "length", "content_filter", "tool_calls", "eos", None])
def test_canonical_chat_completion_requires_wire_specific_termination(monkeypatch, role, finish):
    transport, consumer, invoke, text, error_type = canonical_consumer(role, wire="chat")
    choice = {"message": {"role": "assistant", "content": text}}
    if finish is not None:
        choice["finish_reason"] = finish
    body = {"choices": [choice], "usage": {"prompt_tokens": 20, "completion_tokens": 8}}
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps(body).encode("utf-8")

    def urlopen(request, timeout):
        requests.append(request)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    if finish == "stop":
        assert_success(role, invoke())
    else:
        with pytest.raises(error_type):
            invoke()
    assert len(requests) == 1
    assert len(consumer.call_history) == 1
    assert consumer.last_call.input_tokens == 20
    assert consumer.last_call.output_tokens == 8
