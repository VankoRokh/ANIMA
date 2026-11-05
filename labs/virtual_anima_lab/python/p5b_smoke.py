#!/usr/bin/env python3
"""P5-B isolated Godot↔Python v0.2 contract smoke, without ANIMA Core."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from .contracts import (
        validate_observation, validate_receipt, validate_events_page,
    )
    from .lab_client import LabClient, LabProtocolError, LabRejected, PROTOCOL_V2
    from .smoke import _binary, _free_port, GODOT_PROJECT
except ImportError:
    from contracts import (
        validate_observation, validate_receipt, validate_events_page,
    )
    from lab_client import LabClient, LabProtocolError, LabRejected, PROTOCOL_V2
    from smoke import _binary, _free_port, GODOT_PROJECT


def _check(assertion: bool, reason: str) -> None:
    if not assertion:
        raise AssertionError(reason)


def _await_bridge(process, port: int, *, seconds: int = 14) -> LabClient:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Godot exited before bridge ready (exit={process.returncode})")
        client = LabClient(port, role="agent", protocol=PROTOCOL_V2, timeout=1.0)
        try:
            client.connect()
            hello = client.call("hello")
            _check(hello["data"]["action_schema"] == "val.action/0.1", "wrong action schema")
            return client
        except (OSError, TimeoutError, ConnectionError):
            client.close()
            time.sleep(0.07)
        except Exception:
            client.close()
            raise
    raise TimeoutError("P5-B bridge did not start")


def _exercise(client: LabClient) -> tuple[dict, list[dict]]:
    trace: list[dict] = []
    counts: dict[str, bool] = {}

    def call(role: str, operation: str, **kwargs) -> dict:
        client.role = role  # Local test-harness role, NOT authentication.
        try:
            response = client.call(operation, **kwargs)
        except LabRejected as exc:
            response = exc.response
        trace.append({
            "role": role, "op": operation, "request": kwargs, "response": response,
        })
        return response

    def step(key: str, direction: str, epoch: int, revision: int) -> dict:
        response = call(
            "agent", "act", operation_id=key,
            action={"schema": "val.action/0.1", "direction": direction},
            expected_epoch=epoch, expected_revision=revision,
        )
        if response["ok"]:
            validate_receipt(response["data"], action_id=key)
        return response

    agent_hello = call("agent", "hello")
    operator_hello = call("operator", "hello")
    _check(agent_hello["data"]["source_ref"] == "lab.sensor.anima.proximity",
           "source not declared")
    _check("act" in agent_hello["data"]["capabilities"], "missing typed action")
    _check("inspect" not in agent_hello["data"]["capabilities"],
           "debug authority listed for agent")
    _check("inspect" in operator_hello["data"]["capabilities"],
           "operator debug unavailable")
    initial = call("operator", "inspect")["data"]
    epoch = initial["epoch"]
    revision = initial["revision"]
    _check(epoch >= 1 and revision == 0, "unexpected initial world epoch/revision")
    first = call("agent", "observe")
    validate_observation(first["data"], first)
    _check(first["data"]["readings"] != [],
           "proximity sensor produced no readings")
    forbidden = call("agent", "inspect")
    _check(not forbidden["ok"] and forbidden["error"] == "FORBIDDEN",
           "agent may read debug world truth")
    denied_events = call("agent", "events")
    _check(not denied_events["ok"] and denied_events["error"] == "FORBIDDEN",
           "agent may read operator event trace")
    counts["versioned_observation_provenance"] = True
    counts["operator_debug_separation"] = True

    first_step = step("p5b:001", "W", epoch, revision)
    _check(first_step["ok"] and first_step["data"]["effect_applied"],
           "first conditional move failed")
    revision = first_step["revision"]
    replay = step("p5b:001", "W", epoch, 0)
    _check(replay["ok"] and replay["data"]["replayed"], "duplicate not identified")
    _check(replay["event_seq"] == first_step["event_seq"],
           "duplicate action created another event")
    _check(replay["data"]["event_id"] == first_step["data"]["event_id"],
           "duplicate action does not return original receipt")
    conflict = step("p5b:001", "E", epoch, 0)
    _check(not conflict["ok"] and conflict["error"] == "OPERATION_ID_CONFLICT",
           "same operation id with different payload was accepted")
    stale = step("p5b:stale", "E", epoch, 0)
    _check(not stale["ok"] and stale["error"] == "STALE_WORLD",
           "old revision precondition was accepted")
    counts["keyed_replay_without_duplicate_effect"] = True
    counts["collision_and_stale_preconditions"] = True

    human = call("operator", "human_move", direction="E")
    _check(human["ok"], "operator Human move failed")
    _check(human["revision"] == revision + 1,
           "independent Human intervention did not advance revision")
    revision = human["revision"]
    for index, direction in enumerate(("N", "W", "N"), start=2):
        result = step(f"p5b:{index:03}", direction, epoch, revision)
        _check(result["ok"] and result["data"]["effect_applied"],
               f"agent route step {index} failed")
        revision = result["revision"]
    door_closed = call("agent", "observe")
    validate_observation(door_closed["data"], door_closed)
    _check(
        any(
            r["subject_ref"] == "lab.door.01"
            and r["typed_value"] == {"type": "symbol", "value": "closed"}
            for r in door_closed["data"]["readings"]
        ),
        "closed door was not seen by typed observation",
    )
    blocked = step("p5b:blocked", "W", epoch, revision)
    _check(blocked["ok"] and blocked["data"]["status"] == "BLOCKED",
           "closed-door attempt was not blocked")
    _check(blocked["revision"] == revision and not blocked["data"]["effect_applied"],
           "blocked action changed world revision")
    blocked_replay = step("p5b:blocked", "W", epoch, revision)
    _check(blocked_replay["ok"] and blocked_replay["data"]["replayed"]
           and blocked_replay["event_seq"] == blocked["event_seq"],
           "replayed blocked move changed event log")
    counts["blocked_action_receipt_not_success"] = True

    intervention = call("operator", "set_door", open=True)
    _check(intervention["ok"] and intervention["revision"] > revision,
           "operator intervention did not change world")
    wrong = step("p5b:late", "W", epoch, revision)
    _check(not wrong["ok"] and wrong["error"] == "STALE_WORLD",
           "stale belief allowed action despite external intervention")
    fresh = call("agent", "observe")
    validate_observation(fresh["data"], fresh)
    _check(any(
        x["subject_ref"] == "lab.door.01"
        and x["typed_value"] == {"type": "symbol", "value": "open"}
        for x in fresh["data"]["readings"]
    ), "new door state not visible")
    crossing = step("p5b:cross", "W", epoch, intervention["revision"])
    _check(crossing["ok"] and crossing["data"]["position"] == {"x": 6, "y": 3},
           "agent did not cross changed door")
    illegal_close = call("operator", "set_door", open=False)
    _check(not illegal_close["ok"] and illegal_close["error"] == "DOOR_OCCUPIED",
           "operator closed occupied door")
    counts["external_intervention_invalidates_revision"] = True
    counts["readback_is_not_execution_receipt"] = True

    cursor = 0
    all_events = []
    for _ in range(32):
        page = call("operator", "events", after_seq=cursor, limit=8)
        _check(page["ok"], f"operator event page failed: {page}")
        validate_events_page(page["data"], after_seq=cursor)
        all_events.extend(page["data"]["events"])
        cursor = page["data"]["next_cursor"]
        if not page["data"]["has_more"]:
            break
    else:
        raise AssertionError("event pagination loop exceeded bound")
    _check(cursor == crossing["event_seq"] + 0 or cursor == illegal_close["event_seq"],
           "event cursor did not reach current world event sequence")
    _check(len({event["event_id"] for event in all_events}) == len(all_events),
           "duplicate event IDs in paged history")
    move_events = [
        e for e in all_events if e["actor"] == "anima" and e["event"] == "move"
    ]
    _check(len(move_events) == 6, "event log duplicated a keyed movement")
    counts["monotonic_paginated_event_log"] = True

    prior_epoch = crossing["epoch"]
    latest_seq = cursor
    reset = call("operator", "reset")
    _check(reset["ok"] and reset["epoch"] == prior_epoch + 1
           and reset["revision"] == 0, "reset did not advance epoch")
    new_sensor = call("agent", "observe")
    validate_observation(new_sensor["data"], new_sensor)
    _check(new_sensor["data"]["observation_id"] != first["data"]["observation_id"],
           "sample identity reused across world reset")
    old_epoch = step("p5b:001", "W", prior_epoch, 0)
    _check(not old_epoch["ok"] and old_epoch["error"] == "STALE_WORLD",
           "old-world operation replayed after reset")
    after_reset = call("operator", "events", after_seq=latest_seq, limit=8)
    _check(after_reset["ok"], "world reset event cannot be read by cursor")
    validate_events_page(after_reset["data"], after_seq=latest_seq)
    _check(after_reset["data"]["events"][0]["event"] == "reset",
           "reset event provenance missing")
    counts["epoch_prevents_old_world_actions"] = True

    counts["p5a_compatibility_profile_retained"] = False  # set after legacy ping
    client.protocol = "val.bridge/0.1"
    legacy = call("agent", "ping")
    _check(legacy["ok"] and legacy["data"]["world_version"] == "p5a-grid/0.1",
           "original P5-A profile was broken")
    counts["p5a_compatibility_profile_retained"] = True
    client.protocol = PROTOCOL_V2

    result = {
        "protocol": "val.p5b.acceptance/0.1",
        "result": "PASS",
        "checks": counts,
        "requests": len(trace),
        "world_epoch": reset["epoch"],
        "last_event_seq": after_reset["event_seq"],
        "core_connected": False,
    }
    return result, trace


def _run(args) -> int:
    binary = _binary(args.godot)
    port = args.port or _free_port()
    if not 1024 <= port <= 65535:
        raise ValueError("port must be 1024..65535")
    output = args.report_dir.resolve() if args.report_dir else None
    if output is not None:
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("report-dir must be absent or empty")
        output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anima_val_p5b_") as temp:
        logfile = Path(temp) / "godot.log"
        with logfile.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [
                    binary, "--headless", "--path", str(GODOT_PROJECT), "--",
                    "--lab-port", str(port), "--lab-seed", str(args.seed),
                ],
                cwd=GODOT_PROJECT, stdout=log, stderr=subprocess.STDOUT,
            )
            client = None
            try:
                client = _await_bridge(proc, port)
                result, trace = _exercise(client)
                print("Virtual ANIMA Lab / P5-B / typed bridge")
                print(f"  {result['result']}  {len(result['checks'])}/{len(result['checks'])} checks")
                print(f"  Protocol: {result['protocol']}  Requests: {result['requests']}")
                for key in result["checks"]:
                    print(f"  ✓ {key}")
                print("  ANIMA Core not connected; role is not authenticated.")
                if output:
                    (output / "summary.json").write_text(
                        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    (output / "summary.md").write_text(
                        "# Virtual ANIMA Lab P5-B\n\n**Result: PASS**\n\n"
                        + "\n".join(f"- [x] {key}" for key in result["checks"]) + "\n",
                        encoding="utf-8",
                    )
                    (output / "trace.jsonl").write_text(
                        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                                for item in trace),
                        encoding="utf-8",
                    )
                client.role = "operator"
                client.call("reset")
                return 0
            except Exception as exc:
                print(f"Virtual ANIMA Lab P5-B: FAIL — {exc}", file=sys.stderr)
                if output:
                    (output / "failure.txt").write_text(str(exc), encoding="utf-8")
                return 1
            finally:
                if client is not None:
                    client.close()
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                if output:
                    (output / "godot.log").write_text(
                        logfile.read_text(encoding="utf-8", errors="replace"),
                        encoding="utf-8",
                    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", default=None, help="Godot 4.7.x binary path")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("seed must be nonnegative")
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
