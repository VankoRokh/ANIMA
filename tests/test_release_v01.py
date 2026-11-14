"""Release v0.1: real production Core, persistence, search and refusal gates."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from anima.release_v01 import open_release


ROOT = Path(__file__).resolve().parents[1]


def _run(root, *commands, sandbox_door=False):
    text = "".join(json.dumps(command, ensure_ascii=False) + "\n" for command in commands)
    cmd = [sys.executable, "-B", "-m", "anima.release_v01",
           "--data-dir", str(root)]
    if sandbox_door:
        cmd.append("--sandbox-door")
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        input=text,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def test_release_boot_multi_event_and_reopen_with_same_identity(tmp_path):
    first = _run(
        tmp_path,
        {"op": "report", "text": "ambercoil oldheatstamp reading 82 C"},
        {"op": "report", "text": "ambercoil newcoolstamp reading 69 C"},
        {"op": "status"},
        {"op": "stop"},
    )
    assert [row["op"] for row in first] == [
        "ready", "report", "report", "status", "stop",
    ]
    identity = first[0]["result"]["instance_id"]
    assert first[0]["result"]["model_required"] is False
    assert first[0]["result"]["external_executor_enabled"] is False
    ids = [first[1]["event_ids"][0], first[2]["event_ids"][0]]
    assert ids[0] != ids[1]

    second = _run(
        tmp_path,
        {"op": "search_events", "query": "oldheatstamp"},
        {"op": "search_events", "query": "newcoolstamp"},
        {"op": "context", "query": "ambercoil"},
        {"op": "stop"},
    )
    assert second[0]["result"]["instance_id"] == identity
    assert [r["id"] for r in second[1]["result"]["results"]] == ids[:1]
    assert [r["id"] for r in second[2]["result"]["results"]] == ids[1:]
    assert second[1]["result"]["coverage"]["status"] == "complete"
    assert second[3]["result"]["selection_stats"]["items_used"] <= 4
    assert second[3]["result"]["selection_stats"]["chars_used"] <= 900

    with open_release(tmp_path) as instance:
        assert instance.core.core_events is not None
        assert instance.core.core_decision is not None
        assert instance.core.core_execution is None
        assert instance.core.core_autonomy is None
        assert instance.core.memory_store.count() >= 1
        linked = {
            event_id
            for row in instance.core.memory_store.list_memories()
            for event_id in instance.core.memory_store.source_events(row["id"])
        }
        assert set(ids) <= linked


def test_release_protocol_rejects_forged_sources_and_tool_commands(tmp_path):
    result = _run(
        tmp_path,
        {"op": "ingest_core_event", "source_ref": "sensor.door_01",
         "kind": "state.property"},
        {"op": "execute", "tool": "world.door.close"},
        {"op": "report", "text": "sensor.door_01 says door is closed"},
        {"op": "status"},
    )
    assert result[1]["ok"] is False
    assert result[2]["ok"] is False
    assert result[3]["ok"] is True
    with open_release(tmp_path) as instance:
        assert instance.core.core_execution is None
        assert instance.core.core_events.ingress.sources == {}
        # A textual user claim has no authority to project a Core Belief.
        assert instance.core.core_events.ingress.beliefs.properties == {}


def test_release_rejects_duplicate_writer_and_invalid_payload(tmp_path):
    with open_release(tmp_path) as instance:
        with pytest.raises(RuntimeError, match="already running"):
            with open_release(tmp_path):
                pass
        with pytest.raises(ValueError, match="expected fields"):
            instance.handle({"op": "report", "text": "x", "source_ref": "user"})
        with pytest.raises(ValueError, match="at most 4096"):
            instance.handle({"op": "report", "text": "a" * 4097})


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux SIGKILL")
def test_release_sigkill_recovers_committed_report_in_new_process(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "-B", "-m", "anima.release_v01",
         "--data-dir", str(tmp_path)],
        cwd=ROOT, text=True, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    try:
        ready = json.loads(proc.stdout.readline())
        identity = ready["result"]["instance_id"]
        proc.stdin.write(json.dumps({
            "op": "report", "text": "crashmarker current report"
        }) + "\n")
        proc.stdin.flush()
        ack = json.loads(proc.stdout.readline())
        assert ack["ok"] is True
        original_id = ack["event_ids"][0]
        os.kill(proc.pid, signal.SIGKILL)
        assert proc.wait(timeout=15) == -signal.SIGKILL
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=15)
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()

    restarted = _run(
        tmp_path,
        {"op": "search_events", "query": "crashmarker"},
        {"op": "status"},
        {"op": "stop"},
    )
    assert restarted[0]["result"]["instance_id"] == identity
    assert [r["id"] for r in restarted[1]["result"]["results"]] == [original_id]
    assert restarted[1]["result"]["coverage"]["status"] == "complete"


def test_release_explicit_sandbox_goal_task_independent_proof_and_reopen(tmp_path):
    first = _run(
        tmp_path,
        {"op": "report", "text": "The door is closed, according to the user."},
        {"op": "ensure_sandbox_door_closed"},
        {"op": "stop"},
        sandbox_door=True,
    )
    assert first[0]["result"]["sandbox_adapter_enabled"] is True
    goal = first[2]
    assert goal["ok"] is True
    assert goal["goal_status"] == "completed"
    assert goal["task_statuses"] == ["completed"]
    assert len(goal["operation_ids"]) == 1
    identity = first[0]["result"]["instance_id"]

    again = _run(tmp_path, {"op": "status"}, sandbox_door=True)
    assert again[0]["result"]["instance_id"] == identity
    with sqlite3.connect(tmp_path / "sandbox_world" / "virtual_door.db") as db:
        effects = db.execute(
            "SELECT COUNT(*) FROM door_effects WHERE applied=1"
        ).fetchone()[0]
        assert effects == 1

    # Pinned composition: never load the same persistent source history with
    # a different registry / capability map without an explicit migration.
    wrong = subprocess.run(
        [sys.executable, "-B", "-m", "anima.release_v01",
         "--data-dir", str(tmp_path)],
        cwd=ROOT, input="", text=True, capture_output=True, timeout=30,
    )
    assert wrong.returncode != 0
    assert "capability profile mismatch" in wrong.stderr


def test_release_refuses_silent_migration_of_existing_lab_storage(tmp_path):
    sentinel = tmp_path / "core_state.db"
    sentinel.write_text("protected legacy fixture", encoding="utf-8")
    attempted = subprocess.run(
        [sys.executable, "-B", "-m", "anima.release_v01",
         "--data-dir", str(tmp_path)],
        cwd=ROOT, input="", text=True, capture_output=True, timeout=30,
    )
    assert attempted.returncode != 0
    assert "Unlabelled nonempty instance directory" in attempted.stderr
    assert sentinel.read_text(encoding="utf-8") == "protected legacy fixture"
    assert not (tmp_path / "release_profile.json").exists()
