import json
from copy import deepcopy

import pytest

from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.host_temporal_projection import project_temporal_claims
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
from labs.virtual_anima_lab.python.cognition.claim_verification import ObservationClaimVerifier
from labs.virtual_anima_lab.python.lifecycle.egocentric import E23ObserverPort
from tests.test_e25a_cognition import memory, view
from tests.test_e26a_native_tools import Fake, completion

ENTITY = "lab.item.crate"
REQ = CompletionRequirement("historical_and_latest_observation", (ENTITY,))


def run(tmp_path, monkeypatch, mode):
    mem = memory(tmp_path, monkeypatch)
    entity = next(e for e in mem.world_model()["entities"] if e["entity_ref"] == ENTITY)
    past = completion("lookup_raw_evidence", json.dumps({"event_ids":[entity["last_seen_event_id"]]}), call_id="past")
    latest = completion("inspect_latest_observation", "{}", call_id="latest")
    stop = completion(content="Untrusted model prose may be wrong.")
    responses, steps = {
        "complete": ([past, stop, latest, stop], 4),
        "latest_only": ([latest, stop, stop], 4),
        "past_only": ([past, stop, stop], 4),
        "exhausted": ([past, latest], 2),
        "rejected": ([past, latest, completion("lookup_raw_evidence", '{"event_ids":["ev_hidden"]}', call_id="bad")], 4),
    }[mode]
    transport = Fake(*responses)
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        trace_path=tmp_path/"host-calls.jsonl", task="Compare captured observations",
        transport=transport, temporal=True, compact_temporal=True, latest_observation=True)
    coord = E25LabCognitiveCoordinator(mem, max_steps=steps, latest_observation=True)
    report = coord.run_turn(adapter, turn_id="host_temporal",
        completion_requirement=REQ, resource_limits=ResourceLimits(max_calls=steps))
    return mem, coord, report, transport


@pytest.mark.parametrize("mode,expected_status,expected_calls", [
    ("complete", "STOPPED", 4), ("exhausted", "STEP_BUDGET_EXHAUSTED", 2),
])
def test_r6_complete_evidence_projects_without_more_inference(tmp_path, monkeypatch, mode, expected_status, expected_calls):
    mem, coord, report, transport = run(tmp_path, monkeypatch, mode)
    before = deepcopy(report)
    result = project_temporal_claims(coord, REQ, report)
    assert report == before and report["status"] == expected_status
    assert len(transport.requests) == report["resource_budget"]["reserved_calls"] == expected_calls
    assert result["status"] == "VERIFIED"
    assert result["origin"] == "DETERMINISTIC_HOST"
    assert result["temporal_claim_coverage"] and result["information_satisfied"]
    assert [(c["scope"],c["value"]) for c in result["claims"]] == [
        ("source_sample", True), ("latest_captured_sample", False)]
    assert all(v["status"] == "VERIFIED" for v in result["verdicts"])
    assert result["model_calls"] == result["new_service_reads"] == 0
    assert "Untrusted model prose" not in result["answer"]
    assert "not observed in latest captured sample 3" in result["answer"]
    assert not result["world_truth_authority"] and not result["knowledge_write"]
    assert result["task_completion"] == "NOT_ESTABLISHED"
    assert project_temporal_claims(coord, REQ, report) == result
    assert len(mem._core.event_log.load_events()) == 3
    assert mem._core.memory_store.count() == 0


@pytest.mark.parametrize("mode", ["latest_only", "past_only"])
def test_r6_missing_evidence_not_repaired_by_host(tmp_path, monkeypatch, mode):
    _, coord, report, transport = run(tmp_path, monkeypatch, mode)
    result = project_temporal_claims(coord, REQ, report)
    assert result["status"] == "INFORMATION_INCOMPLETE"
    assert not result["information_satisfied"] and not result["temporal_claim_coverage"]
    assert result["claims"] == result["verdicts"] == []
    assert result["answer"] is None and len(transport.requests) == 3


def test_r6_rejected_research_does_not_publish_claims(tmp_path, monkeypatch):
    _, coord, report, transport = run(tmp_path, monkeypatch, "rejected")
    assert report["status"] == "REJECTED"
    result = project_temporal_claims(coord, REQ, report)
    assert result["status"] == "RESEARCH_REJECTED"
    assert not result["temporal_claim_coverage"] and not result["claims"]
    assert len(transport.requests) == 3


def test_r6_stale_context_rejected(tmp_path, monkeypatch):
    mem, coord, report, _ = run(tmp_path, monkeypatch, "complete")
    monkeypatch.setattr(E23ObserverPort, "observe", lambda _: view(4, visible=True))
    mem.observe_and_record()
    result = project_temporal_claims(coord, REQ, report)
    assert result["status"] == "STALE_CONTEXT"
    assert not result["claims"] and result["answer"] is None


def test_r6_failed_verification_never_publishes_partial_answer(tmp_path, monkeypatch):
    _, coord, report, _ = run(tmp_path, monkeypatch, "complete")
    verify = ObservationClaimVerifier.verify
    def invalid(self, turn_id, claim):
        verdict = verify(self, turn_id, claim)
        if claim.scope == "latest_captured_sample":
            verdict.update(status="UNSUPPORTED", reason_code="RAW_INTEGRITY_FAILURE")
        return verdict
    monkeypatch.setattr(ObservationClaimVerifier, "verify", invalid)
    result = project_temporal_claims(coord, REQ, report)
    assert result["status"] == "VERIFICATION_FAILED"
    assert not result["claims"] and result["answer"] is None
    assert not result["temporal_claim_coverage"]
    assert len(result["verdicts"]) == 2


def test_r6_unbound_report_rejected(tmp_path, monkeypatch):
    _, coord, report, _ = run(tmp_path, monkeypatch, "complete")
    report["outcomes"] = report["outcomes"][:-1]
    result = project_temporal_claims(coord, REQ, report)
    assert result["status"] == "SOURCE_INTEGRITY_FAILURE"
    assert not result["claims"] and result["answer"] is None
