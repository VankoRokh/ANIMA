"""R9.2.4: separate projection must not replace the original research answer."""
from copy import deepcopy
import json

import pytest

from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion

CRATE = "lab.item.crate"
REQ = CompletionRequirement("verified_observation", (CRATE,))


@pytest.mark.parametrize("mode,projection_status,claim_status,coverage", [
    ("success", "GENERATED", "ALL_CLAIMS_VERIFIED", "COMPLETE"),
    ("wrong_scope", "GENERATED", "CLAIMS_NOT_ALL_VERIFIED", "INCOMPLETE"),
    ("empty", "GENERATED", "NO_CLAIMS", "INCOMPLETE"),
    ("budget", "BUDGET_UNAVAILABLE", "NO_ACCEPTED_FINAL", "INCOMPLETE"),
    ("usage", "RESOURCE_REJECTED", "NO_ACCEPTED_FINAL", "INCOMPLETE"),
    ("length", "INVALID_RESPONSE", "NO_ACCEPTED_FINAL", "INCOMPLETE"),
    ("tool_attempt", "INVALID_RESPONSE", "NO_ACCEPTED_FINAL", "INCOMPLETE"),
    ("incomplete", "INFORMATION_INCOMPLETE", "NO_ACCEPTED_FINAL", "INCOMPLETE"),
])
def test_projection_and_research_keep_independent_authority(
        tmp_path, monkeypatch, mode, projection_status, claim_status, coverage):
    mem = memory(tmp_path / "core", monkeypatch)
    entity = next(e for e in mem.world_model()["entities"] if e["entity_ref"] == CRATE)
    event = entity["last_seen_event_id"]
    lookup = completion("lookup_raw_evidence", json.dumps({"event_ids": [event]}), call_id="past")
    original = "The crate is visible right now."
    final = completion(content=original)
    item = {"entity_ref": CRATE, "predicate": "observed_in_sample", "value": True,
            "event_id": event, "sample_seq": 2,
            "scope": "latest_captured_sample" if mode == "wrong_scope" else "source_sample"}
    projected = json.dumps({"answer": "It was observed in sample 2.",
                            "claims": [] if mode == "empty" else [item]})
    projection = completion(content=projected, finish="length" if mode == "length" else "stop")
    if mode == "usage":
        projection["usage"]["prompt_tokens"] = 9000
    if mode == "tool_attempt":
        projection = lookup
    responses = [final, final] if mode == "incomplete" else [lookup, final, projection]
    transport = Fake(*responses)
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        trace_path=tmp_path / "calls.jsonl", task="Verify past observation", transport=transport)
    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(adapter, turn_id="r92_projection",
        completion_requirement=REQ, resource_limits=ResourceLimits(max_calls=2 if mode == "budget" else 4),
        project_result_claims=True)
    before = deepcopy(report)
    calls_before = deepcopy(adapter.calls)
    count = len(transport.requests)
    result = build_cognitive_result(coord, report, requirement=REQ,
                                    research_calls=adapter.calls, claim_phase="claim_projection")
    assert report == before and adapter.calls == calls_before
    assert len(transport.requests) == count == report["resource_budget"]["reserved_calls"]
    reasoning = result["reasoning"]
    evidence = result["evidence"]
    presentation = result["presentation"]
    assert reasoning["projection_status"] == projection_status
    assert evidence["model_claims"]["status"] == claim_status
    assert evidence["model_claims"]["coverage"] == coverage
    assert presentation["model_text"] == original
    assert presentation["model_text_authority"] == presentation["projection_text_authority"] == "UNVERIFIED"
    assert presentation["whole_answer_verified"] is False
    if mode in ("success", "wrong_scope", "empty"):
        assert reasoning["projection_final_index"] == len(adapter.calls)
        assert presentation["projection_text"] == "It was observed in sample 2."
        assert reasoning["model_text_attempts"][-1]["original_text"] == projected
    else:
        assert reasoning["projection_final_index"] is None
        assert presentation["projection_text"] is None
        if mode in ("usage", "length"):
            assert reasoning["model_text_attempts"][-1]["original_text"] == projected
            assert reasoning["model_text_attempts"][-1]["protocol_status"] == "INTERMEDIATE_OR_UNACCEPTED"
    assert evidence["claim_coverage"] == ("INCOMPLETE" if mode == "incomplete" else "COMPLETE")
    assert len(mem._core.event_log.load_events()) == 3
    assert mem._core.memory_store.count() == 0


def test_incomplete_research_call_sequence_rejected(tmp_path, monkeypatch):
    mem = memory(tmp_path / "core", monkeypatch)
    transport = Fake(completion(content="4"))
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        trace_path=tmp_path / "calls.jsonl", task="2+2", transport=transport)
    coord = E25LabCognitiveCoordinator(mem)
    req = CompletionRequirement("no_service_read")
    report = coord.run_turn(adapter, turn_id="count_binding", completion_requirement=req,
                            resource_limits=ResourceLimits())
    with pytest.raises(ValueError, match="research call count"):
        build_cognitive_result(coord, report, requirement=req,
                               research_calls=[], claim_phase="research")
