#!/usr/bin/env python3
"""ANIMA P6 integration fault gate: real Godot + Core process hard crashes.

Tests two deliberately targeted cut points in the *Core* process:
  before: Core execution is durable and marked executing, but no effect ran.
  after:  VAL applied one effect, then Core process dies before receiving receipt.

Cold recovery must never issue a second act_door and must only complete Goal
when independent sensor evidence confirms the effect.

Run from ANIMA repo root using its .venv Python:
  .venv/bin/python -m labs.virtual_anima_lab.python.p6_core_crash_recovery_gate

Only the Godot child processes started by THIS script are killed.
All Core data lives in temporary test directories, never in ANIMA_DATA_DIR.
This does not simulate physical power removal or prove transport authentication.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path.cwd().resolve()
if not (ROOT / "anima/core/assembly.py").is_file():
    raise SystemExit("Run from the ANIMA repository root")

sys.path.insert(0, str(ROOT))
from anima.core.door_world import DOOR_SUBJECT, DOOR_PREDICATE  # noqa: E402
from anima.core.goal_decision import GoalCriterion  # noqa: E402
from labs.virtual_anima_lab.python.run_core_demo import make_core  # noqa: E402
from labs.virtual_anima_lab.python.lab_client import LabClient, LabProtocolError, PROTOCOL_V2  # noqa: E402

EXPECTED = {"type": "symbol", "value": "closed"}


def call(port: int, role: str, op: str, **args) -> dict:
    with LabClient(port, role=role, protocol=PROTOCOL_V2, timeout=2) as client:
        return client.call(op, **args)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def stop_child(child: subprocess.Popen | None) -> None:
    if child is not None and child.poll() is None:
        child.kill()
    if child is not None:
        child.wait(timeout=6)


def start_godot(godot: Path, port: int, log) -> subprocess.Popen:
    child = subprocess.Popen(
        [str(godot), "--headless", "--path",
         str(ROOT / "labs/virtual_anima_lab/godot"), "--",
         "--lab-port", str(port), "--lab-seed", "7",
         "--lab-scenario", "p6_door", "--lab-ui", "debug"],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        until = time.monotonic() + 12
        while time.monotonic() < until:
            if child.poll() is not None:
                raise AssertionError(f"Godot exited during start (rc={child.returncode})")
            try:
                hello = call(port, "agent", "hello")["data"]
                if hello.get("scenario") == "p6_door":
                    return child
            except (OSError, TimeoutError, LabProtocolError):
                time.sleep(0.15)
        raise AssertionError("No P6 Godot bridge after 12 seconds")
    except BaseException:
        stop_child(child)
        raise


def effect_events(port: int) -> list[dict]:
    """External harness may read operator trace; Core never does."""
    cursor = 0
    effects = []
    for _ in range(100):
        result = call(port, "operator", "events", after_seq=cursor, limit=8)["data"]
        for event in result["events"]:
            if event["actor"] == "anima" and event["event"] == "close_door":
                effects.append(event)
        next_cursor = result["next_cursor"]
        if not result["has_more"]:
            return effects
        if next_cursor <= cursor:
            raise AssertionError("VAL event cursor did not advance")
        cursor = next_cursor
    raise AssertionError("VAL event listing exceeded bounded test size")


def operations(data_dir: Path, goal_id: str) -> list[dict]:
    path = data_dir / "core" / "execution.db"
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT public_id, status FROM execution_operations WHERE goal_id=?",
            (goal_id,),
        ).fetchall()
    return [{"operation_id": x[0], "status": x[1]} for x in rows]


def crash_child(mode: str, data_dir: Path, port: int) -> None:
    """Kill the entire Core process at a controlled pre-receipt cut point.

    The override never returns, so Core has committed 'executing' but the
    Executor cannot receive a receipt or change Operation status.
    """
    core = make_core(data_dir, port=port)
    core.runtime.wake()
    goal = core.internal_state.goals.create_goal(
        source="test.operator.p6", priority=5,
        description="Crash/recover: close door once",
        success_criterion="Independent observed door state is closed",
        reason="P6 Core real-process integration failure gate",
    )
    goal_id = goal["id"]
    (data_dir / "goal_id.txt").write_text(goal_id, encoding="utf-8")
    criterion = GoalCriterion(
        goal_id=goal_id, subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE, expected=dict(EXPECTED),
    )

    def cut_point(action, descriptor, handler):
        # This is the point where ExecutionOperation has already become
        # executing. Crash before running effect, OR after it but before
        # returning any receipt to Executor.
        if mode == "after":
            output = handler.execute(
                str(core.core_execution.world.root),
                action.to_dict()["arguments"], action.operation_id,
            )
            assert output == {"operation_id": action.operation_id, "applied": True}
        (data_dir / "crash_marker.txt").write_text(
            f"{mode}:{action.operation_id}", encoding="utf-8",
        )
        os._exit(73 if mode == "after" else 74)

    core.core_execution.executor._run_worker = cut_point
    core.runtime.bind_core_goal(criterion)
    raise AssertionError("Fault injection was not reached")


def recover_child(mode: str, data_dir: Path, port: int) -> None:
    goal_id = (data_dir / "goal_id.txt").read_text(encoding="utf-8").strip()
    core = make_core(data_dir, port=port)
    core.runtime.wake()
    # Run a bounded second drain to detect accidental retries/duplicate effects.
    core.runtime.run_core_autonomous(max_steps=4)
    core.runtime.run_core_autonomous(max_steps=4)
    goal = core.internal_state.goals.get_goal(goal_id)
    ops = core.core_execution.store.list_operations(goal_id=goal_id)
    proof = core.core_execution._proof(goal_id)
    record = {
        "goal_id": goal_id, "goal_status": goal["status"],
        "operations": [{"operation_id": op["id"], "status": op["status"]} for op in ops],
        "proof": proof is not None, "attempts": list(core.core_autonomy.attempts()),
    }
    (data_dir / "recovery.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    if mode == "after":
        assert goal["status"] == "completed", record
        assert len(ops) == 1 and ops[0]["status"] == "succeeded", record
        assert proof is not None, record
    else:
        assert goal["status"] == "active", record
        assert len(ops) == 1 and ops[0]["status"] == "uncertain", record
        assert proof is None, record
    core.runtime.sleep()


def invoke_worker(phase: str, mode: str, data_dir: Path, port: int, timeout=30):
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
        "--phase", phase, "--mode", mode,
        "--data-dir", str(data_dir), "--port", str(port),
    ]
    return subprocess.run(
        cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=timeout, check=False,
    )


def run_case(mode: str, godot: Path, scratch: Path) -> dict:
    port = free_port()
    data = scratch / f"core_{mode}"
    data.mkdir()
    lab = None
    log_path = scratch / f"godot_{mode}.log"
    with log_path.open("wb") as log:
        try:
            lab = start_godot(godot, port, log)
            before = call(port, "agent", "hello")
            crash = invoke_worker("crash", mode, data, port)
            wanted = 73 if mode == "after" else 74
            assert crash.returncode == wanted, (
                f"Core did not die at intended cut: rc={crash.returncode}, output={crash.stdout}"
            )
            goal_id = (data / "goal_id.txt").read_text(encoding="utf-8").strip()
            marker = (data / "crash_marker.txt").read_text(encoding="utf-8")
            assert marker.startswith(mode + ":"), marker
            op_id = marker.split(":", 1)[1]
            pending = operations(data, goal_id)
            assert pending == [{"operation_id": op_id, "status": "executing"}], pending
            effects_before = effect_events(port)
            found_before = call(
                port, "agent", "door_operation_status", operation_id=op_id
            )["data"]["found"]
            assert len(effects_before) == (1 if mode == "after" else 0), effects_before
            assert found_before == (mode == "after")
            print(f"P6_CORE_{mode.upper()}_CUT_PASS", flush=True)

            # Cold-restart a fresh Core process against the SAME live Godot
            # process + same durable Core/port directories.
            recovery = invoke_worker("recover", mode, data, port)
            assert recovery.returncode == 0, (
                f"Recovery failed: rc={recovery.returncode}, output={recovery.stdout}"
            )
            result = json.loads((data / "recovery.json").read_text(encoding="utf-8"))
            effects_after = effect_events(port)
            assert effects_before == effects_after, (
                f"Recovery created a new action! before={effects_before}, after={effects_after}"
            )
            found_after = call(
                port, "agent", "door_operation_status", operation_id=op_id
            )["data"]["found"]
            assert found_after == found_before
            sensed = call(port, "agent", "observe")["data"]
            door_values = [
                row["typed_value"]["value"]
                for row in sensed["readings"]
                if row["subject_ref"] == "lab.door.01"
            ]
            assert door_values == ["closed" if mode == "after" else "open"], door_values
            assert call(port, "agent", "hello")["data"]["world_instance_id"] == (
                before["data"]["world_instance_id"]
            )
            print(f"P6_CORE_{mode.upper()}_COLD_RECOVERY_PASS", flush=True)
            return {
                "case": mode, "goal_id": goal_id, "operation_id": op_id,
                "effects": len(effects_after),
                "goal_status": result["goal_status"],
                "operation_status": result["operations"][0]["status"],
                "proof": result["proof"],
            }
        except BaseException:
            log.flush()
            print("GODOT LOG:\n" + log_path.read_text(
                encoding="utf-8", errors="replace")[-3000:],
                file=sys.stderr,
            )
            raise
        finally:
            stop_child(lab)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", type=Path, default=(
        Path.home() / ".local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"))
    parser.add_argument("--phase", choices=["main", "crash", "recover"], default="main")
    parser.add_argument("--mode", choices=["before", "after", "both"], default="both")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--report", type=Path,
                        help="Optional JSON report path outside the repo")
    args = parser.parse_args()

    if args.phase != "main":
        if args.mode == "both" or args.port is None or args.data_dir is None:
            parser.error("child needs --mode before|after, --port, --data-dir")
        if args.phase == "crash":
            crash_child(args.mode, args.data_dir, args.port)
        else:
            recover_child(args.mode, args.data_dir, args.port)
        return

    godot = args.godot.expanduser().resolve()
    if not godot.is_file():
        parser.error(f"Godot executable missing: {godot}")
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    print(f"P6_CORE_RECOVERY_SHA {sha}", flush=True)
    cases = ["before", "after"] if args.mode == "both" else [args.mode]
    with tempfile.TemporaryDirectory(prefix="anima-p6-core-crash-") as tmp:
        scratch = Path(tmp)
        results = [run_case(mode, godot, scratch) for mode in cases]
    if args.report:
        destination = args.report.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({
            "schema": "anima.p6.core-crash-gate/0.1",
            "commit": sha, "cases": results,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("P6_CORE_CRASH_RECOVERY_GATE_PASS", flush=True)


if __name__ == "__main__":
    main()
