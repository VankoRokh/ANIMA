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
