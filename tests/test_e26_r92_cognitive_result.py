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
