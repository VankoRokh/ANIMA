"""R9.2.5: reconstruction rejects internally inconsistent resealed exports."""
import json

import pytest

from anima.agent.native_tools import LoopbackChatTransport
from labs.virtual_anima_lab.python.cognition.cognitive_result import SCHEMA
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as evidence
from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import CASES, run_cases
from labs.virtual_anima_lab.python.lifecycle.egocentric import EgocentricView
from tests import test_e25a_cognition as fixtures
from tests.test_e25a_cognition import memory, view
from tests.test_e26a_native_tools import Fake, completion


def make_result_bundle(tmp_path, monkeypatch):
    def with_shortcut(seq, *, visible):
        data = view(seq, visible=visible).as_dict()
        if visible:
            data["readings"].append({
                "entity_ref": "lab.obstacle.shortcut", "category": "obstacle",
                "bearing_mdeg": 20000, "range_milli_cells": 3000, "properties": {},
            })
        return EgocentricView(data)
    monkeypatch.setattr(fixtures, "view", with_shortcut)
    mem = memory(tmp_path / "core", monkeypatch)
    entity = next(e for e in mem.world_model()["entities"] if e["entity_ref"] == "lab.item.crate")
    event = entity["last_seen_event_id"]
    item = {"entity_ref": "lab.item.crate", "predicate": "observed_in_sample",
            "value": True, "event_id": event, "sample_seq": 2, "scope": "source_sample"}
    final = json.dumps({"answer": "The crate is visible right now.", "claims": [item]})
    transport = Fake(completion("lookup_raw_evidence", json.dumps({"event_ids": [event]}),
                                call_id="past"), completion(content=final))
    monkeypatch.setattr(LoopbackChatTransport, "complete",
                        lambda self, payload: transport.complete(payload))
    coord = E25LabCognitiveCoordinator(mem, max_steps=4, ranked=True, error_feedback=True)
    out = tmp_path / "output"
    out.mkdir()
    root = out / "reproducibility"
    root.mkdir()
    run_cases(mem, coord, out, 7, base_url="http://127.0.0.1:8085", model="test",
              check_world=lambda: True, check_core=lambda: True,
              variant="claims", selected_cases=["C01"])
    case = next(c for c in CASES if c["id"] == "C01")
    manifest = {"schema": evidence.SCHEMA, "git_sha": "a" * 40, "world_seeds": [7],
                "variant": "claims", "scenarios": [case], "cognitive_result_schema": SCHEMA}
    evidence.seal_bundle(root, manifest, complete=True)
    assert evidence.verify_bundle(root)["requests"] == 2
    return root, manifest, transport


@pytest.mark.parametrize("fault", [
    "foreign_fact", "wrong_scope", "wrong_value", "fake_model_verdict",
    "promoted_prose", "rewritten_prose", "false_coverage", "missing_result",
    "changed_variant", "changed_completion", "changed_model_metric",
])
def test_resealed_result_inconsistency_rejected(tmp_path, monkeypatch, fault):
    root, manifest, transport = make_result_bundle(tmp_path, monkeypatch)
    path = root / "case-7-C01.json"
    fixture = evidence.read_json(path)
    aggregate = fixture["result"]
    result = aggregate["cognitive_result"]
    if fault == "foreign_fact":
        result["evidence"]["facts"][0]["verdict"]["claim"]["event_id"] = "ev_foreign"
    elif fault == "wrong_scope":
        result["evidence"]["facts"][0]["verdict"]["claim"]["scope"] = "latest_captured_sample"
    elif fault == "wrong_value":
        result["evidence"]["facts"][0]["verdict"]["claim"]["value"] = False
    elif fault == "fake_model_verdict":
        result["evidence"]["model_claims"]["verified_candidates"][0]["verdict"]["observed_value"] = False
    elif fault == "promoted_prose":
        result["presentation"]["whole_answer_verified"] = True
    elif fault == "rewritten_prose":
        result["reasoning"]["model_text_attempts"][0]["original_text"] = "Corrected after the fact."
    elif fault == "false_coverage":
        result["evidence"]["claim_coverage"] = "INCOMPLETE"
    elif fault == "missing_result":
        del aggregate["cognitive_result"]
    elif fault == "changed_variant":
        aggregate["variant"] = "baseline"
    elif fault == "changed_completion":
        aggregate["information_completion"]["information_requirement_satisfied"] = False
    elif fault == "changed_model_metric":
        aggregate["model_claims"]["free_text_verified"] = True
    evidence.write_json(path, fixture)
    (root / "checksums.json").unlink()
    evidence.seal_bundle(root, manifest, complete=True)
    with pytest.raises(ValueError, match="cognitive result"):
        evidence.verify_bundle(root)
    assert len(transport.requests) == 2


def test_legacy_export_without_result_remains_readable(tmp_path, monkeypatch):
    root, manifest, transport = make_result_bundle(tmp_path, monkeypatch)
    path = root / "case-7-C01.json"
    fixture = evidence.read_json(path)
    del fixture["result"]["cognitive_result"]
    del manifest["cognitive_result_schema"]
    evidence.write_json(path, fixture)
    (root / "checksums.json").unlink()
    evidence.seal_bundle(root, manifest, complete=True)
    assert evidence.verify_bundle(root)["requests"] == 2
    assert len(transport.requests) == 2
