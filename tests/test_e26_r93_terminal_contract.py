"""R9.3 RED: valid JSON must not bypass terminal status checks."""
import json
from types import SimpleNamespace

import pytest

from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.local_fast import (
    LocalFastChoiceAdapter, LocalFastEvidenceAdapter,
)
from tests.test_e25a_cognition import memory


class StructuredResponse:
    def __init__(self, text, finish):
        self.text = text
        self.finish = finish
        self.calls = 0

    def complete_structured(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(text=self.text, finish_reason=self.finish,
                               latency_ms=1.0, input_tokens=20, output_tokens=8)


@pytest.mark.parametrize("profile", ["legacy", "choice"])
@pytest.mark.parametrize("operation", ["stop", "read"])
@pytest.mark.parametrize("finish", ["eos", "word", "limit", "length", "unknown", None, "none", "stop", "tool_calls"])
def test_structured_adapter_requires_completed_generation(tmp_path, monkeypatch,
                                                          profile, operation, finish):
    mem = memory(tmp_path / "core", monkeypatch)
    if profile == "legacy":
        adapter_type = LocalFastEvidenceAdapter
        value = {"operation": "stop" if operation == "stop" else "retrieve_memory",
                 "query": "" if operation == "stop" else "crate", "event_ids": []}
    else:
        adapter_type = LocalFastChoiceAdapter
        value = {"choice": "stop" if operation == "stop" else "search_crate"}
    transport = StructuredResponse(json.dumps(value), finish)
    adapter = adapter_type(base_url="http://127.0.0.1:8085", model="test",
                           trace_path=tmp_path / "calls.jsonl", transport=transport)
    coord = E25LabCognitiveCoordinator(mem, max_steps=1)
    report = coord.run_turn(adapter, turn_id="terminal_contract")
    trace, = adapter.calls
    assert transport.calls == 1
    assert trace["transport_ok"] is True
    assert trace["finish_reason"] == finish
    assert trace["input_tokens"] == 20 and trace["output_tokens"] == 8
    assert trace["raw_response"] == transport.text
    records = coord.decision_records("terminal_contract")
    assert trace["termination_status"] == (
        "TEXT_COMPLETE" if finish in ("eos", "word") else
        "INCOMPLETE" if finish in ("limit", "none") else "UNKNOWN")
    if finish in ("eos", "word"):
        assert trace["valid"] is True
        if operation == "stop":
            assert report["status"] == "STOPPED" and not records
        else:
            assert len(records) == 1 and records[0]["outcome"]["status"] == "COMPLETED"
    else:
        assert trace["valid"] is False
        assert report["status"] == "REJECTED"
        assert not any(r["outcome"]["status"] == "COMPLETED" for r in records)
    assert len(mem._core.event_log.load_events()) == 3
    assert mem._core.memory_store.count() == 0


@pytest.mark.parametrize("wire,reason,expected", [
    ("llama_cpp_completion", "eos", "TEXT_COMPLETE"),
    ("llama_cpp_completion", "word", "TEXT_COMPLETE"),
    ("llama_cpp_completion", "limit", "INCOMPLETE"),
    ("llama_cpp_completion", "none", "INCOMPLETE"),
    ("llama_cpp_completion", "stop", "UNKNOWN"),
    ("chat_completion", "stop", "TEXT_COMPLETE"),
    ("chat_completion", "tool_calls", "TOOL_CALL_COMPLETE"),
    ("chat_completion", "length", "INCOMPLETE"),
    ("chat_completion", "content_filter", "INCOMPLETE"),
    ("chat_completion", "eos", "UNKNOWN"),
    ("chat_completion", "word", "UNKNOWN"),
    ("chat_completion", "limit", "UNKNOWN"),
    ("chat_completion", None, "UNKNOWN"),
    ("llama_cpp_completion", True, "UNKNOWN"),
    ("llama_cpp_completion", " eos ", "UNKNOWN"),
    ("chat_completion", "STOP", "UNKNOWN"),
])
def test_termination_mapping_is_wire_specific(wire, reason, expected):
    from anima.agent.generation_termination import classify_termination
    assert classify_termination(reason, wire=wire) == expected


def test_unknown_wire_not_inferred():
    from anima.agent.generation_termination import classify_termination
    with pytest.raises(ValueError, match="unsupported generation wire protocol"):
        classify_termination("stop", wire="unknown")


@pytest.mark.parametrize("kind", ["text", "tool"])
@pytest.mark.parametrize("finish", ["stop", "tool_calls", "length", "content_filter",
                                    "eos", "word", "limit", "unknown", None])
def test_native_terminal_parity(kind, finish):
    from tests.test_e26a_native_tools import completion, session
    from anima.agent.generation_termination import classify_termination
    response = (completion(content="Done") if kind == "text" else
                completion("retrieve_memory", '{"query":"crate","top_k":3}'))
    if finish is None:
        del response["choices"][0]["finish_reason"]
    else:
        response["choices"][0]["finish_reason"] = finish
    native, transport = session(response)
    accepted = (kind, finish) in (("text", "stop"), ("tool", "tool_calls"))
    if accepted:
        result = native.next()
        assert (result is None) == (kind == "text")
    else:
        with pytest.raises(ValueError):
            native.next()
        assert native.pending is None
    call, = native.calls
    assert call["valid"] is accepted
    assert call["transport_ok"] is True
    assert call["finish_reason"] == finish
    assert call["termination_status"] == classify_termination(finish, wire="chat_completion")
    assert call["raw_response"] == response
    assert (call["input_tokens"], call["output_tokens"]) == (10, 4)
    assert len(transport.requests) == 1


@pytest.mark.parametrize("finish", ["stop", "tool_calls", "length", "content_filter",
                                    "eos", "word", "limit", "unknown", None])
def test_projection_terminal_parity(tmp_path, monkeypatch, finish):
    from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement
    from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
    from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits
    from labs.virtual_anima_lab.python.cognition.cognitive_result import build_cognitive_result
    from anima.agent.generation_termination import classify_termination
    from tests.test_e26a_native_tools import completion, Fake
    mem = memory(tmp_path / "core", monkeypatch)
    original = completion(content="4")
    response = completion(content='{"answer":"4","claims":[]}')
    if finish is None:
        del response["choices"][0]["finish_reason"]
    else:
        response["choices"][0]["finish_reason"] = finish
    transport = Fake(original, response)
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model="test",
                               task="2+2", trace_path=tmp_path / "native.jsonl", transport=transport)
    coord = E25LabCognitiveCoordinator(mem)
    req = CompletionRequirement("no_service_read")
    report = coord.run_turn(adapter, turn_id="terminal_projection",
                            completion_requirement=req, resource_limits=ResourceLimits(),
                            project_result_claims=True)
    projection = report["claim_projection"]
    call = projection["call"]
    assert projection["status"] == ("GENERATED" if finish == "stop" else "INVALID_RESPONSE")
    assert call["valid"] is (finish == "stop")
    assert call["transport_ok"] is True and call["raw_response"] == response
    assert call["finish_reason"] == finish
    assert call["termination_status"] == classify_termination(finish, wire="chat_completion")
    assert (call["input_tokens"], call["output_tokens"]) == (10, 4)
    result = build_cognitive_result(coord, report, requirement=req,
                                    research_calls=adapter.calls, claim_phase="claim_projection")
    assert result["presentation"]["model_text"] == "4"
    assert result["presentation"]["projection_text"] == ("4" if finish == "stop" else None)
    assert result["presentation"]["whole_answer_verified"] is False
    assert len(transport.requests) == report["resource_budget"]["reserved_calls"] == 2
    assert not coord.decision_records("terminal_projection")
    assert len(mem._core.event_log.load_events()) == 3
