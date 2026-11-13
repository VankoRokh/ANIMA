"""M1 notebook gate: source-backed historical context never licenses world action."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_memory_v1_integrated_decision_gate import (
    MANIFEST, SCENARIOS, _child, run_gate,
)

ROOT = Path(__file__).resolve().parents[1]


def test_m1_full_read_only_memory_to_core_action_boundary():
    report = run_gate()
    assert report["status"] == "M1_INTEGRATED_DECISION_PASS"
    assert [s["scenario"] for s in report["scenarios"]] == list(SCENARIOS)
    assert [s["effect_count"] for s in report["scenarios"]] == [1, 0, 1]
    assert [s["sensor_failure_blocked"] for s in report["scenarios"]] == [
        False, False, True
    ]
    for result in report["scenarios"]:
        assert result["independent_sensor_proof"] is True
        assert result["goal_status"] == "completed"
        assert result["query_excluded_from_historical_snapshot"] is True
        assert result["history_id"] != result["query_id"]
        assert result["fast_memory_ids"]
        assert result["history_memory_ids"]
        assert result["fast_items"] <= 6 and result["fast_chars"] <= 1200
        assert result["memory_used_as_sensor_authority"] is False
        assert result["typed_goal_explicitly_operator_bound"] is True
        assert result["effect_replayed"] is False
        assert result["knowledge_count"] == 0
        assert result["godot_val_tested"] is False


@pytest.mark.parametrize("scenario", ["false_closed", "false_open"])
def test_m1_second_interpreter_reopens_same_goal_and_receipts(tmp_path, scenario):
    folder = tmp_path / scenario
    first = _child("seed", folder, scenario)
    assert first["status"] == "M1_SEED_PASS"
    second = _child("verify", folder, scenario)
    assert second["status"] == "M1_SCENARIO_PASS"
    assert second["effect_count"] == (1 if scenario == "false_closed" else 0)

    manifest = json.loads((folder / MANIFEST).read_text())
    assert manifest["query_id"] not in manifest["historical_source_ids_at_read"]
    assert manifest["history_id"] in manifest["historical_source_ids_at_read"]


def test_m1_refuses_nonempty_directory_and_preserves_sentinel(tmp_path):
    folder = tmp_path / "protected"
    folder.mkdir()
    sentinel = folder / "state.json"
    sentinel.write_text("UNCHANGED", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_integrated_decision_gate",
         "--internal-phase", "seed", "--scenario", "false_closed",
         "--root", str(folder)],
        cwd=ROOT, text=True, capture_output=True, timeout=30,
    )
    assert proc.returncode != 0
    assert "completely empty" in proc.stderr
    assert sentinel.read_text(encoding="utf-8") == "UNCHANGED"


def test_m1_rejects_corrupt_recovery_manifest(tmp_path):
    folder = tmp_path / "changed"
    _child("seed", folder, "false_closed")
    file = folder / MANIFEST
    manifest = json.loads(file.read_text())
    manifest["schema"] = "untrusted"
    file.write_text(json.dumps(manifest), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_integrated_decision_gate",
         "--internal-phase", "verify", "--scenario", "false_closed",
         "--root", str(folder)],
        cwd=ROOT, text=True, capture_output=True, timeout=30,
    )
    assert proc.returncode != 0
    assert "AssertionError" in proc.stderr
