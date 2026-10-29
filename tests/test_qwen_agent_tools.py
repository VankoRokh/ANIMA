import json

import pytest

from anima.cognition.qwen_agent_tools import (
    AnimaReadOnlyToolGateway,
    QwenAgentToolLoop,
    QwenToolProtocolError,
)
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.retrieval import RetrievalEngine


MEMORY_ID = "mem_11111111-1111-4111-8111-111111111111"
EVENT_ID = "ev_22222222-2222-4222-8222-222222222222"
TIMESTAMP = "2026-10-29T12:00:00+00:00"


class FakeStateRuntime:
    def snapshot(self, *, transition_limit=20):
        assert transition_limit == 0
        return {
            "states": {
                "fatigue": 0.25,
                "uncertainty": 0.1,
                "frustration": 0.0,
                "satisfaction": 0.2,
            },
            "goals": [
                {
                    "id": "goal_demo",
                    "description": "Reach the target",
                    "priority": 2.0,
                    "status": "active",
                }
            ],
            "goal_arbitration": {"selected_goal_id": "goal_demo"},
        }


class FakeLLM:
    def __init__(self, response_batches):
        self.response_batches = list(response_batches)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if not self.response_batches:
            raise AssertionError("FakeLLM has no queued response")
        return self.response_batches.pop(0)


def build_gateway(tmp_path, *, with_state=False):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    store.create_memory(
        memory_type="episodic",
        domain="user",
        content="Пользователь предпочитает кофе эспрессо.",
        status="closed",
        importance=2,
        created_at=TIMESTAMP,
        public_id=MEMORY_ID,
        source_event_id=EVENT_ID,
    )
    retrieval = RetrievalEngine(memory_store=store, link_store=links)
    return AnimaReadOnlyToolGateway(
        retrieval=retrieval,
        internal_state_runtime=FakeStateRuntime() if with_state else None,
    )


def test_gateway_exposes_only_read_only_functions(tmp_path):
    gateway = build_gateway(tmp_path)

    names = [item["name"] for item in gateway.function_schemas()]

    assert names == ["memory_search", "memory_get", "state_read"]


def test_memory_search_uses_existing_retrieval_engine(tmp_path):
    gateway = build_gateway(tmp_path)

    result = json.loads(
        gateway.execute(
            "memory_search",
            {"query": "кофе эспрессо", "limit": 3},
        )
    )

    assert result["count"] == 1
    assert result["results"][0]["id"] == MEMORY_ID
    assert result["results"][0]["content"] == (
        "Пользователь предпочитает кофе эспрессо."
    )


def test_memory_get_reads_exact_object_without_direct_database_access(tmp_path):
    gateway = build_gateway(tmp_path)

    result = json.loads(
        gateway.execute("memory_get", {"object_id": MEMORY_ID})
    )

    assert result["found"] is True
    assert result["object"]["id"] == MEMORY_ID
    assert result["object"]["kind"] == "memory"


def test_state_read_returns_compact_snapshot(tmp_path):
    gateway = build_gateway(tmp_path, with_state=True)

    result = json.loads(gateway.execute("state_read", {}))

    assert result["available"] is True
    assert result["states"]["fatigue"] == 0.25
    assert result["selected_goal_id"] == "goal_demo"
    assert result["goals"] == [
        {
            "id": "goal_demo",
            "description": "Reach the target",
            "priority": 2.0,
            "status": "active",
        }
    ]


def test_tool_loop_executes_anima_tool_and_returns_final_answer(tmp_path):
    gateway = build_gateway(tmp_path)
    llm = FakeLLM(
        [
            [
                {
                    "role": "assistant",
                    "content": "",
                    "function_call": {
                        "name": "memory_search",
                        "arguments": json.dumps(
                            {"query": "кофе эспрессо", "limit": 3}
                        ),
                    },
                }
            ],
            [{"role": "assistant", "content": "Ты предпочитаешь эспрессо."}],
        ]
    )
    loop = QwenAgentToolLoop(llm=llm, gateway=gateway)

    turn = loop.run("Какой кофе я предпочитаю?")

    assert turn.response_text == "Ты предпочитаешь эспрессо."
    assert [call.name for call in turn.tool_calls] == ["memory_search"]
    assert turn.tool_calls[0].result["results"][0]["id"] == MEMORY_ID
    assert llm.calls[0]["functions"][0]["name"] == "memory_search"
    function_messages = [
        message
        for message in llm.calls[1]["messages"]
        if message.get("role") == "function"
    ]
    assert len(function_messages) == 1
    assert function_messages[0]["name"] == "memory_search"


