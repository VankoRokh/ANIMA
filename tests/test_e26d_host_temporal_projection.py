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


@pytest.mark.parametrize("enabled", [False, True])
def test_r6_suite_keeps_model_metrics_separate_from_host(tmp_path, monkeypatch, enabled):
    from anima.agent.native_tools import LoopbackChatTransport
    from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as evidence
    from labs.virtual_anima_lab.python.lifecycle.egocentric import EgocentricView
    from labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite import run_cases
    from tests import test_e25a_cognition as fixtures

    def with_shortcut(seq, *, visible):
        data = view(seq, visible=visible).as_dict()
        if visible:
            data["readings"].append({
                "entity_ref":"lab.obstacle.shortcut", "category":"obstacle",
                "bearing_mdeg":20000, "range_milli_cells":3000, "properties":{},
            })
        return EgocentricView(data)

    monkeypatch.setattr(fixtures, "view", with_shortcut)
    mem = memory(tmp_path/"core", monkeypatch)
    entity = next(e for e in mem.world_model()["entities"] if e["entity_ref"] == ENTITY)
    past = completion("lookup_raw_evidence", json.dumps({"event_ids":[entity["last_seen_event_id"]]}), call_id="past")
    latest = completion("inspect_latest_observation", "{}", call_id="latest")
    stop = completion(content="Unverified prose.")
    transport = Fake(past, stop, latest, stop)
    monkeypatch.setattr(LoopbackChatTransport, "complete", lambda self, payload: transport.complete(payload))
    coord = E25LabCognitiveCoordinator(mem, max_steps=4, ranked=True, error_feedback=True, latest_observation=True)
    out = tmp_path/"evidence"
    out.mkdir()
    (out/"reproducibility").mkdir()
    result, = run_cases(mem, coord, out, 7, base_url="http://127.0.0.1:8085", model="test",
        check_world=lambda: True, check_core=lambda: len(mem._core.event_log.load_events()) == 3,
        variant="temporal_completion", selected_cases=["C06"], host_temporal_projection=enabled)
    assert result["operation_gate_pass"] and result["strict_operation_gate_pass"]
    assert result["information_completion"]["information_requirement_satisfied"]
    assert result["total_model_calls"] == len(transport.requests) == 4
    assert not result["claim_objective_pass"] and not result["temporal_claim_coverage"]
    cognitive = result["cognitive_result"]
    assert cognitive["evidence"]["claim_coverage"] == "COMPLETE"
    assert cognitive["evidence"]["model_claims"]["coverage"] == "INCOMPLETE"
    assert cognitive["presentation"]["whole_answer_verified"] is False
    assert cognitive["presentation"]["model_text"] == "Unverified prose."
    assert cognitive["reasoning"]["projection_status"] == (
        "NOT_REQUESTED_HOST_PROFILE" if enabled else "BUDGET_UNAVAILABLE")
    assert [a["protocol_status"] for a in cognitive["reasoning"]["model_text_attempts"]] == [
        "INTERMEDIATE_OR_UNACCEPTED", "ACCEPTED_FINAL"]
    assert result["model_claims"]["format_status"] == "NO_ACCEPTED_FINAL"
    if enabled:
        assert result["claim_projection_status"] == "NOT_REQUESTED_HOST_PROFILE"
        assert result["host_temporal_claim_pass"] is True
        assert result["host_temporal_projection"]["status"] == "VERIFIED"
    else:
        assert result["claim_projection_status"] == "BUDGET_UNAVAILABLE"
        assert "host_temporal_projection" not in result
    raw = evidence.read_json(out/"reproducibility"/"raw-seed-7.json")
    case = evidence.read_json(out/"reproducibility"/"case-7-C06.json")
    assert case["result"] == result
    assert evidence.verify_case(case, raw) == 4
