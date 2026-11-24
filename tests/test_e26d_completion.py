import pytest

from labs.virtual_anima_lab.python.cognition.completion import (
    CompletionRequirement, evaluate_completion,
)

TURN = "test_turn"
CTX = "ctx_test"
A = "lab.item.a"
B = "lab.item.b"


def fixture(operations=(), status="STOPPED"):
    records = []
    outcomes = []
    for i, (kind, args, result) in enumerate(operations):
        p = {"proposal_id": f"p{i}", "turn_id": TURN, "context_snapshot_id": CTX,
             "operation_kind": kind, "arguments": args}
        o = {"proposal_id": f"p{i}", "step_index": i, "status": "COMPLETED",
             "operation_kind": kind, "result": result}
        outcomes.append(o)
        records.append({"turn_id": TURN, "step_index": i, "context_snapshot": {
            "context_snapshot_id": CTX}, "admission": "ADMITTED", "proposal": p,
            "outcome": o})
    return {"turn_id": TURN, "context_snapshot_id": CTX,
            "status": status, "outcomes": outcomes}, records


def search(query, records=()):
    return ("retrieve_memory", {"query":query,"top_k":1},
            {"kind":"working_world_memory_search", "records":list(records),
             "returned":len(records), "possible_matches":len(records), "truncated":False})


def raw(*entities):
    return ("lookup_raw_evidence", {"event_ids":["ev_a"]},
            {"kind":"verified_raw_evidence", "records":[
                {"event_id":"ev_a","status":"verified_source_view",
                 "entities_observed":list(entities)}]})


def evaluate(requirement, operations=(), status="STOPPED"):
    return evaluate_completion(requirement,*fixture(operations,status))


def test_memory_record_is_not_verified_observation():
    got=evaluate(CompletionRequirement("verified_observation",(A,)),
                 [search("a",[{"entity_ref":A,"last_seen_event_id":"ev_a"}])])
    assert got["model_stopped"] and not got["information_requirement_satisfied"]
    assert got["missing_entities"] == [A]
    assert got["claim_verification"] == "NOT_PERFORMED"


def test_wrong_entity_with_valid_source_does_not_complete():
    got=evaluate(CompletionRequirement("verified_observation",(A,B)),[raw(B)])
    assert not got["information_requirement_satisfied"]
    assert got["missing_entities"] == [A]


def test_evidence_and_terminal_status_are_independent():
    got=evaluate(CompletionRequirement("verified_observation",(A,B)),[raw(A,B)],
                 "STEP_BUDGET_EXHAUSTED")
    assert got["information_requirement_satisfied"] and not got["model_stopped"]
    assert got["task_completion"] == "NOT_ESTABLISHED"
    assert got["verified_sources_by_entity"] == {A:["ev_a"],B:["ev_a"]}


def test_empty_search_remains_empty_search_after_other_reads():
    got=evaluate(CompletionRequirement("empty_search",query="Elephant"),
                 [search(" elephant "),raw(B)])
    assert got["information_requirement_satisfied"]
    assert got["completed_service_reads"] == 2
    assert got["claim_verification"] == "NOT_PERFORMED"


def test_wrong_or_truncated_search_is_not_confirmed_empty():
    req=CompletionRequirement("empty_search",query="elephant")
    assert not evaluate(req,[search("not elephant")])["information_requirement_satisfied"]
    op=search("elephant")
    op[2]["truncated"]=True
    assert not evaluate(req,[op])["information_requirement_satisfied"]


def test_no_read_is_not_proof_of_correct_answer():
    req=CompletionRequirement("no_service_read")
    got=evaluate(req)
    assert got["information_requirement_satisfied"]
    assert got["task_completion"] == "NOT_ESTABLISHED"
    assert not evaluate(req,[raw(A)])["information_requirement_satisfied"]


def test_rejected_step_does_not_supply_evidence():
    report,trace=fixture([raw(A)])
    report["outcomes"][0]["status"]="REJECTED"
    trace[0]["admission"]="REJECTED"
    got=evaluate_completion(CompletionRequirement("verified_observation",(A,)),report,trace)
    assert not got["information_requirement_satisfied"]
    assert got["rejected_steps"]==1 and got["completed_service_reads"]==0


@pytest.mark.parametrize("corruption",["missing","context","source","turn"])
def test_inconsistent_trace_rejected(corruption):
    report,trace=fixture([raw(A)])
    if corruption=="missing":
        trace=[]
    elif corruption=="context":
        trace[0]["context_snapshot"]["context_snapshot_id"]="other"
    elif corruption=="source":
        report["outcomes"][0]["result"]["records"][0]["event_id"]="ev_other"
    else:
        trace[0]["turn_id"]="other"
    with pytest.raises(ValueError):
        evaluate_completion(CompletionRequirement("verified_observation",(A,)),report,trace)


@pytest.mark.parametrize("kind,entities,query",[
    ("unknown",(),""),
    ("verified_observation",(),""),
    ("verified_observation",(A,A),""),
    ("empty_search",()," "),
    ("no_service_read",(A,),""),
])
def test_invalid_requirement_rejected(kind,entities,query):
    with pytest.raises(ValueError):
        CompletionRequirement(kind,entities,query)
