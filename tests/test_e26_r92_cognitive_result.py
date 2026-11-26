"""R9.2.2 deterministic cognitive-result basis; no actual model inference."""
from copy import deepcopy

import pytest

from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
from labs.virtual_anima_lab.python.cognition.coordinator import (
    E25LabCognitiveCoordinator, TwoStepEvidenceStub,
)
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import E24MemoryError
from tests.test_e25a_cognition import memory, prop
from tests.test_e26d_host_temporal_projection import run, REQ

CRATE = "lab.item.crate"


class Stop:
    def propose(self, context, outcomes, **kwargs):
        return None


class SearchOnly:
    def __init__(self, query):
        self.query = query

    def propose(self, context, outcomes, *, turn_id, step_index):
        if outcomes:
            return None
        return prop(context, turn_id, "retrieve_memory",
                    {"query": self.query, "top_k": 3})


@pytest.mark.parametrize("mode", ["complete", "exhausted", "past_only", "latest_only", "rejected"])
def test_temporal_result_keeps_status_and_verified_scope(tmp_path, monkeypatch, mode):
    mem, coord, report, transport = run(tmp_path, monkeypatch, mode)
    before = deepcopy(report)
    calls = len(transport.requests)
    result = build_cognitive_result(coord, report, requirement=REQ)
    assert report == before
    assert result["execution"]["turn_status"] == report["status"]
    assert result["execution"]["task_completion"] == "NOT_ESTABLISHED"
    evidence = result["evidence"]
    assert not evidence["world_truth_authority"] and not evidence["knowledge_write"]
    claims = { (v["verdict"]["claim"]["scope"], v["verdict"]["claim"]["value"])
               for v in evidence["facts"] }
    expected = {"complete": {("source_sample", True), ("latest_captured_sample", False)},
                "exhausted": {("source_sample", True), ("latest_captured_sample", False)},
                "rejected": {("source_sample", True), ("latest_captured_sample", False)},
                "past_only": {("source_sample", True)},
                "latest_only": {("latest_captured_sample", False)}}[mode]
    assert claims == expected
    assert evidence["claim_coverage"] == (
        "INCOMPLETE" if mode in ("past_only", "latest_only") else "COMPLETE")
    assert all(v["origin"] == "DETERMINISTIC_HOST" and
               v["verdict"]["status"] == "VERIFIED" for v in evidence["facts"])
    assert len(transport.requests) == calls
    assert len(mem._core.event_log.load_events()) == 3
    assert mem._core.memory_store.count() == 0
    assert build_cognitive_result(coord, report, requirement=REQ) == result


