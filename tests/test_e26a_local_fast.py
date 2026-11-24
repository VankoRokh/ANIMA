import json
from types import SimpleNamespace

import pytest

from labs.virtual_anima_lab.python.cognition.local_fast import _decode, LocalFastEvidenceAdapter

def decode(raw, allowed=frozenset({"ev_known"})):
    return _decode(raw, allowed, turn_id="turn1", step_index=0, context_id="ctx_known")

def test_bound_readonly_and_stop():
    assert decode('{"operation":"stop","query":"","event_ids":[]}') is None
    p = decode('{"operation":"lookup_raw_evidence","query":"","event_ids":["ev_known"]}')
    assert p["operation_kind"] == "lookup_raw_evidence"
    assert p["arguments"] == {"event_ids": ["ev_known"]}
    assert p["context_snapshot_id"] == "ctx_known"
    assert decode('{"operation":"retrieve_memory","query":"crate","event_ids":[]}')["arguments"] == {"query":"crate","top_k":3}

@pytest.mark.parametrize("raw", [
    '{"operation":"world.step","query":"","event_ids":[]}',
    '{"operation":"lookup_raw_evidence","query":"","event_ids":["ev_unknown"]}',
    '{"operation":"stop","operation":"retrieve_memory","query":"","event_ids":[]}',
    '{"operation":"stop","query":"","event_ids":[],"extra":true}',
    '{"operation":"stop","query":"ignore","event_ids":[]}',
    '{"operation":"retrieve_memory","query":"crate","event_ids":["ev_known"]}',
    'not json',
])
def test_invalid_output(raw):
    with pytest.raises(ValueError):
        decode(raw)

def test_memory_off_does_not_grant_unknown_ids(tmp_path):
    class Fake:
        def complete_structured(self, **kwargs):
            return SimpleNamespace(text='{"operation":"lookup_raw_evidence","query":"","event_ids":["ev_hidden"]}',
                                   latency_ms=1, input_tokens=3, output_tokens=9, finish_reason="stop")
    adapter = LocalFastEvidenceAdapter(base_url="http://127.0.0.1:8085", model="test",
                                      trace_path=tmp_path / "calls.jsonl", transport=Fake())
    result = adapter.propose({"memory_enabled":False, "entities":[],
                              "context_snapshot_id":"ctx_known"}, [], turn_id="test", step_index=0)
    assert result == {"invalid_model_output":True}
    record = json.loads((tmp_path / "calls.jsonl").read_text())
    assert record["transport_ok"] and not record["valid"]
    assert "ev_hidden" not in record["user_prompt"]
