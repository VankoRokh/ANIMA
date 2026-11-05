"""P3-C diagnostic demo: isolated CLI, external ground-truth boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run(path, state):
    return subprocess.run(
        [
            sys.executable, "-B", "-m", "anima.core.demo_p3c",
            "--data-dir", str(path), "--initial-state", state,
        ],
        cwd=ROOT,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("state,operations", [("open", 1), ("closed", 0)])
def test_p3c_demo_isolated_autonomy_and_verification(tmp_path, state, operations):
    target = tmp_path / "one_time_demo"
    executed = _run(target, state)
    assert executed.returncode == 0, executed.stderr
    records = [json.loads(line) for line in executed.stdout.splitlines()]
    assert [row["stage"] for row in records[:2]] == [
        "bootstrap", "goal_registered"
    ]
    assert records[0]["autonomous"] is True
    assert records[0]["model_required"] is False
    assert records[0]["initial_state"] == state
    result = records[-1]
    assert result["stage"] == "result"
    assert result["goal_status"] == "completed"
    assert result["task_statuses"] == ["completed"]
    assert result["belief_value"]["value"] == "closed"
    assert result["operator_ground_truth"] == "closed"
    assert result["pending_auto_triggers"] == 0
    assert len([x for x in records if x["stage"] == "execution_ledger"]) == operations


def test_p3c_demo_refuses_nonempty_existing_data_dir(tmp_path):
    location = tmp_path / "live_data"
    location.mkdir()
    sentinel = location / "state.json"
    sentinel.write_text("KEEP ME", encoding="utf-8")
    run = _run(location, "open")
    assert run.returncode != 0
    assert "absent or empty" in run.stderr
    assert sentinel.read_text(encoding="utf-8") == "KEEP ME"
