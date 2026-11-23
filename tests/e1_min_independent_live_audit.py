"""Independent E1-min black-box acceptance against *unchanged* E1.1–E1.4.

No Core, model, operator map or fixture topology is provided to any agent.
This harness (not ANIMA) deliberately issues known movements to exercise both
routes, external state revisions, fresh sensor proof and replay boundaries.
Requires Godot 4.7.2 and is safe only on an isolated loopback test machine.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from labs.virtual_anima_lab.python.lab_client import LabClient, LabRejected, PROTOCOL_V2
from labs.virtual_anima_lab.python.lifecycle.contracts import (
    ACTION_SCHEMA, WorldAction, WorldObservation, WorldReceipt,
)
from labs.virtual_anima_lab.python.lifecycle.recovery import query_world_operation
from labs.virtual_anima_lab.python.lifecycle.world_smoke import (
    PROJECT, _binary, _port, _wait,
)
from labs.virtual_anima_lab.python.lifecycle.world_verification import verify_world_effect


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def rejected(client: LabClient, error_code: str, op: str, **kwargs) -> None:
    try:
        client.call(op, **kwargs)
    except LabRejected as exc:
        require(exc.error == error_code, f"{op}: wanted {error_code}; got {exc.error}")
    else:
        raise AssertionError(f"{op} unexpectedly accepted, expected {error_code}")


def observe(client: LabClient) -> WorldObservation:
    return WorldObservation(client.call("observe")["data"])


def action(before: WorldObservation, operation_id: str, kind: str, args: dict) -> WorldAction:
    state = before.as_dict()
    return WorldAction({
        "schema": ACTION_SCHEMA,
        "world_instance_id": state["world_instance_id"],
        "epoch": state["epoch"],
        "expected_revision": state["revision"],
        "observation_id": state["sample_id"],
        "operation_id": operation_id,
        "action_type": kind,
        "arguments": args,
    })


class RunningWorld:
    def __init__(self, binary: str, seed: int, flags: list[str], logfile: Path) -> None:
        self.port = _port()
        self.flags = flags
        self.seed = seed
        self.logfile = logfile
        self.binary = binary
        self.process: subprocess.Popen | None = None
        self.output = None
        self.client: LabClient | None = None

    def __enter__(self) -> "RunningWorld":
        self.output = self.logfile.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [self.binary, "--headless", "--path", str(PROJECT),
             "res://LifecycleWorld.tscn", "--",
             "--lifecycle-port", str(self.port),
             "--lifecycle-seed", str(self.seed), *self.flags],
            cwd=PROJECT, stdout=self.output, stderr=subprocess.STDOUT,
        )
        self.client = _wait(self.process, self.port)
        return self

    def reconnect(self) -> LabClient:
        if self.client is not None:
            self.client.close()
        self.client = LabClient(
            self.port, role="agent", protocol=PROTOCOL_V2, timeout=3,
        ).connect()
        return self.client

    def __exit__(self, *_exc) -> None:
        if self.client is not None:
            self.client.close()
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.output is not None:
            self.output.close()


def capabilities(binary: str, seed: int, logdir: Path) -> dict:
    results = {}
    modes = [
        ("observe", [], ["observe"]),
        ("effects", ["--lifecycle-effects"], ["observe", "act"]),
        ("ledger", ["--lifecycle-effects", "--lifecycle-ledger"],
         ["observe", "act", "operation_status"]),
    ]
    for mode, flags, expected in modes:
        with RunningWorld(binary, seed, flags, logdir / f"cap-{mode}.log") as world:
            client = world.client
            assert client is not None
            greeting = client.call("hello")["data"]
            require(greeting["capabilities"] == expected, f"capability escalation: {mode}")
            require("seed" not in greeting and "walls" not in greeting, "designer truth leaked")
            before = observe(client)
            first = before.as_dict()
            require(first["observer_ref"] == "lab.actor.anima",
                    "untrusted observer namespace")
            present = {r["subject_ref"] for r in first["readings"]}
            require("lab.item.crate" in present, "nearby crate invisible")
            require("lab.zone.delivery" not in present, "remote delivery truth leaked")
            for operation in ("inspect", "reset"):
                rejected(client, "FORBIDDEN", operation)
            rejected(client, "FORBIDDEN", "set_obstacle",
                     at={"x": 4, "y": 4}, blocked=True)
            if mode == "observe":
                rejected(client, "FORBIDDEN", "act", action={
                    "action_type": "world.move",
                })
            else:
                valid = action(before, f"e1min.cap.{mode}", "world.move",
                               {"direction": "E"})
                if mode == "effects":
                    rejected(
                        client, "FORBIDDEN", "operation_status",
                        world_instance_id=first["world_instance_id"],
                        epoch=first["epoch"], operation_id=valid.as_dict()["operation_id"],
                        action=valid.as_dict(),
                    )
                    executed = client.call("act", action=valid.as_dict())["data"]
                    require(WorldReceipt(executed).as_dict()["status"] == "APPLIED",
                            "effects-only did not permit E1.3 move")
                    rejected(client, "OPERATION_REUSED", "act", action=valid.as_dict())
                else:
                    state = query_world_operation(client, valid)
                    require(state.state == "UNKNOWN" and not state.safe_to_reissue,
                            "unknown status became authority")
            results[mode] = expected
    return results


def discard_response_without_reading(port: int, a: WorldAction) -> None:
    """Real TCP send followed by deliberate application-side response discard.

    The server stays alive. This is *not* a process-kill or power-loss test.
    """
    raw = {
        "protocol": PROTOCOL_V2, "id": 1, "role": "agent", "op": "act",
        "action": a.as_dict(),
    }
    data = (json.dumps(raw, separators=(",", ":"), sort_keys=True) + "\n").encode()
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(data)
        # Give the Godot event loop an opportunity to consume the request.
        # Deliberately NEVER read or inspect the response.
        time.sleep(0.25)


def complete_route(binary: str, seed: int, route: str, logdir: Path) -> dict:
    flags = ["--lifecycle-effects", "--lifecycle-ledger"]
    with RunningWorld(binary, seed, flags,
                      logdir / f"route-{seed}-{route}.log") as world:
        client = world.client
        assert client is not None
        first = observe(client)
        baseline = first.as_dict()
        world_id = baseline["world_instance_id"]
        pickup = action(first, f"e1min.{seed}.{route}.pick",
                        "world.pick", {"item_ref": "lab.item.crate"})
        missing = query_world_operation(client, pickup)
        require(missing.state == "UNKNOWN" and not missing.safe_to_reissue,
                "absent operation was treated as safe to retry")

        # Start real TCP action while intentionally never consuming response.
        client.close()
        world.client = None
        discard_response_without_reading(world.port, pickup)
        client = world.reconnect()
        recovered = query_world_operation(client, pickup)
        require(recovered.state == "RECORDED", "response loss not recoverable")
        require(not recovered.safe_to_reissue and recovered.receipt is not None,
                "recovery gave implicit permission to retry")
        second = observe(client)
        pickup_proof = verify_world_effect(first, pickup, recovered.receipt, second)
        require(pickup_proof.success, f"pickup proof failed: {pickup_proof.reason}")

        # Forged sensor, with plausible identifiers and fresh sample, must not
        # transform the recovered receipt into a successful readback.
        altered = second.as_dict()
        for reading in altered["readings"]:
            if (reading["subject_ref"] == "lab.item.crate"
                    and reading["predicate_ref"] == "owner"):
                reading["status"] = "absent"
                reading["value"] = None
        bogus = WorldObservation(altered)
        require(not verify_world_effect(first, pickup, recovered.receipt, bogus).success,
                "forged ownership reading accepted")
        replay_claim = recovered.receipt.as_dict()
        replay_claim["replayed"] = True
        require(not verify_world_effect(
            first, pickup, WorldReceipt(replay_claim), second
        ).success, "replayed receipt became a new success proof")

        snapshot = client.call("observe")
        replay = WorldReceipt(client.call("act", action=pickup.as_dict())["data"])
        aftermath = client.call("observe")
        require(replay.as_dict()["replayed"] is True, "replay marker absent")
        require(all(snapshot[k] == aftermath[k] for k in
                    ("epoch", "revision", "tick", "event_seq")),
                "replay created a duplicate effect or event")

        conflict = pickup.as_dict()
        conflict["action_type"] = "world.move"
        conflict["arguments"] = {"direction": "W"}
        rejected(client, "OPERATION_CONFLICT", "act", action=conflict)
        # Status is bound to the complete action, not just operation_id.
        rejected(
            client, "OPERATION_CONFLICT", "operation_status",
            world_instance_id=world_id, epoch=pickup.as_dict()["epoch"],
            operation_id=pickup.as_dict()["operation_id"], action=conflict,
        )

        # External operator intervention after an observation must revoke
        # stale admission, without silently recording the rejected effect.
        pre_external = observe(client)
        stale = action(pre_external, f"e1min.{seed}.{route}.stale",
                       "world.move", {"direction": "E"})
        client.role = "operator"
        changed = client.call(
            "set_obstacle", at={"x": 4, "y": 4}, blocked=True,
        )
        client.role = "agent"
        require(changed["data"]["changed"] and changed["revision"] >
                pre_external.as_dict()["revision"], "external revision not monotonic")
        rejected(client, "STALE_REVISION", "act", action=stale.as_dict())
        unresolved = query_world_operation(client, stale)
        require(unresolved.state == "UNKNOWN" and not unresolved.safe_to_reissue,
                "rejected stale action acquired false receipt")
        # Direct raw malformed command bypasses Python DTO validation.
        malformed = pickup.as_dict()
        malformed["operation_id"] = f"e1min.{seed}.{route}.invalid"
        malformed["action_type"] = "fs.delete"
        malformed["arguments"] = {"path": "/home"}
        rejected(client, "INVALID_ACTION", "act", action=malformed)

        # The route exists only in this independent harness. The agent does
        # not get a plan, map, operator inspection or seeded obstacle list.
        counters = {"VERIFIED_SUCCESS": 1, "VERIFIED_BLOCKED": 0}
        index = 0

        def attempt(kind: str, args: dict, wanted: str = "VERIFIED_SUCCESS") -> None:
            nonlocal index
            index += 1
            observed = observe(client)
            intent = action(observed, f"e1min.{seed}.{route}.{index}", kind, args)
            receipt = WorldReceipt(client.call("act", action=intent.as_dict())["data"])
            after = observe(client)
            verified = verify_world_effect(observed, intent, receipt, after)
            require(verified.status == wanted,
                    f"{kind} {index}: {verified.status}/{verified.reason} != {wanted}")
            counters[wanted] += 1
            if kind == "world.drop":
                require(verified.delivery_verified, "delivery is unverified")
            if wanted == "VERIFIED_BLOCKED":
                replayed = client.call("act", action=intent.as_dict())["data"]
                require(replayed["replayed"] and not replayed["effect_applied"],
                        "blocked attempt was executed again")
                terminal = query_world_operation(client, intent)
                require(terminal.state == "RECORDED" and
                        terminal.receipt.as_dict() == receipt.as_dict(),
                        "blocked attempt lost its terminal receipt")

        for direction in ("E", "E"):
            attempt("world.move", {"direction": direction})
        attempt("world.move", {"direction": "E"}, "VERIFIED_BLOCKED")
        axis = "N" if route == "top" else "S"
        back = "S" if route == "top" else "N"
        for direction in (axis, axis, axis, "E", "E", back, back, back,
                          "E", "E", "E"):
            attempt("world.move", {"direction": direction})
        attempt("world.drop", {"item_ref": "lab.item.crate"})

        final = observe(client).as_dict()
        require(final["self_position"] == {"x": 10, "y": 5},
                "route did not reach delivery")
        owner_readings = [
            x for x in final["readings"]
            if x["subject_ref"] == "lab.item.crate" and x["predicate_ref"] == "owner"
        ]
        require(owner_readings and owner_readings[0]["status"] == "absent",
                "item owner not released at delivery")
        client.role = "operator"
        truth = client.call("inspect")["data"]
        client.role = "agent"
        require(truth["actor"] == truth["delivery"] == truth["item"] ==
                {"x": 10, "y": 5} and truth["item_owner"] == "",
                "operator-only final truth contradicts sensor proof")
        old_status = query_world_operation(client, pickup)
        require(old_status.state == "RECORDED",
                "first receipt evicted during long route")

        # Reset is NOT durable recovery. Old epoch must not produce a
        # misleading success or execute old operation.
        client.role = "operator"
        epoch_info = client.call("reset")["data"]
        client.role = "agent"
        require(epoch_info["epoch"] == baseline["epoch"] + 1,
                "reset failed to advance epoch")
        late_status = query_world_operation(client, pickup)
        require(late_status.state == "UNKNOWN" and not late_status.safe_to_reissue,
                "old epoch lost status became a retry")
        rejected(client, "EPOCH_CHANGED", "act", action=pickup.as_dict())

        return {
            "seed": seed, "route": route,
            "world_epoch_before": baseline["epoch"],
            "verified_success": counters["VERIFIED_SUCCESS"],
            "verified_blocked": counters["VERIFIED_BLOCKED"],
            "lost_reply_recovered": True,
            "replay_effects": 0,
            "readback_delivered": True,
            "reset_old_epoch_status": "UNKNOWN",
            "no_core_or_model": True,
        }


def capacity_blackbox(binary: str, seed: int, logdir: Path) -> dict:
    """Independent TCP capacity check (not a Godot private-method shortcut)."""
    with RunningWorld(
        binary, seed, ["--lifecycle-effects", "--lifecycle-ledger"],
        logdir / "capacity-live.log",
    ) as world:
        client = world.client
        assert client is not None
        baseline = observe(client)
        first_action = None
        first_receipt = None
        for i in range(256):
            intended = action(
                baseline, f"e1min.capacity.{i:03d}",
                "world.drop", {"item_ref": "lab.item.crate"},
            )
            receipt = WorldReceipt(client.call("act", action=intended.as_dict())["data"])
            require(receipt.as_dict()["status"] == "BLOCKED",
                    f"capacity probe {i}: unexpectedly applied effect")
            if i == 0:
                first_action = intended
                first_receipt = receipt
        assert first_action is not None and first_receipt is not None
        overflow = action(
            baseline, "e1min.capacity.overflow", "world.drop",
            {"item_ref": "lab.item.crate"},
        )
        tick_before = client.call("hello")["tick"]
        rejected(client, "OPERATION_CAPACITY", "act", action=overflow.as_dict())
        require(client.call("hello")["tick"] == tick_before,
                "rejected capacity overflow mutated world tick")
        stored = query_world_operation(client, first_action)
        require(stored.state == "RECORDED" and
                stored.receipt.as_dict() == first_receipt.as_dict(),
                "full ledger lost first receipt")
        replayed = WorldReceipt(client.call("act", action=first_action.as_dict())["data"])
        require(replayed.as_dict()["replayed"] and
                replayed.as_dict()["status"] == "BLOCKED",
                "blocked replay failed under capacity")
        require(client.call("hello")["tick"] == tick_before,
                "replay under capacity changed tick")
        unknown = query_world_operation(client, overflow)
        require(unknown.state == "UNKNOWN" and not unknown.safe_to_reissue,
                "overflow acquired fake ledger record")
        final = observe(client).as_dict()
        require(final["revision"] == baseline.as_dict()["revision"] and
                final["self_position"] == baseline.as_dict()["self_position"],
                "capacity probe changed virtual actor")
        return {"capacity": 256, "blocked_recorded": 256,
                "overflow": "OPERATION_CAPACITY",
                "old_receipt_preserved": True, "no_effects": True}


def restart_boundary(binary: str, seed: int, logdir: Path) -> dict:
    """Process restart changes world identity; no cross-incarnation replay."""
    flags = ["--lifecycle-effects", "--lifecycle-ledger"]
    with RunningWorld(binary, seed, flags, logdir / "restart-before.log") as first_world:
        client = first_world.client
        assert client is not None
        before = observe(client)
        initial_id = before.as_dict()["world_instance_id"]
        intent = action(before, "e1min.restart.pick", "world.pick",
                        {"item_ref": "lab.item.crate"})
        receipt = WorldReceipt(client.call("act", action=intent.as_dict())["data"])
        require(receipt.as_dict()["effect_applied"], "restart precondition not executed")
    with RunningWorld(binary, seed, flags, logdir / "restart-after.log") as second_world:
        client = second_world.client
        assert client is not None
        state = observe(client).as_dict()
        require(state["world_instance_id"] != initial_id, "world process ID reused")
        status = query_world_operation(client, intent)
        require(status.state == "UNKNOWN" and not status.safe_to_reissue,
                "old instance receipt falsely restored")
        rejected(client, "WORLD_CHANGED", "act", action=intent.as_dict())
    return {"world_process_restarted": True, "durable_ledger": False,
            "safe_reissue_after_restart": False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--godot", required=True)
    p.add_argument("--evidence-dir", help="persistent folder for raw Godot logs")
    args = p.parse_args()
    godot = _binary(args.godot)
    try:
        workspace = (nullcontext(args.evidence_dir) if args.evidence_dir else
                     tempfile.TemporaryDirectory(prefix="anima-e1min-audit-"))
        with workspace as directory:
            tmp = Path(directory)
            tmp.mkdir(parents=True, exist_ok=True)
            mode_checks = capabilities(godot, 7, tmp)
            traces = [
                complete_route(godot, seed, route, tmp)
                for seed in (7, 8) for route in ("top", "bottom")
            ]
            capacity = capacity_blackbox(godot, 7, tmp)
            restarts = restart_boundary(godot, 7, tmp)
        print(json.dumps({
            "schema": "anima.e1min.independent_lab_audit/0.1",
            "status": "E1_MIN_INDEPENDENT_LIVE_PASS",
            "capability_profiles": mode_checks,
            "routes": traces,
            "process_restart": restarts,
            "capacity_blackbox": capacity,
            "core_connected": False,
            "model_used": False,
            "physical_effects_tested": False,
            "operator_role_authenticated": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"E1_MIN_INDEPENDENT_LIVE_FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
