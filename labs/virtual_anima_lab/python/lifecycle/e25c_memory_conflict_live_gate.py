"""E2.5c live real-Godot memory advantage and stale-memory correction.

2 seeds × 2 randomized-free paired history conditions × 2 scenarios.
Each pair receives the SAME seeded prehistory before first policy action.
Only trusted operator fixture knows the relocated crate target coordinates;
the actor gets E2.3 egocentric Raw and E2.4 remembered sensor evidence.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from labs.virtual_anima_lab.python.lab_client import LabClient, LabRejected, PROTOCOL_V2
from .visual_runner import VisualRunnerError, launch
from .visual_runner_live_gate import request, until
from .world_smoke import _binary


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def run_case(godot, seed, scenario, memory_enabled, root, *, core_stage6=False):
    condition = "memory_on" if memory_enabled else "memory_off"
    case_root = root / f"{scenario}-seed{seed}-{condition}"
    session, service, process, logfile = launch(
        godot=godot, seed=seed, headless=True,
        report_dir=case_root, step_interval=0.22,
        scenario=scenario, memory_enabled=memory_enabled, core_stage6=core_stage6,
    )
    port, token = service.server.server_address[1], service.token
    try:
        status, initial = request(port, token, "/state")
        require(status == 200, "visual controller unavailable")
        require(initial["scenario"] == scenario
                and initial["memory_enabled"] is memory_enabled
                and initial["steps"] == 0, "uncontrolled trial startup")
        authority = "CORE_STAGE2_TASK_STAGE6" if core_stage6 else "LAB_ONLY_NOT_STAGE6"
        require(initial["action_admission"] == authority
                and initial["mode"] == "DETERMINISTIC"
                and not initial["model_connected"], "misrepresented FAST or Core authority")
        require(initial["latest_sample"] is not None, "trial prehistory not captured")
        remembered = {x["entity_ref"] for x in initial["memory"]}
        if memory_enabled:
            require("lab.item.crate" in remembered, "familiarization not remembered")
        else:
            require("lab.item.crate" not in remembered,
                    "memory-off condition leaked previous crate")
        if scenario == "relocated":
            # The agent executor credential must never be able to call the
            # operator-only intervention, even though both share loopback.
            view = session.memory.raw_evidence(initial["latest_sample"]).as_dict()
            with LabClient(session.world_port, role="agent", protocol=PROTOCOL_V2) as client:
                try:
                    client.call(
                        "relocate_item", auth=session.executor_key,
                        fixture_id="agent_attempt",
                        world_instance_id=view["world_instance_id"],
                        epoch=view["epoch"], expected_revision=view["revision"],
                        expected_sample_id=view["sample_id"],
                        at={"x": 4, "y": 5},
                    )
                except LabRejected as error:
                    require(error.error == "FORBIDDEN", "fixture leak to agent role")
                else:
                    raise AssertionError("agent invoked operator-only fixture")
            pose = session.pose.reconstruct()
            require(len(pose["verified_external_changes"]) == 1,
                    "relocation did not reconcile as a non-actor world change")
            require(pose["poses"][-1]["local_right_steps"] == 0,
                    "operator fixture moved ANIMA's local position")
        # Starting live continuous policy from identical historical views.
        code, response = request(port, token, "/run", method="POST")
        require(code == 202, "RUN not accepted")
        finished = until(
            port, token,
            lambda s: s.get("goal_status") != "ACTIVE" and not s.get("busy"),
            seconds=18,
        )
        require(finished["goal_status"] == "COMPLETED_LAB_CONDITION",
                f"agent failed to complete bounded task: {finished}")
        expected_steps = (
            2 if (scenario == "familiar" and memory_enabled) else
            4 if (scenario == "familiar") else
            4 if memory_enabled else 2
        )
        require(finished["steps"] == expected_steps,
                f"expected {expected_steps} decision actions, got {finished['steps']}")
        assert finished["last_choice"]["basis"] == "current_raw"
        assert finished["last_choice"]["operation"] == "world.step"
        require(not finished["run_enabled"], "goal did not pause")
        require(finished["last_outcome"]["status"] == "VERIFIED_EFFECT",
                "forward approach step not actually executed")
        hypotheses = finished["hypotheses"]
        if scenario == "relocated" and memory_enabled:
            require(len(hypotheses) == 1, "failed to detect stale memory location")
            require(hypotheses[0]["status"] == "REOBSERVED_AFTER_CONFLICT",
                    "old hypothesis was not revised after new direct observation")
            require(hypotheses[0]["prior_event_id"] != hypotheses[0]["suspected_event_id"],
                    "hypothesis and contradiction were not separate source events")
            require(hypotheses[0]["revised_event_id"] is not None,
                    "no new Core event for relocated crate")
            require(all("cell" not in str(h) and '"x"' not in str(h)
                        for h in hypotheses),
                    "hidden coordinates exposed in policy hypothesis")
        else:
            require(hypotheses == [], "spurious memory contradiction")

        with sqlite3.connect(session.memory._file) as db:
            if core_stage6:
                decisions = db.execute(
                    "SELECT sequence,source_event_id,reason,'CORE_STAGE6',outcome,"
                    "after_sample_id,proposal_json FROM visual_core_decisions ORDER BY sequence"
                ).fetchall()
                linked_operations = db.execute(
                    "SELECT operation_id,pre_sample_id,source_event_id FROM "
                    "visual_core_decisions ORDER BY sequence"
                ).fetchall()
                require(db.execute("SELECT count(*) FROM visual_decisions").fetchone()[0] == 0,
                        "Core mode wrote lab-only admission records")
            else:
                decisions = db.execute(
                    "SELECT sequence,source_event_id,reason,admission,outcome,"
                    "after_sample_id,proposal_json FROM visual_decisions ORDER BY sequence"
                ).fetchall()
                require(db.execute("SELECT count(*) FROM visual_core_decisions").fetchone()[0] == 0,
                        "LAB mode wrote Core decision trace")
            stored_hypotheses = db.execute(
                "SELECT count(*) FROM visual_hypotheses"
            ).fetchone()[0]
        require(len(decisions) == expected_steps
                and all(x[3] == ("CORE_STAGE6" if core_stage6 else "LAB_ADMITTED")
                        and x[4] == "VERIFIED_EFFECT" and x[5] for x in decisions),
                "decisions not durably admitted before action / verified after")
        if core_stage6:
            require(finished["core_goal_status"] == "completed", "Core Goal not complete")
            tasks = session.core_gateway.tasks.list_tasks(goal_id=session.core_goal_id)
            operations = session.core_gateway.store.list_operations(goal_id=session.core_goal_id)
            require(len(tasks) == expected_steps and all(t.status == "completed" for t in tasks),
                    "canonical Task count/status mismatch")
            require(len(operations) == expected_steps
                    and all(op["status"] == "succeeded" for op in operations),
                    "canonical execution count/status mismatch")
            require({op["id"] for op in operations} == {row[0] for row in linked_operations},
                    "decision trace not bound to exact canonical operations")
            for op_id, sample_id, event_id in linked_operations:
                action = session.core_gateway.store.load_action(op_id)
                spec = session.core_gateway.store.load_verification_spec(op_id)
                require(action.operation_id == op_id and spec is not None
                        and spec.criterion_kind == "world.egocentric_transition"
                        and spec.parameters["before_sample_id"] == sample_id
                        and spec.parameters["source_event_id"] == event_id,
                        "canonical Action/Spec not bound to pre-action Raw")
        reasons = [x[2] for x in decisions]
        require(
            reasons[0] == ("CHECK_REMEMBERED_TARGET" if memory_enabled
                           else "SEARCH_NEW_VIEW"),
            f"memory condition did not change first reason: {reasons}",
        )
        if scenario == "relocated" and memory_enabled:
            require("PRIOR_LOCATION_NOT_REOBSERVED" in reasons,
                    "policy did not register contradiction during active turn")
            require("SEARCH_AFTER_MEMORY_CONFLICT" in reasons,
                    "policy continued trusting disconfirmed geometry")
            require(stored_hypotheses == 1, "hypothesis not durable")
        require(
            not any("self_position" in x[6] or '"at"' in x[6] for x in decisions),
            "operator coordinates entered action proposal",
        )
        if scenario == "relocated" and memory_enabled:
            with sqlite3.connect(session.memory._file) as db:
                original = db.execute(
                    "SELECT prior_event_id FROM visual_hypotheses"
                ).fetchone()[0]
                db.execute(
                    "UPDATE visual_hypotheses SET prior_event_id='ev_forged'"
                )
            try:
                session.hypotheses()
            except VisualRunnerError:
                pass
            else:
                raise AssertionError("forged hypothesis provenance was accepted")
            finally:
                with sqlite3.connect(session.memory._file) as db:
                    db.execute(
                        "UPDATE visual_hypotheses SET prior_event_id=?",
                        (original,),
                    )
            require(session.hypotheses()[0]["prior_event_id"] == original,
                    "hypothesis proof did not recover after restoring DB")
        effects = session.pose.reconstruct()["verified_transitions"]
        require(len(effects) == expected_steps + 2,
                "missing verified prehistory/action transitions")
        require(all(x["verified_clocks"] for x in effects),
                "unverified world transition used")
        require(len(session.memory._core.event_log.load_events()) ==
                expected_steps + (4 if scenario == "relocated" else 3),
                "Core Raw/EventLog count mismatched actual views")
        require(session.memory._core.memory_store.count() == 0,
                "working observations promoted without Knowledge permission")
        require(session.memory._core.core_execution is None,
                "generic CoreExecution must remain unbound in this lab")
        # UI requests must not mutate Core/sensor after stop.
        stable = len(session.memory._core.event_log.load_events())
        for _ in range(3):
            status, _ = request(port, token, "/state")
            require(status == 200, "state unavailable")
        require(len(session.memory._core.event_log.load_events()) == stable,
                "telemetry GET secretly executed an observation")
        return {
            "seed": seed, "scenario": scenario, "memory_enabled": memory_enabled,
            "status": "PASS", "policy_actions": len(decisions),
            "first_reason": reasons[0], "all_reasons": reasons,
            "goal_status": finished["goal_status"],
            "confirmed_actor_effects": len(effects),
            "recorded_stale_hypotheses": stored_hypotheses,
            "llm_used": False,
            "action_authority": authority,
            "stage6_operations": expected_steps if core_stage6 else 0,
            "world_change_operator_only": scenario == "relocated",
            "hidden_operator_coordinates_in_agent_context": False,
        }
    finally:
        service.stop()
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()
            process.wait(timeout=5)
        logfile.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--godot", default=None)
    ap.add_argument("--evidence-dir", default=None)
    ap.add_argument("--core-stage6", action="store_true")
    args = ap.parse_args()
    root = (Path(args.evidence_dir) if args.evidence_dir else
            Path(tempfile.mkdtemp(prefix="anima-e25c-")))
    root.mkdir(parents=True, exist_ok=True)
    godot = _binary(args.godot)
    cases = []
    for seed in (7, 8):
        for scenario in ("familiar", "relocated"):
            for memory_enabled in (True, False):
                cases.append(run_case(godot, seed, scenario, memory_enabled, root,
                                      core_stage6=args.core_stage6))
    comparisons = []
    for seed in (7, 8):
        for scenario in ("familiar", "relocated"):
            on = next(x for x in cases if x["seed"] == seed
                      and x["scenario"] == scenario and x["memory_enabled"])
            off = next(x for x in cases if x["seed"] == seed
                       and x["scenario"] == scenario and not x["memory_enabled"])
            comparisons.append({
                "seed": seed, "scenario": scenario,
                "memory_on_actions": on["policy_actions"],
                "memory_off_actions": off["policy_actions"],
                "difference_on_minus_off": (
                    on["policy_actions"] - off["policy_actions"]
                ),
                "interpretation": (
                    "remembered location helps when still valid"
                    if scenario == "familiar"
                    else "stale memory initially misleads but is revised"
                ),
            })
            require(
                (on["policy_actions"] < off["policy_actions"])
                if scenario == "familiar" else
                (on["policy_actions"] > off["policy_actions"]),
                "paired policy-memory ablation result contradicts scenario",
            )
    result = {
        "schema": "anima.e25c.memory_conflict_gate/0.1",
        "status": ("E2_5C_INTEGRATED_MEMORY_STAGE6_PASS" if args.core_stage6
                   else "E2_5C_PAIRED_MEMORY_CONFLICT_PASS"),
        "cases": cases, "comparisons": comparisons,
        "limitations": {
            "scripted_preparation_not_policy_behavior": True,
            "lab_admission_not_stage6": not args.core_stage6,
            "only_two_seeded_grid_cases": True,
            "operator_fixture_is_trusted_test_intervention": True,
            "stale_is_suspected_not_confirmed_absence": True,
            "no_llm_used": True,
        },
    }
    (root / "e25c-results.json").write_text(
        json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
