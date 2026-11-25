"""E2.5c real Godot + Stage2 Goal/Task + Stage6 SandboxExecutor acceptance.

Deliberately uses authenticated control API, not direct step() for the
integration path. No native Stage6, goal completion explicitly LAB-only.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from uuid import uuid4
import http.client
import json
import sqlite3
import tempfile
import time
from pathlib import Path

from anima.core.spatial_action_gate import CoreSpatialAdmissionError, SpatialSourceProof
from anima.execution.contracts import ActionSpec, ExecutionAction, thaw
from anima.execution.sandbox import ExecutionRejectedError

from .visual_runner import launch, CONTROL_SCHEMA
from .world_smoke import _binary


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def request(port, token, route, method="GET", *, authorized=True, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    headers = {"X-ANIMA-Control-Key": token if authorized else "invalid"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        connection.request(method, route, body=body, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        return response.status, data
    finally:
        connection.close()


def until(port, token, predicate, *, seconds=12):
    expiry = time.monotonic() + seconds
    last = {}
    while time.monotonic() < expiry:
        status, state = request(port, token, "/state")
        require(status == 200, f"control status {status}")
        last = state
        if predicate(state):
            return state
        time.sleep(0.06)
    raise AssertionError(f"runner never reached expected state: {last}")


def one_case(binary, seed, root):
    directory = root / f"seed-{seed}"
    session, service, process, logfile = launch(
        godot=binary, seed=seed, headless=True,
        report_dir=directory, step_interval=0.25, core_stage6=True,
    )
    port = service.server.server_address[1]
    token = service.token
    try:
        status, ignored = request(port, token, "/state", authorized=False)
        require(status == 403, "unauthenticated state was exposed")
        status, ignored = request(port, token, "/step", method="POST", authorized=False)
        require(status == 403, "unauthenticated step was accepted")
        status, ignored = request(port, token, "/step", method="POST", body='{"secret":"x"}')
        require(status == 400, "control API accepted arbitrary body")
        status, state = request(port, token, "/state")
        require(status == 200 and state["schema"] == CONTROL_SCHEMA, "bad telemetry schema")
        require(state["mode"] == "DETERMINISTIC" and not state["model_connected"],
                "fabricated FAST status")
        require(state["action_admission"] == "CORE_STAGE2_TASK_STAGE6",
                "native Core admission not active")
        require(state["core_goal_id"] is not None
                and state["core_goal_status"] == "active",
                "visual Goal not created in Stage2")
        require(state["steps"] == 0 and state["latest_sample"] is None,
                "UI polling must not create Raw sensor observations")
        # MEMORY toggle: operator preference, not model behavior or world effect.
        status, _ = request(port, token, "/memory", method="POST")
        require(status == 202, "memory toggle not accepted")
        state = until(port, token, lambda s: s["memory_enabled"] is False)
        require(state["steps"] == 0, "memory toggle caused a world action")
        status, _ = request(port, token, "/memory", method="POST")
        require(status == 202, "memory re-enable refused")
        until(port, token, lambda s: s["memory_enabled"] is True)

        # STEP should observe north, decide to rotate, observe east. Neither
        # world truth nor old absolute coordinates should enter telemetry.
        status, _ = request(port, token, "/step", method="POST")
        require(status == 202, "STEP wasn't queued")
        first = until(port, token, lambda s: s.get("steps") == 1 and not s.get("busy"))
        require(first["goal_status"] == "ACTIVE", "goal terminated after one turn")
        require(first["last_choice"]["operation"] == "world.turn",
                "agent did not choose an information-seeking turn")
        require(first["last_outcome"]["status"] == "VERIFIED_EFFECT",
                "first action failed independent readback+Core Raw")
        require(any(x["entity_ref"] == "lab.item.crate"
                    for x in first["agent_view"]), "next sensor did not see crate")
        require(first["relative_pose"]["relative_heading_quadrants"] == 1,
                "viewpoint pose not advanced by verified turn")
        for field in ("world_truth", "self_position", "actor", "global_map"):
            require(field not in first, f"operator truth leaked in decision telemetry: {field}")

        # RUN performs the next *decision* based on changed Raw and then
        # pauses automatically after an admitted, verified approach step.
        status, _ = request(port, token, "/run", method="POST")
        require(status == 202, "RUN refused")
        finished = until(
            port, token,
            lambda s: s.get("goal_status") != "ACTIVE" and not s.get("busy"),
        )
        require(finished["goal_status"] == "COMPLETED_LAB_CONDITION"
                and finished["core_goal_status"] == "completed",
                f"Core Stage2 Goal was not verified: {finished}")
        require(finished["steps"] == 2, "expected 2 agent-chosen actions")
        require(finished["last_choice"]["operation"] == "world.step",
                "agent did not decide on forward approach from current Raw")
        require(finished["last_choice"]["basis"] == "current_raw",
                "movement came from nonobserved or hidden target")
        require(finished["relative_pose"]["local_right_steps"] == 1,
                "verified forward step did not change local pose")
        require(finished["run_enabled"] is False, "runner didn't stop at goal")
        require(finished["last_outcome"]["status"] == "VERIFIED_EFFECT",
                "step not verified")
        require(len(session.memory._core.event_log.load_events()) == 3,
                "UI / polling / decisions duplicated Core events")
        require(session.memory._core.memory_store.count() == 0,
                "visual runner bypassed episodic memory authority")
        require(session.memory._core.core_execution is None,
                "runner falsely used Stage6 CoreExecution")
        poses = session.pose.reconstruct()
        require(len(poses["verified_transitions"]) == 2,
                "not all world actions verified against agent-only Raw")
        require(session.core_gateway is not None, "missing Core spatial gateway")
        goal = session.core_gateway.goals.get_goal(session.core_goal_id)
        require(goal["status"] == "completed", "Stage2 Goal not terminal")
        tasks = session.core_gateway.tasks.list_tasks(goal_id=session.core_goal_id)
        require(len(tasks) == 2 and all(t.status == "completed" for t in tasks),
                "Stage6 Tasks not completed after verified effects")
        operations = session.core_gateway.store.list_operations(
            goal_id=session.core_goal_id,
        )
        require(len(operations) == 2
                and all(op["status"] == "succeeded" for op in operations),
                "Stage6 execution operations not durably successful")
        for operation in operations:
            action = session.core_gateway.store.load_action(operation["id"])
            spec = session.core_gateway.store.load_verification_spec(operation["id"])
            require(spec is not None
                    and spec.criterion_kind == "world.egocentric_transition"
                    and action.operation_id == operation["id"],
                    "Stage6 Action/VerificationSpec missing or unbound")
        with sqlite3.connect(session.memory._file) as db:
            old_lab = db.execute(
                "SELECT COUNT(*) FROM visual_decisions",
            ).fetchone()[0]
        require(old_lab == 0, "Core run still used bypass lab decision ledger")
        # A further STEP cannot continue a completed goal.
        status, _ = request(port, token, "/step", method="POST")
        require(status == 202, "completed goal step must respond safely")
        time.sleep(0.3)
        require(request(port, token, "/state")[1]["steps"] == 2,
                "completed goal accepted another world effect")
        return {
            "seed": seed, "result": "PASS",
            "core_backed_views": 3, "agent_selected_world_actions": 2,
            "readback_plus_raw_verified_transitions": 2,
            "stage6_task_count": 2, "stage6_operations": 2,
            "core_goal_terminal": True,
            "unauthenticated_control_rejected": True,
            "ui_polling_did_not_create_raw": True,
            "full_hidden_godot_truth_exposed_to_agent": False,
            "mode": "DETERMINISTIC", "llm_used": False,
            "action_authority": "CORE_STAGE2_TASK_STAGE6",
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


def identity_negative_case(binary, root):
    """CA-01 / L02: cancelled operation cannot borrow another active Goal/Task."""
    session, service, process, logfile = launch(
        godot=binary, seed=314159, headless=True,
        report_dir=root / "ca01-l02", step_interval=0.25, core_stage6=True,
    )
    try:
        with session.lock:
            gate = session.core_gateway
            record = session.memory.observe_and_record()
            before = SpatialSourceProof(
                sample_id=record.sample_id, core_event_id=record.core_event_id,
                raw_json=session.memory.raw_evidence(record.sample_id).canonical_json,
            )
            second_goal = gate.core.internal_state.create_goal(
                source="lab.visual", source_id="ca01-l02-second",
                priority=1.0, description="Independent active goal",
                success_criterion="Independent verified transition", reason="CA-01",
            )
            first = gate.prepare(
                goal_id=session.core_goal_id, proof=before,
                tool_kind="world.turn", direction="right", reason="CA-01 first",
            )
            second = gate.prepare(
                goal_id=second_goal["id"], proof=before,
                tool_kind="world.turn", direction="left", reason="CA-01 second",
            )
            gate.goals.transition_goal(
                first.goal_id, to_status="cancelled", reason="L02 cancellation",
            )
            forged = replace(first, goal_id=second.goal_id, task_id=second.task_id)
            for candidate in (first, forged):
                try:
                    gate.execute_once(candidate, proof=before)
                except CoreSpatialAdmissionError:
                    pass
                else:
                    raise AssertionError("CA-01 admitted cancelled action")
            after_record = session.memory.observe_and_record()
            a = json.loads(before.raw_json)
            b = json.loads(session.memory.raw_evidence(
                after_record.sample_id,
            ).canonical_json)
            require((a["world_instance_id"], a["epoch"], a["tick"], a["revision"])
                    == (b["world_instance_id"], b["epoch"], b["tick"], b["revision"]),
                    "CA-01 rejection changed world clocks")
            require(b["sample_seq"] > a["sample_seq"], "missing fresh Raw")
            require(gate.goals.get_goal(first.goal_id)["status"] == "cancelled",
                    "cancelled Goal changed")
            require(gate.goals.get_goal(second.goal_id)["status"] == "active",
                    "unrelated Goal changed")
            for candidate in (first, second):
                require(gate.store.get_operation(candidate.operation_id)["status"]
                        == "prepared", "rejected Operation changed")
                require(gate.tasks.get_task(candidate.task_id).status == "active",
                        "rejected Task changed")
            return {
                "seed": 314159, "result": "PASS",
                "cancelled_action_rejected": True, "cross_wired_action_rejected": True,
                "tick_delta": b["tick"] - a["tick"],
                "revision_delta": b["revision"] - a["revision"],
                "both_operations_prepared": True, "both_tasks_active": True,
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


def admission_negative_case(binary, root):
    """CA-02 / L01: a persisted orphan intent is not spatial authority."""
    session, service, process, logfile = launch(
        godot=binary, seed=314159, headless=True,
        report_dir=root / "ca02-l01", step_interval=0.25, core_stage6=True,
    )
    try:
        with session.lock:
            gate = session.core_gateway
            record = session.memory.observe_and_record()
            before = SpatialSourceProof(
                sample_id=record.sample_id, core_event_id=record.core_event_id,
                raw_json=session.memory.raw_evidence(record.sample_id).canonical_json,
            )
            valid = gate.prepare(
                goal_id=session.core_goal_id, proof=before,
                tool_kind="world.turn", direction="right", reason="CA-02 control",
            )
            candidate = ActionSpec(
                candidate_id=valid.action.candidate_id, tool=valid.action.tool,
                tool_version=valid.action.tool_version, arguments=thaw(valid.action.arguments),
            )
            orphan = ExecutionAction.from_spec(
                candidate, registry=gate.registry, created_at=valid.action.created_at,
                goal_id=valid.goal_id.rsplit("_", 1)[0] + "_" + str(uuid4()),
                persistent_task_id=valid.task_id.rsplit("_", 1)[0] + "_" + str(uuid4()),
            )
            gate.store.create_operation(orphan, registry=gate.registry)
            for action in (orphan, valid.action):
                try:
                    gate.executor.execute(action)
                except ExecutionRejectedError:
                    pass
                else:
                    raise AssertionError("CA-02 direct executor admitted effect")
                require(gate.store.get_operation(action.operation_id)["status"]
                        == "prepared", "rejected operation changed")
            after = session.memory.observe_and_record()
            a = json.loads(before.raw_json)
            b = json.loads(session.memory.raw_evidence(after.sample_id).canonical_json)
            require((a["world_instance_id"], a["epoch"], a["tick"], a["revision"])
                    == (b["world_instance_id"], b["epoch"], b["tick"], b["revision"]),
                    "CA-02 direct executor changed world clocks")
            require(b["sample_seq"] > a["sample_seq"], "missing fresh Raw")
            require(gate.goals.get_goal(orphan.goal_id) is None, "orphan Goal exists")
            require(gate.tasks.get_task(orphan.persistent_task_id) is None, "orphan Task exists")
            require(gate.tasks.get_task(valid.task_id).status == "active",
                    "valid Task changed without admission")
            return {
                "seed": 314159, "result": "PASS",
                "orphan_rejected": True, "direct_valid_intent_rejected": True,
                "both_operations_prepared": True,
                "tick_delta": b["tick"] - a["tick"],
                "revision_delta": b["revision"] - a["revision"],
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", default=None)
    parser.add_argument("--evidence-dir", default=None)
    args = parser.parse_args()
    root = Path(args.evidence_dir) if args.evidence_dir else Path(
        tempfile.mkdtemp(prefix="anima-visual-test-")
    )
    root.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "anima.e25c.core_stage6_visual_gate/0.1",
        "status": "E2_5C_CORE_STAGE6_VISUAL_PASS",
        "cases": [one_case(_binary(args.godot), seed, root) for seed in (7, 8)],
        "identity_negative": identity_negative_case(_binary(args.godot), root),
        "admission_negative": admission_negative_case(_binary(args.godot), root),
    }
    (root / "e25b-result.json").write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
