"""R9.3.5: actual adapter boundaries, rejection accounting and frozen evidence."""
import json

import pytest

from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
from labs.virtual_anima_lab.python.cognition.local_fast import (
    LocalFastChoiceAdapter, LocalFastEvidenceAdapter,
)
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as evidence
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion
from tests.test_e26_r92_export_integrity import make_result_bundle, _reseal_mutated_fixture


@pytest.mark.parametrize("profile", ["legacy", "choice"])
@pytest.mark.parametrize("metadata,reason,accepted", [
    ({"stop_type": "eos", "stop": True}, "eos", True),
    ({"stop_type": "word", "stop": True}, "word", True),
    ({"stop_type": "limit", "stop": True}, "limit", False),
    ({"stop_type": "none", "stop": False}, "none", False),
    ({"stop": True}, "stop", False),
    ({"stop": False}, None, False),
    ({"stop_type": 17}, "17", False),
])
def test_native_completion_transport_metadata(tmp_path, monkeypatch, profile,
                                              metadata, reason, accepted):
    mem = memory(tmp_path / "core", monkeypatch)
    adapter_type = LocalFastEvidenceAdapter if profile == "legacy" else LocalFastChoiceAdapter
    adapter = adapter_type(base_url="http://127.0.0.1:8085", model="test",
                           trace_path=tmp_path / "calls.jsonl")
    value = ({"operation": "stop", "query": "", "event_ids": []}
             if profile == "legacy" else {"choice": "stop"})
    payload = {"content": json.dumps(value), "tokens_evaluated": 20,
               "tokens_predicted": 8, **metadata}
    requests = []

    def post(endpoint, body, *, timeout_seconds):
        requests.append((endpoint, body))
        if endpoint.endswith("/apply-template"):
            return {"prompt": "rendered"}
        assert endpoint.endswith("/completion")
        return payload

    monkeypatch.setattr(adapter.transport, "_post_json", post)
    coord = E25LabCognitiveCoordinator(mem, max_steps=1)
    report = coord.run_turn(adapter, turn_id="wire_metadata")
    trace, = adapter.calls
    assert len(requests) == 2
    assert requests[-1][1]["n_predict"] == 256
    assert trace["transport_ok"] is True
    assert trace["finish_reason"] == reason
    assert trace["valid"] is accepted
    assert (trace["input_tokens"], trace["output_tokens"]) == (20, 8)
    assert report["status"] == ("STOPPED" if accepted else "REJECTED")
    assert not any(r["outcome"]["status"] == "COMPLETED"
                   for r in coord.decision_records("wire_metadata"))
    assert len(mem._core.event_log.load_events()) == 3


class FaultTransport(Fake):
    def complete(self, payload):
        result = super().complete(payload)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("phase", ["research", "projection"])
