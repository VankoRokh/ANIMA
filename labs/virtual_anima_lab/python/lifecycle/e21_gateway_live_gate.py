"""Live E2.1 Core-bound *observation-only* gateway acceptance against Godot.

No FAST, no synthetic Goal, no direct Stage6 world executor or Raw projection.
All operator interventions are made by the independent test harness, never
through the gateway. Each world has disposable Core storage and an ephemeral
loopback port. World restart deliberately fails closed.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.lab_client import LabClient, LabRejected, PROTOCOL_V2
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


def start(binary: str, port: int, seed: int, log: Path, keys: tuple[str, str, str]):
    output = log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [binary, "--headless", "--path", str(PROJECT),
         "res://LifecycleWorld.tscn", "--",
         "--lifecycle-port", str(port),
         "--lifecycle-seed", str(seed),
         "--lifecycle-effects", "--lifecycle-ledger", "--lifecycle-guarded"],
        cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT,
        env={**os.environ,
             "ANIMA_LIFECYCLE_OBSERVER_KEY": keys[0],
             "ANIMA_LIFECYCLE_EXECUTOR_KEY": keys[1],
             "ANIMA_LIFECYCLE_OPERATOR_KEY": keys[2]},
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


def negative_bootstrap(binary: str, evidence: Path) -> dict:
    """A guarded listener must not start with absent/weak/reused credentials."""
    cases = {
        "missing": ("", "", ""),
        "same": ("s" * 43, "s" * 43, "o" * 43),
        "weak": ("x" * 12, "e" * 43, "o" * 43),
    }
    for label, keys in cases.items():
        port = _port()
        env = {
            **os.environ,
            "ANIMA_LIFECYCLE_OBSERVER_KEY": keys[0],
            "ANIMA_LIFECYCLE_EXECUTOR_KEY": keys[1],
            "ANIMA_LIFECYCLE_OPERATOR_KEY": keys[2],
        }
        logfile = evidence / f"bootstrap-{label}.log"
        with logfile.open("w", encoding="utf-8") as output:
            completed = subprocess.run(
                [binary, "--headless", "--path", str(PROJECT),
                 "res://LifecycleWorld.tscn", "--",
                 "--lifecycle-port", str(port),
                 "--lifecycle-seed", "7",
                 "--lifecycle-effects", "--lifecycle-ledger",
                 "--lifecycle-guarded"],
                cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT,
                env=env, timeout=10, check=False,
            )
        require(completed.returncode != 0,
                f"guarded {label} config started without valid credentials")
        require("ANIMA_LIFECYCLE_WORLD_READY" not in logfile.read_text(encoding="utf-8"),
                f"guarded {label} config opened a listener before failing")
    return {"missing": "REJECTED", "reused": "REJECTED", "weak": "REJECTED"}


def run_once(binary: str, seed: int, evidence: Path) -> dict:
    port = _port()
    data_dir = evidence / f"instance-{seed}"
    keys = tuple(secrets.token_urlsafe(32) for _ in range(3))
    observer_key, executor_key, operator_key = keys
    assembly = core(data_dir)
    adapter = CoreBoundObservationGateway(
        assembly, port=port, observer_key=observer_key,
    )
    process, log_output = start(
        binary, port, seed, evidence / f"godot-{seed}.log", keys,
    )
    old_world_id = None
    try:
        first_client = _wait(process, port)
        first_client.close()
        # Direct loopback role spoof is rejected in guarded mode.
        with LabClient(port, role="operator", protocol=PROTOCOL_V2) as attacker:
            for credentials in ({}, {"auth": observer_key}, {"auth": executor_key}):
                try:
                    attacker.call("inspect", **credentials)
                except LabRejected as exc:
                    require(exc.error == "UNAUTHORIZED",
                            "operator spoof was not rejected by Godot itself")
                else:
                    raise AssertionError("raw socket obtained operator world truth")
            truth = attacker.call("inspect", auth=operator_key)["data"]
            require(truth["seed"] == seed, "trusted operator could not inspect")
        with LabClient(port, role="agent", protocol=PROTOCOL_V2) as raw:
            try:
                raw.call("observe")
            except LabRejected as exc:
                require(exc.error == "UNAUTHORIZED",
                        "anonymous world observation was accepted")
            else:
                raise AssertionError("unauthenticated observe accepted")
            observer_hello = raw.call("hello", auth=observer_key)["data"]
            require(observer_hello["capabilities"] == ["observe"] and
                    observer_hello["auth_mode"] == "guarded" and
                    "seed" not in observer_hello,
                    "observer credential improperly grants extra capabilities")
            try:
                raw.call("act", auth=observer_key, action={})
            except LabRejected as exc:
                require(exc.error == "FORBIDDEN",
                        "read-only key gained execution authority")
            else:
                raise AssertionError("observer key issued act")
            executor_hello = raw.call("hello", auth=executor_key)["data"]
            require(executor_hello["capabilities"] == ["act", "operation_status"],
                    "executor was given observation or operator rights")
            try:
                raw.call("observe", auth=executor_key)
            except LabRejected as exc:
                require(exc.error == "FORBIDDEN",
                        "executor key gained observation rights")
            else:
                raise AssertionError("executor read sensor directly")
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
        adapter = CoreBoundObservationGateway(reopened, port=port, observer_key=observer_key)
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
                auth=operator_key,
            )
            require(changed["data"]["changed"], "fixture operator did not mutate world")
        post_change = adapter.observe().as_dict()
        require(post_change["revision"] > third["revision"],
                "external revision not visible in registered observation")
        require(not reopened.core_events.ingress.pending_event_ids(limit=10),
                "E2.1 is not allowed to assert Raw Event provenance")

        # Reset revokes the entire binding, even when process ID is unchanged.
        with LabClient(port, role="operator", protocol=PROTOCOL_V2) as operator:
            reset = operator.call("reset", auth=operator_key)["data"]
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
    guarded_log = (evidence / f"godot-{seed}.log").read_text(encoding="utf-8")
    require(not any(key in guarded_log for key in keys),
            "guarded world accidentally logged a bearer capability")
    require(f"seed={seed}" not in guarded_log,
            "guarded mode published the scenario seed in stdout")

    # New Godot process and new port, same Core storage. No auto-rebind.
    next_port = _port()
    next_process, next_output = start(
        binary, next_port, seed, evidence / f"godot-{seed}-restarted.log", keys,
    )
    try:
        client = _wait(next_process, next_port)
        newer_id = client.call("hello", auth=observer_key)["data"]["world_instance_id"]
        client.close()
        require(newer_id != old_world_id, "fresh world process reused incarnation")
        reopened = core(data_dir)
        adapter = CoreBoundObservationGateway(reopened, port=next_port, observer_key=observer_key)
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
        "role_bearer_guard_enabled": True,
        "operator_spoof_rejected_by_server": True,
        "observer_credential_can_execute": False,
        "os_process_and_secret_isolation_verified": False,
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
            bootstrap = negative_bootstrap(binary, root)
            trials = [run_once(binary, seed, root) for seed in (7, 8)]
        else:
            with tempfile.TemporaryDirectory(prefix="anima-e21-trust-") as tmp:
                bootstrap = negative_bootstrap(binary, Path(tmp))
                trials = [run_once(binary, seed, Path(tmp)) for seed in (7, 8)]
        print(json.dumps({
            "schema": "anima.e2_1.core_world_boundary_gate/0.1",
            "status": "E2_1_READ_ONLY_GATE_PASS",
            "trials": trials,
            "invalid_guarded_bootstrap": bootstrap,
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
