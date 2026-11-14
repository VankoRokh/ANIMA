"""M6-A seven-case same-source execution admission and hard-exit recovery gate.

Not Godot, not production authorization, not SIGKILL/power loss. Never points
to user data: generates isolated new Core/M3–M5/VirtualDoor worlds each case.
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

from anima.core.door_world import DOOR_SOURCE, VirtualDoorWorld
from labs.virtual_anima_lab.python.m6_execution_admission import (
    M6Admission, OperatorExecutionDecision, OPERATOR, SCHEMA, observed,
)
from labs.virtual_anima_lab.python.m5_binding_admission import restricted_core
from scripts.run_memory_v1_binding_gate import _m5, seed as m5_seed

CASES = (
    "normal", "before_effect", "after_effect",
    "no_approval", "rejected", "source_modified", "world_changed",
)
MANIFEST = "m6_manifest.json"


def _m6(root):
    core = restricted_core(root)
    # M5's read-only bridge indexes any legacy wake/sleep events explicitly.
    return M6Admission(root=root, core=core, m5=_m5(core, root))


def _receipt(row, case, *, action="APPROVE"):
    return OperatorExecutionDecision(
        ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
        decision_id="m6-host-execution-approval-" + case,
        operator_ref=OPERATOR, action=action,
    )


def _effects(root):
    with sqlite3.connect(root / "world" / "virtual_door.db") as db:
        return db.execute("SELECT COUNT(*) FROM door_effects").fetchone()[0]


def _knowledge(root):
    with sqlite3.connect(root / "runtime" / "memory.db") as db:
        return db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]


def _operations(root, goal_id):
    p = root / "runtime" / "execution.db"
    with sqlite3.connect(p) as db:
        return db.execute(
            "SELECT public_id,status FROM execution_operations WHERE goal_id=?",
            (goal_id,),
        ).fetchall()


def _base_assert(root, goal_id, *, effects, goal_status, op_status=None):
    gate = _m6(root)
    assert gate.core.core_execution is None and gate.core.core_autonomy is None
    goal = gate.core.internal_state.goals.get_goal(goal_id)
    assert goal["status"] == goal_status
    assert gate.core.internal_state.goals.goal_count() == 1
    binding = gate.core.core_decision._binding(goal_id)
    assert binding is not None
    assert binding["expected_json"] == '{"type":"symbol","value":"closed"}'
    assert len(gate.core.internal_state.goals.list_goal_transitions(goal_id=goal_id)) == (
        2 if goal_status == "completed" else 1
    )
    ops = _operations(root, goal_id)
    assert len(ops) == (0 if op_status is None else 1), ops
    if op_status is not None:
        assert ops[0][1] == op_status, ops
    assert _effects(root) == effects
    assert _knowledge(root) == 0
    if effects == 0 and goal_status == "active":
        assert gate.core.internal_state.goals.get_goal(goal_id)["status"] != "completed"
    return gate


def _new_sensor(gate, root):
    return observed(gate.core, root)


def seed(root, case):
    if case not in CASES:
        raise ValueError("Unsupported M6-A case")
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("M6-A requires a fresh empty isolated directory")
    result = m5_seed(root, "normal")
    assert result["status"] == "M5_SEED_PASS"
    m5manifest = json.loads((root / "m5_manifest.json").read_text())
    gate = _m6(root)
    goal_id = m5manifest["goal_id"]
    assert gate.core.internal_state.goals.goal_count() == 1
    event_id, tick = _new_sensor(gate, root)
    row = gate.stage(
        m5_ticket_id=m5manifest["m5_ticket_id"],
        sensor_event_id=event_id, tick=tick,
    )
    assert row["status"] == "staged"
    assert gate.stage(
        m5_ticket_id=m5manifest["m5_ticket_id"],
        sensor_event_id=event_id, tick=tick,
    )["ticket_id"] == row["ticket_id"]
    with (root / MANIFEST).open("x", encoding="utf-8") as fp:
        json.dump({
            "schema": SCHEMA, "case": case, "goal_id": goal_id,
            "m4_ticket_id": m5manifest["m4_ticket_id"],
            "m5_ticket_id": m5manifest["m5_ticket_id"],
            "m6_ticket_id": row["ticket_id"],
            "m6_fingerprint": row["fingerprint"],
        }, fp, indent=2, sort_keys=True)
        fp.write("\n")

    if case == "no_approval":
        _base_assert(root, goal_id, effects=0, goal_status="active")
        return {"case": case, "phase": "seed", "status": "M6_SEED_PASS"}
    if case == "rejected":
        assert gate.decide(_receipt(row, case, action="REJECT"))["status"] == "rejected"
        _base_assert(root, goal_id, effects=0, goal_status="active")
        return {"case": case, "phase": "seed", "status": "M6_SEED_PASS"}
    assert gate.decide(_receipt(row, case))["status"] == "approved"
    assert gate.decide(_receipt(row, case))["status"] == "approved"
    _base_assert(root, goal_id, effects=0, goal_status="active")

    if case == "source_modified":
        m4 = gate.m5.m4.get_ticket(m5manifest["m4_ticket_id"])
        memory_id = json.loads(m4["draft_json"])["memory_id"]
        gate.core.memory_store.update_memory(
            memory_id, content="M6_CHANGE_AFTER_EXECUTION_APPROVAL",
        )
        return {"case": case, "phase": "seed", "status": "M6_SEED_PASS"}
    if case == "world_changed":
        VirtualDoorWorld(root / "world").change_by_environment("closed")
        return {"case": case, "phase": "seed", "status": "M6_SEED_PASS"}

    fresh_id, fresh_tick = _new_sensor(gate, root)
    executable = gate.assemble(
        row["ticket_id"], event_id=fresh_id, tick=fresh_tick,
    )
    if case in ("before_effect", "after_effect"):
        def cut_point(action, descriptor, handler):
            # Core ExecutionOperation already durable 'executing', no receipt.
            if case == "after_effect":
                result = handler.execute(
                    str(executable.core_execution.world.root),
                    action.to_dict()["arguments"], action.operation_id,
                )
                assert result == {
                    "operation_id": action.operation_id, "applied": True,
                }
            (root / "m6_cut_marker.txt").write_text(
                f"{case}:{action.operation_id}", encoding="utf-8",
            )
            os._exit(74 if case == "before_effect" else 73)
        executable.core_execution.executor._run_worker = cut_point

    turn = gate.execute_approved(row["ticket_id"], executable)
    if case != "normal":
        raise AssertionError("M6-A expected hard exit but returned")
    assert turn.outcome == "VERIFIED_SUCCESS", turn
    assert executable.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert executable.core_execution._proof(goal_id) is not None
    assert gate.ticket(row["ticket_id"])["status"] == "claimed"
    _base_assert(root, goal_id, effects=1, goal_status="completed",
                 op_status="succeeded")
    return {"case": case, "phase": "seed", "status": "M6_SEED_PASS"}


def verify(root, case):
    saved = json.loads((root / MANIFEST).read_text())
    assert saved["schema"] == SCHEMA and saved["case"] == case
    gate = _m6(root)
    row = gate.ticket(saved["m6_ticket_id"])
    assert row and row["goal_id"] == saved["goal_id"]
    assert row["fingerprint"] == saved["m6_fingerprint"]
    goal_id = saved["goal_id"]
    expected_before = {
        "normal": ("claimed", 1, "completed", "succeeded"),
        "before_effect": ("approved", 0, "active", "executing"),
        "after_effect": ("claimed", 1, "active", "executing"),
        "no_approval": ("staged", 0, "active", None),
        "rejected": ("rejected", 0, "active", None),
        "source_modified": ("approved", 0, "active", None),
        "world_changed": ("approved", 0, "active", None),
    }[case]
    assert row["status"] == expected_before[0], row
    _base_assert(root, goal_id, effects=expected_before[1],
                 goal_status=expected_before[2], op_status=expected_before[3])

    if case in ("no_approval", "rejected", "source_modified", "world_changed"):
        event_id, tick = _new_sensor(gate, root)
        try:
            gate.assemble(row["ticket_id"], event_id=event_id, tick=tick)
        except ValueError as exc:
            if case in ("no_approval", "rejected"):
                assert "execution APPROVE" in str(exc)
            elif case == "source_modified":
                assert "fresh" in str(exc) or "changed" in str(exc)
            else:
                assert "door/open" in str(exc) or "fresh" in str(exc)
        else:
            raise AssertionError("M6-A denied ticket assembled executable Core")
        _base_assert(root, goal_id, effects=0, goal_status="active")
        final = {"normal":False,"before_effect":False,"after_effect":False}.get(case,False)
        op_status = None
        permit_claimed = False
    else:
        event_id, tick = _new_sensor(gate, root)
        if case == "normal":
            # Completed Goal is not allowed to create another action; inspect only.
            assert row["operation_id"] is not None
            assert gate.core.internal_state.goals.get_goal(goal_id)["status"] == "completed"
            op_status = "succeeded"
        else:
            executable = gate.assemble(
                row["ticket_id"], event_id=event_id, tick=tick,
            )
            turn = gate.execute_approved(row["ticket_id"], executable)
            assert turn.outcome in ("DEFERRED", "VERIFIED_SUCCESS"), turn
            # A second explicit recovery turn must not produce a second Tool effect.
            # This is READ-ONLY recovery of an existing Core operation, NOT
            # a second M6 execution admission. Any attempted new Tool call
            # remains blocked by the single-use handler.
            again = executable.runtime.run_core_door_goal(goal_id)
            assert again.outcome in (
                "DEFERRED", "VERIFIED_SUCCESS", "RECOVERED_VERIFIED_SUCCESS"
            ), again
            op_status = "uncertain" if case == "before_effect" else "succeeded"
        _base_assert(
            root, goal_id, effects=0 if case == "before_effect" else 1,
            goal_status="active" if case == "before_effect" else "completed",
            op_status=op_status,
        )
        final = case != "before_effect"
        permit_claimed = case != "before_effect"
        if permit_claimed:
            from anima.execution.store import ExecutionStore
            ops = _operations(root, goal_id)
            assert len(ops) == 1
            assert gate.ticket(row["ticket_id"])["operation_id"] == ops[0][0]
        if final:
            chk = gate.core.core_events.ingress
            # Canonical independent P2 sensor must prove result, never Tool receipt.
            from anima.core.door_world import DOOR_SUBJECT, DOOR_PREDICATE
            snap = chk.read_belief(DOOR_SUBJECT, DOOR_PREDICATE)
            assert snap["value"] == {"type": "symbol", "value": "closed"}
    # The second process saw the same world and no duplicate physical action.
    assert _effects(root) == (1 if final else 0)
    return {
        "schema": SCHEMA, "case": case, "phase": "verify",
        "status": "M6_CASE_PASS",
        "goal_id": goal_id, "m4_ticket_id": saved["m4_ticket_id"],
        "m5_ticket_id": saved["m5_ticket_id"],
        "m6_ticket_id": row["ticket_id"],
        "goal_completed": final, "permit_claimed": permit_claimed,
        "world_effect_count": 1 if final else 0,
        "tool_operations": 0 if op_status is None else 1,
        "operation_status": op_status,
        "no_duplicate_effect": True,
        "independent_sensor_only": True,
        "auto_core_enabled": False,
        "operator_authenticated": False, "godot_tested": False,
        "sigkill_tested": False,
        "python": platform.python_version(), "machine": platform.machine(),
    }


def _child(phase, root, case):
    return subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_execution_gate",
         "--phase", phase, "--root", str(root), "--case", case],
        text=True, capture_output=True, timeout=70,
    )


def run_gate():
    cases = []
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="anima-m6a-" + case + "-") as temp:
            root = Path(temp)
            a = _child("seed", root, case)
            expected = {"before_effect": 74, "after_effect": 73}.get(case, 0)
            if a.returncode != expected:
                raise AssertionError(
                    f"M6 {case} seed rc={a.returncode} expected={expected} "
                    f"\n{a.stderr[-4600:]}\n{a.stdout[-1000:]}"
                )
            b = _child("verify", root, case)
            if b.returncode != 0:
                raise AssertionError(
                    f"M6 {case} verify rc={b.returncode} "
                    f"\n{b.stderr[-4600:]}\n{b.stdout[-1000:]}"
                )
            item = json.loads(b.stdout)
            assert item["status"] == "M6_CASE_PASS"
            cases.append(item)
    return {
        "schema": SCHEMA, "status": "M6_EXECUTION_ADMISSION_PASS",
        "python": platform.python_version(), "machine": platform.machine(),
        "cases": cases, "effect_total": sum(x["world_effect_count"] for x in cases),
        "production_code_changed": False, "llm_used": False,
        "godot_tested": False, "pi_tested": False,
        "true_sigkill_tested": False, "operator_authenticated": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=("main", "seed", "verify"), default="main")
    ap.add_argument("--case", choices=CASES)
    ap.add_argument("--root", type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)
    if args.phase == "main":
        if args.root is not None or args.case is not None:
            ap.error("M6 --case and --root are internal-only")
        if args.report is not None:
            out = args.report.expanduser().resolve()
            if out.exists() or out.is_relative_to(Path.cwd().resolve()):
                ap.error("M6 report must be new and outside repository")
        result = run_gate()
    else:
        if args.case is None or args.root is None or args.report is not None:
            ap.error("M6 worker requires --case and --root but no --report")
        result = seed(args.root, args.case) if args.phase == "seed" else verify(
            args.root, args.case,
        )
    raw = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if args.report is not None:
        with args.report.expanduser().resolve().open("x", encoding="utf-8") as fp:
            fp.write(raw)
    print(raw, end="")


if __name__ == "__main__":
    main()
