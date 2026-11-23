"""E2.4 real Godot / actual Core Raw / working-memory ablation.

No FAST, no Core world executor, no hidden state sent to the agent. Executor
is a separate lab harness to alter viewpoint while measuring memory semantics.
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
from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .e21_gateway_live_gate import finish
from .egocentric import E23ObserverPort, EgocentricAction, VIEW_ACTION_SCHEMA
from .e24_working_memory import (
    E24WorkingMemory, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)
from .world_smoke import PROJECT, _binary, _port, _wait


def require(ok, label):
    if not ok:
        raise AssertionError(label)


def build(root: Path):
    return build_core(
        root, sources={SOURCE: vision_source_registration()},
        properties={(SUBJECT, PREDICATE): vision_digest_rule()},
    )


def turn(port: int, key: str, view: dict, operation: str):
    action = EgocentricAction({
        "schema": VIEW_ACTION_SCHEMA,
        "world_instance_id": view["world_instance_id"], "epoch": view["epoch"],
        "expected_revision": view["revision"],
        "observation_id": view["sample_id"], "operation_id": operation,
        "action_type": "world.turn", "arguments": {"direction": "right"},
    }).as_dict()
    with LabClient(port, role="agent", protocol=PROTOCOL_V2) as client:
        receipt = client.call("act", auth=key, action=action)["data"]
        require(receipt["status"] == "APPLIED", "lab viewpoint turn not applied")
        again = client.call("act", auth=key, action=action)["data"]
        require(again["replayed"] and again["event_id"] == receipt["event_id"],
                "turn replay duplicated an effect")
    return receipt


def case(binary: str, seed: int, root: Path) -> dict:
    port = _port()
    keys = tuple(secrets.token_urlsafe(32) for _ in range(3))
    report = root / f"e24-world-seed-{seed}.log"
    output = report.open("w", encoding="utf-8")
    core_root = root / f"e24-core-seed-{seed}"
    process = subprocess.Popen(
        [binary, "--headless", "--path", str(PROJECT), "res://LifecycleWorld.tscn", "--",
         "--lifecycle-port", str(port), "--lifecycle-seed", str(seed),
         "--lifecycle-guarded", "--lifecycle-effects", "--lifecycle-ledger",
         "--lifecycle-egocentric"],
        cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT,
        env={**os.environ,
             "ANIMA_LIFECYCLE_OBSERVER_KEY": keys[0],
             "ANIMA_LIFECYCLE_EXECUTOR_KEY": keys[1],
             "ANIMA_LIFECYCLE_OPERATOR_KEY": keys[2]},
    )
    try:
        ready = _wait(process, port)
        ready.close()
        core = build(core_root)
        memory = E24WorkingMemory(
            core, E23ObserverPort(port=port, observer_key=keys[0]),
        )

        # View 1: spawn facing north, crate east is not visible.
        first = memory.observe_and_record()
        baseline = memory.world_model()
        require("lab.item.crate" not in {e["entity_ref"] for e in baseline["entities"]},
                "first view leaked unseen crate")
        # View 2: explicit harness-only action turns to east; crate now visible.
        turn(port, keys[1], memory.raw_evidence(first.sample_id).as_dict(), f"e24turn1_{seed}")
        second = memory.observe_and_record()
        east = memory.world_model()
        current = {e["entity_ref"]: e for e in east["entities"]}
        require(current.get("lab.item.crate", {}).get("current_observation") == "observed",
                "visual east view failed to establish crate observation")
        # View 3: another explicit turn to south, crate no longer visible.
        turn(port, keys[1], memory.raw_evidence(second.sample_id).as_dict(), f"e24turn2_{seed}")
        third = memory.observe_and_record()
        remembered = memory.world_model(memory_enabled=True)
        ablated = memory.world_model(memory_enabled=False)
        remembered_entities = {e["entity_ref"]: e for e in remembered["entities"]}
        ablated_entities = {e["entity_ref"]: e for e in ablated["entities"]}
        crate = remembered_entities.get("lab.item.crate")
        require(crate is not None, "prior-view crate not recovered from memory")
        require(crate["last_seen_sample"] == second.sample_id,
                "memory chose wrong source observation")
        require(crate["current_observation"] == "not_observed"
                and not crate["current_relative_geometry_verified"],
                "unobserved crate was fabricated as currently visible/absent")
        require("lab.item.crate" not in ablated_entities,
                "memory-off condition illegally retained earlier observation")
        require(any(e["kind"] == "co_observed" and
                    "lab.item.crate" in (e["first_ref"], e["second_ref"])
                    for e in remembered["relations"]),
                "no associative co-visibility edge for prior crate")
        require(remembered["historical_samples"] == 3
                and ablated["historical_samples"] == 1,
                "memory ablation input mismatch")

        # Core process reopens while Godot remains alive, no network reads here.
        reopened_core = build(core_root)
        reopened = E24WorkingMemory(
            reopened_core, E23ObserverPort(port=port, observer_key=keys[0]),
        )
        require(reopened.world_model() == remembered,
                "Core/process reopen lost derived working model")
        require(reopened.raw_evidence(second.sample_id).as_dict() ==
                memory.raw_evidence(second.sample_id).as_dict(),
                "Core/process reopen changed exact Raw")
        require(len(reopened_core.event_log.load_events()) == 3,
                "Core/EventLog didn't preserve exactly three source pointers")
        require(reopened_core.memory_store.count() == 0,
                "visual observations illegally became conversational episodic memories")
        require(reopened_core.core_execution is None, "unexpected Core action authority")
        require(reopened.recover() == (), "recovery generated duplicate Core events")
        require(len(reopened_core.event_log.load_events()) == 3,
                "recovery produced duplicate EventLog effects")

        evidence = {
            "seed": seed, "status": "PASS", "core_pointer_events": 3,
            "full_raw_snapshots": 3,
            "persistent_entity_recall": True,
            "memory_off_crate_found": False,
            "past_crate_marked": "not_observed",
            "traceable_proof_event_id": crate["last_seen_event_id"],
            "co_visibility_link": True,
            "reopened_same_core_identity": True,
            "godot_world_effects_issued_by_memory": 0,
            "godot_turns_issued_by_external_harness": 2,
            "llm_used": False, "core_stage6_used": False,
        }
        return evidence
    finally:
        finish(process, output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", default=None)
    parser.add_argument("--evidence-dir", default=None)
    args = parser.parse_args()
    binary = _binary(args.godot)
    root = (Path(args.evidence_dir) if args.evidence_dir else
            Path(tempfile.mkdtemp(prefix="anima-e24-")))
    root.mkdir(parents=True, exist_ok=True)
    results = [case(binary, seed, root) for seed in (7, 8)]
    payload = {
        "schema": "anima.e24.working_memory_gate/0.1",
        "status": "E2_4_MEMORY_GATE_PASS",
        "results": results,
    }
    (root / "e24-result.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
