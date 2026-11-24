from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import assess, CASES, CRATE, SHORTCUT


def test_no_tool_case_requires_stop_and_final_response():
    case = next(c for c in CASES if c["id"] == "C09")
    calls = [{"valid":True, "transport_ok":True, "final_text":"4"}]
    assert assess(case, {"status":"STOPPED","outcomes":[]}, [], calls)["operation_gate_pass"]
    assert not assess(case, {"status":"STEP_BUDGET_EXHAUSTED","outcomes":[]}, [], calls)["operation_gate_pass"]
    assert assess(case, {"status":"STOPPED","outcomes":[]}, [], calls)["semantic_review"] == "PENDING"


def test_multi_target_requires_both_verified_entities():
    case = next(c for c in CASES if c["id"] == "C03")
    calls = [{"valid":True, "transport_ok":True, "final_text":"Both verified"}]
    row = {"status":"verified_source_view","entities_observed":[CRATE]}
    report = {"status":"STOPPED","outcomes":[{"status":"COMPLETED",
              "operation_kind":"lookup_raw_evidence","result":{"records":[row]}}]}
    assert not assess(case, report, [], calls)["operation_gate_pass"]
    row["entities_observed"].append(SHORTCUT)
    assert assess(case, report, [], calls)["operation_gate_pass"]
    row["status"] = "not_found"
    assert not assess(case, report, [], calls)["operation_gate_pass"]


def test_negative_requires_actual_matching_empty_search():
    case = next(c for c in CASES if c["id"] == "C02")
    calls = [{"valid":True, "transport_ok":True, "final_text":"No evidence."}]
    report = {"status":"STOPPED","outcomes":[]}
    assert not assess(case, report, [], calls)["operation_gate_pass"]
    outcome = {"status":"COMPLETED","operation_kind":"retrieve_memory","result":{"records":[]}}
    report["outcomes"].append(outcome)
    trace = [{"proposal":{"operation_kind":"retrieve_memory","arguments":{"query":"elephant"}},
              "outcome":outcome}]
    assert assess(case, report, trace, calls)["operation_gate_pass"]
    trace[0]["proposal"]["arguments"]["query"] = "crate"
    assert not assess(case, report, trace, calls)["operation_gate_pass"]
