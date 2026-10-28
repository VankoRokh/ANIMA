from copy import deepcopy
import json

import pytest

from anima.agent.executor import build_sandbox_registry
from anima.agent.llama_cpp_transport import (
    LlamaCppSmallModelTransport,
    _project_llama_cpp_schema,
)
from anima.agent.small_llm import build_small_llm_response_schema


def _proposal_variants(schema):
    for branch in schema["oneOf"]:
        proposals = branch["properties"]["proposals"]
        if branch["properties"]["status"]["const"] == "proposals_available":
            yield from proposals["items"]["oneOf"]


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


def test_llama_cpp_projection_only_removes_known_path_pattern():
    schema = build_small_llm_response_schema(build_sandbox_registry().list_descriptors())
    original = deepcopy(schema)
    expected = deepcopy(schema)
    for variant in _proposal_variants(expected):
        path = variant["properties"]["arguments"]["properties"]["path"]
        assert path.pop("pattern") == r"^[^/].*$"
        assert path["type"] == "string"
        assert path["minLength"] == 1
        assert path["maxLength"] == 512
        assert "Sandbox-relative path" in path["description"]

    projected = _project_llama_cpp_schema(schema)
    # Whole-schema equality checks status/tool branches, const, required,
    # additionalProperties, maxItems, and tool-specific argument structure too.
    assert projected == expected
    assert schema == original
    projected["oneOf"][0]["properties"]["status"]["const"] = "probe"
    assert schema == original


def test_llama_cpp_projection_preserves_other_patterns_and_literal_data():
    literal = {"properties": {"path": {"type": "string", "pattern": r"^[^/].*$"}}}
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "pattern": "^[a-z]+$"},
            "other": {"type": "string", "pattern": r"^[^/].*$"},
            "literal": {"const": literal},
        },
    }
    assert _project_llama_cpp_schema(schema) == schema


@pytest.mark.parametrize("with_tools", [True, False])
def test_llama_cpp_transport_sends_projected_schema_without_mutation(monkeypatch, with_tools):
    tools = build_sandbox_registry().list_descriptors() if with_tools else ()
    schema = build_small_llm_response_schema(tools)
    original = deepcopy(schema)
    calls = []

    def post_json(endpoint, payload, *, timeout_seconds):
        calls.append((endpoint, deepcopy(payload)))
        if endpoint.endswith("/apply-template"):
            return {"prompt": "<templated>"}
        return {
            "content": '{"status":"cannot_progress","proposals":[],"plan_summary":"none"}',
            "tokens_evaluated": 10,
            "tokens_predicted": 10,
            "stop_type": "eos",
        }

    transport = LlamaCppSmallModelTransport(
        base_url="http://127.0.0.1:8080/v1", model="local-test",
    )
    monkeypatch.setattr(transport, "_post_json", post_json)
    transport.complete_structured(
        system_prompt="unchanged system", user_prompt="unchanged user",
        timeout_seconds=10, response_schema=schema,
    )
    assert calls[-1][0] == "http://127.0.0.1:8080/completion"
    expected = deepcopy(original)
    for variant in _proposal_variants(expected):
        del variant["properties"]["arguments"]["properties"]["path"]["pattern"]
    assert calls[-1][1]["json_schema"] == expected
    assert calls[0][1]["messages"] == [
        {"role": "system", "content": "unchanged system"},
        {"role": "user", "content": "unchanged user"},
    ]
    assert schema == original
