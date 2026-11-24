import json
import pytest

from anima.agent.native_tools import NativeToolCatalog, NativeToolSession
from anima.agent.tools import ToolDescriptor, ToolRegistry
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter, lab_registry


def completion(name=None, args=None, call_id="id1", content=None, finish=None):
    msg = {"role": "assistant", "content": content}
    if name is not None:
        msg["tool_calls"] = [{"id": call_id, "type": "function",
                              "function": {"name": name, "arguments": args}}]
    return {"choices": [{"message": msg, "finish_reason": finish or
                         ("tool_calls" if name is not None else "stop")}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4}}


class Fake:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, payload):
        self.requests.append(payload)
        return next(self.responses)


def session(*responses, registry=None):
    fake = Fake(*responses)
    return NativeToolSession(NativeToolCatalog(registry or lab_registry()),
                             model="test", system_prompt="test", user_prompt="test",
                             transport=fake), fake


def test_registry_projection_and_new_tool_without_adapter_change():
    schema = {"type": "object", "properties": {"word": {"type": "string"}},
              "required": ["word"], "additionalProperties": False}
    desc = ToolDescriptor(name="test.echo", version="1", description="Echo",
                          input_schema=schema, output_schema=schema,
                          effect_class="read_only", idempotency="repeat_safe")
    s, fake = session(completion("test_echo", '{"word":"hello"}'),
                      completion(content="Done"), registry=ToolRegistry([desc]))
    got, args = s.next()
    assert got is desc and args == {"word": "hello"}
    assert fake.requests[0]["tools"][0]["function"]["parameters"] == schema
    s.submit_result(got, args)
    assert s.next() is None
    messages = fake.requests[1]["messages"]
    assert messages[-1] == {"role":"tool","tool_call_id":"id1","content":'{"word":"hello"}'}
    assert messages[-2]["tool_calls"][0]["id"] == "id1"


@pytest.mark.parametrize("name,args", [
    ("world_step", '{}'),
    ("retrieve_memory", '{"query":"crate","top_k":true}'),
    ("retrieve_memory", '{"query":"crate","top_k":5,"extra":1}'),
    ("retrieve_memory", '{"query":"crate","query":"other","top_k":5}'),
    ("retrieve_memory", '{"query":"crate","top_k":99}'),
])
def test_invalid_calls(name, args):
    s, _ = session(completion(name, args))
    with pytest.raises(ValueError):
        s.next()
    assert s.calls[-1]["transport_ok"] and not s.calls[-1]["valid"]


def test_native_nonstop_is_not_success():
    s, _ = session(completion(content="unfinished", finish="length"))
    with pytest.raises(ValueError):
        s.next()


def test_native_pending_result_binding():
    s, _ = session(completion("retrieve_memory", '{"query":"crate","top_k":5}'))
    d, _ = s.next()
    with pytest.raises(ValueError):
        s.next()
    with pytest.raises(ValueError):
        s.submit_result(d, {"invalid": True})


def context():
    return {"context_snapshot_id":"ctx_test", "entities":[], "memory_enabled":False}


def test_unexposed_raw_rejected(tmp_path):
    fake = Fake(completion("lookup_raw_evidence", '{"event_ids":["ev_hidden"]}'))
    a = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
                         trace_path=tmp_path/"calls.jsonl", task="find crate", transport=fake)
    assert a.propose(context(), [], turn_id="t", step_index=0) == {"invalid_model_output":True}
    assert not a.calls[-1]["valid"]


def test_verified_result_roundtrip_and_stop(tmp_path):
    fake = Fake(completion("retrieve_memory", '{"query":"crate","top_k":5}'),
                completion(content="No past evidence found."))
    a = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
                         trace_path=tmp_path/"calls.jsonl", task="find crate", transport=fake)
    p = a.propose(context(), [], turn_id="t", step_index=0)
    result = {"kind":"working_world_memory_search", "strategy":"substring_baseline_not_semantic_retrieval",
              "records":[], "returned":0, "possible_matches":0, "truncated":False,
              "memory_enabled":False}
    outcome = {"proposal_id":p["proposal_id"], "operation_kind":p["operation_kind"],
               "step_index":0, "status":"COMPLETED", "result":result}
    assert a.propose(context(), [outcome], turn_id="t", step_index=1) is None
    assert json.loads(fake.requests[-1]["messages"][-1]["content"]) == result
    assert a.calls[-1]["final_text"] == "No past evidence found."


def test_required_only_first_then_auto():
    fake = Fake(completion("retrieve_memory", '{"query":"crate","top_k":5}'),
                completion(content="No evidence found."))
    s = NativeToolSession(NativeToolCatalog(lab_registry()), model="test",
                          system_prompt="test", user_prompt="test", transport=fake,
                          first_tool_required=True)
    descriptor, _ = s.next()
    result = {"kind":"working_world_memory_search",
              "strategy":"substring_baseline_not_semantic_retrieval",
              "records":[], "returned":0, "possible_matches":0,
              "truncated":False, "memory_enabled":False}
    s.submit_result(descriptor, result)
    assert s.next() is None
    assert [r["tool_choice"] for r in fake.requests] == ["required", "auto"]
    assert fake.requests[1]["messages"][-1]["tool_call_id"] == "id1"


def test_required_rejects_premature_final_answer():
    fake = Fake(completion(content="No evidence."))
    s = NativeToolSession(NativeToolCatalog(lab_registry()), model="test",
                          system_prompt="test", user_prompt="test", transport=fake,
                          first_tool_required=True)
    with pytest.raises(ValueError, match="required first tool call missing"):
        s.next()
    assert not s.calls[-1]["valid"]


def test_required_profile_still_rejects_hidden_source(tmp_path):
    fake = Fake(completion("lookup_raw_evidence", '{"event_ids":["ev_hidden"]}'))
    a = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
                         trace_path=tmp_path/"calls.jsonl", task="find crate", transport=fake,
                         first_tool_required=True)
    assert a.propose(context(), [], turn_id="t", step_index=0) == {"invalid_model_output":True}
    assert fake.requests[0]["tool_choice"] == "required"
    assert not a.calls[-1]["valid"]
