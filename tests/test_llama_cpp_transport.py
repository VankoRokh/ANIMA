import json

from anima.agent.llama_cpp_transport import (
    LLAMA_CPP_DEFAULT_MIN_P,
    LLAMA_CPP_DEFAULT_TEMPERATURE,
    LLAMA_CPP_DEFAULT_TOP_K,
    LLAMA_CPP_DEFAULT_TOP_P,
    LLAMA_CPP_PLANNER_JSON_SCHEMA,
    LlamaCppSmallModelTransport,
)
from anima.agent.small_llm import SMALL_LLM_MAX_OUTPUT_TOKENS


def _response_payload():
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "status": "cannot_progress",
                            "proposals": [],
                            "plan_summary": "no valid action",
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 44, "completion_tokens": 25},
    }


def test_llama_cpp_transport_sends_verified_sampling_and_json_schema(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            return json.dumps(_response_payload()).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(
        "anima.agent.llama_cpp_transport.urllib.request.urlopen",
        fake_urlopen,
    )
    transport = LlamaCppSmallModelTransport(
        base_url="http://127.0.0.1:8080/v1",
        model="qwen3-0.6b",
        provider="llama.cpp",
    )

    result = transport.complete(
        system_prompt="system",
        user_prompt="{}",
        timeout_seconds=10,
    )

    payload = captured["payload"]
    assert payload["temperature"] == LLAMA_CPP_DEFAULT_TEMPERATURE
    assert payload["top_k"] == LLAMA_CPP_DEFAULT_TOP_K
    assert payload["top_p"] == LLAMA_CPP_DEFAULT_TOP_P
    assert payload["min_p"] == LLAMA_CPP_DEFAULT_MIN_P
    assert payload["max_tokens"] == SMALL_LLM_MAX_OUTPUT_TOKENS
    assert payload["response_format"] == {
        "type": "json_schema",
        "schema": LLAMA_CPP_PLANNER_JSON_SCHEMA,
    }
    assert result.provider == "llama.cpp"
    assert result.model == "qwen3-0.6b"
    assert result.input_tokens == 44
    assert result.output_tokens == 25
    assert result.finish_reason == "stop"


def test_llama_cpp_transport_can_disable_backend_schema(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            return json.dumps(_response_payload()).encode("utf-8")

    def fake_urlopen(request, timeout):
        del timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return Response()

    monkeypatch.setattr(
        "anima.agent.llama_cpp_transport.urllib.request.urlopen",
        fake_urlopen,
    )
    transport = LlamaCppSmallModelTransport(
        base_url="http://127.0.0.1:8080/v1",
        model="qwen3-0.6b",
        constrain_json=False,
    )

    transport.complete(
        system_prompt="system",
        user_prompt="{}",
        timeout_seconds=10,
    )

    assert "response_format" not in captured["payload"]


def test_llama_cpp_planner_schema_keeps_exact_outer_contract():
    assert LLAMA_CPP_PLANNER_JSON_SCHEMA["required"] == [
        "status",
        "proposals",
        "plan_summary",
    ]
    assert LLAMA_CPP_PLANNER_JSON_SCHEMA["additionalProperties"] is False
    proposal = LLAMA_CPP_PLANNER_JSON_SCHEMA["properties"]["proposals"]["items"]
    assert proposal["additionalProperties"] is False
    assert proposal["required"] == [
        "tool",
        "tool_version",
        "arguments",
        "expected_observation",
        "rationale_summary",
    ]
