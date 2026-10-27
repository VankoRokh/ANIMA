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


def _planner_content():
    return json.dumps(
        {
            "status": "cannot_progress",
            "proposals": [],
            "plan_summary": "no valid action",
        }
    )


def _template_response():
    return {"prompt": "<templated-qwen-prompt>"}


def _completion_response():
    return {
        "content": _planner_content(),
        "tokens_evaluated": 44,
        "tokens_predicted": 25,
        "stop": True,
        "stop_type": "eos",
    }


def test_llama_cpp_transport_uses_template_then_native_constrained_completion(monkeypatch):
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append(
            {
                "url": request.full_url,
                "payload": payload,
                "timeout": timeout,
            }
        )
        if request.full_url.endswith("/apply-template"):
            return Response(_template_response())
        if request.full_url.endswith("/completion"):
            return Response(_completion_response())
        raise AssertionError(f"unexpected URL: {request.full_url}")

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

    assert len(calls) == 2
    template_call, completion_call = calls

    assert template_call["url"] == "http://127.0.0.1:8080/apply-template"
    assert template_call["payload"] == {
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "{}"},
        ],
        "add_generation_prompt": True,
        "enable_thinking": False,
    }

    assert completion_call["url"] == "http://127.0.0.1:8080/completion"
    payload = completion_call["payload"]
    assert payload["prompt"] == "<templated-qwen-prompt>"
    assert payload["temperature"] == LLAMA_CPP_DEFAULT_TEMPERATURE
    assert payload["top_k"] == LLAMA_CPP_DEFAULT_TOP_K
    assert payload["top_p"] == LLAMA_CPP_DEFAULT_TOP_P
    assert payload["min_p"] == LLAMA_CPP_DEFAULT_MIN_P
    assert payload["n_predict"] == SMALL_LLM_MAX_OUTPUT_TOKENS
    assert payload["stream"] is False
    assert payload["json_schema"] == LLAMA_CPP_PLANNER_JSON_SCHEMA

    assert result.provider == "llama.cpp"
    assert result.model == "qwen3-0.6b"
    assert result.input_tokens == 44
    assert result.output_tokens == 25
    assert result.finish_reason == "eos"
    assert json.loads(result.text)["plan_summary"] == "no valid action"


def test_llama_cpp_transport_can_disable_backend_schema(monkeypatch):
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        del timeout
        payload = json.loads(request.data.decode("utf-8"))
        calls.append((request.full_url, payload))
        if request.full_url.endswith("/apply-template"):
            return Response(_template_response())
        return Response(_completion_response())

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

    completion_payload = calls[-1][1]
    assert "json_schema" not in completion_payload


def test_llama_cpp_transport_normalizes_supported_base_urls():
    cases = {
        "http://127.0.0.1:8080": "http://127.0.0.1:8080",
        "http://127.0.0.1:8080/v1": "http://127.0.0.1:8080",
        "http://127.0.0.1:8080/v1/chat/completions": "http://127.0.0.1:8080",
        "http://127.0.0.1:8080/completion": "http://127.0.0.1:8080",
    }
    for base_url, expected in cases.items():
        transport = LlamaCppSmallModelTransport(
            base_url=base_url,
            model="qwen3-0.6b",
        )
        assert transport.server_root == expected


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
