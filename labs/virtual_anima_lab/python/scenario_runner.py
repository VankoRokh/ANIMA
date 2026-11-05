#!/usr/bin/env python3
"""P5-C deterministic command-script replay over isolated Godot v0.2.

Only scripted HEADLESS command order is replayed. Real GUI keyboard timings,
crash durability, source authorization and ANIMA cognition are not tested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from .contracts import validate_observation, validate_receipt
    from .lab_client import LabClient, LabRejected, PROTOCOL_V2
    from .smoke import GODOT_PROJECT, _binary, _free_port
except ImportError:
    from contracts import validate_observation, validate_receipt
    from lab_client import LabClient, LabRejected, PROTOCOL_V2
    from smoke import GODOT_PROJECT, _binary, _free_port


SUITE = Path(__file__).resolve().parents[1] / "scenarios" / "p5c_suite.json"
_ALLOWED = {
    "agent": {"observe", "act"},
    "operator": {"set_door", "set_obstacle", "emit_noise", "human_move", "reset"},
}
_EXPECT_FIELDS = {
    "ok", "error", "status", "reason", "present", "absent", "states",
    "revision_delta", "event_seq_delta",
}
_WORLDS = {"base", "detour", "clutter"}
_DIRECTION = {"N", "S", "E", "W"}


class ScenarioError(ValueError):
    """An invalid fixture or failed scenario assertion (never Core evidence)."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioError(message)


def _natural(value: Any, *, maximum: int = 2_147_483_647) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _valid_step(step: Any, context: str) -> None:
    _check(type(step) is dict and set(step) == {"role", "op", "args", "expect"},
           f"{context}: expected step fields")
    role, op, args, expect = (step[key] for key in ("role", "op", "args", "expect"))
    _check(type(role) is str and role in _ALLOWED
           and type(op) is str and op in _ALLOWED[role],
           f"{context}: operation not admitted for role")
    _check(type(args) is dict, f"{context}: arguments must be an object")
    _check(type(expect) is dict and bool(expect)
           and set(expect) <= _EXPECT_FIELDS
           and type(expect.get("ok")) is bool,
           f"{context}: invalid explicit expectation")
    if op == "observe" or op == "reset":
        _check(not args, f"{context}: read/reset accepts no arguments")
    elif op == "act" or op == "human_move":
        _check(set(args) == {"direction"} and type(args["direction"]) is str
               and args["direction"] in _DIRECTION,
               f"{context}: invalid direction or extra fields")
    elif op == "set_door":
        _check(set(args) == {"open"} and type(args["open"]) is bool,
               f"{context}: invalid door fixture")
    elif op == "set_obstacle":
        point = args.get("at")
        _check(set(args) == {"at", "blocked"}
               and type(args["blocked"]) is bool and type(point) is dict
               and set(point) == {"x", "y"}
               and _natural(point["x"], maximum=11)
               and _natural(point["y"], maximum=7),
               f"{context}: invalid obstacle fixture")
    elif op == "emit_noise":
        label = args.get("label")
        _check(set(args) == {"label"} and type(label) is str
               and bool(re.fullmatch(r"[a-zA-Z0-9._:-]{1,32}", label)),
               f"{context}: invalid noise fixture")
    for key in ("revision_delta", "event_seq_delta"):
        if key in expect:
            _check(_natural(expect[key], maximum=64),
                   f"{context}: invalid nonnegative {key}")
    for key in ("present", "absent"):
        if key in expect:
            values = expect[key]
            _check(op == "observe" and type(values) is list
                   and len(values) <= 64
                   and all(type(x) is str and x.startswith("lab.") for x in values),
                   f"{context}: invalid {key} expectation")
    if "states" in expect:
        states = expect["states"]
        _check(op == "observe" and type(states) is dict
               and all(type(k) is str and k.startswith("lab.")
                       and v in ("open", "closed") for k, v in states.items()),
               f"{context}: invalid states expectation")
    if "error" in expect:
        _check(expect["ok"] is False and type(expect["error"]) is str,
               f"{context}: error expected only on rejected operations")
    for key in ("status", "reason"):
        if key in expect:
            _check(op == "act" and expect["ok"] is True
                   and type(expect[key]) is str,
                   f"{context}: {key} only available on admitted action")


