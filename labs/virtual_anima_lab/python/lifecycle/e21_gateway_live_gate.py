"""Live E2.1 Core-bound *observation-only* gateway acceptance against Godot.

No FAST, no synthetic Goal, no direct Stage6 world executor or Raw projection.
All operator interventions are made by the independent test harness, never
through the gateway. Each world has disposable Core storage and an ephemeral
loopback port. World restart deliberately fails closed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .core_gateway import (
    SOURCE_REF, CoreBoundObservationGateway, WorldBoundaryError,
    lifecycle_source_registration,
)
from .world_smoke import PROJECT, _binary, _port, _wait


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AssertionError(reason)


def core(root: Path):
    return build_core(
        root,
        sources={SOURCE_REF: lifecycle_source_registration()},
        properties={},
    )


def start(binary: str, port: int, seed: int, log: Path):
    output = log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [binary, "--headless", "--path", str(PROJECT),
         "res://LifecycleWorld.tscn", "--",
         "--lifecycle-port", str(port),
         "--lifecycle-seed", str(seed),
         "--lifecycle-effects", "--lifecycle-ledger"],
        cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT,
    )
    return process, output


def finish(process, output):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    output.close()


def run_once(binary: str, seed: int, evidence: Path) -> dict:
    port = _port()
    data_dir = evidence / f"instance-{seed}"
    assembly = core(data_dir)
    adapter = CoreBoundObservationGateway(assembly, port=port)
    process, log_output = start(binary, port, seed, evidence / f"godot-{seed}.log")
    old_world_id = None
    try:
        first_client = _wait(process, port)
        first_client.close()
        first = adapter.observe()
        a = first.as_dict()
        old_world_id = a["world_instance_id"]
        require(adapter.binding_snapshot()["sample_seq"] == a["sample_seq"],
                "sample not pinned before exposing observation")
        require(a["source_ref"] == SOURCE_REF, "wrong registered sensor")
        require("lab.zone.delivery" not in {row["subject_ref"] for row in a["readings"]},
                "hidden world truth leaked through gateway")
        second = adapter.observe().as_dict()
        require(second["sample_seq"] > a["sample_seq"],
                "new observation failed monotonicity")

        # Trusted Core identity, same storage, new process object: binding
        # must survive Core-side reopen with the *same* Godot still running.
        reopened = core(data_dir)
        adapter = CoreBoundObservationGateway(reopened, port=port)
        require(adapter.binding_snapshot()["world_instance_id"] == old_world_id,
                "Core reopen discarded the world identity")
        third = adapter.observe().as_dict()
        require(third["sample_seq"] > second["sample_seq"],
                "Core process reopen reused sample identity")

        # The gateway API cannot issue operator commands or any world effect.
        for method in ("act", "execute", "operation_status", "reset", "inspect",
                       "set_obstacle", "connect", "client"):
            require(not hasattr(adapter, method),
                    f"unsafe capability exported to Core/Fast caller: {method}")

        # An external operator action changes world revision; only the
        # test-harness obtains the separate operator session.
        with LabClient(port, role="operator", protocol=PROTOCOL_V2) as operator:
            changed = operator.call(
                "set_obstacle", at={"x": 4, "y": 4}, blocked=True,
            )
            require(changed["data"]["changed"], "fixture operator did not mutate world")
        post_change = adapter.observe().as_dict()
        require(post_change["revision"] > third["revision"],
                "external revision not visible in registered observation")
        require(not reopened.core_events.ingress.pending_event_ids(limit=10),
                "E2.1 is not allowed to assert Raw Event provenance")

        # Reset revokes the entire binding, even when process ID is unchanged.
        with LabClient(port, role="operator", protocol=PROTOCOL_V2) as operator:
            reset = operator.call("reset")["data"]
        require(reset["epoch"] == a["epoch"] + 1, "reset did not increment epoch")
        before_reject = adapter.binding_snapshot()
        try:
            adapter.observe()
        except WorldBoundaryError as exc:
            require("binding changed" in str(exc),
                    "reset did not fail by the expected boundary")
        else:
            raise AssertionError("gateway silently accepted a world reset")
        require(adapter.binding_snapshot() == before_reject,
                "failed reset admission modified Core binding")
    finally:
        finish(process, log_output)

    # New Godot process and new port, same Core storage. No auto-rebind.
    next_port = _port()
    next_process, next_output = start(
        binary, next_port, seed, evidence / f"godot-{seed}-restarted.log",
    )
    try:
        client = _wait(next_process, next_port)
        newer_id = client.call("hello")["data"]["world_instance_id"]
        client.close()
        require(newer_id != old_world_id, "fresh world process reused incarnation")
        reopened = core(data_dir)
        adapter = CoreBoundObservationGateway(reopened, port=next_port)
        before = adapter.binding_snapshot()
        try:
            adapter.observe()
        except WorldBoundaryError as exc:
            require("binding changed" in str(exc),
                    "process replacement did not report identity mismatch")
        else:
            raise AssertionError("gateway silently rebound to new world process")
        require(adapter.binding_snapshot() == before, "failed rebind corrupted pin")
    finally:
        finish(next_process, next_output)

    return {
        "seed": seed, "world_reopen_same_process": "ACCEPTED",
        "external_revision_observed": True,
        "world_reset": "REJECTED",
        "world_process_restart": "REJECTED",
        "core_raw_events_written": 0,
        "world_effects_issued_by_gateway": 0,
        "core_execution_registered": False,
        "role_authenticated": False,
        "raw_socket_isolated_from_untrusted_OS_process": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", required=True)
    parser.add_argument("--evidence-dir")
    args = parser.parse_args(argv)
    try:
        binary = _binary(args.godot)
        if args.evidence_dir:
            root = Path(args.evidence_dir)
            root.mkdir(parents=True, exist_ok=True)
            trials = [run_once(binary, seed, root) for seed in (7, 8)]
        else:
            with tempfile.TemporaryDirectory(prefix="anima-e21-trust-") as tmp:
                trials = [run_once(binary, seed, Path(tmp)) for seed in (7, 8)]
        print(json.dumps({
            "schema": "anima.e2_1.core_world_boundary_gate/0.1",
            "status": "E2_1_READ_ONLY_GATE_PASS",
            "trials": trials,
            "scope": "CORE_BOUND_OBSERVE_ONLY",
            "stage6_execution_admitted": False,
            "model_used": False,
            "raw_ingress_integrated": False,
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"E2_1_READ_ONLY_GATE_FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
