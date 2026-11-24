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


from labs.virtual_anima_lab.python.cognition.local_fast import (
    LocalFastChoiceAdapter, _choice_context, _decode_choice,
)


def choice_context(enabled=True):
    return {"memory_enabled": enabled, "context_snapshot_id": "ctx_test",
            "entities": [{"category": "item", "entity_ref": "lab.item.crate",
                          "current_observation": "not_observed",
                          "last_seen_event_id": "ev_crate"}] if enabled else []}


def test_choice_exact_source_binding():
    payload, choices = _choice_context(choice_context(), [])
    assert "ev_crate" not in json.dumps(payload)
    assert payload["observations"][0]["source"] == "source_1"
    result = _decode_choice('{"choice":"inspect_source_1"}', choices,
                            turn_id="test", step_index=0, context_id="ctx_test")
    assert result["arguments"] == {"event_ids": ["ev_crate"]}
    assert result["context_snapshot_id"] == "ctx_test"
    assert choices["search_crate"][1]["query"] == "crate"


@pytest.mark.parametrize("raw", [
    '{"choice":"inspect_source_1"}',
    '{"choice":"world.step"}',
    '{"choice":"stop","choice":"search_crate"}',
    '{"choice":"search_crate","query":"crate"}',
    '{"choice":1}',
    '{"choice":"stop"} trailing',
])
def test_choice_no_history_no_extra_authority(raw):
    _, choices = _choice_context(choice_context(False), [])
    with pytest.raises(ValueError):
        _decode_choice(raw, choices, turn_id="test", step_index=0, context_id="ctx_test")


def test_choice_preserves_model_mistake(tmp_path):
    class Fake:
        def complete_structured(self, **kwargs):
            assert "inspect_source_1" not in kwargs["response_schema"]["properties"]["choice"]["enum"]
            return SimpleNamespace(text='{"choice":"search_obstacle"}',
                                   latency_ms=1, input_tokens=3, output_tokens=9, finish_reason="eos")
    adapter = LocalFastChoiceAdapter(base_url="http://127.0.0.1:8085", model="test",
                                     trace_path=tmp_path / "calls.jsonl", transport=Fake())
    result = adapter.propose(choice_context(False), [], turn_id="test", step_index=0)
    assert result["arguments"] == {"query": "obstacle", "top_k": 3}
    assert adapter.calls[0]["valid"]
