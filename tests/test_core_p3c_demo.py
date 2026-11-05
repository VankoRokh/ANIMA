"""P3-C diagnostic demo: isolated CLI, external ground-truth boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run(path, state, *, format="json", extra=()):
    return subprocess.run(
        [
            sys.executable, "-B", "-m", "anima.core.demo_p3c",
            "--data-dir", str(path), "--initial-state", state,
            "--format", format, *extra,
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



@pytest.mark.parametrize("state,expected_effect", [("open", 1), ("closed", 0)])
def test_p3c_human_report_is_default_and_explains_decisions(tmp_path, state, expected_effect):
    run = _run(tmp_path / "human", state, format="text")
    assert run.returncode == 0, run.stderr
    assert "ANIMA  /  CORE v0.1" in run.stdout
    assert "ХОД ВЫПОЛНЕНИЯ" in run.stdout
    assert "ПРОВЕРКИ" in run.stdout
    assert "РЕЗУЛЬТАТ: PASS" in run.stdout
    assert f"Эффектов: {expected_effect}" in run.stdout
    assert ("предложить действие" if expected_effect else "действие не требуется") in run.stdout
    assert "Мир — привилегированная проверка оператора" in run.stdout


def test_p3c_demo_markdown_report_with_snapshot_and_no_overwrite(tmp_path):
    output = tmp_path / "trace.md"
    result = _run(
        tmp_path / "demo", "open", format="text",
        extra=("--report-md", str(output), "--snapshot", "example-commit-abc"),
    )
    assert result.returncode == 0, result.stderr
    assert output.is_file()
    markdown = output.read_text(encoding="utf-8")
    assert "# ANIMA Core v0.1 — Demonstration P3-C" in markdown
    assert "**Result:** PASS" in markdown
    assert "example-commit-abc" in markdown
    assert "Verification" not in markdown or "evidence" in markdown
    assert "[x] `goal_completed`" in markdown
    assert "Operator world ground truth" in markdown

    again = _run(
        tmp_path / "another_demo", "closed", format="text",
        extra=("--report-md", str(output)),
    )
    assert again.returncode != 0
    assert "refusing to overwrite" in again.stderr
    assert output.read_text(encoding="utf-8") == markdown


def test_p3c_demo_default_text_no_json_blob(tmp_path):
    run = subprocess.run(
        [
            sys.executable, "-B", "-m", "anima.core.demo_p3c",
            "--data-dir", str(tmp_path / "plain"),
            "--initial-state", "closed",
        ],
        cwd=ROOT,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "РЕЗУЛЬТАТ: PASS" in run.stdout
    assert not run.stdout.lstrip().startswith("{")
