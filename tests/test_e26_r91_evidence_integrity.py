"""R9.1 RED gate: internally inconsistent but correctly resealed E2.6 exports.

The fixtures are synthetic, generated through the existing lab exporter.
They reproduce R8-N01's class of failure, not the original R7 archive bytes.
Never edit the original evidence. A checksum-only failure is not a pass.
"""
from copy import deepcopy

import pytest

from labs.virtual_anima_lab.python.cognition.coordinator import E25LabCognitiveCoordinator
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from tests.test_e25a_cognition import memory
from tests.test_e26a_native_tools import Fake, completion

from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as r
from tests.test_e26_reproducibility import make_bundle


def _replace_json(path, value):
    # Only temporary copies owned by this test are rewritten.
    path.unlink()
    r.write_json(path, value)


def _reseal_checksums(root):
    index = root / "checksums.json"
    index.unlink()
    r.write_json(index, {
        p.name: r.file_digest(p)
        for p in sorted(root.glob("*.json"))
    })


def _mutate(root, defect):
    case_path = root / "case-7-C06.json"
    raw_path = root / "raw-seed-7.json"
    manifest_path = root / "manifest.json"
    case = r.read_json(case_path)
    raw = r.read_json(raw_path)
    manifest = r.read_json(manifest_path)
    lookup = case["trace"][1]
    assert lookup["proposal"]["operation_kind"] == "lookup_raw_evidence"
    assert lookup["admission"] == "ADMITTED"
    assert lookup["outcome"]["status"] == "COMPLETED"

    if defect == "unrequested_source":
        lookup["proposal"]["arguments"]["event_ids"] = ["ev_not_requested"]
        _replace_json(case_path, case)
    elif defect == "foreign_context_world":
        for record in case["trace"]:
            record["context_snapshot"]["world_instance_id"] = "foreign_world"
        _replace_json(case_path, case)
    elif defect == "rejected_admission":
        lookup["admission"] = "REJECTED"
        _replace_json(case_path, case)
    elif defect == "core_fingerprint":
        raw["samples"][0]["core_event"]["content_sha256"] = "0" * 64
        _replace_json(raw_path, raw)
    elif defect == "duplicate_seed":
        manifest["world_seeds"].append(manifest["world_seeds"][0])
        _replace_json(manifest_path, manifest)
    elif defect == "duplicate_scenario":
        manifest["scenarios"].append(dict(manifest["scenarios"][0]))
        _replace_json(manifest_path, manifest)
    elif defect == "foreign_proposal_turn":
        lookup["proposal"]["turn_id"] = "other_turn"
        _replace_json(case_path, case)
    else:
        raise AssertionError("unknown test mutation")
    _reseal_checksums(root)


@pytest.mark.parametrize("defect", [
    "unrequested_source",
    "foreign_context_world",
    "rejected_admission",
    "core_fingerprint",
    "duplicate_seed",
    "duplicate_scenario",
    "foreign_proposal_turn",
])
def test_r91_resealed_inconsistent_bundle_rejected(tmp_path, monkeypatch, defect):
    root, _, _ = make_bundle(tmp_path, monkeypatch)
    assert r.verify_bundle(root)["status"] == "E26_EVIDENCE_VERIFIED"
    _mutate(root, defect)
    # Prove that the negative test reaches semantic verification, not the
    # ordinary file checksum gate.
    checksums = r.read_json(root / "checksums.json")
    assert set(checksums) == {
        p.name for p in root.iterdir() if p.name != "checksums.json"
    }
    assert all(r.file_digest(root / name) == sha
               for name, sha in checksums.items())
    with pytest.raises(ValueError) as exc:
        r.verify_bundle(root)
    assert "checksum mismatch" not in str(exc.value)
    assert "file set mismatch" not in str(exc.value)


def _rebind_context(case, edit):
    """Update every reference to the frozen Context, including its digest."""
    context = deepcopy(case["trace"][0]["context_snapshot"])
    context.pop("context_snapshot_id")
    edit(context)
    identity = "ctx_" + r.digest(r.canonical(context))
    context["context_snapshot_id"] = identity
    case["turn"]["context_snapshot_id"] = identity
    for record in case["trace"]:
        record["context_snapshot"] = deepcopy(context)
        if record["proposal"] is not None:
            record["proposal"]["context_snapshot_id"] = identity
    for call in case["model_calls"]:
        if "context_snapshot_id" in call:
            call["context_snapshot_id"] = identity
        if call.get("proposal") is not None:
            call["proposal"]["context_snapshot_id"] = identity


def _refresh_calls(root, case):
    raw = r.read_json(root / "raw-seed-7.json")
    case["requests"] = [r.freeze_call(call, raw["aliases"], i)
                        for i, call in enumerate(case["model_calls"])]


