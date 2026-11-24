import json
from copy import deepcopy

import pytest

from labs.virtual_anima_lab.python.cognition.contracts import CognitiveStepProposal
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.source_binding import admitted_source_rows
from labs.virtual_anima_lab.python.cognition.claim_verification import ObservationClaim, ObservationClaimVerifier
from labs.virtual_anima_lab.python.cognition.model_claims import evaluate_model_claims
from tests.test_e25a_cognition import memory, prop
from tests.test_e26a_native_tools import Fake, completion


@pytest.mark.parametrize("enabled", [True,False])
def test_latest_source_is_frozen_and_available_without_history(tmp_path,monkeypatch,enabled):
    mem=memory(tmp_path,monkeypatch)
    fake=Fake(completion("inspect_latest_observation","{}"),completion(content="Done"))
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"calls.jsonl",task="inspect latest observation",transport=fake,
        temporal=True,compact_temporal=True,latest_observation=True)
    coord=E25LabCognitiveCoordinator(mem,latest_observation=True)
    report=coord.run_turn(adapter,turn_id="latest",memory_enabled=enabled)
    assert report["status"]=="STOPPED"
    rec=coord.decision_records("latest")[0]
    row,=admitted_source_rows(rec)
    assert row["sample_seq"]==3 and row["sample_id"]==rec["context_snapshot"]["latest_sample_id"]
    assert "lab.item.crate" not in row["entities_observed"]
    returned=json.loads(fake.requests[1]["messages"][-1]["content"])
    assert returned["records"][0]["temporal_scope"]=="latest_captured_sample"
    assert returned["records"][0]["event_id"]==row["event_id"]
    assert "sample_id" not in returned["records"][0]
    claim=ObservationClaim("lab.item.crate","observed_in_sample",False,row["event_id"],row["sample_id"],"latest_captured_sample")
    verifier=ObservationClaimVerifier(coord)
    assert verifier.verify("latest",claim)["status"]=="VERIFIED"
    assert not verifier.verify("latest",claim)["world_truth_authority"]
    wire={"entity_ref":"lab.item.crate","predicate":"observed_in_sample","value":False,
          "event_id":row["event_id"],"sample_seq":3,"scope":"latest_captured_sample"}
    call={"valid":True,"transport_ok":True,"finish_reason":"stop","turn_id":"latest",
          "context_snapshot_id":report["context_snapshot_id"],
          "final_text":json.dumps({"answer":"Not observed in latest sample","claims":[wire]})}
    assert evaluate_model_claims(coord,report,[call])["verdicts"][0]["status"]=="VERIFIED"
    assert len(mem._core.event_log.load_events())==3
    assert mem._core.memory_store.count()==0


def test_latest_operation_requires_host_admission(tmp_path,monkeypatch):
    mem=memory(tmp_path,monkeypatch)
    class Adapter:
        def propose(self,context,outcomes,*,turn_id,step_index):
            return prop(context,turn_id,"inspect_latest_observation",{})
    coord=E25LabCognitiveCoordinator(mem)
    report=coord.run_turn(Adapter(),turn_id="blocked")
    assert report["status"]=="REJECTED"
    assert report["outcomes"][0]["reason_code"]=="OPERATION_UNAVAILABLE"


@pytest.mark.parametrize("args",[{"event_id":"ev_hidden"},{"sample_seq":2},{"path":"/tmp/raw"}])
def test_latest_tool_cannot_choose_source(args):
    ctx={"context_snapshot_id":"ctx_test"}
    with pytest.raises(ValueError):
        CognitiveStepProposal(prop(ctx,"turn","inspect_latest_observation",args))


@pytest.mark.parametrize("field,value",[
    ("sample_seq",2),("sample_id","worldobs:foreign:1:3"),("source_ref","foreign"),
])
def test_wrong_latest_binding_not_eligible(tmp_path,monkeypatch,field,value):
    mem=memory(tmp_path,monkeypatch)
    class Adapter:
        def propose(self,context,outcomes,*,turn_id,step_index):
            return None if outcomes else prop(context,turn_id,"inspect_latest_observation",{})
    coord=E25LabCognitiveCoordinator(mem,latest_observation=True)
    coord.run_turn(Adapter(),turn_id="source")
    rec=deepcopy(coord.decision_records("source")[0])
    assert admitted_source_rows(rec)
    rec["outcome"]["result"]["records"][0][field]=value
    assert not admitted_source_rows(rec)


def test_missing_raw_cannot_supply_latest(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import E24MemoryError
    mem=memory(tmp_path,monkeypatch)
    def broken(self,sample_id):
        raise E24MemoryError("missing")
    monkeypatch.setattr(type(mem),"raw_evidence",broken)
    class Adapter:
        def propose(self,context,outcomes,*,turn_id,step_index):
            return prop(context,turn_id,"inspect_latest_observation",{})
    coord=E25LabCognitiveCoordinator(mem,latest_observation=True)
    report=coord.run_turn(Adapter(),turn_id="missing")
    assert report["status"]=="REJECTED"
    assert not admitted_source_rows(coord.decision_records("missing")[0])
