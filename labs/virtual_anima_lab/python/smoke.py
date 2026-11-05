#!/usr/bin/env python3
"""P5-A headless Godot feasibility smoke; no ANIMA Core imports.

Requires a locally installed Godot 4.7.x standard binary. This does not
assert external action idempotency or authenticate role claims.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from .lab_client import LabClient, LabRejected
except ImportError:
    from lab_client import LabClient, LabRejected


LAB_ROOT = Path(__file__).resolve().parents[1]
GODOT_PROJECT = LAB_ROOT / "godot"


def _binary(explicit: str | None) -> str:
    candidate = explicit or os.environ.get("GODOT_BIN")
    if candidate:
        found = shutil.which(candidate)
        if found:
            return found
        raise FileNotFoundError(f"Godot executable not found: {candidate}")
    for name in ("godot", "godot4"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(
        "Godot was not found in PATH. Install stable Godot 4.7.x "
        "and pass --godot /absolute/path/to/Godot_binary."
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(port: int, process: subprocess.Popen, *, deadline: float) -> LabClient:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Godot exited during startup: {process.returncode}")
        client = LabClient(port, role="operator", timeout=1)
        try:
            client.connect()
            ping = client.call("ping")
            if ping["data"]["world_version"] != "p5a-grid/0.1":
                raise AssertionError("unexpected Godot world version")
            return client
        except (OSError, TimeoutError, ConnectionError):
            client.close()
            time.sleep(0.08)
    raise TimeoutError("Godot did not expose the loopback bridge within 12 seconds")


def _check(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def _run(client: LabClient, seed: int) -> tuple[list[dict], dict]:
    records: list[dict] = []

    def call(role: str, op: str, **kwargs) -> dict:
        client.role = role  # P5 local test role, NOT authentication.
        try:
            answer = client.call(op, **kwargs)
        except LabRejected as error:
            answer = error.response
        records.append({"role": role, "command": op, "arguments": kwargs, "response": answer})
        return answer

    initial = call("operator", "debug_snapshot")["data"]
    _check(initial["seed"] == seed, "seed not applied")
    _check(initial["anima"] == {"x": 9, "y": 5}, "unexpected ANIMA starting cell")
    _check(initial["human"] == {"x": 2, "y": 2}, "unexpected Human starting cell")
    first_obs = call("agent", "observe")["data"]
    _check(first_obs["self"] == initial["anima"], "agent observation has wrong origin")
    _check(
        not any(row.get("name") == "human" for row in first_obs["visible"]),
        "agent received hidden Human position",
    )
    denied = call("agent", "debug_snapshot")
    _check(denied["ok"] is False and denied["error"] == "FORBIDDEN",
           "agent accessed privileged world snapshot")
    moved_human = call("operator", "human_move", direction="E")["data"]
    _check(moved_human["moved"], "independent human movement failed")
    after_human = call("operator", "debug_snapshot")["data"]
    _check(after_human["anima"] == initial["anima"],
           "moving Human also moved ANIMA")
    _check(after_human["human"] == {"x": 3, "y": 2},
           "Human move was not applied")

    call("operator", "pause")
    paused = call("agent", "move", direction="W")
    _check(not paused["ok"] and paused["error"] == "PAUSED",
           "movement while paused was accepted")
    old_tick = call("operator", "debug_snapshot")["data"]["tick"]
    stepped = call("operator", "step")["data"]["tick"]
    _check(stepped == old_tick + 1, "operator step did not advance logical time")
    call("operator", "resume")

    for direction in ("W", "N", "W", "N"):
        step = call("agent", "move", direction=direction)
        _check(step["ok"] and step["data"]["moved"], "ANIMA path blocked unexpectedly")
    before_door = call("agent", "observe")["data"]
    _check(
        any(x.get("kind") == "door" and x.get("state") == "closed"
            for x in before_door["visible"]),
        "door not visible when within sensor radius",
    )
    blocked = call("agent", "move", direction="W")["data"]
    _check(not blocked["moved"] and blocked["reason"] == "closed_door",
           "closed door does not block ANIMA")
    call("operator", "set_door", open=True)
    after_door = call("agent", "observe")["data"]
    _check(
        any(x.get("kind") == "door" and x.get("state") == "open"
            for x in after_door["visible"]),
        "independent door intervention did not change sensor observation",
    )
    crossed = call("agent", "move", direction="W")["data"]
    _check(crossed["moved"] and crossed["position"] == {"x": 6, "y": 3},
           "agent did not cross open door")
    occupied = call("operator", "set_door", open=False)
    _check(not occupied["ok"] and occupied["error"] == "DOOR_OCCUPIED",
           "operator closed door on occupied cell")
    trace = call("operator", "trace")["data"]["events"]
    _check(any(x["actor"] == "human" and x["event"] == "move" for x in trace),
           "Human movement absent from event log")
    _check(any(x["actor"] == "anima" and x["event"] == "move" for x in trace),
           "ANIMA movement absent from event log")

    reset = call("operator", "reset")["data"]
    _check(reset["marker"] == initial["marker"], "seeded marker changed after reset")
    _check(reset["tick"] == 0 and reset["anima"] == initial["anima"],
           "reset did not restore initial world")
    result = {
        "protocol": "val.p5a.acceptance/0.1",
        "result": "PASS",
        "seed": seed,
        "world_version": initial["world_version"],
        "checks": {
            "two_actors_independent": True,
            "hidden_human_ground_truth": True,
            "agent_restricted_operations": True,
            "pause_and_logical_step": True,
            "walls_and_closed_door_collision": True,
            "operator_world_intervention": True,
            "new_observation_after_intervention": True,
            "seeded_reset": True,
            "human_and_anima_event_log": True,
        },
        "requests": len(records),
    }
    return records, result


_LABELS = {
    "two_actors_independent": "Human и ANIMA перемещаются независимо",
    "hidden_human_ground_truth": "Скрытое состояние мира не передаётся агенту",
    "agent_restricted_operations": "Запрет тестовых операторских команд для роли agent",
    "pause_and_logical_step": "Пауза и пошаговое логическое время",
    "walls_and_closed_door_collision": "Столкновения со стенами и закрытой дверью",
    "operator_world_intervention": "Внешнее изменение двери",
    "new_observation_after_intervention": "Новое наблюдение после вмешательства",
    "seeded_reset": "Повторяемый сброс по seed",
    "human_and_anima_event_log": "События обоих акторов в журнале",
}


def _render(result: dict) -> str:
    lines = [
        "Virtual ANIMA Lab / P5-A / Godot feasibility",
        "═" * 54,
        f"Результат : {result['result']}",
        f"Протокол  : {result['protocol']}",
        f"Seed      : {result['seed']}",
        f"Мир       : {result['world_version']}",
        f"Команд    : {result['requests']}",
        "",
        "ПРОВЕРКИ",
    ]
    for key, value in result["checks"].items():
        lines.append(f"  {'✓' if value else '✗'} {_LABELS.get(key, key)}")
    lines += ["", "ANIMA Core не подключён. Внешний TCP bridge не аутентифицирован."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", default=None, help="Godot 4.7.x executable")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("seed must be nonnegative")
    binary = _binary(args.godot)
    port = args.port or _free_port()
    if not 1024 <= port <= 65535:
        parser.error("port must be 1024..65535")
    report_dir = args.report_dir.resolve() if args.report_dir else None
    if report_dir is not None:
        if report_dir.exists() and (not report_dir.is_dir() or any(report_dir.iterdir())):
            parser.error("report-dir must be absent or empty, no overwrite")
        report_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="anima_val_p5a_") as work:
        godot_log = Path(work) / "godot.log"
        with godot_log.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    binary, "--headless", "--path", str(GODOT_PROJECT), "--",
                    "--lab-port", str(port), "--lab-seed", str(args.seed),
                ],
                stdout=log, stderr=subprocess.STDOUT,
                cwd=GODOT_PROJECT,
            )
            client = None
            try:
                client = _wait_ready(port, process, deadline=time.monotonic() + 12)
                records, result = _run(client, args.seed)
                print(_render(result), end="", flush=True)
                if report_dir:
                    (report_dir / "trace.jsonl").write_text(
                        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                for r in records),
                        encoding="utf-8",
                    )
                    (report_dir / "summary.json").write_text(
                        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    (report_dir / "summary.md").write_text(
                        "# Virtual ANIMA Lab — P5-A\n\n"
                        + "\n".join(
                            f"- [{'x' if value else ' '}] {key}"
                            for key, value in result["checks"].items()
                        ) + "\n\n**Result:** PASS\n",
                        encoding="utf-8",
                    )
                client.role = "operator"
                try:
                    client.call("shutdown")
                except (OSError, ConnectionError):
                    pass
                return 0
            except Exception as error:
                print(f"Virtual ANIMA Lab P5-A: FAIL — {error}", file=sys.stderr)
                if report_dir:
                    (report_dir / "failure.txt").write_text(str(error), encoding="utf-8")
                return 1
            finally:
                if client:
                    client.close()
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if report_dir:
                    (report_dir / "godot.log").write_text(
                        godot_log.read_text(encoding="utf-8", errors="replace"),
                        encoding="utf-8",
                    )


if __name__ == "__main__":
    raise SystemExit(main())