def validate_suite(value: Any) -> dict[str, Any]:
    _check(type(value) is dict and set(value) == {
        "schema", "description", "scenarios",
    } and value["schema"] == "val.scenario_suite/0.1"
           and type(value["description"]) is str,
           "scenario suite schema mismatch")
    scenarios = value["scenarios"]
    _check(type(scenarios) is list and 1 <= len(scenarios) <= 8,
           "scenario count must be 1..8")
    ids: set[str] = set()
    for entry in scenarios:
        _check(type(entry) is dict and set(entry) == {
            "id", "seed", "world", "steps",
        }, "scenario record fields")
        scenario_id = entry["id"]
        _check(type(scenario_id) is str
               and bool(re.fullmatch(r"[a-z][a-z0-9_]{1,35}", scenario_id))
               and scenario_id not in ids,
               "duplicate or invalid scenario ID")
        ids.add(scenario_id)
        _check(_natural(entry["seed"]) and type(entry["world"]) is str
               and entry["world"] in _WORLDS,
               f"{scenario_id}: seed/world config")
        steps = entry["steps"]
        _check(type(steps) is list and 3 <= len(steps) <= 64,
               f"{scenario_id}: bounded step count")
        observed = False
        for n, step in enumerate(steps, 1):
            _valid_step(step, f"{scenario_id} step {n}")
            if step["role"] == "agent" and step["op"] == "observe":
                observed = True
            if step["op"] == "reset":
                observed = False
            if step["op"] == "act":
                _check(observed, f"{scenario_id} step {n}: act without fresh observation")
    return value


def load_suite(path: Path = SUITE) -> dict[str, Any]:
    return validate_suite(json.loads(path.read_text(encoding="utf-8")))


def _connect(proc: subprocess.Popen, port: int, expected_world: str) -> tuple[LabClient, dict]:
    end = time.monotonic() + 14
    while time.monotonic() < end:
        if proc.poll() is not None:
            raise ScenarioError(f"Godot exited unexpectedly: {proc.returncode}")
        client = LabClient(port, role="operator", protocol=PROTOCOL_V2, timeout=1)
        try:
            client.connect()
            hello = client.call("hello")
            _check(hello["data"].get("scenario") == expected_world,
                   f"wrong engine scenario: {hello['data']!r}")
            return client, hello
        except (OSError, TimeoutError):
            client.close()
            time.sleep(0.08)
        except Exception:
            client.close()
            raise
    raise ScenarioError("Godot did not open P5-C loopback port")


def _assert_step(step: dict, response: dict, previous: dict, *, name: str) -> None:
    expected = step["expect"]
    _check(response["ok"] is expected["ok"], f"{name}: expected ok={expected['ok']}")
    for key in ("revision_delta", "event_seq_delta"):
        if key in expected:
            field = "revision" if key == "revision_delta" else "event_seq"
            _check(response[field] - previous[field] == expected[key],
                   f"{name}: unexpected {field} change")
    if not response["ok"]:
        if "error" in expected:
            _check(response["error"] == expected["error"],
                   f"{name}: error {response['error']!r}, expected {expected['error']!r}")
        return
    data = response["data"]
    for key in ("status", "reason"):
        if key in expected:
            _check(data.get(key) == expected[key],
                   f"{name}: {key}={data.get(key)!r}, expected {expected[key]!r}")
    if step["op"] != "observe":
        return
    subjects = {r["subject_ref"]: r for r in data["readings"]}
    for subject in expected.get("present", []):
        _check(subject in subjects, f"{name}: missing sensed {subject}")
    for subject in expected.get("absent", []):
        _check(subject not in subjects, f"{name}: unexpected sensed {subject}")
    for subject, state in expected.get("states", {}).items():
        _check(subject in subjects
               and subjects[subject]["typed_value"] == {
                   "type": "symbol", "value": state,
               }, f"{name}: wrong sensed state of {subject}")


def _exercise(client: LabClient, hello: dict, scenario: dict) -> list[dict]:
    trace: list[dict] = [{
        "step": 0, "role": "operator", "op": "hello",
        "request": {}, "response": hello,
    }]
    previous = hello
    sample = None
    for index, step in enumerate(scenario["steps"], 1):
        role, op = step["role"], step["op"]
        args = dict(step["args"])
        client.role = role
        if op == "act":
            _check(sample is not None, f"{scenario['id']} step {index}: no observation")
            operation_id = f"p5c:{scenario['id']}:{index:03d}"
            args = {
                "operation_id": operation_id,
                "action": {"schema": "val.action/0.1", "direction": args["direction"]},
                "expected_epoch": sample["observed_at"]["epoch"],
                "expected_revision": sample["world_revision"],
            }
        else:
            operation_id = None
        try:
            answer = client.call(op, **args)
        except LabRejected as exc:
            answer = exc.response
        if answer["ok"] and role == "agent" and op == "observe":
            validate_observation(answer["data"], answer)
            sample = answer["data"]
        if answer["ok"] and role == "agent" and op == "act":
            validate_receipt(answer["data"], action_id=operation_id)
        if op == "reset" and answer["ok"]:
            sample = None
        _assert_step(step, answer, previous,
                     name=f"{scenario['id']} step {index} ({role}.{op})")
        trace.append({
            "step": index, "role": role, "op": op,
            "request": args, "response": answer,
        })
        previous = answer
    client.role = "operator"
    snapshot = client.call("inspect")
    _check(snapshot["ok"] and snapshot["data"]["scenario"] == scenario["world"],
           "operator-only final snapshot missing/wrong")
    trace.append({
        "step": len(scenario["steps"]) + 1, "role": "operator",
        "op": "inspect", "request": {}, "response": snapshot,
    })
    return trace


