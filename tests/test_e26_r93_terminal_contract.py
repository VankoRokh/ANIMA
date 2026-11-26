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
@pytest.mark.parametrize("finish", ["eos", "word", "limit", "length", "unknown", None])
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
