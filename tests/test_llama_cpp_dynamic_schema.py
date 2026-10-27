import json

from anima.agent.llama_cpp_transport import LlamaCppSmallModelTransport


def test_llama_cpp_complete_structured_sends_supplied_schema(monkeypatch):
    calls = []
    supplied_schema = {
        "type": "object",
        "properties": {"probe": {"const": "schema-enforced"}},
        "required": ["probe"],
        "additionalProperties": False,
    }

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
            return Response({"prompt": "<templated>"})
        if request.full_url.endswith("/completion"):
            return Response(
                {
                    "content": '{"probe":"schema-enforced"}',
                    "tokens_evaluated": 10,
                    "tokens_predicted": 6,
                    "stop": True,
                    "stop_type": "eos",
                }
            )
        raise AssertionError(f"unexpected URL: {request.full_url}")

    monkeypatch.setattr(
        "anima.agent.llama_cpp_transport.urllib.request.urlopen",
        fake_urlopen,
    )
    transport = LlamaCppSmallModelTransport(
        base_url="http://127.0.0.1:8080/v1",
        model="qwen3-0.6b",
    )

    result = transport.complete_structured(
        system_prompt="system",
        user_prompt="user",
        timeout_seconds=10,
        response_schema=supplied_schema,
    )

    assert calls[-1][0] == "http://127.0.0.1:8080/completion"
    assert calls[-1][1]["json_schema"] == supplied_schema
    assert json.loads(result.text) == {"probe": "schema-enforced"}


def test_llama_cpp_complete_structured_respects_disabled_constraints(monkeypatch):
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
            return Response({"prompt": "<templated>"})
        return Response(
            {
                "content": '{"status":"cannot_progress","proposals":[],"plan_summary":"none"}',
                "tokens_evaluated": 10,
                "tokens_predicted": 10,
                "stop": True,
                "stop_type": "eos",
            }
        )

    monkeypatch.setattr(
        "anima.agent.llama_cpp_transport.urllib.request.urlopen",
        fake_urlopen,
    )
    transport = LlamaCppSmallModelTransport(
        base_url="http://127.0.0.1:8080/v1",
        model="qwen3-0.6b",
        constrain_json=False,
    )

    transport.complete_structured(
        system_prompt="system",
        user_prompt="user",
        timeout_seconds=10,
        response_schema={"type": "object"},
    )

    assert "json_schema" not in calls[-1][1]
