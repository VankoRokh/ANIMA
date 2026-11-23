"""E1.3 live Godot smoke: actions + fresh sensor evidence, no Core/FAST.

The route is a *test harness* sequence, NEVER passed to the agent or a model.
Each run starts a disposable Godot process on loopback with opt-in effects.
No permanent ledger: E1.4 status/replay/recovery is deliberately NOT claimed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from ..lab_client import LabRejected
from .contracts import (
    ACTION_SCHEMA, WorldAction, WorldObservation, WorldReceipt,
)
from .world_smoke import PROJECT, _binary, _port, _wait
from .world_verification import verify_world_effect


def _check(ok: bool, error: str) -> None:
    if not ok:
        raise AssertionError(error)


def _one_run(binary: str, seed: int, logfile: Path) -> dict:
    port = _port()
    with logfile.open("w", encoding="utf-8") as output:
        proc = subprocess.Popen(
            [binary, "--headless", "--path", str(PROJECT),
             "res://LifecycleWorld.tscn", "--",
             "--lifecycle-port", str(port), "--lifecycle-seed", str(seed),
             "--lifecycle-effects"],
            cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT,
        )
        client = None
        try:
            client = _wait(proc, port)
            hello = client.call("hello")["data"]
            _check(hello["capabilities"] == ["observe", "act"] and "seed" not in hello,
                   "effect capability not explicitly scoped to E1.3")
            count = 0
            proofs: list[str] = []

            def observe() -> WorldObservation:
                return WorldObservation(client.call("observe")["data"])

            def do(kind: str, args: dict, expected: str = "VERIFIED_SUCCESS"):
                nonlocal count
                before = observe()
                b = before.as_dict()
                count += 1
                action = WorldAction({
                    "schema": ACTION_SCHEMA,
                    "world_instance_id": b["world_instance_id"],
                    "epoch": b["epoch"], "expected_revision": b["revision"],
                    "observation_id": b["sample_id"],
                    "operation_id": f"op.e13.{count}",
                    "action_type": kind, "arguments": args,
                })
                envelope = client.call("act", action=action.as_dict())
                receipt = WorldReceipt(envelope["data"])
                after = observe()
                proof = verify_world_effect(before, action, receipt, after)
                _check(proof.status == expected,
                       f"{kind}/{count}: {proof.status} {proof.reason}, expected {expected}")
                proofs.append(proof.status)
                return action, proof

            pick, _ = do("world.pick", {"item_ref": "lab.item.crate"})
            do("world.move", {"direction": "E"})
            do("world.move", {"direction": "E"})
            do("world.move", {"direction": "E"}, "VERIFIED_BLOCKED")

            # The same operation ID is not silently executed a second time;
            # reconciliation and replay are reserved for E1.4.
            try:
                client.call("act", action=pick.as_dict())
            except LabRejected as e:
                _check(e.error == "OPERATION_REUSED", "unsafe duplicate retry")
            else:
                raise AssertionError("duplicate operation was accepted")
            current = observe().as_dict()
            stale = {
                "schema": ACTION_SCHEMA,
                "world_instance_id": current["world_instance_id"],
                "epoch": current["epoch"],
                "expected_revision": current["revision"] - 1,
                "observation_id": current["sample_id"],
                "operation_id": "op.e13.stale",
                "action_type": "world.move", "arguments": {"direction": "E"},
            }
            WorldAction(stale)
            try:
                client.call("act", action=stale)
            except LabRejected as e:
                _check(e.error == "STALE_REVISION", "stale action was not rejected")
            else:
                raise AssertionError("stale revision action accepted")
            corrupt = dict(stale)
            corrupt["expected_revision"] = current["revision"]
            corrupt["operation_id"] = "op.e13.invalid"
            corrupt["action_type"] = "fs.delete"
            try:
                client.call("act", action=corrupt)
            except LabRejected as e:
                _check(e.error == "INVALID_ACTION", "unsupported action escaped allowlist")
            else:
                raise AssertionError("filesystem action accepted")

            client.role = "operator"
            try:
                client.call("act", action=pick.as_dict())
            except LabRejected as e:
                _check(e.error == "FORBIDDEN", "operator tunneled into agent effect")
            else:
                raise AssertionError("operator could send agent effect")
            client.role = "agent"
            try:
                client.call("operation_status", operation_id="op.e13.1")
            except LabRejected as e:
                _check(e.error == "FORBIDDEN", "E1.4 ledger exposed prematurely")
            else:
                raise AssertionError("unimplemented E1.4 status was exposed")

            # Harness route via upper gate x=6,y=2. Never disclosed to the agent.
            for direction in ("N", "N", "N", "E", "E", "S", "S", "S", "E", "E", "E"):
                do("world.move", {"direction": direction})
            _, final_proof = do("world.drop", {"item_ref": "lab.item.crate"})
            _check(final_proof.delivery_verified, "drop did not get fresh delivery proof")
            last = observe().as_dict()
            _check(last["self_position"] == {"x": 10, "y": 5},
                   "delivery not reached")
            _check(all(x in ("VERIFIED_SUCCESS", "VERIFIED_BLOCKED") for x in proofs),
                   "unverified action")
            _check(proofs.count("VERIFIED_BLOCKED") == 1, "unexpected blocked count")
            return {
                "seed": seed, "version": hello["world_version"], "effects_opt_in": True,
                "core_connected": False, "model_used": False,
                "operations": count, "statuses": proofs,
                "delivery_verified": final_proof.delivery_verified,
                "final_position": last["self_position"],
            }
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        binary = _binary(args.godot)
        with tempfile.TemporaryDirectory(prefix="anima_e13_world_") as directory:
            temp = Path(directory)
            left = _one_run(binary, args.seed, temp / "godot-1.log")
            right = _one_run(binary, args.seed, temp / "godot-2.log")
            _check(left == right, "same-seed E1.3 effect/readback trace differs")
        print(json.dumps({"status": "E1_3_LIVE_PASS", "runs": 2, **left},
                         sort_keys=True))
        return 0
    except Exception as exc:
        print(f"E1_3_LIVE_FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
