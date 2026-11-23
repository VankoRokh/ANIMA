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
    assert result["outcomes"][0]["result"]["records"][0] == {
        "event_id": "ev_nonexistent", "status": "not_found",
    }
    assert len(mem._core.event_log.load_events()) == 3