def _one_run(binary: str, scenario: dict, *, log_path: Path) -> list[dict]:
    port = _free_port()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([
            binary, "--headless", "--path", str(GODOT_PROJECT), "--",
            "--lab-port", str(port), "--lab-seed", str(scenario["seed"]),
            "--lab-scenario", scenario["world"],
        ], cwd=GODOT_PROJECT, stdout=log, stderr=subprocess.STDOUT)
        client = None
        try:
            client, hello = _connect(proc, port, scenario["world"])
            return _exercise(client, hello, scenario)
        finally:
            if client:
                client.close()
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def _canonical(trace: list[dict]) -> bytes:
    return (json.dumps(
        trace, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ) + "\n").encode("utf-8")


def _git_sha() -> str:
    try:
        return subprocess.check_output([
            "git", "-C", str(GODOT_PROJECT.parents[2]), "rev-parse", "HEAD",
        ], text=True, timeout=5).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unavailable"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", default=None)
    parser.add_argument("--suite", type=Path, default=SUITE)
    parser.add_argument("--scenario", default=None, help="run one exact scenario ID")
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        suite = load_suite(args.suite)
        cases = suite["scenarios"]
        if args.scenario is not None:
            cases = [c for c in cases if c["id"] == args.scenario]
            _check(bool(cases), f"unknown scenario: {args.scenario}")
        binary = _binary(args.godot)
        output = args.report_dir.resolve() if args.report_dir else None
        if output is not None:
            _check(not output.exists() or (
                output.is_dir() and not any(output.iterdir())
            ), "report-dir must be absent or empty")
            output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="anima_val_p5c_") as temp:
            logs = output / "logs" if output else Path(temp) / "logs"
            logs.mkdir(parents=True)
            summary = {
                "schema": "val.p5c.acceptance/0.1",
                "result": "PASS",
                "suite": str(args.suite.name),
                "git_sha": _git_sha(),
                "run_count": 2,
                "world_versions": "p5a-grid/0.1",
                "scenarios": [],
                "core_connected": False,
            }
            representative: list[dict] = []
            for scenario in cases:
                first = _one_run(
                    binary, scenario,
                    log_path=logs / f"{scenario['id']}-1.log",
                )
                second = _one_run(
                    binary, scenario,
                    log_path=logs / f"{scenario['id']}-2.log",
                )
                a, b = _canonical(first), _canonical(second)
                _check(a == b, f"{scenario['id']}: trace diverged between runs")
                digest = hashlib.sha256(a).hexdigest()
                summary["scenarios"].append({
                    "id": scenario["id"], "world": scenario["world"],
                    "seed": scenario["seed"], "steps": len(scenario["steps"]),
                    "digest_sha256": digest,
                    "replays_equal": True,
                })
                representative.extend([
                    {"scenario": scenario["id"], **row} for row in first
                ])
                print(f"  PASS {scenario['id']}: {len(scenario['steps'])} steps, replay SHA256 {digest[:16]}", flush=True)
            print(f"Virtual ANIMA Lab / P5-C: PASS {len(cases)}/{len(cases)} scenarios, 2 runs each")
            print("Scripted headless command replay only. ANIMA Core NOT connected.")
            if output:
                (output / "summary.json").write_text(
                    json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                (output / "summary.md").write_text(
                    "# Virtual ANIMA Lab — P5-C\n\n**Result:** PASS\n\n"
                    + "\n".join(
                        f"- [x] {row['id']}: {row['steps']} steps, "
                        f"seed={row['seed']}, world={row['world']}"
                        for row in summary["scenarios"]
                    ) + "\n\nExact ordered JSON replies matched across two fresh Godot runs.\n",
                    encoding="utf-8",
                )
                (output / "trace.jsonl").write_text(
                    "".join(json.dumps(row, ensure_ascii=False, sort_keys=True)
                            + "\n" for row in representative),
                    encoding="utf-8",
                )
            return 0
    except Exception as exc:
        print(f"Virtual ANIMA Lab / P5-C: FAIL — {exc}", file=sys.stderr)
        if args.report_dir is not None:
            directory = args.report_dir.resolve()
            if directory.is_dir():
                (directory / "failure.txt").write_text(str(exc) + "\n",
                                                      encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
