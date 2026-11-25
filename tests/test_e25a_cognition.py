"""E2.5a typed cognitive initiation without world or Memory writes."""
from __future__ import annotations

import json
import sqlite3

import pytest

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.cognition.contracts import SCHEMA
from labs.virtual_anima_lab.python.cognition.coordinator import (
    E25LabCognitiveCoordinator, E25CognitionError, TwoStepEvidenceStub,
)
from labs.virtual_anima_lab.python.lifecycle.egocentric import (
    E23ObserverPort, EgocentricView, VIEW_SCHEMA,
)
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import (
    E24WorkingMemory, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)

WORLD = "a" * 32
KEY = "o" * 43


def view(seq: int, *, visible: bool):
    data = {
        "schema": VIEW_SCHEMA, "world_instance_id": WORLD, "epoch": 1,
        "sample_seq": seq, "sample_id": f"worldobs:{WORLD}:1:{seq}",
        "revision": seq - 1, "tick": seq - 1,
        "observer_ref": "lab.actor.anima", "source_ref": SOURCE,
        "coverage": {"kind": "view_cone", "fov_degrees": 90,
                     "range_limit": "none", "occlusion": "opaque_grid_cells"},
        "readings": [{
            "entity_ref": "lab.surface." + "e" * 24,
            "category": "surface", "bearing_mdeg": 0,
            "range_milli_cells": 2000, "properties": {},
        }],
    }
    if visible:
        data["readings"].append({
            "entity_ref": "lab.item.crate", "category": "item",
            "bearing_mdeg": 10_000, "range_milli_cells": 1000,
            "properties": {"owner": {"status": "absent", "value": None}},
        })
    return EgocentricView(data)


def memory(tmp_path, monkeypatch):
    observations = iter([
        view(1, visible=False), view(2, visible=True), view(3, visible=False),
    ])
    monkeypatch.setattr(E23ObserverPort, "observe", lambda _: next(observations))
    instance = build_core(
        tmp_path,
        sources={SOURCE: vision_source_registration()},
        properties={(SUBJECT, PREDICATE): vision_digest_rule()},
    )
    mem = E24WorkingMemory(instance, E23ObserverPort(port=46029, observer_key=KEY))
    for _ in range(3):
        mem.observe_and_record()
    return mem


def prop(context, turn, kind, arguments, proposal_id="pr1"):
    return {
        "schema": SCHEMA, "proposal_id": proposal_id, "turn_id": turn,
        "context_snapshot_id": context["context_snapshot_id"],
        "operation_kind": kind, "arguments": arguments,
        "expected_information": "Get verified information",
    }


