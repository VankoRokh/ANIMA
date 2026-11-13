"""M2 offline checks: real Core+Memory composition, no Godot required.

The online CI stage separately executes actual Godot 4.7.2 P6 bridge.
"""
import json
import subprocess
import sys

import pytest

from labs.virtual_anima_lab.python.m2_integrated_gate import (
    FrozenHistory, MANIFEST, QUERY, SCHEMA, _prepare, seed,
)
from labs.virtual_anima_lab.python.run_core_demo import make_core


def test_m2_p6_composition_can_read_real_historical_memory_before_world_goal(tmp_path):
    data = tmp_path / "isolated"
    data.mkdir()
    # Port never contacted: only historical query and unbound typed Goal exist.
    core = make_core(data, port=49998, enable_event_retrieval=True)
    goal_id = _prepare(core, data, "normal")
    manifest = json.loads((data / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema"] == SCHEMA
    assert manifest["goal_id"] == goal_id
    assert manifest["history_id"] in manifest["captured_sources"]
    assert manifest["query_id"] not in manifest["captured_sources"]
    assert set(manifest["memory_ids"]) & set(manifest["selected_ids"])
    assert manifest["fast_items"] <= 6
    assert manifest["fast_chars"] <= 1200
    assert core.core_decision._binding(goal_id) is None
    assert core.core_execution.store.list_operations() == []
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "active"
    assert core.core_autonomy is not None
    assert core.event_retrieval.get(manifest["history_id"])["payload"]["text"].startswith(
        "Unverified earlier report"
    )
    assert core.event_retrieval.get(manifest["query_id"])["payload"]["text"] == QUERY
    core.runtime.sleep()


def test_m2_frozen_history_is_read_only_query_specific():
    context = {"query": QUERY, "consumer": "FAST", "memories": []}
    snapshot = FrozenHistory(QUERY, context)
    assert snapshot.build(QUERY) is context
    with pytest.raises(ValueError):
        snapshot.build("another question")
    with pytest.raises(ValueError):
        snapshot.build(QUERY, consumer="DEEP")


def test_m2_seed_rejects_existing_user_data_before_core_creation(tmp_path):
    path = tmp_path / "protected"
    path.mkdir()
    sentinel = path / "keep.txt"
    sentinel.write_text("KEEP", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh empty"):
        seed("normal", path, 49998)
    assert sentinel.read_text(encoding="utf-8") == "KEEP"


def test_m2_seed_rejects_unknown_mode_without_data_touch(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        seed("unknown", tmp_path / "missing", 49998)
    assert not (tmp_path / "missing").exists()

def test_m2_rejects_non_godot_executable_before_world_creation(tmp_path):
    report = tmp_path / "must-not-exist.json"
    run = subprocess.run(
        [
            sys.executable, "-m",
            "labs.virtual_anima_lab.python.m2_integrated_gate",
            "--godot", sys.executable, "--report", str(report),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert run.returncode != 0
    assert "requires exact Godot 4.7.2" in run.stderr
    assert not report.exists()