def _assert_semantic_rejection(root):
    _reseal_checksums(root)
    checksums = r.read_json(root / "checksums.json")
    assert all(r.file_digest(root / name) == sha
               for name, sha in checksums.items())
    with pytest.raises(ValueError) as exc:
        r.verify_bundle(root)
    assert "checksum mismatch" not in str(exc.value)
    assert "file set mismatch" not in str(exc.value)


@pytest.mark.parametrize("defect", [
    "rehash_foreign_world",
    "rehash_unbound_context_event",
    "rehash_memory_off_history",
])
def test_r91_consistently_rehashed_context(tmp_path, monkeypatch, defect):
    root, _, _ = make_bundle(tmp_path, monkeypatch)
    assert r.verify_bundle(root)["status"] == "E26_EVIDENCE_VERIFIED"
    path = root / "case-7-C06.json"
    case = r.read_json(path)

    def edit(context):
        if defect == "rehash_foreign_world":
            context["world_instance_id"] = "f" * 32
        elif defect == "rehash_unbound_context_event":
            crate = next(row for row in context["entities"]
                         if row["entity_ref"] == "lab.item.crate")
            crate["last_seen_event_id"] = "ev_unbound"
        else:
            assert any(row["last_seen_sample"] != context["latest_sample_id"]
                       for row in context["entities"])
            context["memory_enabled"] = False

    _rebind_context(case, edit)
    _refresh_calls(root, case)
    _replace_json(path, case)
    _assert_semantic_rejection(root)


def _native_bundle(tmp_path, monkeypatch, *, stop_only=False):
    mem = memory(tmp_path / "core", monkeypatch)
    out = tmp_path / "native_bundle"
    out.mkdir()
    raw = r.export_raw(mem, out, 7)
    responses = ([completion(content="No additional reads needed.")] if stop_only
                 else [completion("retrieve_memory", '{"query":"crate","top_k":3}'),
                       completion(content="Historical observations only.")])
    adapter = NativeLabAdapter(
        base_url="http://127.0.0.1:8085", model="test",
        trace_path=tmp_path / "native_calls.jsonl", task="Find the crate.",
        transport=Fake(*responses),
    )
    coordinator = E25LabCognitiveCoordinator(mem)
    report = coordinator.run_turn(adapter, turn_id="native_evidence")
    assert report["status"] == "STOPPED"
    trace = coordinator.decision_records("native_evidence")
    assert len(trace) == (0 if stop_only else 1)
    assert all(call["valid"] for call in adapter.calls)
    r.export_case(out, 7, "C06", report, trace, adapter.calls, raw)
    r.seal_bundle(out, {"schema": r.SCHEMA, "git_sha": "a" * 40,
                        "world_seeds": [7],
                        "scenarios": [{"id": "C06", "enabled": True}]},
                  complete=True)
    return out


@pytest.mark.parametrize("stop_only", [False, True])
def test_r91_native_valid_bundle(tmp_path, monkeypatch, stop_only):
    root = _native_bundle(tmp_path, monkeypatch, stop_only=stop_only)
    result = r.verify_bundle(root)
    assert result["status"] == "E26_EVIDENCE_VERIFIED"
    assert result["requests"] == (1 if stop_only else 2)


@pytest.mark.parametrize("defect", [
    "wire_arguments_disagree",
    "call_proposal_disagrees",
    "call_context_disagrees",
    "missing_research_call",
    "deleted_service_journal",
    "manifest_memory_mode_disagrees",
    "unexpected_sealed_file",
])
def test_r91_native_call_chain(tmp_path, monkeypatch, defect):
    root = _native_bundle(tmp_path, monkeypatch)
    assert r.verify_bundle(root)["status"] == "E26_EVIDENCE_VERIFIED"
    path = root / "case-7-C06.json"
    case = r.read_json(path)
    call = case["model_calls"][0]
    assert call["proposal"] == case["trace"][0]["proposal"]
    if defect == "wire_arguments_disagree":
        fn = call["raw_response"]["choices"][0]["message"]["tool_calls"][0]["function"]
        fn["arguments"] = '{"query":"elephant","top_k":3}'
    elif defect == "call_proposal_disagrees":
        call["proposal"]["arguments"]["query"] = "elephant"
    elif defect == "call_context_disagrees":
        call["context_snapshot_id"] = "ctx_other"
    elif defect == "missing_research_call":
        case["model_calls"].pop(0)
    elif defect == "deleted_service_journal":
        case["trace"] = []
        case["turn"]["outcomes"] = []
    elif defect == "manifest_memory_mode_disagrees":
        manifest_path = root / "manifest.json"
        manifest = r.read_json(manifest_path)
        manifest["scenarios"][0]["enabled"] = False
        _replace_json(manifest_path, manifest)
    elif defect == "unexpected_sealed_file":
        r.write_json(root / "unreferenced.json", {"unexpected": True})
    else:
        raise AssertionError("unknown test mutation")
    _refresh_calls(root, case)
    _replace_json(path, case)
    _assert_semantic_rejection(root)
