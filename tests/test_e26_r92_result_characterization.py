"""R9.2.1: characterize existing scoring boundaries, not a new result API.

Synthetic captured observations and recorded fake completions only.
A PASS shows that legacy operation/claim metrics cannot establish prose truth.
The cases deliberately use wrong natural-language answers.
"""
import json

import pytest

from anima.agent.native_tools import LoopbackChatTransport
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import run_cases
from labs.virtual_anima_lab.python.lifecycle.egocentric import EgocentricView
from tests import test_e25a_cognition as fixtures
from tests.test_e25a_cognition import memory, view
from tests.test_e26a_native_tools import Fake, completion


@pytest.mark.parametrize("case_id,wrong_answer", [
    ("C09", "2 plus 2 equals 5."),
    ("C02", "Elephants do not exist anywhere in the world."),
    ("C01", "The crate is visible right now."),
])
def test_r92_legacy_gate_does_not_establish_prose_correctness(
        tmp_path, monkeypatch, case_id, wrong_answer):
    def with_shortcut(seq, *, visible):
        data = view(seq, visible=visible).as_dict()
        if visible:
            data["readings"].append({
                "entity_ref": "lab.obstacle.shortcut",
                "category": "obstacle",
                "bearing_mdeg": 20000,
                "range_milli_cells": 3000,
                "properties": {},
            })
        return EgocentricView(data)

    monkeypatch.setattr(fixtures, "view", with_shortcut)
    mem = memory(tmp_path / "core", monkeypatch)
    claims = []
    responses = []
    if case_id == "C02":
        responses.append(completion("retrieve_memory",
                                    '{"query":"elephant","top_k":3}', call_id="search"))
    elif case_id == "C01":
        entity = next(row for row in mem.world_model()["entities"]
                      if row["entity_ref"] == "lab.item.crate")
        assert entity["current_observation"] == "not_observed"
        event_id = entity["last_seen_event_id"]
        responses.append(completion("lookup_raw_evidence",
                                    json.dumps({"event_ids": [event_id]}), call_id="past"))
        claims.append({"entity_ref": "lab.item.crate", "predicate": "observed_in_sample",
                       "value": True, "event_id": event_id, "sample_seq": 2,
                       "scope": "source_sample"})
    responses.append(completion(content=json.dumps({"answer": wrong_answer, "claims": claims})))
    transport = Fake(*responses)
    monkeypatch.setattr(LoopbackChatTransport, "complete",
                        lambda self, payload: transport.complete(payload))
    coord = E25LabCognitiveCoordinator(mem, max_steps=4, ranked=True, error_feedback=True)
    out = tmp_path / "evidence"
    out.mkdir()
    (out / "reproducibility").mkdir()
    result, = run_cases(mem, coord, out, 7, base_url="http://127.0.0.1:8085",
                        model="test", check_world=lambda: True,
                        check_core=lambda: len(mem._core.event_log.load_events()) == 3,
                        variant="claims", selected_cases=[case_id])
    assert result["operation_gate_pass"]
    assert result["information_completion"]["information_requirement_satisfied"]
    assert result["claim_objective_pass"]  # legacy typed objective, NOT semantic PASS
    evaluation = result["model_claims"]
    assert evaluation["format_status"] == "VALID"
    assert evaluation["answer"] == wrong_answer
    assert evaluation["free_text_verified"] is False
    assert evaluation["task_completion"] == "NOT_ESTABLISHED"
    assert result["semantic_review"] == "PENDING"
    if case_id == "C01":
        assert len(evaluation["verdicts"]) == 1
        assert evaluation["verdicts"][0]["status"] == "VERIFIED"
    else:
        assert evaluation["claims"] == evaluation["verdicts"] == []
    assert len(transport.requests) == len(responses)
    assert mem._core.memory_store.count() == 0
