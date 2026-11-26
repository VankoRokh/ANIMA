"""R9.1 RED gate: internally inconsistent but correctly resealed E2.6 exports.

The fixtures are synthetic, generated through the existing lab exporter.
They reproduce R8-N01's class of failure, not the original R7 archive bytes.
Never edit the original evidence. A checksum-only failure is not a pass.
"""
import pytest

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
