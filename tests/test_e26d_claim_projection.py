import json

import pytest

from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter, SYSTEM
from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
from labs.virtual_anima_lab.python.cognition.model_claims import evaluate_model_claims
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion


@pytest.mark.parametrize("mode",["success","budget","tool_attempt","wrong_scope","incomplete","usage_exceeded"])
def test_separate_claim_projection(tmp_path,monkeypatch,mode):
    mem=memory(tmp_path,monkeypatch)
    entity=next(e for e in mem.world_model()["entities"] if e["entity_ref"]=="lab.item.crate")
    event=entity["last_seen_event_id"]
    lookup=completion("lookup_raw_evidence",json.dumps({"event_ids":[event]}))
    final=completion(content="The crate was observed in the past.")
    claim={"entity_ref":"lab.item.crate","predicate":"observed_in_sample","value":True,
           "event_id":event,"sample_seq":2,
           "scope":"latest_captured_sample" if mode=="wrong_scope" else "source_sample"}
    projection=completion(content=json.dumps({"answer":"Past observation","claims":[claim]}))
    if mode=="tool_attempt":
        projection=completion("lookup_raw_evidence",json.dumps({"event_ids":[event]}))
    elif mode=="usage_exceeded":
        projection["usage"]["prompt_tokens"]=9000
    responses=[lookup,final,projection] if mode!="incomplete" else [final,final]
    fake=Fake(*responses)
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"calls.jsonl",task="Verify prior crate observation",transport=fake)
    coord=E25LabCognitiveCoordinator(mem)
    report=coord.run_turn(adapter,turn_id="separated",
        completion_requirement=CompletionRequirement("verified_observation",("lab.item.crate",)),
        resource_limits=ResourceLimits(max_calls=2 if mode=="budget" else 4),
        project_result_claims=True)
    result=report["claim_projection"]
    assert fake.requests[0]["messages"][0]["content"]==SYSTEM
    assert report["status"]=="STOPPED"
    assert report["resource_budget"]["reserved_calls"]==len(fake.requests)
    assert len(adapter.calls)==2
    assert len(coord.decision_records("separated"))==(0 if mode=="incomplete" else 1)
    assert len(mem._core.event_log.load_events())==3
    assert mem._core.memory_store.count()==0
    if mode in ("budget","incomplete"):
        assert len(fake.requests)==2 and result["call"] is None
        assert result["status"]==("BUDGET_UNAVAILABLE" if mode=="budget" else "INFORMATION_INCOMPLETE")
    else:
        assert len(fake.requests)==3
        assert "tools" not in fake.requests[-1]
        assert "tool_choice" not in fake.requests[-1]
        assert result["call"]["model_call_index"]==2
        if mode in ("tool_attempt","usage_exceeded"):
            assert result["status"]==("INVALID_RESPONSE" if mode=="tool_attempt" else "RESOURCE_REJECTED")
            assert not result["call"]["valid"]
        else:
            assert result["status"]=="GENERATED"
            evaluated=evaluate_model_claims(coord,report,[result["call"]])
            assert evaluated["verdicts"][0]["status"]==("UNSUPPORTED" if mode=="wrong_scope" else "VERIFIED")
