"""E2.5b live Godot + real Core decision-runner acceptance (no FAST).

Deliberately uses authenticated control API, not direct step() for the
integration path. No native Stage6, goal completion explicitly LAB-only.
"""
from __future__ import annotations

import argparse
import http.client
import json
import sqlite3
import tempfile
import time
from pathlib import Path

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
        report_dir=directory, step_interval=0.25,
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
        require(state["action_admission"] == "LAB_ONLY_NOT_STAGE6",
                "prototype must not claim native Core permission")
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
        require(finished["goal_status"] == "COMPLETED_LAB_CONDITION",
                f"deterministic policy did not meet bounded goal: {finished}")
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
        with sqlite3.connect(session.memory._file) as db:
            ledger = db.execute(
                "SELECT sequence,admission,outcome,after_sample_id FROM visual_decisions "
                "ORDER BY sequence"
            ).fetchall()
        require(len(ledger) == 2
                and all(x[1] == "LAB_ADMITTED" and x[2] == "VERIFIED_EFFECT"
                        and x[3] is not None for x in ledger),
                "decision ledger not fully durable/verified")
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
            "decision_ledger_records": 2,
            "unauthenticated_control_rejected": True,
            "ui_polling_did_not_create_raw": True,
            "full_hidden_godot_truth_exposed_to_agent": False,
            "mode": "DETERMINISTIC", "llm_used": False,
            "action_authority": "LAB_NOT_STAGE6",
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
        "schema": "anima.e25b.visual_decision_gate/0.1",
        "status": "E2_5B_VISUAL_DECISION_GATE_PASS",
        "cases": [one_case(_binary(args.godot), seed, root) for seed in (7, 8)],
    }
    (root / "e25b-result.json").write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
