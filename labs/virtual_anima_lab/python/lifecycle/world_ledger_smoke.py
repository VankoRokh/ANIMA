"""E1.4 live status/replay proof with a disposable Godot world process.

The lost response here is an application-discard simulation. No physical
power-loss, Godot process restart, authenticated transport or durable replay
is claimed. A missing ledger record means UNKNOWN, never "safe to retry".
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from ..lab_client import LabClient, LabRejected, PROTOCOL_V2
from .contracts import (
    ACTION_SCHEMA, WorldAction, WorldObservation, WorldReceipt,
)
from .recovery import query_world_operation
from .world_smoke import PROJECT, _binary, _port, _wait
from .world_verification import verify_world_effect


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _action(observation: WorldObservation, operation_id: str, kind: str,
            arguments: dict) -> WorldAction:
    d = observation.as_dict()
    return WorldAction({
        "schema": ACTION_SCHEMA, "world_instance_id": d["world_instance_id"],
        "epoch": d["epoch"], "expected_revision": d["revision"],
        "observation_id": d["sample_id"], "operation_id": operation_id,
        "action_type": kind, "arguments": arguments,
    })


def _one_run(binary: str, seed: int, logfile: Path) -> dict:
    port = _port()
    with logfile.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [binary, "--headless", "--path", str(PROJECT),
             "res://LifecycleWorld.tscn", "--",
             "--lifecycle-port", str(port),
             "--lifecycle-seed", str(seed),
             "--lifecycle-effects", "--lifecycle-ledger"],
            cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT,
        )
        client = None
        try:
            client = _wait(process, port)
            hello = client.call("hello")["data"]
            _require(hello["capabilities"] == [
                "observe", "act", "operation_status",
            ], "E1.4 capabilities not scoped")
            before = WorldObservation(client.call("observe")["data"])
            pick = _action(before, "e14.live.pick", "world.pick",
                           {"item_ref": "lab.item.crate"})
            unknown = query_world_operation(client, pick)
            _require(unknown.state == "UNKNOWN" and not unknown.safe_to_reissue,
                     "absence of ledger was treated as permission to act")
            first = WorldReceipt(client.call("act", action=pick.as_dict())["data"])
            _require(first.as_dict()["status"] == "APPLIED", "initial pick failed")

            # Simulate losing the receipt at the calling application boundary:
            # do not consume 'first' for recovery; close then reconnect.
            client.close()
            client = None
            with LabClient(port, role="agent", protocol=PROTOCOL_V2) as recovered:
                entry = query_world_operation(recovered, pick)
                _require(entry.state == "RECORDED" and
                         entry.receipt.as_dict() == first.as_dict(),
                         "lost-answer status failed to recover the original receipt")
                after = WorldObservation(recovered.call("observe")["data"])
                proof = verify_world_effect(before, pick, entry.receipt, after)
                _require(proof.success, f"recovered receipt lacks sensor proof: {proof.reason}")

                # A duplicate returns original receipt with replayed=true,
                # but must never change epoch/revision/tick/event sequence.
                before_duplicate = recovered.call("observe")
                duplicate = WorldReceipt(
                    recovered.call("act", action=pick.as_dict())["data"]
                )
                after_duplicate = recovered.call("observe")
                expected = first.as_dict()
                expected["replayed"] = True
                _require(duplicate.as_dict() == expected, "replay receipt changed content")
                for field in ("epoch", "revision", "tick", "event_seq"):
                    _require(before_duplicate[field] == after_duplicate[field],
                             f"replay mutated world clock: {field}")

                conflict = pick.as_dict()
                conflict["action_type"] = "world.move"
                conflict["arguments"] = {"direction": "W"}
                try:
                    recovered.call("act", action=conflict)
                except LabRejected as exc:
                    _require(exc.error == "OPERATION_CONFLICT",
                             "conflicting operation ID was not identified")
                else:
                    raise AssertionError("conflicting operation reused same ID")

                # A lookup for an existing ID with changed intent must fail
                # before it could be misinterpreted as the new action receipt.
                try:
                    query_world_operation(recovered, WorldAction(conflict))
                except LabRejected as exc:
                    _require(exc.error == "OPERATION_CONFLICT",
                             "status lookup accepted altered payload")
                else:
                    raise AssertionError("forged status lookup returned old receipt")

                wrong = pick.as_dict()
                wrong["operation_id"] = "e14.missing"
                missing = query_world_operation(recovered, WorldAction(wrong))
                _require(missing.state == "UNKNOWN" and
                         not missing.safe_to_reissue, "UNKNOWN became permission")

                # Prove an ordinary action still works after ledger queries.
                move_before = WorldObservation(recovered.call("observe")["data"])
                move = _action(move_before, "e14.live.move", "world.move",
                               {"direction": "E"})
                move_receipt = WorldReceipt(
                    recovered.call("act", action=move.as_dict())["data"]
                )
                move_after = WorldObservation(recovered.call("observe")["data"])
                _require(verify_world_effect(move_before, move, move_receipt,
                                             move_after).success,
                         "move effect not independently observed")
                _require(query_world_operation(recovered, move).state == "RECORDED",
                         "ordinary move missing from ledger")

                # Role is a laboratory declaration: operator status must be
                # rejected even though this is NOT process authentication.
                recovered.role = "operator"
                try:
                    recovered.call(
                        "operation_status",
                        world_instance_id=pick.as_dict()["world_instance_id"],
                        epoch=pick.as_dict()["epoch"],
                        operation_id=pick.as_dict()["operation_id"],
                        action=pick.as_dict(),
                    )
                except LabRejected as exc:
                    _require(exc.error == "UNKNOWN_OPERATION",
                             "unexpected operator status response")
                else:
                    raise AssertionError("operator was allowed to query ledger")
                recovered.role = "agent"

            # Operator reset: same Godot process, new epoch, old evidence
            # is deliberately unavailable rather than falsely restored.
            with LabClient(port, role="operator", protocol=PROTOCOL_V2) as operator:
                reset = operator.call("reset")["data"]
            with LabClient(port, role="agent", protocol=PROTOCOL_V2) as again:
                old = query_world_operation(again, pick)
                _require(old.state == "UNKNOWN", "pre-reset ledger leaked")
                _require(reset["epoch"] == before.as_dict()["epoch"] + 1,
                         "reset did not advance epoch")
                try:
                    again.call("act", action=pick.as_dict())
                except LabRejected as exc:
                    _require(exc.error == "EPOCH_CHANGED",
                             "old epoch intent got a different error")
                else:
                    raise AssertionError("old epoch action replayed after reset")

            return {
                "seed": seed, "status": "E1_4_LIVE_PASS",
                "runs": 1, "world_version": hello["world_version"],
                "recoverable_claim": "RECORDED", "unknown_is_retry": False,
                "replayed_without_effect": True, "conflict_rejected": True,
                "reset_epoch_isolated": True, "sensor_verified": proof.success,
                "core_connected": False, "model_used": False,
                "world_process_restart_tested": False,
            }
        finally:
            if client is not None:
                client.close()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--godot")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)
    try:
        binary = _binary(args.godot)
        with tempfile.TemporaryDirectory(prefix="anima-e14-") as directory:
            path = Path(directory)
            a = _one_run(binary, args.seed, path / "first-godot.log")
            b = _one_run(binary, args.seed, path / "second-godot.log")
            _require(a == b, "same-seed ledger trace was non-deterministic")
        print(json.dumps({**a, "runs": 2}, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"E1_4_LIVE_FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
