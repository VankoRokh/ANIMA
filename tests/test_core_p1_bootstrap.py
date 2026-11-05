"""P1 tests: one composition root, headless lifecycle, persisted identity.

P2 Belief and P3 autonomous action tests belong to later slices.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from anima.core.assembly import build_core


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_p1_build_core_is_idle_until_explicit_wake(tmp_path):
    core = build_core(tmp_path)
    before = core.runtime.snapshot()

    assert before["state"]["status"] == "created"
    assert before["state"]["session"] == 0
    assert before["state"]["events_processed"] == 0
    assert before["memory"]["count"] == 0

    assert [event.event_type for event in core.runtime.wake()] == ["system.wake"]
    assert [event.event_type for event in core.runtime.sleep()] == ["system.sleep"]

    after = core.runtime.snapshot()
    assert after["state"]["status"] == "sleeping"
    assert after["state"]["session"] == 1
    assert after["state"]["events_processed"] == 2


def test_p1_reopen_preserves_identity_and_memory(tmp_path):
    original = build_core(tmp_path)
    instance_id = original.identity.get()["instance_id"]
    original.runtime.wake()
    original.runtime.user_input("P1 persistence sentinel")
    original.runtime.sleep()

    reopened = build_core(tmp_path)
    assert reopened.identity.get()["instance_id"] == instance_id
    assert reopened.runtime.snapshot()["state"]["session"] == 1
    assert reopened.runtime.snapshot()["state"]["events_processed"] == 3
    assert reopened.runtime.snapshot()["memory"]["count"] == 1

    reopened.runtime.wake()
    reopened.runtime.sleep()
    result = reopened.runtime.snapshot()
    assert result["state"]["session"] == 2
    assert result["state"]["events_processed"] == 5
    assert result["memory"]["count"] == 1


def _smoke(data_dir, *args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "anima.core",
            *args,
            "--data-dir",
            str(data_dir),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        env=env,
        check=False,
    )


def test_p1_headless_command_restarts_without_model_or_gui(tmp_path):
    first = _smoke(tmp_path, "--once")
    assert first.returncode == 0, first.stderr
    first_result = json.loads(first.stdout)

    assert first_result["phase"] == "P1_BOOTSTRAP_ONLY"
    assert first_result["autonomous_loop"] is False
    assert first_result["status"] == "sleeping"
    assert first_result["session"] == 1
    assert first_result["events_processed"] == 2
    assert first_result["memories"] == 0

    second = _smoke(tmp_path, "--once")
    assert second.returncode == 0, second.stderr
    second_result = json.loads(second.stdout)

    assert second_result["instance_id"] == first_result["instance_id"]
    assert second_result["session"] == 2
    assert second_result["events_processed"] == 4
    assert second_result["status"] == "sleeping"
    assert second_result["memories"] == 0


def test_p1_headless_smoke_requires_explicit_once(tmp_path):
    result = _smoke(tmp_path)
    assert result.returncode != 0
    assert "--once is required" in result.stderr
    assert not (tmp_path / "identity.json").exists()
