import json

import pytest

from labs.virtual_anima_lab.python.cognition.completion import (
    CompletionRequirement, evaluate_completion,
)
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion, session

CRATE = "lab.item.crate"

@pytest.mark.parametrize("mode,budget,expected_calls,expected_status,expected_satisfied",[
    ("repair",4,4,"STOPPED",True),
    ("stop_again",4,3,"STOPPED",False),
    ("budget",2,2,"STOPPED",False),
    ("already_satisfied",4,2,"STOPPED",True),
    ("denied",4,3,"REJECTED",False),
    ("exhausted_after_read",3,3,"STEP_BUDGET_EXHAUSTED",True),
])
def test_host_continuation_keeps_call_budget_and_authority(tmp_path,monkeypatch,mode,budget,
                                                         expected_calls,expected_status,expected_satisfied):
    mem = memory(tmp_path,monkeypatch)
    entity = next(e for e in mem.world_model()["entities"] if e["entity_ref"]==CRATE)
    lookup = completion("lookup_raw_evidence",json.dumps({"event_ids":[entity["last_seen_event_id"]]}),call_id="lookup")
    search = completion("retrieve_memory",'{"query":"crate","top_k":1}',call_id="search")
    stop = completion(content="I have finished.")
    denied = completion("lookup_raw_evidence",'{"event_ids":["ev_hidden"]}',call_id="denied")
    responses = [lookup,stop] if mode=="already_satisfied" else [search,stop]
    if mode in ("repair","exhausted_after_read"):
        responses += [lookup,stop]
    elif mode=="stop_again":
        responses += [stop]
    elif mode=="denied":
        responses += [denied]
    transport=Fake(*responses)
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"calls.jsonl",task="Verify crate observation",transport=transport)
    coord=E25LabCognitiveCoordinator(mem,max_steps=budget)
    req=CompletionRequirement("verified_observation",(CRATE,))
    report=coord.run_turn(adapter,turn_id="continuation",completion_requirement=req)
    trace=coord.decision_records("continuation")
    result=evaluate_completion(req,report,trace)
    assert report["status"]==expected_status
    assert result["information_requirement_satisfied"]==expected_satisfied
    assert len(transport.requests)==len(adapter.calls)==report["model_calls_used"]==expected_calls
    assert len(trace)==len(report["outcomes"])
    assert [r["step_index"] for r in trace]==list(range(len(trace)))
    assert [c["model_call_index"] for c in adapter.calls]==list(range(expected_calls))
    if mode in ("repair","stop_again","denied","exhausted_after_read"):
        assert report["continuation_decisions"][0]["decision"]=="CONTINUE"
        msg=transport.requests[2]["messages"]
        assert msg[-2]=={"role":"assistant","content":"I have finished."}
        feedback=json.loads(msg[-1]["content"])
        assert feedback["reason_code"]=="REQUIRED_SOURCE_NOT_VERIFIED"
        assert "ev_" not in msg[-1]["content"]
        assert transport.requests[2]["tools"]==transport.requests[0]["tools"]
        assert transport.requests[2]["tool_choice"]=="auto"
    if mode=="budget":
        assert report["continuation_decisions"][0]["decision"]=="BUDGET_EXHAUSTED"
    if mode=="already_satisfied":
        assert report["continuation_decisions"]==[]
    assert len(mem._core.event_log.load_events())==3
    assert mem._core.memory_store.count()==0 and mem._core.core_execution is None

def test_invalid_final_cannot_resume():
    s,_=session(completion(content="truncated",finish="length"))
    with pytest.raises(ValueError):
        s.next()
    with pytest.raises(ValueError):
        s.resume_after_stop({"status":"INCOMPLETE"})

def test_no_service_read_objective_never_retries_irreversible_read(tmp_path,monkeypatch):
    mem=memory(tmp_path,monkeypatch)
    fake=Fake(completion("retrieve_memory",'{"query":"crate","top_k":1}'),completion(content="done"))
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"calls.jsonl",task="Arithmetic",transport=fake)
    coord=E25LabCognitiveCoordinator(mem)
    req=CompletionRequirement("no_service_read")
    report=coord.run_turn(adapter,turn_id="no_read",completion_requirement=req)
    assert len(fake.requests)==2 and report["continuation_decisions"]==[]
    assert not evaluate_completion(req,report,coord.decision_records("no_read"))["information_requirement_satisfied"]
