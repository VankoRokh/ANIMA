import pytest

from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceBudget, ResourceLimits
from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement, evaluate_completion
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion


def usage(a=10,b=4):
    return {"input_tokens":a,"output_tokens":b}


@pytest.mark.parametrize("kwargs",[
    {"max_calls":0},{"max_elapsed_ms":True},{"max_reported_input_tokens":-1},
    {"max_reported_output_tokens":1.5},
])
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        ResourceLimits(**kwargs)


def test_reservation_counts_and_output_headroom():
    b=ResourceBudget(ResourceLimits(max_reported_output_tokens=260))
    assert b.reserve()
    assert b.settle(usage(b=5)) is None
    assert not b.reserve()
    assert b.snapshot()["stop_reason"]=="OUTPUT_RESERVATION_LIMIT"
    assert b.calls==1


@pytest.mark.parametrize("record,reason",[
    (None,"USAGE_UNAVAILABLE"),(usage(True,4),"USAGE_UNAVAILABLE"),
    (usage(-1,4),"USAGE_UNAVAILABLE"),(usage(10,257),"OUTPUT_USAGE_EXCEEDED"),
    (usage(8193,4),"INPUT_USAGE_EXCEEDED"),
])
def test_usage_failure_is_terminal(record,reason):
    b=ResourceBudget(ResourceLimits())
    assert b.reserve()
    assert b.settle(record)==reason
    assert not b.reserve()
    assert b.calls==1


def test_elapsed_boundary():
    now=[0.]
    b=ResourceBudget(ResourceLimits(max_elapsed_ms=100),clock=lambda:now[0])
    assert b.reserve()
    now[0]=0.101
    assert b.settle(usage())=="ELAPSED_LIMIT"
    assert not b.reserve()


def test_no_double_reservation():
    b=ResourceBudget(ResourceLimits())
    assert b.reserve()
    with pytest.raises(ValueError):
        b.reserve()
    b.settle(usage())
    with pytest.raises(ValueError):
        b.settle(usage())


@pytest.mark.parametrize("mode",["call_limit","input_exceeded","normal"])
def test_coordinator_budget_keeps_completed_evidence_and_blocks_new_reads(tmp_path,monkeypatch,mode):
    mem=memory(tmp_path,monkeypatch)
    e=next(r for r in mem.world_model()["entities"] if r["entity_ref"]=="lab.item.crate")
    import json
    response=completion("lookup_raw_evidence",json.dumps({"event_ids":[e["last_seen_event_id"]]}))
    limits=ResourceLimits(max_calls=1) if mode=="call_limit" else ResourceLimits()
    if mode=="input_exceeded":
        response["usage"]["prompt_tokens"]=8193
    transport=Fake(response,completion(content="Verified"))
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"calls.jsonl",task="Verify crate",transport=transport)
    coord=E25LabCognitiveCoordinator(mem)
    req=CompletionRequirement("verified_observation",("lab.item.crate",))
    got=coord.run_turn(adapter,turn_id="budget",completion_requirement=req,resource_limits=limits)
    trace=coord.decision_records("budget")
    result=evaluate_completion(req,got,trace)
    assert len(transport.requests)==(2 if mode=="normal" else 1)
    assert got["status"]==("STOPPED" if mode=="normal" else "STEP_BUDGET_EXHAUSTED")
    assert result["information_requirement_satisfied"]==(mode!="input_exceeded")
    assert len(trace)==(0 if mode=="input_exceeded" else 1)
    assert got["resource_budget"]["stop_reason"]=={
        "call_limit":"MODEL_CALL_LIMIT","input_exceeded":"INPUT_USAGE_EXCEEDED","normal":None}[mode]
    assert len(mem._core.event_log.load_events())==3
    assert mem._core.memory_store.count()==0
