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


def set_catalog():
    return NativeToolCatalog(lab_registry(),
        set_arguments={("lookup_raw_evidence", "1"): ("event_ids",)})


def test_set_projection_keeps_canonical_contract_and_wire_log():
    catalog = set_catalog()
    raw = '{"event_ids":["ev_a","ev_a","ev_b"]}'
    fake = Fake(completion("lookup_raw_evidence", raw))
    s = NativeToolSession(catalog, model="test", system_prompt="test",
                          user_prompt="test", transport=fake)
    d, args = s.next()
    assert args == {"event_ids":["ev_a","ev_b"]}
    assert s.calls[-1]["original_arguments"] == json.loads(raw)
    assert s.calls[-1]["arguments_normalized"]
    assert s.messages[-1]["tool_calls"][0]["function"]["arguments"] == raw
    with pytest.raises(ValueError):
        d.validate_input(json.loads(raw))
    assert "uniqueItems" not in next(x for x in catalog.definitions()
        if x["function"]["name"] == "lookup_raw_evidence")["function"]["parameters"]["properties"]["event_ids"]


@pytest.mark.parametrize("args", [
    {"event_ids":["ev_a"]*17},
    {"event_ids":["ev_a", 1]},
    {"event_ids":[]},
    {"event_ids":["ev_a"], "extra":True},
])
def test_set_projection_validates_original_bounds(args):
    with pytest.raises(ValueError):
        set_catalog().decode("lookup_raw_evidence", json.dumps(args))


def test_set_projection_never_authorizes_unexposed_ids(tmp_path):
    fake = Fake(completion("lookup_raw_evidence", '{"event_ids":["ev_hidden","ev_hidden"]}'))
    a = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        trace_path=tmp_path/"calls.jsonl", task="find", transport=fake, canonical_sets=True)
    assert a.propose(context(), [], turn_id="t", step_index=0) == {"invalid_model_output":True}
    assert a.calls[-1]["arguments_normalized"] and not a.calls[-1]["valid"]


def test_temporal_projection_binds_verified_source_to_latest_sample(tmp_path):
    ctx = {**context(), "memory_enabled":True, "latest_sample_id":"sample3",
           "entities":[{"category":"item","entity_ref":"lab.item.crate",
                        "current_observation":"not_observed","last_seen_event_id":"ev_a",
                        "last_seen_sample":"sample2"}]}
    fake = Fake(completion("lookup_raw_evidence", '{"event_ids":["ev_a"]}'),
                completion(content="Historical observation."))
    a = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        trace_path=tmp_path/"calls.jsonl", task="find", transport=fake, temporal=True)
    p = a.propose(ctx, [], turn_id="t", step_index=0)
    prompt = json.loads(fake.requests[0]["messages"][1]["content"])
    assert prompt["as_of_latest_sample_id"] == "sample3"
    assert prompt["observations"][0]["last_seen_sample_id"] == "sample2"
    result = {"kind":"verified_raw_evidence","records":[
        {"event_id":"ev_a","status":"verified_source_view","sample_id":"sample2"},
        {"event_id":"ev_b","status":"verified_source_view","sample_id":"sample3"},
        {"event_id":"ev_c","status":"not_found"}]}
    outcome = {"proposal_id":p["proposal_id"], "operation_kind":p["operation_kind"],
               "step_index":0,"status":"COMPLETED","result":result}
    assert a.propose(ctx,[outcome],turn_id="t",step_index=1) is None
    projected = json.loads(fake.requests[1]["messages"][-1]["content"])
    assert projected["as_of_sample_id"] == "sample3"
    assert [r["temporal_scope"] for r in projected["records"]] == [
        "historical_sample","latest_captured_sample","unverified"]
    assert "as_of_sample_id" not in result and "temporal_scope" not in result["records"][0]
