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
            record, = consumer.rejected_generation_history
            assert record["wire_protocol"] == "llama_cpp_completion"
            assert record["finish_reason"] == metadata.get("stop_type")
            assert (record["input_tokens"], record["output_tokens"]) == (20, 8)
            assert record["termination_status"] in ("INCOMPLETE", "UNKNOWN")
            assert "text" not in record
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


@pytest.mark.parametrize("planner_type", [LLMPlanner, SmallModelLLMPlanner])
@pytest.mark.parametrize("wire,finish,expected", [
    ("chat_completion", "stop", "TEXT_COMPLETE"),
    ("llama_cpp_completion", "eos", "TEXT_COMPLETE"),
    ("chat_completion", "eos", "UNKNOWN"),
    ("llama_cpp_completion", "stop", "UNKNOWN"),
    (None, "stop", "UNKNOWN"),
    ("unsupported", "stop", "UNKNOWN"),
    ("chat_completion", " stop ", "UNKNOWN"),
    ("chat_completion", "", "UNKNOWN"),
    ("chat_completion", "length", "INCOMPLETE"),
    ("llama_cpp_completion", "limit", "INCOMPLETE"),
])
def test_planner_custom_transport_declares_wire(planner_type, wire, finish, expected):
    from anima.agent.llm_planner import LLMTransport, LLMCallResult

    class Custom(LLMTransport):
        wire_protocol = wire

        def complete(self, **kwargs):
            return LLMCallResult(provider="llama.cpp", model="test", text=json.dumps(_decision()),
                                 latency_ms=1, input_tokens=20, output_tokens=8,
                                 finish_reason=finish)

    planner = planner_type(Custom())
    if expected == "TEXT_COMPLETE":
        assert planner.plan(_request()).status == "proposals_available"
    else:
        with pytest.raises(LLMPlannerError, match="generation not confirmed complete"):
            planner.plan(_request())
    record = planner.last_call
    assert record.finish_reason == finish
    assert record.termination_status == expected
    assert record.wire_protocol == (wire if wire in ("chat_completion", "llama_cpp_completion") else None)
    assert record.total_tokens == 28
    assert "text" not in record.to_dict() and "prompt" not in record.to_dict()
    assert len(record.response_hash) == 64


@pytest.mark.parametrize("role", ["fast", "deep"])
@pytest.mark.parametrize("wire,finish,expected", [
    ("chat_completion", "stop", "TEXT_COMPLETE"),
    ("llama_cpp_completion", "eos", "TEXT_COMPLETE"),
    ("chat_completion", "eos", "UNKNOWN"),
    ("llama_cpp_completion", "stop", "UNKNOWN"),
    (None, "stop", "UNKNOWN"),
    ("unsupported", "stop", "UNKNOWN"),
    ("chat_completion", " stop ", "UNKNOWN"),
    ("chat_completion", "", "UNKNOWN"),
    ("chat_completion", "length", "INCOMPLETE"),
    ("llama_cpp_completion", "limit", "INCOMPLETE"),
])
def test_cognitive_custom_transport_declares_wire(role, wire, finish, expected):
    from anima.cognition.llm_transport import LLMCallResult

    class Custom:
        wire_protocol = wire

        def complete(self, **kwargs):
            return LLMCallResult(provider="llama.cpp", model="test", text="private diagnostic text",
                                 thinking=False, latency_ms=1, input_tokens=20,
                                 output_tokens=8, finish_reason=finish)

    backend = FastLLMBackend(Custom()) if role == "fast" else DeepLLMBackend(Custom())
    request = fast_request() if role == "fast" else routed_request()
    if expected == "TEXT_COMPLETE":
        backend.complete(request)
        assert len(backend.call_history) == 1
        assert not backend.rejected_generation_history
    else:
        error_type = FastLLMModelOutputError if role == "fast" else LLMModelOutputError
        with pytest.raises(error_type, match="generation not confirmed complete"):
            backend.complete(request)
        assert not backend.call_history
        record, = backend.rejected_generation_history
        assert record["finish_reason"] == finish
        assert record["termination_status"] == expected
        assert record["wire_protocol"] == (wire if wire in ("chat_completion", "llama_cpp_completion") else None)
        assert (record["input_tokens"], record["output_tokens"]) == (20, 8)
        assert "text" not in record and "private diagnostic text" not in repr(record)


@pytest.mark.parametrize("role", ["fast", "deep"])
def test_rejected_generation_metadata_is_bounded(role):
    from anima.cognition.llm_transport import LLMCallResult, MAX_REJECTED_GENERATION_HISTORY

    class Custom:
        wire_protocol = "chat_completion"
        count = 0

        def complete(self, **kwargs):
            self.count += 1
            return LLMCallResult("test", "test", "partial", False, 1,
                                 input_tokens=self.count, finish_reason="length")

    backend = FastLLMBackend(Custom()) if role == "fast" else DeepLLMBackend(Custom())
    request = fast_request() if role == "fast" else routed_request()
    error_type = FastLLMModelOutputError if role == "fast" else LLMModelOutputError
    for _ in range(MAX_REJECTED_GENERATION_HISTORY + 2):
        with pytest.raises(error_type):
            backend.complete(request)
    assert not backend.call_history
    assert len(backend.rejected_generation_history) == MAX_REJECTED_GENERATION_HISTORY
    assert backend.rejected_generation_history[0]["input_tokens"] == 3
    assert backend.rejected_generation_history[-1]["input_tokens"] == MAX_REJECTED_GENERATION_HISTORY + 2
    assert all("text" not in record for record in backend.rejected_generation_history)