def test_two_step_initiative_proves_retrieval_to_raw_chain(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    got = coord.run_turn(TwoStepEvidenceStub(), turn_id="turn_memory", memory_enabled=True)
    assert got["status"] == "STOPPED"
    assert [o["operation_kind"] for o in got["outcomes"]] == [
        "retrieve_memory", "lookup_raw_evidence",
    ]
    first, second = got["outcomes"]
    assert first["status"] == "COMPLETED"
    assert first["result"]["kind"] == "working_world_memory_search"
    item = first["result"]["records"][0]
    assert item["entity_ref"] == "lab.item.crate"
    assert item["current_observation"] == "not_observed"
    assert second["result"]["records"][0]["status"] == "verified_source_view"
    assert second["result"]["records"][0]["event_id"] == item["last_seen_event_id"]
    assert "lab.item.crate" in second["result"]["records"][0]["entities_observed"]
    assert got["lab_admission_only"] and not got["model_executive_authority"]
    trace = coord.decision_records("turn_memory")
    assert len(trace) == 2
    assert all(x["admission"] == "ADMITTED" for x in trace)
    assert trace[0]["context_snapshot"]["memory_enabled"] is True

    off = coord.run_turn(TwoStepEvidenceStub(), turn_id="turn_no_memory",
                         memory_enabled=False)
    assert len(off["outcomes"]) == 1
    assert off["outcomes"][0]["result"]["records"] == []
    assert len(coord.decision_records("turn_no_memory")) == 1
    assert mem._core.memory_store.count() == 0
    assert mem._core.core_execution is None
    assert len(mem._core.event_log.load_events()) == 3


@pytest.mark.parametrize("mutator", [
    lambda ctx, turn: {**prop(ctx, turn, "retrieve_memory", {"query": "crate", "top_k": 1}),
                       "context_snapshot_id": "ctx_bad"},
    lambda ctx, turn: {**prop(ctx, turn, "retrieve_memory", {"query": "crate", "top_k": 1}),
                       "turn_id": "wrong_turn"},
    lambda ctx, turn: prop(ctx, turn, "world.step", {"direction": "forward"}),
    lambda ctx, turn: prop(ctx, turn, "delete_memory", {"memory_id": "x"}),
    lambda ctx, turn: prop(ctx, turn, "retrieve_memory", {"query": "crate", "top_k": 100}),
    lambda ctx, turn: {**prop(ctx, turn, "retrieve_memory", {"query": "crate", "top_k": 1}),
                       "auth": "none"},
])
def test_untrusted_proposals_fail_closed(tmp_path, monkeypatch, mutator):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    class Malicious:
        def propose(self, context, outcomes, *, turn_id, step_index):
            return mutator(context, turn_id)
    got = coord.run_turn(Malicious(), turn_id="turn_attack")
    assert got["status"] == "REJECTED"
    assert got["outcomes"][0]["reason_code"] == "INVALID_PROPOSAL"
    assert coord.decision_records("turn_attack")[0]["admission"] == "REJECTED"
    assert len(mem._core.event_log.load_events()) == 3


def test_unavailable_goal_admission_rejected(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    class Asking:
        def propose(self, context, outcomes, *, turn_id, step_index):
            return prop(context, turn_id, "inspect_goal_status", {"goal_id": "goal1"})
    out = coord.run_turn(Asking(), turn_id="turn_goal")
    assert out["status"] == "REJECTED"
    assert out["outcomes"][0]["reason_code"] == "OPERATION_UNAVAILABLE"
    assert coord.decision_records("turn_goal")[0]["admission"] == "REJECTED"


def test_read_belief_uses_actual_core_belief(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    class Belief:
        def propose(self, context, outcomes, *, turn_id, step_index):
            if outcomes:
                return None
            return prop(context, turn_id, "inspect_current_belief", {
                "subject_ref": SUBJECT, "predicate_ref": PREDICATE,
            })
    output = coord.run_turn(Belief(), turn_id="turn_belief")
    result = output["outcomes"][0]["result"]
    assert result["kind"] == "core_working_belief"
    assert result["record"]["subject_ref"] == SUBJECT
    assert result["record"]["predicate_ref"] == PREDICATE
    assert result["record"]["status"] == "known"
    assert result["record"]["evidence_event_ids"]


def test_budget_exhaustion_and_no_reusing_turn(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem, max_steps=1)
    got = coord.run_turn(TwoStepEvidenceStub(), turn_id="turn_budget")
    assert got["status"] == "STEP_BUDGET_EXHAUSTED"
    assert len(got["outcomes"]) == 1
    with pytest.raises(E25CognitionError, match="already recorded"):
        coord.run_turn(TwoStepEvidenceStub(), turn_id="turn_budget")
    with pytest.raises(ValueError):
        E25LabCognitiveCoordinator(mem, max_steps=100)


def test_decision_trace_fails_closed_on_tampered_context(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    coord.run_turn(TwoStepEvidenceStub(), turn_id="turn_trace")
    with sqlite3.connect(mem._file) as db:
        db.execute(
            "UPDATE e25_cognitive_trace SET context_json='{}' "
            "WHERE turn_id='turn_trace'",
        )
    with pytest.raises(E25CognitionError, match="context was modified"):
        coord.decision_records("turn_trace")


def test_tampered_outcome_is_not_accepted_as_decision_record(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    coord.run_turn(TwoStepEvidenceStub(), turn_id="turn_outcome")
    with sqlite3.connect(mem._file) as db:
        db.execute(
            "UPDATE e25_cognitive_trace SET outcome_json='{}' "
            "WHERE turn_id='turn_outcome'",
        )
    with pytest.raises(E25CognitionError, match="result was modified"):
        coord.decision_records("turn_outcome")


def test_sensor_change_during_adapter_proposal_rejected(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    class RacingAdapter:
        def propose(self, context, outcomes, *, turn_id, step_index):
            monkeypatch.setattr(
                E23ObserverPort, "observe", lambda _: view(4, visible=True),
            )
            mem.observe_and_record()
            return prop(context, turn_id, "retrieve_memory",
                        {"query": "crate", "top_k": 1})
    result = coord.run_turn(RacingAdapter(), turn_id="turn_race")
    assert result["status"] == "REJECTED"
    assert result["outcomes"][0]["reason_code"] == "STALE_CONTEXT"
    record = coord.decision_records("turn_race")[0]
    assert record["admission"] == "REJECTED"
    assert record["proposal"] is None
    assert len(mem._core.event_log.load_events()) == 4


def test_adapter_failure_recorded_without_effects(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    class Broken:
        def propose(self, context, outcomes, *, turn_id, step_index):
            raise RuntimeError("bad LLM")
    got = coord.run_turn(Broken(), turn_id="turn_failure")
    assert got["status"] == "REJECTED"
    assert got["outcomes"][0]["reason_code"] == "ADAPTER_FAILURE"
    assert coord.decision_records("turn_failure")[0]["admission"] == "REJECTED"


def test_unknown_raw_event_not_created_by_model(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    class Raw:
        def propose(self, context, outcomes, *, turn_id, step_index):
            if outcomes:
                return None
            return prop(context, turn_id, "lookup_raw_evidence",
                        {"event_ids": ["ev_nonexistent"]})
    result = coord.run_turn(Raw(), turn_id="turn_unknown")
    outcome = result["outcomes"][0]
    assert outcome["status"] == "REJECTED"
    assert outcome["reason_code"] == "UNEXPOSED_EVIDENCE_ID"
    assert outcome["execution_performed"] is False
    assert "result" not in outcome
    assert len(mem._core.event_log.load_events()) == 3


@pytest.mark.parametrize("repeat", [False, True])
def test_native_error_feedback_is_bounded_and_does_not_read_hidden_source(tmp_path, monkeypatch, repeat):
    from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
    from labs.virtual_anima_lab.python.cognition import coordinator as module
    mem = memory(tmp_path, monkeypatch)
    crate = next(r for r in mem.world_model()["entities"] if r["entity_ref"] == "lab.item.crate")
    hidden = crate["last_seen_event_id"]
    reads = []
    original = module._read_only_result
    def observe_read(*args, **kwargs):
        reads.append(kwargs["kind"])
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "_read_only_result", observe_read)
    def tool(name, arguments, call_id):
        return {"choices":[{"finish_reason":"tool_calls","message":{"role":"assistant",
            "content":"","tool_calls":[{"id":call_id,"type":"function","function":{
                "name":name,"arguments":json.dumps(arguments)}}]}}]}
    denied = lambda i: tool("lookup_raw_evidence", {"event_ids":[hidden]}, i)
    stop = {"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"No accessible history."}}]}
    responses = iter([denied("one"), denied("two")] if repeat else [
        denied("one"), tool("retrieve_memory", {"query":"crate","top_k":1},"two"), stop])
    class Transport:
        def complete(self,payload):
            return next(responses)
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"feedback.jsonl",task="find crate",transport=Transport(),
        error_feedback=True)
    coord = E25LabCognitiveCoordinator(mem, error_feedback=True)
    report = coord.run_turn(adapter,turn_id="feedback_turn",memory_enabled=False)
    records = coord.decision_records("feedback_turn")
    assert records[0]["admission"] == "REJECTED"
    assert records[0]["outcome"]["execution_performed"] is False
    assert records[0]["reason_code"] == "UNEXPOSED_EVIDENCE_ID"
    assert not adapter.calls[0]["valid"]
    feedback = json.loads(adapter.calls[1]["request"]["messages"][-1]["content"])
    assert feedback["error_code"] == "UNEXPOSED_EVIDENCE_ID" and hidden not in json.dumps(feedback)
    assert reads == ([] if repeat else ["retrieve_memory"])
    assert not adapter.allowed_ids
    assert report["status"] == ("REJECTED" if repeat else "STOPPED")
    assert len(mem._core.event_log.load_events()) == 3
    if not repeat:
        assert report["outcomes"][1]["result"]["records"] == []
        from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import assess, CASES
        case = next(c for c in CASES if c["id"] == "C02_OFF")
        score = assess(case,report,records,adapter.calls)
        assert score["operation_gate_pass"] and not score["strict_operation_gate_pass"]
        assert score["recovered_objective"] and score["feedback_deliveries"] == 1


def test_feedback_uses_last_budget_step_without_extra_model_call(tmp_path, monkeypatch):
    from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
    mem = memory(tmp_path, monkeypatch)
    class Transport:
        def complete(self,payload):
            return {"choices":[{"finish_reason":"tool_calls","message":{"role":"assistant",
                "content":"","tool_calls":[{"id":"one","type":"function","function":{
                    "name":"lookup_raw_evidence","arguments":'{"event_ids":["ev_hidden"]}'}}]}}]}
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"feedback.jsonl",task="find crate",transport=Transport(),
        error_feedback=True)
    coord = E25LabCognitiveCoordinator(mem,max_steps=1,error_feedback=True)
    report = coord.run_turn(adapter,turn_id="feedback_budget",memory_enabled=False)
    assert report["status"] == "STEP_BUDGET_EXHAUSTED"
    assert len(adapter.calls) == 1
    assert coord.decision_records("feedback_budget")[0]["admission"] == "REJECTED"


@pytest.mark.parametrize("mode", ["stop", "repair", "second_error"])
def test_schema_feedback_and_model_stop_are_separate_from_objective(tmp_path,monkeypatch,mode):
    from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
    from labs.virtual_anima_lab.python.cognition import coordinator as module
    from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import assess, CASES
    mem = memory(tmp_path,monkeypatch)
    reads=[]
    original=module._read_only_result
    def observe_read(*args,**kwargs):
        reads.append(kwargs["kind"])
        return original(*args,**kwargs)
    monkeypatch.setattr(module,"_read_only_result",observe_read)
    def tool(name,args,cid):
        return {"choices":[{"finish_reason":"tool_calls","message":{"role":"assistant",
            "content":"","tool_calls":[{"id":cid,"type":"function",
            "function":{"name":name,"arguments":json.dumps(args)}}]}}]}
    invalid=tool("retrieve_memory",{"query":"crate","top_k":99},"one")
    stop={"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"No accessible history."}}]}
    responses=iter([invalid,stop] if mode=="stop" else (
        [invalid,tool("retrieve_memory",{"query":"crate","top_k":1},"two"),stop]
        if mode=="repair" else [invalid,tool("lookup_raw_evidence",{"event_ids":["ev_hidden"]},"two")]))
    class Transport:
        def complete(self,payload):
            return next(responses)
    adapter=NativeLabAdapter(base_url="http://127.0.0.1:8085",model="test",
        trace_path=tmp_path/"schema-feedback.jsonl",task="find crate",
        transport=Transport(),error_feedback=True)
    coord=E25LabCognitiveCoordinator(mem,error_feedback=True)
    report=coord.run_turn(adapter,turn_id="schema_feedback",memory_enabled=False)
    trace=coord.decision_records("schema_feedback")
    assert trace[0]["outcome"]["reason_code"]=="INVALID_TOOL_ARGUMENTS"
    assert trace[0]["outcome"]["execution_performed"] is False
    assert reads==(["retrieve_memory"] if mode=="repair" else [])
    assert report["status"]==("REJECTED" if mode=="second_error" else "STOPPED")
    case=next(c for c in CASES if c["id"]=="C02_OFF")
    result=assess(case,report,trace,adapter.calls)
    assert result["feedback_deliveries"]==1
    assert result["operation_gate_pass"]==(mode=="repair")
    assert not result["strict_operation_gate_pass"]
    assert len(mem._core.event_log.load_events())==3


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("sample_seq", [1, 2, 3])
def test_ca03_alternative_adapter_only_reads_exposed_sources(
    tmp_path, monkeypatch, enabled, sample_seq,
):
    from labs.virtual_anima_lab.python.cognition import coordinator as module
    mem = memory(tmp_path, monkeypatch)
    with sqlite3.connect(mem._file) as db:
        event = db.execute(
            "SELECT core_event_id FROM e24_raw WHERE sample_id=?",
            (f"worldobs:{WORLD}:1:{sample_seq}",),
        ).fetchone()[0]
    reads = []
    original = module._read_only_result
    def tracked(*args, **kwargs):
        reads.append(kwargs["kind"])
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "_read_only_result", tracked)

    class Adapter:
        def propose(self, context, outcomes, *, turn_id, step_index):
            return None if outcomes else prop(
                context, turn_id, "lookup_raw_evidence", {"event_ids": [event]},
            )

    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(Adapter(), turn_id="ca03_scope", memory_enabled=enabled)
    allowed = sample_seq == 3 or (sample_seq == 2 and enabled)
    outcome = report["outcomes"][0]
    trace = coord.decision_records("ca03_scope")[0]
    if allowed:
        assert reads == ["lookup_raw_evidence"]
        assert outcome["status"] == "COMPLETED"
        assert outcome["result"]["records"][0]["sample_seq"] == sample_seq
        assert trace["admission"] == "ADMITTED"
    else:
        assert reads == []
        assert outcome["reason_code"] == "UNEXPOSED_EVIDENCE_ID"
        assert outcome["execution_performed"] is False
        assert "result" not in outcome
        assert trace["admission"] == "REJECTED"


def test_ca03_mixed_exposed_and_hidden_ids_reject_entire_batch(tmp_path, monkeypatch):
    from labs.virtual_anima_lab.python.cognition import coordinator as module
    mem = memory(tmp_path, monkeypatch)
    rows = mem.world_model()["entities"]
    hidden = next(row["last_seen_event_id"] for row in rows if row["category"] == "item")
    latest = next(row["last_seen_event_id"] for row in rows if row["category"] == "surface")
    def no_read(*args, **kwargs):
        pytest.fail("mixed authorized/unauthorized batch reached service")
    monkeypatch.setattr(module, "_read_only_result", no_read)

    class Adapter:
        def propose(self, context, outcomes, *, turn_id, step_index):
            return prop(context, turn_id, "lookup_raw_evidence",
                        {"event_ids": [latest, hidden]})

    coord = E25LabCognitiveCoordinator(mem)
    out = coord.run_turn(Adapter(), turn_id="ca03_mixed", memory_enabled=False)
    assert out["outcomes"][0]["reason_code"] == "UNEXPOSED_EVIDENCE_ID"
    assert out["outcomes"][0]["execution_performed"] is False


def test_ca03_latest_result_extends_only_current_turn(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem, latest_observation=True)
    class Adapter:
        def propose(self, context, outcomes, *, turn_id, step_index):
            if not outcomes:
                return prop(context, turn_id, "inspect_latest_observation", {})
            if step_index == 1:
                event = outcomes[0]["result"]["records"][0]["event_id"]
                return prop(context, turn_id, "lookup_raw_evidence",
                            {"event_ids": [event]}, proposal_id="pr2")
            return None
    out = coord.run_turn(Adapter(), turn_id="ca03_latest", memory_enabled=False)
    assert out["status"] == "STOPPED"
    assert [item["status"] for item in out["outcomes"]] == ["COMPLETED", "COMPLETED"]
    assert out["outcomes"][1]["result"]["records"][0]["sample_seq"] == 3


def test_ca03_forged_historical_service_result_cannot_be_exposed(tmp_path, monkeypatch):
    from labs.virtual_anima_lab.python.cognition import coordinator as module
    mem = memory(tmp_path, monkeypatch)
    original = module._read_only_result
    def bad_result(*args, **kwargs):
        if kwargs["kind"] == "retrieve_memory":
            return original(*args, **{**kwargs, "memory_enabled": True})
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "_read_only_result", bad_result)
    coord = E25LabCognitiveCoordinator(mem)
    out = coord.run_turn(TwoStepEvidenceStub(), turn_id="ca03_bad_service",
                         memory_enabled=False)
    assert out["status"] == "REJECTED"
    assert out["outcomes"][0]["reason_code"] == "SERVICE_REJECTED"
    assert "result" not in out["outcomes"][0]


def test_ca03_legacy_historical_off_journal_not_eligible_for_claim(tmp_path, monkeypatch):
    from labs.virtual_anima_lab.python.cognition.source_binding import admitted_source_rows
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    coord.run_turn(TwoStepEvidenceStub(), turn_id="ca03_legacy")
    record = coord.decision_records("ca03_legacy")[1]
    assert admitted_source_rows(record)
    record["context_snapshot"]["memory_enabled"] = False
    assert not admitted_source_rows(record)
