"""R9.3-C7 RED: preserve reported usage even before a usable call result exists."""
import json

import pytest

from anima.agent.llm_planner import LLMTransportError
from tests.test_e26_r93_canonical_contract import canonical_consumer


@pytest.mark.parametrize("role,wire", [
    ("planner", "chat"), ("small_planner", "chat"),
    ("planner", "native"), ("small_planner", "native"),
    ("fast", "native"), ("deep", "native"),
])
@pytest.mark.parametrize("content,complete", [
    ("", False),
    ("   ", False),
    (None, False),
    ("", True),
])
def test_unusable_response_preserves_reported_usage(monkeypatch, role, wire, content, complete):
    transport, consumer, invoke, _, output_error = canonical_consumer(role, wire=wire)
    calls = []
    reason = ("stop" if complete else "length") if wire == "chat" else (
        "eos" if complete else "limit")
    protocol = "chat_completion" if wire == "chat" else "llama_cpp_completion"
    expected_error = LLMTransportError if role in ("planner", "small_planner") else output_error
    if wire == "chat":
        body = {
            "choices": [{"finish_reason": reason, "message": {
                "role": "assistant", "content": content,
                "reasoning_content": "PRIVATE_REASONING",
            }}],
            "usage": {"prompt_tokens": 731, "completion_tokens": 256},
        }

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit):
                return json.dumps(body).encode("utf-8")

        def urlopen(request, timeout):
            calls.append(request)
            return Response()

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
    else:
        def post(endpoint, payload, *, timeout_seconds):
            calls.append(endpoint)
            if endpoint.endswith("/apply-template"):
                return {"prompt": "rendered"}
            return {"content": content, "reasoning_content": "PRIVATE_REASONING",
                    "stop_type": reason, "stop": True,
                    "tokens_evaluated": 731, "tokens_predicted": 256}

        monkeypatch.setattr(transport, "_post_json", post)

    with pytest.raises(expected_error) as caught:
        invoke()
    assert len(calls) == (1 if wire == "chat" else 2)
    assert not consumer.call_history
    record, = transport.rejected_response_history
    assert caught.value.generation_diagnostic == record
    assert record["wire_protocol"] == protocol
    assert record["finish_reason"] == reason
    assert record["termination_status"] == ("TEXT_COMPLETE" if complete else "INCOMPLETE")
    assert (record["input_tokens"], record["output_tokens"]) == (731, 256)
    assert record["latency_ms"] >= 0
    assert record["content_chars"] == (len(content) if isinstance(content, str) else 0)
    assert record["reasoning_chars"] == len("PRIVATE_REASONING")
    assert "PRIVATE_REASONING" not in repr(record)
    assert not {"text", "content", "reasoning_content", "raw_response", "prompt"} & set(record)


@pytest.mark.parametrize("role", ["fast", "deep"])
def test_unfinished_inline_reasoning_keeps_usage_without_text(monkeypatch, role):
    transport, consumer, invoke, _, error_type = canonical_consumer(role, wire="native")

    def post(endpoint, payload, *, timeout_seconds):
        if endpoint.endswith("/apply-template"):
            return {"prompt": "rendered"}
        return {"content": "<think>PRIVATE_REASONING", "stop_type": "limit",
                "stop": True, "tokens_evaluated": 250, "tokens_predicted": 32}

    monkeypatch.setattr(transport, "_post_json", post)
    with pytest.raises(error_type) as caught:
        invoke()
    assert not consumer.call_history
    record, = transport.rejected_response_history
    assert caught.value.generation_diagnostic == record
    assert record["termination_status"] == "INCOMPLETE"
    assert (record["input_tokens"], record["output_tokens"]) == (250, 32)
    assert record["content_chars"] == len("<think>PRIVATE_REASONING")
    assert "PRIVATE_REASONING" not in repr(record)


