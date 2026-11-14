#!/usr/bin/env python3
"""M6-B2.3 real Godot 4.7.2 acceptance; one canonical M4 Goal, isolated target.

Each case has a fresh M5/M6-B1/M6-B2 data root and a separate live Godot world.
Core seed / execute / cold recovery run in separate processes. Crash cuts use
os._exit in the Core process; the SAME Godot server remains alive. No real
SIGKILL, power-loss, local-process authentication, or Pi claim is made.

From the repo root:
  .venv/bin/python -m labs.virtual_anima_lab.python.m6b2_live_gate
Optional: --godot /path/to/Godot_v4.7.2-stable_linux.x86_64 --report /tmp/m6b2.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile

from anima.core.door_world import DOOR_SUBJECT
from labs.virtual_anima_lab.python.m6b1_godot_migration import (
    M6B1Migration, OperatorMigrationDecision, OPERATOR as B1_OPERATOR,
)
from labs.virtual_anima_lab.python.m6b2_godot_execution import (
    M6B2Admission, OperatorGodotExecutionDecision, OPERATOR as B2_OPERATOR,
    SCHEMA,
)
from labs.virtual_anima_lab.python.core_port import VALDoorPort
from labs.virtual_anima_lab.python.m5_binding_admission import restricted_core
from labs.virtual_anima_lab.python.p6_core_crash_recovery_gate import (
    ROOT, call, effect_events, free_port, start_godot, stop_child,
)
from scripts.run_memory_v1_binding_gate import _m5, seed as m5_seed

CASES = (
    "normal", "unapproved", "rejected", "source_modified",
    "target_binding_modified", "sample_corrupt", "world_restarted",
    "world_revision_changed", "before_effect", "after_effect",
)
CUT_CODES = {"before_effect": 74, "after_effect": 73}
MANIFEST = "m6b2_manifest.json"


def _gate(root: Path, port: int) -> M6B2Admission:
    return M6B2Admission.reopen(root, port_num=port)


def _receipt(row, *, action="APPROVE"):
    return OperatorGodotExecutionDecision(
        ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
        decision_id="m6b2-live-" + action,
        operator_ref=B2_OPERATOR, action=action,
    )


def _manifest(root):
    saved = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    assert saved["schema"] == SCHEMA and saved["case"] in CASES
    return saved


def _counts(gate, goal_id):
    target = gate._target()
    return {
        "original_goal_count": gate.b1.m5.core.internal_state.goals.goal_count(),
        "original_task_count": len(gate.b1.m5.core.core_decision.tasks.list_tasks()),
        "target_task_count": len(target.decision.tasks.list_tasks()),
        "target_operation_count": len(target.operations.list_operations()),
        "target_proof": (
            target.execution._proof(goal_id) is not None
            if target.execution is not None else
            _target_proof(gate.target_root, goal_id)
        ),
    }


def _target_proof(target_root, goal_id):
    with sqlite3.connect(target_root / "core_work.db") as db:
        row = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='core_world_proofs'"
        ).fetchone()
        if not row:
            return False
        return db.execute(
            "SELECT 1 FROM core_world_proofs WHERE goal_id=?", (goal_id,),
        ).fetchone() is not None


def seed(root: Path, case: str, port: int):
    assert case in CASES
    assert root.is_dir() and not any(root.iterdir())
    assert m5_seed(root, "normal")["status"] == "M5_SEED_PASS"
    original = _m5(restricted_core(root), root)
    port_adapter = VALDoorPort(root / "p6_port", port=port)
    b1 = M6B1Migration(root=root, m5=original, port=port_adapter)
    old = json.loads((root / "m5_manifest.json").read_text(encoding="utf-8"))
    source = b1.stage(old["m5_ticket_id"])
    assert b1.decide(OperatorMigrationDecision(
        ticket_id=source["ticket_id"], fingerprint=source["fingerprint"],
        decision_id="m6b2-live-mapping", action="APPROVE",
        operator_ref=B1_OPERATOR,
    ))["status"] == "approved"
    gate = M6B2Admission(root=root, b1=b1)
    row = gate.stage(source["ticket_id"])
    assert row["status"] == "staged"
    if case != "unapproved":
        action = "REJECT" if case == "rejected" else "APPROVE"
        assert gate.decide(_receipt(row, action=action))["status"] == (
            "rejected" if action == "REJECT" else "approved"
        )
    saved = {
        "schema": SCHEMA, "case": case, "goal_id": row["goal_id"],
        "b1_ticket_id": source["ticket_id"],
        "ticket_id": row["ticket_id"], "fingerprint": row["fingerprint"],
        "world": json.loads(row["snapshot_json"])["world"],
    }
    (root / MANIFEST).write_text(
        json.dumps(saved, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    assert _counts(gate, row["goal_id"]) == {
        "original_goal_count": 1, "original_task_count": 0,
        "target_task_count": 0, "target_operation_count": 0,
        "target_proof": False,
    }
    assert gate.b1.m5.core.core_execution is None
    assert gate.b1.m5.core.core_autonomy is None
    return {"phase": "seed", "status": "M6B2_SEED_PASS", "case": case}


def _mutate(gate, case, row):
    if case == "source_modified":
        original = json.loads(
            (gate.root / "m5_manifest.json").read_text(encoding="utf-8")
        )
        m4 = gate.b1.m5.m4.get_ticket(original["m4_ticket_id"])
        mid = json.loads(m4["draft_json"])["memory_id"]
        gate.b1.m5.core.memory_store.update_memory(
            mid, content="M6B2_HISTORY_TAMPER_AFTER_APPROVAL",
        )
    if case == "target_binding_modified":
        with sqlite3.connect(gate.target_root / "core_work.db") as db:
            db.execute(
                "UPDATE core_goal_bindings SET expected_json=? WHERE goal_id=?",
                ('{"type":"symbol","value":"open"}', row["goal_id"]),
            )
    if case == "sample_corrupt":
        seq = json.loads(row["snapshot_json"])["admission_sample"]["lab_sample"]
        with sqlite3.connect(gate.port.database_file) as db:
            db.execute(
                "UPDATE sample_log SET world_revision=world_revision+1 "
                "WHERE sample_seq=?", (seq,),
            )


def exercise(root: Path, case: str, port: int):
    manifest = _manifest(root)
    assert manifest["case"] == case
    gate = _gate(root, port)
    row = gate.get(manifest["ticket_id"])
    assert row is not None and row["fingerprint"] == manifest["fingerprint"]
    if case in ("source_modified", "target_binding_modified", "sample_corrupt"):
        _mutate(gate, case, row)
    if case in (
        "unapproved", "rejected", "source_modified",
        "target_binding_modified", "sample_corrupt", "world_restarted",
        "world_revision_changed",
    ):
        try:
            gate.assemble(row["ticket_id"])
        except (ValueError, RuntimeError) as exc:
            denied = type(exc).__name__ + ": " + str(exc)
        else:
            raise AssertionError(f"M6-B2 {case} incorrectly assembled an executor")
        assert _counts(gate, row["goal_id"])["target_task_count"] == 0
        assert _counts(gate, row["goal_id"])["target_operation_count"] == 0
        return {
            "phase": "exercise", "status": "M6B2_DENIAL_PASS",
            "case": case, "denial": denied, "world_effect_count": 0,
        }
    target = gate.assemble(row["ticket_id"])
    assert target.execution is not None and gate.b1.m5.core.core_execution is None
    if case in CUT_CODES:
        def cut(action, descriptor, handler):
            if case == "after_effect":
                effect = handler.execute(
                    str(target.execution.world.root),
                    action.to_dict()["arguments"], action.operation_id,
                )
                assert effect == {
                    "operation_id": action.operation_id, "applied": True,
                }
            (root / "m6b2_crash_marker.txt").write_text(
                f"{case}:{action.operation_id}\n", encoding="utf-8",
            )
            os._exit(CUT_CODES[case])
        target.execution.executor._run_worker = cut
        gate.execute_approved(row["ticket_id"], target)
        raise AssertionError("M6-B2 intended process cut was not reached")
    turn = gate.execute_approved(row["ticket_id"], target)
    assert turn.outcome == "VERIFIED_SUCCESS", turn
    assert turn.operation_id and turn.evidence_event_id
    assert gate.get(row["ticket_id"])["status"] == "claimed"
    assert gate.b1.m5.core.internal_state.goals.get_goal(row["goal_id"])[
        "status"
    ] == "completed"
    counts = _counts(gate, row["goal_id"])
    assert counts["original_task_count"] == 0
    assert counts["target_task_count"] == counts["target_operation_count"] == 1
    assert counts["target_proof"]
    # B1 is an OPEN-door preflight; replaying it after the effect must fail.
    try:
        gate.b1.revalidate(row["b1_ticket_id"])
    except (ValueError, RuntimeError):
        pass
    else:
        raise AssertionError("B1 preflight was incorrectly valid after effect")
    return {
        "phase": "exercise", "status": "M6B2_EFFECT_PASS", "case": case,
        "goal_id": row["goal_id"], "operation_id": turn.operation_id,
        "evidence_event_id": turn.evidence_event_id,
        "outcome": turn.outcome, "counts": counts,
    }


def recover(root: Path, case: str, port: int):
    manifest = _manifest(root)
    assert case in ("normal", "before_effect", "after_effect")
    gate = _gate(root, port)
    row = gate.get(manifest["ticket_id"])
    assert row is not None
    target = gate.assemble(row["ticket_id"])
    turn = gate.execute_approved(row["ticket_id"], target)
    expected = "UNCERTAIN_EFFECT_NOT_RETRIED" if case == "before_effect" else None
    if expected is not None:
        assert turn.outcome == "DEFERRED" and turn.reason_code == expected, turn
    else:
        assert turn.outcome in (
            "RECOVERED_VERIFIED_SUCCESS", "VERIFIED_SUCCESS",
        ), turn
    goal = gate.b1.m5.core.internal_state.goals.get_goal(row["goal_id"])
    ops = target.operations.list_operations(goal_id=row["goal_id"])
    assert len(ops) == 1 and target.decision.tasks.list_tasks()
    counts = _counts(gate, row["goal_id"])
    assert counts["original_goal_count"] == 1 and counts["original_task_count"] == 0
    assert counts["target_task_count"] == counts["target_operation_count"] == 1
    if case == "before_effect":
        assert row["status"] == "approved"
        assert goal["status"] == "active" and ops[0]["status"] == "uncertain"
        assert not counts["target_proof"]
    else:
        assert gate.get(row["ticket_id"])["status"] == "claimed"
        assert goal["status"] == "completed" and ops[0]["status"] == "succeeded"
        assert counts["target_proof"]
    return {
        "phase": "recover", "status": "M6B2_RECOVERY_PASS",
        "case": case, "goal_id": row["goal_id"],
        "operation_id": ops[0]["id"], "goal_status": goal["status"],
        "operation_status": ops[0]["status"],
        "outcome": turn.outcome, "counts": counts,
    }


def _worker(phase, root, case, port):
    return subprocess.run([
        sys.executable, "-m", "labs.virtual_anima_lab.python.m6b2_live_gate",
        "--phase", phase, "--root", str(root), "--case", case,
        "--port", str(port),
    ], cwd=ROOT, capture_output=True, text=True, timeout=110)


def _json_result(result, expected_status):
    if result.returncode != 0:
        raise AssertionError(
            f"M6-B2 worker rc={result.returncode}: "
            + result.stderr[-4500:] + "\n" + result.stdout[-2000:]
        )
    value = json.loads(result.stdout)
    assert value["status"] == expected_status, value
    return value


def run_case(godot, scratch, case):
    port = free_port()
    root = scratch / ("case_" + case)
    root.mkdir()
    log_path = scratch / ("godot_" + case + ".log")
    world = None
    with log_path.open("wb") as log:
        try:
            world = start_godot(godot, port, log)
            before = call(port, "agent", "hello")["data"]
            assert before["scenario"] == "p6_door"
            assert effect_events(port) == []
            _json_result(_worker("seed", root, case, port), "M6B2_SEED_PASS")
            assert effect_events(port) == [], "M6-B2 seed caused an effect"
            if case == "world_restarted":
                stop_child(world)
                world = None
                world = start_godot(godot, port, log)
                after_restart = call(port, "agent", "hello")["data"]
                assert after_restart["world_instance_id"] != before["world_instance_id"]
            elif case == "world_revision_changed":
                # Test-only operator modifies and restores the *visible* state.
                # Final door=open, but revised history must invalidate B2 pin.
                initial_revision = call(port, "agent", "observe")["data"][
                    "world_revision"
                ]
                assert call(port, "operator", "set_door", open=False)["data"][
                    "open"
                ] is False
                assert call(port, "operator", "set_door", open=True)["data"][
                    "open"
                ] is True
                final_revision = call(port, "agent", "observe")["data"][
                    "world_revision"
                ]
                assert final_revision > initial_revision
                assert effect_events(port) == []
            worker = _worker("exercise", root, case, port)
            if case in CUT_CODES:
                assert worker.returncode == CUT_CODES[case], (
                    f"M6-B2 cut did not trigger: {worker.returncode} "
                    + worker.stderr[-3000:] + worker.stdout[-1000:]
                )
                marker = (root / "m6b2_crash_marker.txt").read_text(
                    encoding="utf-8",
                ).strip()
                assert marker.startswith(case + ":")
                op_id = marker.split(":", 1)[1]
                with sqlite3.connect(root / "m6b2_target" / "execution.db") as db:
                    op = db.execute(
                        "SELECT status FROM execution_operations WHERE public_id=?",
                        (op_id,),
                    ).fetchone()
                assert op == ("executing",), (case, op)
                with sqlite3.connect(root / "m6b2_admission.db") as db:
                    permit = db.execute(
                        "SELECT status,operation_id FROM m6b2_tickets"
                    ).fetchone()
                assert permit == (
                    ("claimed", op_id) if case == "after_effect"
                    else ("approved", None)
                ), permit
                effects_before = effect_events(port)
                assert len(effects_before) == (1 if case == "after_effect" else 0)
                result = _json_result(
                    _worker("recover", root, case, port), "M6B2_RECOVERY_PASS",
                )
                assert result["operation_id"] == op_id
            elif case == "normal":
                result = _json_result(worker, "M6B2_EFFECT_PASS")
                assert len(effect_events(port)) == 1
                again = _json_result(
                    _worker("recover", root, case, port), "M6B2_RECOVERY_PASS",
                )
                assert result["operation_id"] == again["operation_id"]
                result["recovery"] = again
            else:
                result = _json_result(worker, "M6B2_DENIAL_PASS")
            effects = effect_events(port)
            expected_effects = 1 if case in ("normal", "after_effect") else 0
            assert len(effects) == expected_effects, (case, effects)
            sensed = call(port, "agent", "observe")["data"]
            doors = [
                item["typed_value"]["value"] for item in sensed["readings"]
                if item["subject_ref"] == "lab.door.01"
            ]
            assert doors == (["closed"] if expected_effects else ["open"]), doors
            if case != "world_restarted":
                assert call(port, "agent", "hello")["data"]["world_instance_id"] == (
                    before["world_instance_id"]
                )
            return {
                "case": case, "status": "M6B2_CASE_PASS",
                "world_effect_count": len(effects),
                "goal_id": _manifest(root)["goal_id"],
                "world_instance_id": before["world_instance_id"],
                "result": result,
                "original_goal_count": 1,
                "operator_authenticated": False,
            }
        except BaseException:
            log.flush()
            print(
                f"M6-B2 {case} Godot tail:\n"
                + log_path.read_text(errors="replace")[-4500:],
                file=sys.stderr,
            )
            raise
        finally:
            stop_child(world)


def run_all(godot, *, only_case=None):
    cases = (only_case,) if only_case else CASES
    with tempfile.TemporaryDirectory(prefix="anima-m6b2-live-") as tmp:
        records = [run_case(godot, Path(tmp), case) for case in cases]
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    return {
        "schema": SCHEMA, "status": "M6B2_GODOT_LIVE_GATE_PASS",
        "commit": sha, "machine": platform.machine(),
        "python": platform.python_version(), "godot_version": "4.7.2",
        "cases": records,
        "world_effect_total": sum(x["world_effect_count"] for x in records),
        "godot_tested": True, "pi_tested": False, "operator_authenticated": False,
        "true_sigkill_tested": False, "power_loss_tested": False,
        "production_firewall": False, "llm_used": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=("main", "seed", "exercise", "recover"),
                   default="main")
    p.add_argument("--case", choices=CASES)
    p.add_argument("--port", type=int)
    p.add_argument("--root", type=Path)
    p.add_argument("--godot", type=Path, default=(
        Path.home() / ".local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
    ))
    p.add_argument("--report", type=Path)
    args = p.parse_args(argv)
    if args.phase != "main":
        if args.root is None or args.case is None or args.port is None or args.report:
            p.error("worker requires --root --case --port, not --report")
        value = (
            seed(args.root, args.case, args.port) if args.phase == "seed" else
            exercise(args.root, args.case, args.port) if args.phase == "exercise" else
            recover(args.root, args.case, args.port)
        )
    else:
        if args.root is not None or args.port is not None:
            p.error("worker arguments are internal")
        binary = args.godot.expanduser().resolve()
        if not binary.is_file():
            p.error(f"Godot not found: {binary}")
        version = subprocess.run(
            [str(binary), "--headless", "--version"],
            capture_output=True, text=True, timeout=12,
        )
        if version.returncode != 0 or not version.stdout.startswith("4.7.2"):
            p.error("M6-B2 requires Godot 4.7.2")
        if args.report:
            dest = args.report.expanduser().resolve()
            if dest.exists() or dest.is_relative_to(ROOT):
                p.error("Report must be new and outside the repository")
        value = run_all(binary, only_case=args.case)
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.report:
        with args.report.expanduser().resolve().open("x", encoding="utf-8") as out:
            out.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
