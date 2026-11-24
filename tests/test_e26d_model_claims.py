import json

import pytest

from labs.virtual_anima_lab.python.cognition.model_claims import parse_final, evaluate_model_claims
from tests.test_e26d_claim_verification import fixture


@pytest.mark.parametrize("text",[
    'plain text',
    '{"answer":"ok","answer":"bad","claims":[]}',
    '{"answer":"ok","claims":[],"extra":true}',
    '{"answer":"","claims":[]}',
    '{"answer":"ok","claims":[{}]}',
    '{"answer":"ok","claims":null}',
])
def test_invalid_envelope(text):
    with pytest.raises((ValueError, TypeError)):
        parse_final(text)


@pytest.mark.parametrize("mode,expected",[
    ("correct","VERIFIED"),("wrong_value","CONTRADICTED"),
    ("wrong_event","UNSUPPORTED"),("wrong_sequence","UNSUPPORTED"),
    ("wrong_scope","UNSUPPORTED"),("wrong_entity","CONTRADICTED"),
])
def test_model_claim_binding(tmp_path,monkeypatch,mode,expected):
    mem,coord,row=fixture(tmp_path,monkeypatch)
    trace=coord.decision_records("proof")
    ctx=trace[0]["context_snapshot"]["context_snapshot_id"]
    report={"status":"STOPPED","turn_id":"proof","context_snapshot_id":ctx}
    item={"entity_ref":"lab.item.crate","predicate":"observed_in_sample","value":True,
          "event_id":row["event_id"],"sample_seq":row["sample_seq"],"scope":"source_sample"}
    changes={"wrong_value":{"value":False},"wrong_event":{"event_id":"ev_hidden"},
             "wrong_sequence":{"sample_seq":row["sample_seq"]+1},
             "wrong_scope":{"scope":"latest_captured_sample"},
             "wrong_entity":{"entity_ref":"lab.item.unknown"}}
    item.update(changes.get(mode,{}))
    calls=[{"valid":True,"transport_ok":True,"finish_reason":"stop","turn_id":"proof",
            "context_snapshot_id":ctx,"final_text":json.dumps({"answer":"unverified prose","claims":[item]})}]
    got=evaluate_model_claims(coord,report,calls)
    assert got["format_status"]=="VALID"
    assert got["verdicts"][0]["status"]==expected
    assert not got["free_text_verified"] and got["task_completion"]=="NOT_ESTABLISHED"
    assert len(mem._core.event_log.load_events())==3
    if mode=="correct":
        assert got["verified_positive_entities"]==["lab.item.crate"]
    else:
        assert got["verified_positive_entities"]==[]


def test_empty_claims_not_equivalent_to_verified_answer():
    obj=parse_final('{"answer":"4","claims":[]}')
    assert obj["claims"]==[]


def test_budget_stop_does_not_accept_final():
    got=evaluate_model_claims(None,{"status":"STEP_BUDGET_EXHAUSTED"},[])
    assert got["format_status"]=="NO_ACCEPTED_FINAL"
