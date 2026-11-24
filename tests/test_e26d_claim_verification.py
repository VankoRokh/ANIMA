import pytest
import sqlite3

from labs.virtual_anima_lab.python.cognition.claim_verification import (
    ObservationClaim, ObservationClaimVerifier,
)
from labs.virtual_anima_lab.python.cognition.coordinator import (
    E25LabCognitiveCoordinator, TwoStepEvidenceStub,
)
from tests.test_e25a_cognition import memory, prop

CRATE = "lab.item.crate"

def fixture(tmp_path,monkeypatch):
    mem=memory(tmp_path,monkeypatch)
    coord=E25LabCognitiveCoordinator(mem)
    report=coord.run_turn(TwoStepEvidenceStub(),turn_id="proof")
    row=report["outcomes"][1]["result"]["records"][0]
    return mem,coord,row

def claim(row, predicate="observed_in_sample", value=True, entity=CRATE,
          scope="source_sample"):
    return ObservationClaim(entity,predicate,value,row["event_id"],row["sample_id"],scope)

@pytest.mark.parametrize("predicate,value,status",[
    ("observed_in_sample",True,"VERIFIED"),
    ("observed_in_sample",False,"CONTRADICTED"),
    ("range_milli_cells",1000,"VERIFIED"),
    ("range_milli_cells",3000,"CONTRADICTED"),
    ("bearing_mdeg",10000,"VERIFIED"),
    ("owner_status","absent","VERIFIED"),
    ("owner_status","known","CONTRADICTED"),
])
def test_typed_claim_against_original_view(tmp_path,monkeypatch,predicate,value,status):
    mem,coord,row=fixture(tmp_path,monkeypatch)
    result=ObservationClaimVerifier(coord).verify("proof",claim(row,predicate,value))
    assert result["status"]==status
    assert not result["world_truth_authority"] and not result["knowledge_write"]
    assert len(mem._core.event_log.load_events())==3

def test_historical_cannot_prove_latest(tmp_path,monkeypatch):
    _,coord,row=fixture(tmp_path,monkeypatch)
    result=ObservationClaimVerifier(coord).verify("proof",claim(row,scope="latest_captured_sample"))
    assert result["reason_code"]=="HISTORICAL_SOURCE_NOT_LATEST"

def test_wrong_entity_property_is_unsupported(tmp_path,monkeypatch):
    _,coord,row=fixture(tmp_path,monkeypatch)
    result=ObservationClaimVerifier(coord).verify("proof",claim(row,"range_milli_cells",1000,entity="lab.obstacle.shortcut"))
    assert result["reason_code"]=="ENTITY_NOT_OBSERVED"

def test_memory_without_raw_read_cannot_prove_claim(tmp_path,monkeypatch):
    mem,coord,row=fixture(tmp_path,monkeypatch)
    class SearchOnly:
        def propose(self,context,outcomes,*,turn_id,step_index):
            if outcomes:
                return None
            return prop(context,turn_id,"retrieve_memory",{"query":"crate","top_k":1})
    coord.run_turn(SearchOnly(),turn_id="memory_only")
    verifier=ObservationClaimVerifier(coord)
    assert verifier.verify("memory_only",claim(row))["reason_code"]=="SOURCE_NOT_VERIFIED_IN_TURN"
    assert verifier.verify("unknown_turn",claim(row))["reason_code"]=="SOURCE_NOT_VERIFIED_IN_TURN"

def test_wrong_sample_id_rejected(tmp_path,monkeypatch):
    _,coord,row=fixture(tmp_path,monkeypatch)
    c=ObservationClaim(CRATE,"observed_in_sample",True,row["event_id"],"wrong")
    assert ObservationClaimVerifier(coord).verify("proof",c)["reason_code"]=="SAMPLE_ID_MISMATCH"

def test_latest_not_observed_does_not_prove_absence_in_world(tmp_path,monkeypatch):
    mem,coord,_=fixture(tmp_path,monkeypatch)
    sample_id=mem.world_model()["latest_sample_id"]
    with sqlite3.connect(mem._file) as db:
        event=db.execute("SELECT core_event_id FROM e24_raw WHERE sample_id=?",(sample_id,)).fetchone()[0]
    class Lookup:
        def propose(self,context,outcomes,*,turn_id,step_index):
            if outcomes:
                return None
            return prop(context,turn_id,"lookup_raw_evidence",{"event_ids":[event]})
    report=coord.run_turn(Lookup(),turn_id="latest")
    row=report["outcomes"][0]["result"]["records"][0]
    result=ObservationClaimVerifier(coord).verify("latest",claim(row,value=False,scope="latest_captured_sample"))
    assert result["status"]=="VERIFIED" and not result["world_truth_authority"]

@pytest.mark.parametrize("predicate,value",[("exists_in_world",False),("range_milli_cells",True),("observed_in_sample",1)])
def test_unsupported_claim_shape(predicate,value):
    with pytest.raises(ValueError):
        ObservationClaim(CRATE,predicate,value,"ev_a","sample_a")

def test_canonical_read_failure_never_verifies(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import E24MemoryError
    mem,coord,row=fixture(tmp_path,monkeypatch)
    def broken(_self,_sample):
        raise E24MemoryError("test integrity failure")
    monkeypatch.setattr(type(mem),"raw_evidence",broken)
    assert ObservationClaimVerifier(coord).verify("proof",claim(row))["reason_code"]=="RAW_INTEGRITY_FAILURE"
