"""R9.4.1a measurements on the unchanged C01–C14 mechanisms."""
from copy import deepcopy
import json

import pytest

from labs.virtual_anima_lab.python.cognition.observable import (
    measure_turn, ControlledServiceUnavailable, diagnose_before_context,
)
from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
from labs.virtual_anima_lab.python.cognition.coordinator import _read_only_result
from tests.test_e26_r940_cycle_characterization import (
    memory, run, crate_event, lookup, search, completion, OBS, TEMPORAL, CRATE,
)

BASELINE = "0cde809a9d0f5495d93706a25a9dbe404cc48515"


def measured(coord, report, adapter, case, **kwargs):
    return measure_turn(coord, report, calls=adapter.calls, baseline_sha=BASELINE,
                        case_id=case, requirement=kwargs.pop("requirement", OBS), **kwargs)


@pytest.mark.parametrize("case", ["C01", "C02", "C03", "C04", "C05", "C08", "C09", "C14"])
def test_exact_cycle_measurements(case, tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    event = crate_event(mem)
    req, enabled = OBS, True
    if case == "C01":
        replies = [search(), completion(content="done"), completion(content="done again")]
        expected = (1, 0, 0, 0, 0, None, 0, 3)
    elif case == "C02":
        replies = [lookup(event, f"r{i}") for i in range(4)]
        expected = (4, 1, 3, 0, 1, 1, 3, 4)
    elif case in ("C03", "C09"):
        req = TEMPORAL
        latest = mem.raw_evidence(mem.context_for_cognition()["latest_sample_id"])
        with mem._connect() as db:
            latest_event = db.execute("SELECT core_event_id FROM e24_raw WHERE sample_id=?",
                                      (latest.as_dict()["sample_id"],)).fetchone()[0]
        replies = [lookup(event, "past"), completion("inspect_latest_observation", "{}", call_id="latest")]
        if case == "C03":
            replies.append(lookup(latest_event, "again"))
        replies.append(completion(content="done"))
        expected = ((3, 2, 0, 1, 2, 2, 1, 4) if case == "C03"
                    else (2, 2, 0, 0, 2, 2, 0, 3))
    elif case == "C04":
        req, enabled = CompletionRequirement("empty_search", query="crate"), False
        replies = [search(), completion(content="uncertain")]
        expected = (1, 0, 0, 0, 0, 1, 0, 2)
    elif case == "C05":
        enabled = False
        replies = [search("a"), completion(content="uncertain"), search("b"), completion(content="uncertain")]
        expected = (2, 0, 0, 0, 0, None, 0, 4)
    elif case == "C08":
        replies = [search(), completion(content="done"), completion(content="done")]
        expected = (1, 0, 0, 0, 0, None, 0, 3)
    else:
        entity = next(e["entity_ref"] for e in mem.world_model()["entities"]
                      if e["current_observation"] == "observed")
        req = CompletionRequirement("verified_observation", (entity,))
        replies = [completion("inspect_latest_observation", "{}", call_id="latest"),
                   completion(content="done"), completion(content="done")]
        expected = (1, 1, 0, 0, 0, None, 0, 3)
    coord, report, records, adapter, wire = run(mem, tmp_path, replies, requirement=req, enabled=enabled)
    before = deepcopy((report, records, adapter.calls, wire.requests))
    got = measured(coord, report, adapter, case, requirement=req)
    (tmp_path / f"observable-{case}.json").write_text(json.dumps(got,ensure_ascii=False,sort_keys=True)+"\n")
    final = got["prefixes"][-1]
    assert (final["acquisition"]["completed"], final["evidence"]["unique_sources"],
            final["redundancy"]["same_tool"], final["redundancy"]["cross_tool"],
            final["verified_fact_count"], got["sufficiency"]["first_operation_prefix"],
            got["sufficiency"]["research_calls_after"], final["resources"]["research"]["calls"]) == expected
    assert got["schema"] == "anima.lab.observable_cognitive_state/0.1"
    assert (report, coord.decision_records(report["turn_id"]), adapter.calls, wire.requests) == before
    assert got["model_facing_authority"] is False
    if case in ("C04", "C05"):
        assert final["availability"]["state"] == "DISABLED_BY_POLICY"
    if case == "C05":
        assert final["search_outcome_count"] == 1
        assert got["continuation"][0]["productive"] is False
    if case == "C08":
        assert final["gain"]["exposed_ids"] == 0
        assert final["gain"]["search_outcomes"] == 0  # stop prefixes retain no new search outcome
        assert got["prefixes"][1]["gain"]["search_outcomes"] == 1
    if case == "C09":
        assert final["verification"]["raw_rereads"] > 0
        assert final["acquisition"]["attempts"] == 2
    if case == "C14":
        assert final["coverage"]["covered"] == 0
        assert final["completion"]["information_requirement_satisfied"] is False


@pytest.mark.parametrize("query,count", [("crate", 1), ("box", 0), ("ящик", 0), ("cr", 0)])
def test_c06_search_outcomes_not_world_absence(query, count, tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    req = CompletionRequirement("empty_search", query=query)
    coord, report, _, adapter, _ = run(mem, tmp_path, [
        completion("retrieve_memory", json.dumps({"query":query,"top_k":1}), call_id="s"),
        completion(content="done"), completion(content="done")], requirement=req)
    final = measured(coord, report, adapter, "C06", requirement=req)["prefixes"][-1]
    assert final["searches"][0]["returned"] == count
    assert final["availability"]["state"] == "AVAILABLE_IN_SCOPE"
    assert final["availability"]["scope"]["world_absence"] is False
    assert final["evidence"]["unique_sources"] == 0


def test_c07_truncated_scope_and_c12_unknown_usage(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord, report, _, adapter, _ = run(mem, tmp_path, [
        completion("retrieve_memory", '{"query":"lab","top_k":1}', call_id="s"),
        completion(content="done"), completion(content="done")])
    got = measured(coord, report, adapter, "C07")
    assert got["prefixes"][-1]["availability"]["state"] == "PARTIAL_OR_TRUNCATED"
    calls = deepcopy(adapter.calls)
    calls[0]["input_tokens"] = None
    got = measure_turn(coord, report, calls=calls, baseline_sha=BASELINE, case_id="C12", requirement=None)
    assert got["prefixes"][-1]["resources"]["research"]["missing_input_tokens"] == 1
    assert got["prefixes"][-1]["coverage"]["status"] == "NOT_ASSESSED"


def test_prefix_does_not_use_future_sources_verdicts_or_terminal_status(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord, report, _, adapter, _ = run(mem, tmp_path, [search(), lookup(crate_event(mem), "r"), completion(content="done")])
    got = measured(coord, report, adapter, "prefix")
    assert [p["evidence"]["unique_sources"] for p in got["prefixes"]] == [0, 0, 1, 1]
    assert [p["verified_fact_count"] for p in got["prefixes"]] == [0, 0, 1, 1]
    assert [p["coverage"]["covered"] for p in got["prefixes"]] == [0, 0, 1, 1]
    assert got["prefixes"][1]["completion"]["information_requirement_satisfied"] is False
    assert "model_stopped" not in got["prefixes"][1]["completion"]
    assert got["prefixes"][0]["verification"]["raw_rereads"] == 0


def test_inconsistent_sources_fail_closed_even_if_future_conflict(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord, report, _, adapter, _ = run(mem, tmp_path, [lookup(crate_event(mem), "a"), lookup(crate_event(mem), "b"), completion(content="done")])
    original = coord.decision_records
    bad = original(report["turn_id"])
    bad[1]["outcome"]["result"]["records"][0]["raw_sha256"] = "0" * 64
    altered = deepcopy(report)
    altered["outcomes"][1] = bad[1]["outcome"]
    monkeypatch.setattr(coord, "decision_records", lambda turn: deepcopy(bad))
    with pytest.raises(ValueError, match="INCONSISTENT_SOURCE"):
        measured(coord, altered, adapter, "negative")


def test_c13_diagnostic_is_bounded_and_does_not_catch_programming_errors():
    exc = ControlledServiceUnavailable("memory", "DEPENDENCY_OFFLINE", {"source_ref":"s"})
    result = diagnose_before_context(exc, turn_id="t", case_id="C13", baseline_sha=BASELINE)
    assert result["availability"]["state"] == "SERVICE_UNAVAILABLE"
    assert result["context_status"] == "NOT_FORMED"
    assert not ({"cognitive_result", "facts", "sources", "model_calls"} & result.keys())
    for error in (KeyError("bug"), RuntimeError("arbitrary")):
        with pytest.raises(TypeError):
            diagnose_before_context(error, turn_id="t", case_id="C13", baseline_sha=BASELINE)


def test_no_service_read_sufficiency_is_not_monotone(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    req = CompletionRequirement("no_service_read")
    coord, report, _, adapter, _ = run(mem, tmp_path, [search(), completion(content="done")], requirement=req)
    got = measured(coord, report, adapter, "nonmonotone", requirement=req)
    assert got["prefixes"][0]["coverage"]["covered"] == 1
    assert got["prefixes"][-1]["coverage"]["covered"] == 0
    assert got["sufficiency"]["first_operation_prefix"] == 0
    assert got["sufficiency"]["remained_satisfied"] is False


def test_equal_raw_hash_is_not_event_identity():
    from labs.virtual_anima_lab.python.cognition.observable import source_identity
    context = {"world_instance_id":"world","epoch":1}
    first = {"source_ref":"s","event_id":"e1","sample_id":"a","raw_sha256":"1"*64}
    second = {**first,"event_id":"e2","sample_id":"b"}
    assert source_identity(context,first) != source_identity(context,second)


def test_integrity_and_generic_service_rejection_are_distinct(tmp_path, monkeypatch):
    from labs.virtual_anima_lab.python.cognition.observable import availability
    from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import E24MemoryError
    result = diagnose_before_context(E24MemoryError("bad digest"),turn_id="t",case_id="C13",baseline_sha=BASELINE)
    assert result["availability"]["state"] == "INTEGRITY_REJECTED"
    assert availability(None,rejected_reason="SERVICE_REJECTED")["state"] == "UNKNOWN"
    # No exception message or source data is promoted to verified output.
    assert "bad digest" not in json.dumps(result)


def test_stop_prefix_never_acquires_the_future_read(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord, report, _, adapter, _ = run(mem,tmp_path,[search(),completion(content="uncertain"),lookup(crate_event(mem),"later"),completion(content="done")])
    got = measured(coord,report,adapter,"prefix-stop")
    assert [(p["operation_prefix"],p["evidence"]["unique_sources"]) for p in got["prefixes"]] == [(0,0),(1,0),(1,0),(2,1),(2,1)]
    assert got["continuation"][0]["productive"] is True
    assert got["continuation"][0]["calls_to_coverage_gain"] == 1


def test_missing_calls_are_unknown_not_zero(tmp_path, monkeypatch):
    mem = memory(tmp_path,monkeypatch)
    coord,report,_,adapter,_ = run(mem,tmp_path,[lookup(crate_event(mem),"r"),completion(content="done")])
    got = measure_turn(coord,report,baseline_sha=BASELINE,case_id="unknown",requirement=OBS)
    assert got["prefixes"][-1]["resources"] == {"status":"UNKNOWN"}
    assert got["sufficiency"]["research_calls_after"] is None
    assert got["prefixes"][-1]["call_prefix"] is None


@pytest.mark.parametrize("field,value",[("raw_sha256","0"*64),("sample_id","worldobs:forged:1:3"),
    ("source_ref","forged"),("entities_observed",[]),("event_id","ev_forged")])
def test_inconsistent_source_negatives(field,value,tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.source_policy import E25CognitionError
    mem = memory(tmp_path,monkeypatch)
    coord,report,_,adapter,_ = run(mem,tmp_path,[lookup(crate_event(mem),"r"),completion(content="done")])
    records = coord.decision_records(report["turn_id"])
    bad = deepcopy(report)
    records[0]["outcome"]["result"]["records"][0][field] = value
    bad["outcomes"][0] = records[0]["outcome"]
    monkeypatch.setattr(coord,"decision_records",lambda turn:deepcopy(records))
    with pytest.raises((ValueError,E25CognitionError)):
        measured(coord,bad,adapter,"integrity-negative")


def test_rejected_model_call_after_sufficiency_keeps_known_usage(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
    from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
    from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
    from tests.test_e26a_native_tools import Fake
    mem=memory(tmp_path,monkeypatch)
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",trace_path=tmp_path/"calls.jsonl",
        task="Check",transport=Fake(lookup(crate_event(mem),"r")),temporal=True,compact_temporal=True,latest_observation=True)
    coord=E25LabCognitiveCoordinator(mem,max_steps=4,ranked=True,latest_observation=True)
    report=coord.run_turn(adapter,turn_id="failed",completion_requirement=OBS,resource_limits=ResourceLimits())
    got=measured(coord,report,adapter,"failure-after-sufficient")
    assert got["sufficiency"]["research_model_calls_after"] == 1
    assert got["sufficiency"]["presentation_calls_after"] == 0
    assert got["prefixes"][-1]["resources"]["research"]["missing_input_tokens"] == 1
    assert got["prefixes"][-1]["acquisition"]["completed"] == 1


def test_new_verified_predicate_has_gain_without_new_event_ids(tmp_path,monkeypatch):
    mem=memory(tmp_path,monkeypatch)
    event=crate_event(mem)
    text=json.dumps({"answer":"Captured bearing", "claims":[{"entity_ref":CRATE,"predicate":"bearing_mdeg",
        "value":10000,"event_id":event,"sample_seq":2,"scope":"source_sample"}]})
    coord,report,_,adapter,_=run(mem,tmp_path,[lookup(event,"r"),completion(content=text)])
    got=measured(coord,report,adapter,"predicate-gain",claim_phase="research")
    assert [p["verified_fact_count"] for p in got["prefixes"]] == [0,1,2]
    assert got["prefixes"][-1]["gain"]["evidence"] == 0
    assert got["prefixes"][-1]["gain"]["verified_facts"] == 1
    assert got["prefixes"][-1]["facts_by_origin"]["MODEL_CANDIDATE_VERIFIED"] == 1


def test_later_read_does_not_reverify_an_earlier_model_claim(tmp_path,monkeypatch):
    mem=memory(tmp_path,monkeypatch)
    event=crate_event(mem)
    text=json.dumps({"answer":"Claim before verification", "claims":[{"entity_ref":CRATE,"predicate":"bearing_mdeg",
        "value":10000,"event_id":event,"sample_seq":2,"scope":"source_sample"}]})
    coord,report,_,adapter,_=run(mem,tmp_path,[completion(content=text),lookup(event,"r"),completion(content="done")])
    got=measured(coord,report,adapter,"no-retro-verdict",claim_phase="research")
    assert [p["verified_fact_count"] for p in got["prefixes"]] == [0,0,1,1]
    assert all(p["facts_by_origin"]["MODEL_CANDIDATE_VERIFIED"] == 0 for p in got["prefixes"])
    assert got["prefixes"][1]["verification"]["verdicts"]["MODEL_CANDIDATE|UNSUPPORTED|SOURCE_SEQUENCE_NOT_BOUND"] == 1


def test_incomplete_stop_only_call_trace_is_rejected(tmp_path,monkeypatch):
    mem=memory(tmp_path,monkeypatch)
    req=CompletionRequirement("no_service_read")
    coord,report,_,adapter,_=run(mem,tmp_path,[completion(content="done")],requirement=req)
    with pytest.raises(ValueError,match="call count"):
        measure_turn(coord,report,calls=[],baseline_sha=BASELINE,case_id="missing-calls",requirement=req)


def test_claim_projection_has_fact_gain_but_no_new_acquisition(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
    from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
    from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
    from tests.test_e26a_native_tools import Fake
    mem=memory(tmp_path,monkeypatch)
    event=crate_event(mem)
    text=json.dumps({"answer":"Captured bearing", "claims":[{"entity_ref":CRATE,"predicate":"bearing_mdeg",
        "value":10000,"event_id":event,"sample_seq":2,"scope":"source_sample"}]})
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",trace_path=tmp_path/"calls.jsonl",task="Check",
        transport=Fake(lookup(event,"r"),completion(content="done"),completion(content=text)),
        temporal=True,compact_temporal=True,latest_observation=True)
    coord=E25LabCognitiveCoordinator(mem,ranked=True,latest_observation=True)
    report=coord.run_turn(adapter,turn_id="projection",completion_requirement=OBS,resource_limits=ResourceLimits(),project_result_claims=True)
    calls=[*adapter.calls,report["claim_projection"]["call"]]
    got=measure_turn(coord,report,baseline_sha=BASELINE,case_id="projection",requirement=OBS,calls=calls,claim_phase="claim_projection")
    assert [p["verified_fact_count"] for p in got["prefixes"]] == [0,1,1,2]
    assert got["prefixes"][-1]["acquisition"]["completed"] == 1
    assert got["prefixes"][-1]["resources"]["model_claim_projection"]["calls"] == 1
    assert got["prefixes"][-1]["gain"]["evidence"] == 0
    assert got["prefixes"][-1]["gain"]["verified_facts"] == 1
    with pytest.raises(ValueError,match="projection call count"):
        measure_turn(coord,report,baseline_sha=BASELINE,case_id="incomplete",requirement=OBS,calls=adapter.calls)


def test_c12_generated_attempt_before_journal_is_not_lost(tmp_path,monkeypatch):
    from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
    from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
    from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
    from tests.test_e26a_native_tools import Fake
    mem=memory(tmp_path,monkeypatch)
    context=mem.context_for_cognition()
    reply=lookup(crate_event(mem),"over-budget")
    reply["usage"]["prompt_tokens"]=8193
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",trace_path=tmp_path/"calls.jsonl",task="Check",
        transport=Fake(reply),temporal=True,compact_temporal=True,latest_observation=True)
    coord=E25LabCognitiveCoordinator(mem)
    report=coord.run_turn(adapter,turn_id="c12",completion_requirement=OBS,resource_limits=ResourceLimits())
    assert coord.decision_records("c12") == []
    got=measure_turn(coord,report,baseline_sha=BASELINE,case_id="C12",requirement=OBS,calls=adapter.calls,
        frozen_context={**context,"context_snapshot_id":report["context_snapshot_id"]})
    final=got["prefixes"][-1]
    assert final["acquisition"]["attempts"] == 1
    assert final["acquisition"]["journaled_attempts"] == 0
    assert len(final["acquisition"]["unrecorded_generated_proposals"]) == 1
    assert final["acquisition"]["completed"] == 0
    assert final["evidence"]["unique_sources"] == 0
    assert final["verification"]["raw_rereads"] == 0
    assert final["resources"]["research"]["known_input_tokens"] == 8193
    assert final["legacy_repeated_proposals"] == 0
    assert report["resource_budget"]["stop_reason"] == "INPUT_USAGE_EXCEEDED"