@pytest.mark.parametrize("fault,known_input,known_output,missing_input,missing_output,reason", [
    ("length", 10, 4, 0, 0, None),
    ("missing_input", 0, 4, 1, 0, "USAGE_UNAVAILABLE"),
    ("missing_output", 10, 0, 0, 1, "USAGE_UNAVAILABLE"),
    ("bad_usage_type", 0, 4, 1, 0, "USAGE_UNAVAILABLE"),
    ("output_exceeded", 10, 257, 0, 0, "OUTPUT_USAGE_EXCEEDED"),
    ("input_exceeded", 9000, 4, 0, 0, "INPUT_USAGE_EXCEEDED"),
    ("timeout", 0, 0, 1, 1, "USAGE_UNAVAILABLE"),
])
def test_rejected_call_keeps_known_resource_cost(tmp_path, monkeypatch, phase, fault,
        known_input, known_output, missing_input, missing_output, reason):
    mem = memory(tmp_path / "core", monkeypatch)
    bad = completion(content='{"answer":"4","claims":[]}', finish="length")
    if fault == "missing_input":
        del bad["usage"]["prompt_tokens"]
    elif fault == "missing_output":
        del bad["usage"]["completion_tokens"]
    elif fault == "bad_usage_type":
        bad["usage"]["prompt_tokens"] = True
    elif fault == "output_exceeded":
        bad["usage"]["completion_tokens"] = 257
    elif fault == "input_exceeded":
        bad["usage"]["prompt_tokens"] = 9000
    elif fault == "timeout":
        bad = TimeoutError("synthetic transport timeout")
    preceding = [completion(content="4")] if phase == "projection" else []
    transport = FaultTransport(*preceding, bad)
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
        task="2+2", trace_path=tmp_path / "native.jsonl", transport=transport)
    coord = E25LabCognitiveCoordinator(mem)
    req = CompletionRequirement("no_service_read")
    report = coord.run_turn(adapter, turn_id="fault_accounting",
        completion_requirement=req, resource_limits=ResourceLimits(),
        project_result_claims=(phase == "projection"))
    budget = report["resource_budget"]
    count = len(preceding) + 1
    assert len(transport.requests) == budget["reserved_calls"] == count
    assert budget["reported_input_tokens"] == known_input + 10 * len(preceding)
    assert budget["reported_output_tokens"] == known_output + 4 * len(preceding)
    assert budget["input_usage_missing_calls"] == missing_input
    assert budget["output_usage_missing_calls"] == missing_output
    assert budget["usage_complete"] is not bool(missing_input or missing_output)
    assert budget["reservation_pending"] is False
    assert budget["stop_reason"] == reason
    if phase == "projection":
        assert report["status"] == "STOPPED"
        projection = report["claim_projection"]
        assert projection["status"] == ("RESOURCE_REJECTED" if reason else "INVALID_RESPONSE")
        call = projection["call"]
    else:
        assert report["status"] == (
            "STEP_BUDGET_EXHAUSTED" if reason and fault != "timeout" else "REJECTED")
        call = adapter.calls[-1]
    assert call["valid"] is False
    assert call["transport_ok"] is (fault != "timeout")
    if fault != "timeout":
        assert call["raw_response"] == bad
        assert call["termination_status"] == "INCOMPLETE"
    else:
        assert call["raw_response"] is None
        assert "termination_status" not in call
    result = build_cognitive_result(coord, report, requirement=req,
        research_calls=adapter.calls, claim_phase="claim_projection" if preceding else None)
    assert result["presentation"]["model_text"] == ("4" if preceding else None)
    assert result["presentation"]["projection_text"] is None
    assert result["presentation"]["whole_answer_verified"] is False
    assert not any(r["outcome"]["status"] == "COMPLETED"
                   for r in coord.decision_records("fault_accounting"))
    assert len(mem._core.event_log.load_events()) == 3
    assert mem._core.memory_store.count() == 0


@pytest.mark.parametrize("fault", ["status", "reason"])
def test_resealed_terminal_metadata_disagrees_with_wire(tmp_path, monkeypatch, fault):
    root, manifest, transport = make_result_bundle(tmp_path, monkeypatch)
    path = root / "case-7-C01.json"
    fixture = evidence.read_json(path)
    call = fixture["model_calls"][0]
    assert call["termination_status"] == "TOOL_CALL_COMPLETE"
    if fault == "status":
        call["termination_status"] = "TEXT_COMPLETE"
    else:
        call["finish_reason"] = "stop"
    _reseal_mutated_fixture(root, path, fixture, manifest)
    with pytest.raises(ValueError, match="terminal diagnostic mismatch"):
        evidence.verify_bundle(root)
    assert len(transport.requests) == 2


def test_historical_terminal_metadata_optional(tmp_path, monkeypatch):
    root, manifest, transport = make_result_bundle(tmp_path, monkeypatch)
    path = root / "case-7-C01.json"
    fixture = evidence.read_json(path)
    for call in fixture["model_calls"]:
        del call["termination_status"]
    _reseal_mutated_fixture(root, path, fixture, manifest)
    assert evidence.verify_bundle(root)["requests"] == 2
    assert len(transport.requests) == 2
