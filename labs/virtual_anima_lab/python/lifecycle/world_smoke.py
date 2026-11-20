"""E1.2 live smoke for the isolated Godot LifecycleWorld scene.

Launches TWO fresh Godot processes. No Core, no FAST and no agent world effect.
Uses temporary ports/directories, local loopback only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from ..lab_client import LabClient, LabRejected, PROTOCOL_V2
from .contracts import WorldObservation
from .scenarios import load_fixture, reachable

PROJECT = Path(__file__).resolve().parents[2] / "godot"


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def _binary(name: str | None) -> str:
    binary = name or shutil.which("godot") or shutil.which("godot4")
    if not binary:
        raise FileNotFoundError("Specify --godot with a Godot 4.7.2 binary")
    return binary


def _port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def _wait(proc: subprocess.Popen, port: int) -> LabClient:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Godot exited with code {proc.returncode}")
        client = LabClient(port, role="agent", protocol=PROTOCOL_V2, timeout=1)
        try:
            client.connect()
            return client
        except (OSError, TimeoutError):
            client.close()
            time.sleep(0.08)
    raise TimeoutError("LifecycleWorld did not start listening on loopback")


def _observed(client: LabClient) -> dict:
    result = WorldObservation(client.call("observe")["data"]).as_dict()
    _require(result["visibility"] == {"kind": "line_of_sight", "radius": 3},
             "unexpected visibility policy")
    return result


def _one_run(binary: str, seed: int, log: Path) -> dict:
    port = _port()
    with log.open("w", encoding="utf-8") as output:
        proc = subprocess.Popen(
            [binary, "--headless", "--path", str(PROJECT),
             "res://LifecycleWorld.tscn", "--",
             "--lifecycle-port", str(port), "--lifecycle-seed", str(seed)],
            cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT,
        )
        client = None
        try:
            client = _wait(proc, port)
            hello = client.call("hello")["data"]
            _require(hello["capabilities"] == ["observe"] and "seed" not in hello,
                     "agent hello leaked configuration or authority")
            first = _observed(client)
            _require(first["world_instance_id"] == hello["world_instance_id"],
                     "world identity changed during observation")
            subjects = {r["subject_ref"] for r in first["readings"]}
            _require("lab.item.crate" in subjects and "lab.obstacle.shortcut" in subjects,
                     "nearby item or obstacle not visible")
            _require("lab.zone.delivery" not in subjects
                     and "lab.landmark.right" not in subjects,
                     "remote or occluded data leaked into agent reading")
            try:
                client.call("inspect")
            except LabRejected as error:
                _require(error.error == "FORBIDDEN", "incorrect agent inspect rejection")
            else:
                raise AssertionError("agent inspected designer world truth")
            try:
                client.call("act", direction="E")
            except LabRejected as error:
                _require(error.error == "FORBIDDEN", "incorrect early action rejection")
            else:
                raise AssertionError("E1.2 accidentally exposed an agent effect")
            client.role = "operator"  # Only inside test harness; not authentication.
            truth = client.call("inspect")["data"]
            _require(truth["seed"] == seed and truth["actor"] == first["self_position"],
                     "operator truth mismatch")
            moved = client.call("set_obstacle", at={"x": 4, "y": 4}, blocked=True)
            _require(moved["revision"] == 1 and moved["data"]["changed"] is True,
                     "operator obstacle revision mismatch")
            client.role = "agent"
            second = _observed(client)
            _require("lab.obstacle.4.4" in {r["subject_ref"] for r in second["readings"]},
                     "external change did not enter sensor")
            client.role = "operator"
            reset = client.call("reset")
            _require(reset["epoch"] == 2 and reset["revision"] == 0,
                     "reset world epoch/revision")
            restored = client.call("inspect")["data"]
            for field in ("actor", "item", "delivery", "landmark", "shortcut_blocker",
                          "walls", "obstacles"):
                _require(truth[field] == restored[field],
                         f"seeded reset changed {field}")
            client.role = "agent"
            after = _observed(client)
            _require(first["readings"] == after["readings"]
                     and first["self_position"] == after["self_position"],
                     "seeded reset changed the agent's local view")
            _require(first["sample_id"] != after["sample_id"]
                     and first["world_instance_id"] == after["world_instance_id"],
                     "reset reused sample identity or replaced world process")
            return {
                "seed": seed, "world_version": hello["world_version"],
                "first_readings": first["readings"],
                "after_reset_readings": after["readings"],
                "operator_geometry": {
                    field: truth[field] for field in
                    ("actor", "item", "delivery", "landmark",
                     "shortcut_blocker", "walls", "obstacles")
                },
                "agent_action_capabilities": hello["capabilities"],
            }
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", help="Godot 4.7.2 executable")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        fixture = load_fixture()
        gates = fixture["partition"]["open_y"]
        _require(reachable(args.seed, gate_y=gates[0])
                 and reachable(args.seed, gate_y=gates[2]),
                 "two independent routes are not reachable")
        binary = _binary(args.godot)
        with tempfile.TemporaryDirectory(prefix="anima_e12_world_") as name:
            temp = Path(name)
            first = _one_run(binary, args.seed, temp / "godot-1.log")
            second = _one_run(binary, args.seed, temp / "godot-2.log")
            _require(first == second, "seeded world differs between fresh Godot processes")
        print(json.dumps({
            "status": "E1_2_LIVE_PASS", "seed": args.seed,
            "runs": 2, "godot_world_version": first["world_version"],
            "agent_effects_enabled": False, "core_connected": False,
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"E1_2_LIVE_FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
