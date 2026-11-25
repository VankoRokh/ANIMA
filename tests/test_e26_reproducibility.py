import json

import pytest

from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as r
from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator, TwoStepEvidenceStub
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion


def test_ca05_raw_export_contains_canonical_bytes_and_core_pointers(tmp_path, monkeypatch):
    mem = memory(tmp_path / "core", monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    raw = r.export_raw(mem, out, 7)
    assert r.verify_raw(raw) == 3
    assert len(raw["aliases"]) >= 7
    assert r.read_json(out / "raw-seed-7.json") == raw
    raw["samples"][1]["raw_json"] += " "
    with pytest.raises(ValueError):
        r.verify_raw(raw)


def test_ca05_raw_export_rejects_pointer_mismatch(tmp_path, monkeypatch):
    mem = memory(tmp_path / "core", monkeypatch)
    raw = r.export_raw(mem, tmp_path, 7)
    raw["samples"][0]["core_event"]["payload"]["value"]["value"] = "incorrect"
    with pytest.raises(ValueError, match="pointer mismatch"):
        r.verify_raw(raw)


def make_bundle(tmp_path, monkeypatch):
    mem = memory(tmp_path / "core", monkeypatch)
    out = tmp_path / "bundle"
    out.mkdir()
    raw = r.export_raw(mem, out, 7)
    coord = E25LabCognitiveCoordinator(mem)
    report = coord.run_turn(TwoStepEvidenceStub(), turn_id="evidence")
    trace = coord.decision_records("evidence")
    request = {"model": "test", "messages": [{"role":"user","content": raw["samples"][1]["event_id"]}]}
    response = completion(content="Done")
    calls = [{"request":request, "raw_response":response, "transport_ok":True, "valid":True}]
    r.export_case(out, 7, "C06", report, trace, calls, raw)
    r.seal_bundle(out, {"schema":r.SCHEMA,"git_sha":"a"*40,
                        "world_seeds":[7],"scenarios":[{"id":"C06"}]}, complete=True)
    return out, request, response


def test_ca05_bundle_detects_tampering(tmp_path, monkeypatch):
    out, _, _ = make_bundle(tmp_path, monkeypatch)
    result = r.verify_bundle(out)
    assert result["raw_samples"] == 3 and result["requests"] == 1 and result["cases"] == 1
    with (out / "raw-seed-7.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        r.verify_bundle(out)


def test_ca05_bundle_rejects_missing_case(tmp_path):
    r.seal_bundle(tmp_path, {"schema":r.SCHEMA,"git_sha":"a"*40,
                            "world_seeds":[],"scenarios":[]}, complete=False)
    with pytest.raises(ValueError, match="incomplete"):
        r.verify_bundle(tmp_path)


def test_ca06_exact_replay_preserves_original_request_and_no_dispatch(tmp_path, monkeypatch):
    out, request, response = make_bundle(tmp_path, monkeypatch)
    fake = Fake(response)
    result = r.replay_request(out, seed=7, case_id="C06", index=0, transport=fake)
    assert fake.requests == [request]
    assert result["response_exact_equal"] and result["choices_equal"]
    assert not result["tool_dispatch_performed"]
    changed = Fake(completion("retrieve_memory", '{"query":"crate","top_k":1}'))
    result = r.replay_request(out, seed=7, case_id="C06", index=0, transport=changed)
    assert changed.requests == [request]
    assert not result["response_exact_equal"] and not result["choices_equal"]
    assert not result["tool_dispatch_performed"]


def test_ca06_normalized_hash_is_diagnostic_not_exact_request():
    a = r.canonical({"messages":[{"content":"event ev_first"}]})
    b = r.canonical({"messages":[{"content":"event ev_second"}]})
    assert r.digest(a) != r.digest(b)
    assert r.normalized_request_sha(a, {"ev_first":"ev_sample_0001"}) == (
        r.normalized_request_sha(b, {"ev_second":"ev_sample_0001"}))


def test_ca06_replay_does_not_accept_negative_index(tmp_path, monkeypatch):
    out, _, response = make_bundle(tmp_path, monkeypatch)
    fake = Fake(response)
    with pytest.raises(ValueError):
        r.replay_request(out, seed=7, case_id="C06", index=-1, transport=fake)
    assert fake.requests == []
