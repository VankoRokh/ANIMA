"""E2.5a real Godot → Core Raw → memory → initiated cognitive steps.

External harness turns the sensor; the cognitive module is read-only. The
same captured Raw is tested with memory enabled and disabled; no actual LLM.
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
from labs.virtual_anima_lab.python.cognition.contracts import SCHEMA
from labs.virtual_anima_lab.python.cognition.coordinator import (
    E25LabCognitiveCoordinator, TwoStepEvidenceStub,
)
from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .e21_gateway_live_gate import finish
from .egocentric import E23ObserverPort
from .e24_memory_live_gate import turn
from .e24_working_memory import (
    E24WorkingMemory, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)
from .world_smoke import PROJECT, _binary, _port, _wait


def require(ok, msg):
    if not ok:
        raise AssertionError(msg)


def operator_truth(port, key):
    with LabClient(port, role="operator", protocol=PROTOCOL_V2) as client:
        return client.call("inspect", auth=key)["data"]


def case(binary: str, seed: int, root: Path):
    port = _port()
    keys = tuple(secrets.token_urlsafe(32) for _ in range(3))
    logfile = (root / f"e25a-world-{seed}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [binary, "--headless", "--path", str(PROJECT),
         "res://LifecycleWorld.tscn", "--",
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
        instance = build_core(
            root / f"e25a-core-{seed}",
            sources={SOURCE: vision_source_registration()},
            properties={(SUBJECT, PREDICATE): vision_digest_rule()},
        )
        memory = E24WorkingMemory(
            instance, E23ObserverPort(port=port, observer_key=keys[0]),
        )
        first = memory.observe_and_record()
        require("lab.item.crate" not in {
            x["entity_ref"] for x in memory.world_model()["entities"]
        }, "crate must not be initially visible")
        turn(port, keys[1], memory.raw_evidence(first.sample_id).as_dict(), f"e25turn1_{seed}")
        second = memory.observe_and_record()
        require("lab.item.crate" in {
            x["entity_ref"] for x in memory.world_model()["entities"]
        }, "crate should be visible when east-facing")
        turn(port, keys[1], memory.raw_evidence(second.sample_id).as_dict(), f"e25turn2_{seed}")
        third = memory.observe_and_record()
        require("lab.item.crate" not in {
            x["entity_ref"] for x in memory.world_model(memory_enabled=False)["entities"]
        }, "crate must no longer be visible")
        world_before = operator_truth(port, keys[2])
        coordinator = E25LabCognitiveCoordinator(memory, max_steps=4)
        enabled = coordinator.run_turn(
            TwoStepEvidenceStub(), turn_id=f"mem_on_{seed}", memory_enabled=True,
        )
        disabled = coordinator.run_turn(
            TwoStepEvidenceStub(), turn_id=f"mem_off_{seed}", memory_enabled=False,
        )
        require(enabled["status"] == "STOPPED" and disabled["status"] == "STOPPED",
                "cognition did not terminate cleanly")
        require([x["operation_kind"] for x in enabled["outcomes"]] ==
                ["retrieve_memory", "lookup_raw_evidence"],
                "stub could not initiate a second cognitive operation")
        remembered = enabled["outcomes"][0]["result"]["records"]
        require(len(remembered) == 1 and remembered[0]["entity_ref"] == "lab.item.crate"
                and remembered[0]["current_observation"] == "not_observed",
                "source-backed previous vision was not retrieved")
        proof = enabled["outcomes"][1]["result"]["records"][0]
        require(proof["status"] == "verified_source_view"
                and proof["event_id"] == remembered[0]["last_seen_event_id"],
                "LLM-style follow-up did not read real Raw evidence")
        require(disabled["outcomes"][0]["result"]["records"] == []
                and len(disabled["outcomes"]) == 1,
                "memory-off ablation was not isolated")

        class UntrustedProposal:
            def propose(self, context, outcomes, *, turn_id, step_index):
                return {
                    "schema": SCHEMA, "proposal_id": f"pr_{turn_id}_1",
                    "turn_id": turn_id,
                    "context_snapshot_id": context["context_snapshot_id"],
                    "operation_kind": "world.step",
                    "arguments": {"direction": "forward"},
                    "expected_information": "unsafe",
                }

        rejected = coordinator.run_turn(
            UntrustedProposal(), turn_id=f"attack_{seed}",
        )
        require(rejected["status"] == "REJECTED"
                and rejected["outcomes"][0]["reason_code"] == "INVALID_PROPOSAL",
                "world-effect request bypassed lab cognition policy")
        after = operator_truth(port, keys[2])
        require(after == world_before, "cognitive read-only turn changed Godot state")
        require(len(instance.event_log.load_events()) == 3
                and instance.memory_store.count() == 0
                and instance.core_execution is None,
                "cognitive module bypassed Core/Memory lifecycle")
        trace = coordinator.decision_records(f"mem_on_{seed}")
        require(len(trace) == 2 and all(
            r["admission"] == "ADMITTED" and
            r["outcome"]["status"] == "COMPLETED"
            for r in trace
        ), "missing pre-admission/verified-result trace")
        require(all("self_position" not in r["context_snapshot"]
                    for r in trace), "cognition input leaked absolute world state")
        reopen_core = build_core(
            root / f"e25a-core-{seed}",
            sources={SOURCE: vision_source_registration()},
            properties={(SUBJECT, PREDICATE): vision_digest_rule()},
        )
        reopened = E25LabCognitiveCoordinator(E24WorkingMemory(
            reopen_core, E23ObserverPort(port=port, observer_key=keys[0]),
        ))
        require(reopened.decision_records(f"mem_on_{seed}") == trace,
                "Core reopen changed recorded cognitive decision history")
        return {
            "seed": seed, "status": "PASS",
            "captured_raw_views": 3, "core_events": 3,
            "cognitive_steps_with_memory": 2,
            "cognitive_steps_without_memory": 1,
            "source_backed_followup": True,
            "rejected_mutating_request": True,
            "decision_trace_reopen_equal": True,
            "world_effects_by_cognitive_module": 0,
            "llm_used": False, "core_stage6_used": False,
            "cognitive_admission": "lab_policy_not_native_core_admission",
        }
    finally:
        finish(process, logfile)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--godot", default=None)
    ap.add_argument("--evidence-dir", default=None)
    args = ap.parse_args()
    godot = _binary(args.godot)
    out = Path(args.evidence_dir) if args.evidence_dir else Path(
        tempfile.mkdtemp(prefix="anima-e25a-")
    )
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": "anima.e25a.lab_cognitive_initiative_gate/0.1",
        "status": "E2_5A_READ_ONLY_COGNITION_PASS",
        "cases": [case(godot, seed, out) for seed in (7, 8)],
    }
    (out / "e25a-result.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
