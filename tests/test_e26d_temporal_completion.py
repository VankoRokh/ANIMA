import json
import pytest

from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement, evaluate_completion
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
from labs.virtual_anima_lab.python.cognition.model_claims import evaluate_model_claims, temporal_claim_coverage
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion
from tests.test_e26d_completion import fixture

ENTITY = "lab.item.crate"
OTHER = "lab.item.other"
PREFIX = "worldobs:fixture:1:"
REQ = CompletionRequirement("historical_and_latest_observation",(ENTITY,))


def source(seq, entities, latest_tool=False):
    event = "ev_" + str(seq)
    return ("inspect_latest_observation" if latest_tool else "lookup_raw_evidence",
            {} if latest_tool else {"event_ids":[event]},
            {"kind":"verified_raw_evidence","records":[{
                "event_id":event,"sample_id":PREFIX+str(seq),"sample_seq":seq,
                "source_ref":"vision","status":"verified_source_view",
                "entities_observed":list(entities)}]})


@pytest.mark.parametrize("ops,missing,satisfied",[
    ([],["VERIFIED_HISTORICAL_OBSERVATION","VERIFIED_LATEST_CAPTURED_SAMPLE"],False),
    ([source(2,[ENTITY])],["VERIFIED_LATEST_CAPTURED_SAMPLE"],False),
    ([source(3,[ENTITY],True)],["VERIFIED_HISTORICAL_OBSERVATION"],False),
    ([source(2,[OTHER]),source(3,[],True)],["VERIFIED_HISTORICAL_OBSERVATION"],False),
    ([source(2,[ENTITY]),source(3,[],True)],[],True),
    ([source(2,[ENTITY]),source(3,[ENTITY])],[],True),
    ([source(2,[ENTITY]),source(2,[],True)],["VERIFIED_LATEST_CAPTURED_SAMPLE"],False),
])
def test_temporal_completion(ops,missing,satisfied):
    report,trace=fixture(ops)
    for rec in trace:
        rec["context_snapshot"].update(world_instance_id="fixture",epoch=1,
                                      latest_sample_id=PREFIX+"3",source_ref="vision")
    got=evaluate_completion(REQ,report,trace)
    assert got["missing_requirements"]==missing
    assert got["information_requirement_satisfied"] is satisfied
    if satisfied:
        assert got["latest_observed_by_entity"][ENTITY] is (ENTITY in ops[-1][2]["records"][0]["entities_observed"])
    assert got["task_completion"]=="NOT_ESTABLISHED"


@pytest.mark.parametrize("mode",["continue","projection","history_claim_only","stop_incomplete"])
def test_live_contract_with_scripted_transport(tmp_path,monkeypatch,mode):
    mem=memory(tmp_path,monkeypatch)
    entity=next(e for e in mem.world_model()["entities"] if e["entity_ref"]==ENTITY)
    historical_event=entity["last_seen_event_id"]
    from contextlib import closing
    latest_id=mem.world_model()["latest_sample_id"]
    with closing(mem._connect()) as db:
        latest_event=db.execute("SELECT core_event_id FROM e24_raw WHERE sample_id=?",
            (latest_id,)).fetchone()["core_event_id"]
    past=completion("lookup_raw_evidence",json.dumps({"event_ids":[historical_event]}),call_id="past")
    latest=completion("inspect_latest_observation","{}",call_id="latest")
    stop=completion(content="The crate was previously observed.")
    historical_claim={"entity_ref":ENTITY,"predicate":"observed_in_sample","value":True,
                      "event_id":historical_event,"sample_seq":2,"scope":"source_sample"}
    latest_claim={"entity_ref":ENTITY,"predicate":"observed_in_sample","value":False,
                  "event_id":latest_event,"sample_seq":3,"scope":"latest_captured_sample"}
    claims=[historical_claim] if mode=="history_claim_only" else [historical_claim,latest_claim]
    projection=completion(content=json.dumps({"answer":"Historical and latest evidence","claims":claims}))
    responses=([past,stop,latest,stop] if mode=="continue" else
               [past,stop,stop] if mode=="stop_incomplete" else
               [past,latest,stop,projection])
    transport=Fake(*responses)
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"calls.jsonl",task="Compare past and latest observations",
        transport=transport,temporal=True,compact_temporal=True,latest_observation=True)
    coord=E25LabCognitiveCoordinator(mem,latest_observation=True)
    report=coord.run_turn(adapter,turn_id="temporal",completion_requirement=REQ,
                          resource_limits=ResourceLimits(),project_result_claims=True)
    result=evaluate_completion(REQ,report,coord.decision_records("temporal"))
    assert result["information_requirement_satisfied"] is (mode!="stop_incomplete")
    assert len(transport.requests)==report["resource_budget"]["reserved_calls"]==(3 if mode=="stop_incomplete" else 4)
    assert report["status"]=="STOPPED"
    if mode in ("continue","stop_incomplete"):
        feedback=json.loads(transport.requests[2]["messages"][-1]["content"])
        assert feedback["missing_requirements"]==["VERIFIED_LATEST_CAPTURED_SAMPLE"]
        assert report["claim_projection"]["status"]==("BUDGET_UNAVAILABLE" if mode=="continue" else "INFORMATION_INCOMPLETE")
    else:
        evaluated=evaluate_model_claims(coord,report,[report["claim_projection"]["call"]])
        assert all(v["status"]=="VERIFIED" for v in evaluated["verdicts"])
        assert temporal_claim_coverage(result,evaluated) is (mode=="projection")
    assert len(mem._core.event_log.load_events())==3
    assert mem._core.memory_store.count()==0