def test_tool_loop_can_answer_without_calling_anima_tools(tmp_path):
    gateway = build_gateway(tmp_path)
    llm = FakeLLM(
        [[{"role": "assistant", "content": "4"}]]
    )
    loop = QwenAgentToolLoop(llm=llm, gateway=gateway)

    turn = loop.run("Сколько будет 2 + 2?")

    assert turn.response_text == "4"
    assert turn.tool_calls == ()
    assert turn.rounds == 1


def test_gateway_rejects_invalid_or_write_like_calls(tmp_path):
    gateway = build_gateway(tmp_path)

    with pytest.raises(QwenToolProtocolError):
        gateway.execute("memory_write", {"content": "unsafe"})
    with pytest.raises(QwenToolProtocolError):
        gateway.execute("memory_search", {"query": ""})
    with pytest.raises(QwenToolProtocolError):
        gateway.execute("state_read", {"unexpected": True})


def test_huge_integer_arguments_are_model_protocol_error():
    from anima.cognition.qwen_agent_tools import _normalize_arguments
    from scripts.benchmark_tool_models import classify_run_error

    raw = '{"query":"x","extra":' + '9' * 5000 + '}'
    with pytest.raises(QwenToolProtocolError, match="JSON") as caught:
        _normalize_arguments(raw)
    assert classify_run_error(caught.value) == "model_protocol"


@pytest.mark.parametrize("value", [[], ["invalid"], True, False, 123, "memory_search",
                                    {}, {"arguments": "{}"}, {"name": 123},
                                    {"name": ""}, {"name": " "}])
def test_malformed_function_call_is_protocol_error(tmp_path, value):
    llm = FakeLLM([[{"role": "assistant", "function_call": value, "content": "ignored"}]])
    loop = QwenAgentToolLoop(llm=llm, gateway=build_gateway(tmp_path))
    with pytest.raises(QwenToolProtocolError, match="name"):
        loop.run("test")


@pytest.mark.parametrize("parts,expected", [
    (["Собаку зовут Рекс.", 'Имя собаки неизвестно.\nCONTROL: {"dog_name":null}'],
     'Собаку зовут Рекс.\nИмя собаки неизвестно.\nCONTROL: {"dog_name":null}'),
    (["Выбор: Чай.", 'Выбор: Эспрессо.\nCONTROL: {}'],
     'Выбор: Чай.\nВыбор: Эспрессо.\nCONTROL: {}'),
    ([None, "", " ", "  single response  ", None], "single response"),
])
def test_final_turn_preserves_all_text_in_order(tmp_path, parts, expected):
    llm = FakeLLM([[{"role": "assistant", "content": part} for part in parts]])
    turn = QwenAgentToolLoop(llm=llm, gateway=build_gateway(tmp_path)).run("test")
    assert turn.response_text == expected


@pytest.mark.parametrize("parts", [[None, "", " "], [123], [[], "valid"]])
def test_final_turn_rejects_missing_or_nontext_content(tmp_path, parts):
    llm = FakeLLM([[{"content": part} for part in parts]])
    with pytest.raises(QwenToolProtocolError):
        QwenAgentToolLoop(llm=llm, gateway=build_gateway(tmp_path)).run("test")


def test_function_call_supports_object_like_messages():
    from types import SimpleNamespace
    from anima.cognition.qwen_agent_tools import _jsonable_function_call
    assert _jsonable_function_call(SimpleNamespace()) is None
    assert _jsonable_function_call({"content": "text"}) is None
    value = SimpleNamespace(name="state_read", arguments="{}")
    assert _jsonable_function_call(SimpleNamespace(function_call=value)) == {
        "name": "state_read", "arguments": "{}"}
    with pytest.raises(QwenToolProtocolError):
        _jsonable_function_call(SimpleNamespace(function_call=SimpleNamespace(arguments="{}")))


def test_function_call_does_not_mask_infrastructure_exception():
    from anima.cognition.qwen_agent_tools import _jsonable_function_call
    class BrokenMessage:
        def get(self, *args):
            raise RuntimeError("adapter unavailable")
    with pytest.raises(RuntimeError, match="adapter unavailable"):
        _jsonable_function_call(BrokenMessage())
