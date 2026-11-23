"""E2.3 real Godot directed perception acceptance, with independent operator truth.

This is a sensor/action API gate, NOT a Core Stage6 or LLM acceptance gate.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

from labs.virtual_anima_lab.python.lab_client import LabClient, LabRejected, PROTOCOL_V2
from labs.virtual_anima_lab.python.lifecycle.egocentric import (
    E23ObserverPort, EgocentricAction, EgocentricView, VIEW_ACTION_SCHEMA,
)
from .e21_gateway_live_gate import finish
from .world_smoke import PROJECT, _binary, _port, _wait


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)


def denied(client: LabClient, op: str, key: str, code: str, **params):
    try:
        client.call(op, auth=key, **params)
    except LabRejected as error:
        require(error.error == code, f"{op}: expected {code}, got {error.error}")
    else:
        raise AssertionError(f"{op} unexpectedly allowed")


def cell(raw):
    return int(raw["x"]), int(raw["y"])


def oracle(truth: dict, facing: tuple[int, int]) -> dict[tuple[str, int, int], tuple[int, int]]:
    """Independent designer-truth oracle; never feed these cells to the actor."""
    actor = cell(truth["actor"])
    walls = {cell(c) for c in truth["walls"]}
    obstacles = {cell(c) for c in truth["obstacles"]}
    shortcut = cell(truth["shortcut_blocker"])
    blockers = walls | obstacles | {shortcut}
    entities = (
        [("surface", p) for p in walls] +
        [("obstacle", p) for p in obstacles | {shortcut}] +
        [("item", cell(truth["item"])),
         ("zone", cell(truth["delivery"])),
         ("landmark", cell(truth["landmark"]))]
    )

    def in_view(point):
        dx, dy = point[0] - actor[0], point[1] - actor[1]
        fwd = dx * facing[0] + dy * facing[1]
        right = dx * (-facing[1]) + dy * facing[0]
        if fwd <= 0 or abs(math.degrees(math.atan2(right, fwd))) > 45.0:
            return None
        samples = max(abs(dx), abs(dy)) * 16
        for k in range(1, samples):
            t = k / samples
            sampled = (math.floor(actor[0] + 0.5 + dx * t),
                       math.floor(actor[1] + 0.5 + dy * t))
            if sampled == point:
                break
            if sampled in blockers:
                return None
        return (round(math.degrees(math.atan2(right, fwd)) * 1000),
                round(math.hypot(dx, dy) * 1000))

    result = {}
    for category, position in entities:
        descriptor = in_view(position)
        if descriptor is not None:
            signature = (category, *descriptor)
            require(signature not in result, "duplicate oracle signature")
            result[signature] = position
    return result


def sequential(binary: str, seed: int, root: Path) -> dict:
    port = _port()
    keys = [secrets.token_urlsafe(32) for _ in range(3)]
    outfile = (root / f"e23-godot-seed-{seed}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [binary, "--headless", "--path", str(PROJECT), "res://LifecycleWorld.tscn", "--",
         "--lifecycle-port", str(port), "--lifecycle-seed", str(seed),
         "--lifecycle-guarded", "--lifecycle-effects", "--lifecycle-ledger",
         "--lifecycle-egocentric"],
        cwd=PROJECT, stdout=outfile, stderr=subprocess.STDOUT,
        env={**os.environ, "ANIMA_LIFECYCLE_OBSERVER_KEY": keys[0],
             "ANIMA_LIFECYCLE_EXECUTOR_KEY": keys[1],
             "ANIMA_LIFECYCLE_OPERATOR_KEY": keys[2]},
    )
    try:
        ready = _wait(process, port)
        ready.close()
        observer = E23ObserverPort(port=port, observer_key=keys[0])
        with LabClient(port, role="agent", protocol=PROTOCOL_V2) as client:
            hello = client.call("hello", auth=keys[0])["data"]
            require(hello["capabilities"] == ["observe_view"] and
                    "seed" not in hello and "actor" not in hello,
                    "observer hello leaked old sensor or truth")
            denied(client, "observe", keys[0], "FORBIDDEN")
            denied(client, "inspect", keys[0], "FORBIDDEN")
            denied(client, "act", keys[0], "FORBIDDEN", action={"nonsense": True})
            denied(client, "observe_view", keys[1], "FORBIDDEN")
        # Operator truth is used strictly in the independent test oracle.
        with LabClient(port, role="operator", protocol=PROTOCOL_V2) as client:
            truth = client.call("inspect", auth=keys[2])["data"]
        initial_truth = truth
        require(truth["seed"] == seed, "oracle seed mismatch")
        headings = [(0, -1), (1, 0), (0, 1), (-1, 0), (0, -1)]
        snapshots = []
        opaque_ids = {}
        view = None
        for index, heading in enumerate(headings):
            view = observer.observe().as_dict()
            require("self_position" not in view and "seed" not in view and
                    "heading" not in view and "walls" not in view, "absolute view state leaked")
            expected = oracle(truth, heading)
            actual = {
                (row["category"], row["bearing_mdeg"], row["range_milli_cells"])
                for row in view["readings"]
            }
            require(actual == set(expected),
                    f"view geometry/occlusion differs from oracle seed={seed} heading={heading}: {actual ^ expected}")
            for row in view["readings"]:
                require("cell" not in row and "x" not in row and "y" not in row and
                        "lab.wall." not in row["entity_ref"], "coordinate leak in reading")
                signature = (row["category"], row["bearing_mdeg"], row["range_milli_cells"])
                key = (row["category"], expected[signature])
                if key in opaque_ids:
                    require(opaque_ids[key] == row["entity_ref"], "opaque ID changed across turn")
                opaque_ids[key] = row["entity_ref"]
            snapshots.append({"index": index, "count": len(actual),
                              "sample_seq": view["sample_seq"], "revision": view["revision"]})
            if index == len(headings) - 1:
                break
            direction = "right"
            command = EgocentricAction({
                "schema": VIEW_ACTION_SCHEMA,
                "world_instance_id": view["world_instance_id"], "epoch": view["epoch"],
                "expected_revision": view["revision"], "observation_id": view["sample_id"],
                "operation_id": f"e23turn_{index}", "action_type": "world.turn",
                "arguments": {"direction": direction},
            }).as_dict()
            with LabClient(port, role="agent", protocol=PROTOCOL_V2) as executor:
                reply = executor.call("act", auth=keys[1], action=command)["data"]
                require(reply["status"] == "APPLIED" and reply["effect_applied"] is True,
                        "world turn rejected")
                replay = executor.call("act", auth=keys[1], action=command)["data"]
                require(replay["replayed"] is True and replay["event_id"] == reply["event_id"] and
                        replay["revision"] == reply["revision"], "world turn replay duplicated")
                wrong = dict(command)
                wrong["arguments"] = {"direction": "left"}
                denied(executor, "act", keys[1], "OPERATION_CONFLICT", action=wrong)
            require(reply["revision"] == truth["revision"] + 1, "turn did not increment revision")
            truth = {**truth, "revision": reply["revision"], "tick": reply["tick"]}
        # World.step uses actor-relative heading and a fresh sample.
        require(view is not None, "missing observation")
        step = EgocentricAction({
            "schema": VIEW_ACTION_SCHEMA, "world_instance_id": view["world_instance_id"],
            "epoch": view["epoch"], "expected_revision": view["revision"],
            "observation_id": view["sample_id"], "operation_id": "e23step_final",
            "action_type": "world.step", "arguments": {"direction": "forward"},
        }).as_dict()
        with LabClient(port, role="agent", protocol=PROTOCOL_V2) as executor:
            reply = executor.call("act", auth=keys[1], action=step)["data"]
            require(reply["status"] in ("APPLIED", "BLOCKED"), "step was not recorded")
            old = dict(step)
            old["operation_id"] = "e23step_wrong"
            denied(executor, "act", keys[1], "STALE_REVISION", action=old) if reply["effect_applied"] else None
        # A new epoch is never silently reattached to an old observer port.
        with LabClient(port, role="operator", protocol=PROTOCOL_V2) as operator:
            reset = operator.call("reset", auth=keys[2])["data"]
        require(reset["epoch"] == view["epoch"] + 1, "reset epoch did not advance")
        try:
            observer.observe()
        except Exception as error:
            require("epoch" in str(error), "unexpected reset rejection")
        else:
            raise AssertionError("old observer followed world reset")
        fresh = E23ObserverPort(port=port, observer_key=keys[0]).observe()
        require(fresh.as_dict()["epoch"] == reset["epoch"], "fresh observer failed epoch rebind")
        require(initial_truth["world_instance_id"] == fresh.as_dict()["world_instance_id"],
                "world reset changed instance ID")
        return {
            "seed": seed, "fov_degrees": 90, "views": snapshots,
            "turns_applied": 4, "turn_replays_idempotent": 4,
            "step_outcome": reply["status"], "reset_fail_closed": True,
            "hidden_cells_leaked": 0, "fast_used": False, "core_stage6_used": False,
        }
    finally:
        finish(process, outfile)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", default=None)
    parser.add_argument("--evidence-dir", default=None)
    args = parser.parse_args()
    binary = _binary(args.godot)
    root = Path(args.evidence_dir) if args.evidence_dir else Path(
        tempfile.mkdtemp(prefix="anima-e23-view-")
    )
    root.mkdir(parents=True, exist_ok=True)
    results = [sequential(binary, seed, root) for seed in (7, 8)]
    summary = {"status": "E2_3_VIEW_GATE_PASS", "results": results}
    (root / "e23-view-result.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
