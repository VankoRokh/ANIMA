"""E2.4b real Godot readback → Core-backed view → local pose acceptance.

Only external lab harness has executor key; E24PoseTrail never sends act().
Hidden Godot operator coordinates are used solely as *independent* test oracle.
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
from .e24_pose import E24PoseTrail
from .e24_working_memory import (
    E24WorkingMemory, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)
from .world_smoke import PROJECT, _binary, _port, _wait


def check(ok: bool, note: str):
    if not ok:
        raise AssertionError(note)


def build(root: Path):
    return build_core(
        root, sources={SOURCE: vision_source_registration()},
        properties={(SUBJECT, PREDICATE): vision_digest_rule()},
    )


def operator_truth(port: int, key: str):
    with LabClient(port, role="operator", protocol=PROTOCOL_V2) as client:
        return client.call("inspect", auth=key)["data"]


def effect(port: int, executor_key: str, view: dict, op: str, kind: str, direction: str):
    act = EgocentricAction({
        "schema": VIEW_ACTION_SCHEMA,
        "world_instance_id": view["world_instance_id"],
        "epoch": view["epoch"], "expected_revision": view["revision"],
        "observation_id": view["sample_id"],
        "operation_id": op, "action_type": kind, "arguments": {"direction": direction},
    })
    # External harness only. PoseTrail separately readbacks operation_status.
    with LabClient(port, role="agent", protocol=PROTOCOL_V2) as client:
        receipt = client.call("act", auth=executor_key, action=act.as_dict())["data"]
        replay = client.call("act", auth=executor_key, action=act.as_dict())["data"]
    check(replay["replayed"] is True and replay["event_id"] == receipt["event_id"],
          "external world effect replay was not idempotent")
    return act


def case(binary: str, seed: int, root: Path) -> dict:
    port = _port()
    keys = tuple(secrets.token_urlsafe(32) for _ in range(3))
    logfile = (root / f"e24b-godot-{seed}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [binary, "--headless", "--path", str(PROJECT), "res://LifecycleWorld.tscn", "--",
         "--lifecycle-port", str(port), "--lifecycle-seed", str(seed),
         "--lifecycle-guarded", "--lifecycle-effects", "--lifecycle-ledger",
         "--lifecycle-egocentric"],
        cwd=PROJECT, stdout=logfile, stderr=subprocess.STDOUT,
        env={**os.environ,
             "ANIMA_LIFECYCLE_OBSERVER_KEY": keys[0],
             "ANIMA_LIFECYCLE_EXECUTOR_KEY": keys[1],
             "ANIMA_LIFECYCLE_OPERATOR_KEY": keys[2]},
    )
    try:
        ready = _wait(process, port)
        ready.close()
        start = operator_truth(port, keys[2])
        core_path = root / f"e24b-core-{seed}"
        instance = build(core_path)
        memory = E24WorkingMemory(instance, E23ObserverPort(
            port=port, observer_key=keys[0],
        ))
        pose = E24PoseTrail(memory, port=port, executor_key=keys[1])

        first = memory.observe_and_record()
        check("lab.item.crate" not in {
            e["entity_ref"] for e in memory.world_model()["entities"]
        }, "spawn saw a hidden east crate")
        before1 = memory.raw_evidence(first.sample_id).as_dict()
        turn = effect(port, keys[1], before1, f"e24b_turn_{seed}", "world.turn", "right")
        readback1 = pose.record_verified_external_action(turn)
        check(readback1["status"] == "APPLIED", "turn receipt should be applied")
        check(pose.reconstruct()["pending_next_sensor"] == [turn.as_dict()["operation_id"]],
              "prematurely advanced orientation without next Raw view")

        second = memory.observe_and_record()
        turned = pose.reconstruct()
        check(turned["poses"][-1]["relative_heading_quadrants"] == 1,
              "right turn not reconstructed")
        seen = {e["entity_ref"] for e in memory.world_model()["entities"]}
        check("lab.item.crate" in seen, "east facing view did not see crate")
        before2 = memory.raw_evidence(second.sample_id).as_dict()

        step = effect(port, keys[1], before2, f"e24b_step_{seed}",
                      "world.step", "forward")
        readback2 = pose.record_verified_external_action(step)
        check(readback2["status"] == "APPLIED", "forward step should be applied")
        check(len(pose.reconstruct()["verified_transitions"]) == 1,
              "second movement was inferred before its next Raw observation")
        third = memory.observe_and_record()
        final = pose.reconstruct()
        check(len(final["verified_transitions"]) == 2
              and not final["pending_next_sensor"], "incomplete sensor-backed trail")
        end = final["poses"][-1]
        check(end["local_right_steps"] == 1 and end["local_forward_steps"] == 0
              and end["relative_heading_quadrants"] == 1,
              "relative trajectory differs from observed effects")
        check(not final["hidden_godot_coordinates_used"]
              and final["not_stage6_authorized"], "pose authority misrepresented")

        # Independent world oracle: never passed into working memory or model.
        truth = operator_truth(port, keys[2])
        check(truth["actor"]["x"] - start["actor"]["x"] == end["local_right_steps"]
              and truth["actor"]["y"] - start["actor"]["y"] == -end["local_forward_steps"],
              "independent Godot displacement != locally reconstructed odometry")
        reopened = E24WorkingMemory(build(core_path), E23ObserverPort(
            port=port, observer_key=keys[0],
        ))
        recovered = E24PoseTrail(reopened, port=port, executor_key=keys[1])
        check(recovered.reconstruct() == final,
              "relative odometry changed after Core/process reopen")
        check(len(reopened._core.event_log.load_events()) == 3,
              "world pose tracking duplicated canonical Core/EventLog events")
        check(reopened._core.memory_store.count() == 0,
              "world memory was silently published as episodes/Knowledge")
        return {
            "seed": seed, "status": "PASS",
            "raw_views": 3, "godot_actions_by_external_harness": 2,
            "readback_receipts": 2, "verified_pose_transitions": 2,
            "relative_right_steps": end["local_right_steps"],
            "relative_forward_steps": end["local_forward_steps"],
            "untrusted_model_commands": 0,
            "core_stage6_actions": 0, "llm_used": False,
            "reopen_pose_equal": True,
            "independent_oracle_match": True,
        }
    finally:
        finish(process, logfile)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", default=None)
    parser.add_argument("--evidence-dir", default=None)
    args = parser.parse_args()
    godot = _binary(args.godot)
    root = Path(args.evidence_dir) if args.evidence_dir else Path(
        tempfile.mkdtemp(prefix="anima-e24b-pose-")
    )
    root.mkdir(parents=True, exist_ok=True)
    result = {"schema": "anima.e24b.relative_pose_gate/0.1",
              "status": "E2_4B_POSE_GATE_PASS",
              "cases": [case(godot, seed, root) for seed in (7, 8)]}
    (root / "e24b-result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