@pytest.mark.parametrize("role,wire", [
    ("planner", "chat"), ("small_planner", "chat"),
    ("planner", "native"), ("small_planner", "native"),
    ("fast", "native"), ("deep", "native"),
])
@pytest.mark.parametrize("input_count,output_count,expected", [
    (-1, 8, (None, 8)),
    (20, True, (20, None)),
    ("20", None, (None, None)),
    (0, 0, (0, 0)),
])
def test_early_diagnostic_does_not_invent_usage(monkeypatch, role, wire, input_count, output_count, expected):
    transport, consumer, invoke, _, output_error = canonical_consumer(role, wire=wire)
    if wire == "chat":
        body = {"choices": [{"finish_reason": "length", "message": {"content": ""}}],
                "usage": {"prompt_tokens": input_count, "completion_tokens": output_count}}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return json.dumps(body).encode("utf-8")

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: Response())
    else:
        def post(endpoint, payload, **kwargs):
            if endpoint.endswith("/apply-template"):
                return {"prompt": "rendered"}
            return {"content": "", "stop_type": "limit",
                    "tokens_evaluated": input_count, "tokens_predicted": output_count}

        monkeypatch.setattr(transport, "_post_json", post)

    error_type = LLMTransportError if role in ("planner", "small_planner") else output_error
    with pytest.raises(error_type) as caught:
        invoke()
    record, = transport.rejected_response_history
    assert (record["input_tokens"], record["output_tokens"]) == expected
    assert record["termination_status"] == "INCOMPLETE"
    assert caught.value.generation_diagnostic == record
    caught.value.generation_diagnostic["input_tokens"] = 999
    assert record["input_tokens"] == expected[0]
    assert not consumer.call_history


@pytest.mark.parametrize("role,wire", [
    ("planner", "chat"), ("small_planner", "chat"),
    ("planner", "native"), ("small_planner", "native"),
    ("fast", "native"), ("deep", "native"),
])
def test_failure_before_generation_does_not_invent_response(monkeypatch, role, wire):
    import urllib.error
    from anima.cognition.fast_llm import FastLLMTransportError
    from anima.cognition.llm_transport import LLMTransportError as TextTransportError

    transport, consumer, invoke, _, _ = canonical_consumer(role, wire=wire)
    if wire == "chat":
        def unavailable(*args, **kwargs):
            raise urllib.error.URLError("synthetic unavailable")
        monkeypatch.setattr("urllib.request.urlopen", unavailable)
    else:
        def no_template(endpoint, payload, **kwargs):
            assert endpoint.endswith("/apply-template")
            return {}
        monkeypatch.setattr(transport, "_post_json", no_template)

    expected_error = (FastLLMTransportError if role == "fast" else
                      TextTransportError if role == "deep" else LLMTransportError)
    with pytest.raises(expected_error) as caught:
        invoke()
    assert not hasattr(caught.value, "generation_diagnostic")
    assert not transport.rejected_response_history
    assert not consumer.call_history


@pytest.mark.parametrize("role,wire", [
    ("planner", "chat"), ("planner", "native"), ("fast", "native"),
])
def test_early_diagnostic_history_is_bounded(monkeypatch, role, wire):
    from anima.agent.generation_termination import MAX_REJECTED_RESPONSE_HISTORY
    transport, consumer, invoke, _, output_error = canonical_consumer(role, wire=wire)
    count = 0
    if wire == "chat":
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit):
                nonlocal count
                count += 1
                return json.dumps({
                    "choices": [{"finish_reason": "length", "message": {"content": ""}}],
                    "usage": {"prompt_tokens": count, "completion_tokens": 1},
                }).encode("utf-8")
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: Response())
    else:
        def post(endpoint, payload, **kwargs):
            nonlocal count
            if endpoint.endswith("/apply-template"):
                return {"prompt": "rendered"}
            count += 1
            return {"content": "", "stop_type": "limit",
                    "tokens_evaluated": count, "tokens_predicted": 1}
        monkeypatch.setattr(transport, "_post_json", post)

    expected_error = LLMTransportError if role == "planner" else output_error
    for _ in range(MAX_REJECTED_RESPONSE_HISTORY + 2):
        with pytest.raises(expected_error):
            invoke()
    assert not consumer.call_history
    assert count == MAX_REJECTED_RESPONSE_HISTORY + 2
    assert len(transport.rejected_response_history) == MAX_REJECTED_RESPONSE_HISTORY
    assert transport.rejected_response_history[0]["input_tokens"] == 3
    assert transport.rejected_response_history[-1]["input_tokens"] == count