def test_memory_candidate_without_raw_read_not_fact(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(SearchOnly("crate"), turn_id="search")
    result = build_cognitive_result(coord, report,
                                    requirement=CompletionRequirement("verified_observation", (CRATE,)))
    assert result["information"]["status"] == "INCOMPLETE"
    assert result["evidence"]["facts"] == []
    assert result["evidence"]["claim_coverage"] == "INCOMPLETE"
    assert result["information"]["search_outcomes"][0]["returned"] > 0


@pytest.mark.parametrize("requirement", [None, CompletionRequirement("no_service_read")])
def test_stop_only_result_no_claims_not_correct_answer(tmp_path, monkeypatch, requirement):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(Stop(), turn_id="stop_only")
    result = build_cognitive_result(coord, report, requirement=requirement)
    assert result["identity"]["journal_binding"] == "NO_JOURNAL_ENTRIES"
    assert result["execution"]["operations"] == []
    assert result["execution"]["task_completion"] == "NOT_ESTABLISHED"
    assert result["evidence"]["facts"] == []
    assert result["evidence"]["integrity_status"] == "NO_CLAIMS"
    assert result["evidence"]["claim_coverage"] == (
        "NOT_ASSESSED" if requirement is None else "NOT_APPLICABLE")
    assert result["information"]["status"] == (
        "NOT_ASSESSED" if requirement is None else "SATISFIED")


def test_empty_search_is_bounded_outcome(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(SearchOnly("elephant"), turn_id="empty")
    result = build_cognitive_result(coord, report,
                                    requirement=CompletionRequirement("empty_search", query="elephant"))
    assert result["information"]["status"] == "SATISFIED"
    search, = result["information"]["search_outcomes"]
    assert search["returned"] == search["possible_matches"] == 0
    assert search["truncated"] is False
    assert search["scope"] == "BOUNDED_MEMORY_SEARCH_NOT_WORLD_ABSENCE"
    assert result["evidence"]["facts"] == []
    assert result["evidence"]["claim_coverage"] == "NOT_APPLICABLE"


def test_raw_integrity_failure_cannot_publish_facts(tmp_path, monkeypatch):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(TwoStepEvidenceStub(), turn_id="proof")
    def broken(self, sample_id):
        raise E24MemoryError("test failure")
    monkeypatch.setattr(type(mem), "raw_evidence", broken)
    result = build_cognitive_result(coord, report,
                                    requirement=CompletionRequirement("verified_observation", (CRATE,)))
    assert result["evidence"]["integrity_status"] == "VERIFICATION_FAILED"
    assert result["evidence"]["facts"] == []
    assert result["evidence"]["claim_coverage"] == "INCOMPLETE"
    assert result["evidence"]["verdicts"][0]["verdict"]["status"] == "UNSUPPORTED"
    # Information completion describes the journal, not the subsequent re-read.
    assert result["information"]["status"] == "SATISFIED"


@pytest.mark.parametrize("corruption", ["context", "turn", "outcomes"])
def test_foreign_or_incomplete_report_rejected(tmp_path, monkeypatch, corruption):
    mem = memory(tmp_path, monkeypatch)
    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(TwoStepEvidenceStub(), turn_id="proof")
    if corruption == "context":
        report["context_snapshot_id"] = "ctx_foreign"
    elif corruption == "turn":
        report["turn_id"] = "foreign_turn"
    else:
        report["outcomes"].pop()
    with pytest.raises(ValueError):
        build_cognitive_result(coord, report)


def _native_result_turn(tmp_path, monkeypatch, mode):
    import json
    from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
    from tests.test_e26a_native_tools import Fake, completion
    mem = memory(tmp_path / "core", monkeypatch)
    entity = next(e for e in mem.world_model()["entities"] if e["entity_ref"] == CRATE)
    event = entity["last_seen_event_id"]
    item = {"entity_ref": CRATE, "predicate": "observed_in_sample", "value": True,
            "event_id": event, "sample_seq": 2, "scope": "source_sample"}
    answer = "The crate is visible right now."
    responses = [completion("lookup_raw_evidence", json.dumps({"event_ids": [event]}),
                            call_id="past")]
    requirement = CompletionRequirement("verified_observation", (CRATE,))
    if mode == "contradicted":
        item["value"] = False
    elif mode == "wrong_scope":
        item["scope"] = "latest_captured_sample"
    elif mode == "wrong_event":
        item["event_id"] = "ev_unbound"
    claims = [] if mode == "empty" else [item]
    text = json.dumps({"answer": answer, "claims": claims})
    if mode in ("plain", "invalid", "truncated"):
        text = answer if mode != "truncated" else '{"answer":"The crate'
    if mode == "arithmetic":
        responses = []
        requirement = CompletionRequirement("no_service_read")
        text = json.dumps({"answer": "2 plus 2 equals 5.", "claims": []})
    elif mode == "empty_search":
        responses = [completion("retrieve_memory", '{"query":"elephant","top_k":3}')]
        requirement = CompletionRequirement("empty_search", query="elephant")
        text = json.dumps({"answer": "Elephants do not exist.", "claims": []})
    responses.append(completion(content=text, finish="length" if mode == "truncated" else "stop"))
    transport = Fake(*responses)
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        task="Research", trace_path=tmp_path / "calls.jsonl", transport=transport,
        temporal=True, compact_temporal=True, model_claims=mode != "plain")
    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(adapter, turn_id="result_native")
    return mem, coord, report, adapter, transport, requirement, text


@pytest.mark.parametrize("mode,status,coverage", [
    ("correct_claim_wrong_prose", "ALL_CLAIMS_VERIFIED", "COMPLETE"),
    ("contradicted", "CLAIMS_NOT_ALL_VERIFIED", "INCOMPLETE"),
    ("wrong_scope", "CLAIMS_NOT_ALL_VERIFIED", "INCOMPLETE"),
    ("wrong_event", "CLAIMS_NOT_ALL_VERIFIED", "INCOMPLETE"),
    ("empty", "NO_CLAIMS", "INCOMPLETE"),
    ("invalid", "INVALID", "INCOMPLETE"),
    ("plain", "NOT_REQUESTED", "NOT_ASSESSED"),
    ("truncated", "NO_ACCEPTED_FINAL", "INCOMPLETE"),
    ("arithmetic", "NO_CLAIMS", "NOT_APPLICABLE"),
    ("empty_search", "NO_CLAIMS", "NOT_APPLICABLE"),
])
def test_r92_model_output_and_host_facts_are_independent(tmp_path, monkeypatch, mode, status, coverage):
    mem, coord, report, adapter, transport, req, text = _native_result_turn(tmp_path, monkeypatch, mode)
    calls_before = deepcopy(adapter.calls)
    report_before = deepcopy(report)
    count = len(transport.requests)
    result = build_cognitive_result(coord, report, requirement=req,
        research_calls=adapter.calls, claim_phase=None if mode == "plain" else "research")
    assert adapter.calls == calls_before and report == report_before
    assert len(transport.requests) == count
    evidence = result["evidence"]
    model = evidence["model_claims"]
    assert model["status"] == status and model["coverage"] == coverage
    assert model["free_text_verified"] is False
    attempt, = result["reasoning"]["model_text_attempts"]
    assert attempt["original_text"] == text and attempt["authority"] == "UNVERIFIED"
    assert result["presentation"]["whole_answer_verified"] is False
    assert result["presentation"]["semantic_review"] == "NOT_PERFORMED"
    if mode == "truncated":
        assert attempt["protocol_status"] == "INTERMEDIATE_OR_UNACCEPTED"
        assert result["presentation"]["model_text"] is None
        assert result["execution"]["turn_status"] == "REJECTED"
    else:
        assert attempt["protocol_status"] == "ACCEPTED_FINAL"
        assert result["presentation"]["model_text_authority"] == "UNVERIFIED"
    if mode in ("arithmetic", "empty_search"):
        assert not evidence["facts"]
    else:
        fact, = evidence["facts"]
        assert fact["origin"] == "DETERMINISTIC_HOST"
        assert fact["verdict"]["claim"]["scope"] == "source_sample"
        assert fact["verdict"]["claim"]["value"] is True
    if mode == "correct_claim_wrong_prose":
        candidate, = model["verified_candidates"]
        assert candidate["origin"] == "MODEL_CANDIDATE_VERIFIED"
        assert result["presentation"]["model_text"] == "The crate is visible right now."
    else:
        assert not model["verified_candidates"]
    assert mem._core.memory_store.count() == 0
    assert len(mem._core.event_log.load_events()) == 3


@pytest.mark.parametrize("field,value", [
    ("turn_id", "foreign"), ("context_snapshot_id", "ctx_foreign"), ("model_call_index", 99),
])
def test_r92_foreign_native_record_cannot_be_attached(tmp_path, monkeypatch, field, value):
    _, coord, report, adapter, _, req, _ = _native_result_turn(tmp_path, monkeypatch, "plain")
    calls = deepcopy(adapter.calls)
    calls[-1][field] = value
    with pytest.raises(ValueError, match="does not bind cognitive result"):
        build_cognitive_result(coord, report, requirement=req, research_calls=calls)
