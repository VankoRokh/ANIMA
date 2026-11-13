"""M5 typed-binding laptop gate with no WorldPort, executor or scheduler.

Real M4 source-backed Goal, real P2 trusted sensor and P3-A CoreGoalDecision.
Six/seven independent-process cases; os._exit is not real SIGKILL/power loss.
"""
import argparse
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile

from anima.core.door_world import DOOR_SOURCE, VirtualDoorWorld
from labs.virtual_anima_lab.python.m4_approval_bridge import (
    M4ApprovalBridge, OperatorDecision as M4Decision, OPERATOR as M4_OPERATOR,
)
from labs.virtual_anima_lab.python.m5_binding_admission import (
    M5BindingAdmission, OperatorBindingDecision, OPERATOR, SCHEMA,
    restricted_core,
)
from scripts.run_memory_v1_goal_proposal_gate import (
    _candidate, _current_id, _gate, _prepare, _sync,
)

CASES = (
    "normal", "before_bind", "after_bind", "resume_approval",
    "rejected", "source_modified", "world_changed",
)
MANIFEST = "m5_manifest.json"


def _m4(core, root):
    return M4ApprovalBridge(
        database_file=root / "m4_approval.db",
        preview_gate=_gate(core), goal_store=core.internal_state.goals,
    )


def _m5(core, root):
    return M5BindingAdmission(
        database_file=root / "m5_binding.db",
        core=core, m4=_m4(core, root),
    )


def _sense(core, root):
    """Trust-bound test adapter: physical fixture read → registered P2 admission."""
    raw, tick = VirtualDoorWorld(root / "world").sense()
    result = core.core_events.ingress.admit(raw, source_ref=DOOR_SOURCE)
    assert result.status == "ACCEPTED", result
    return result.event_id, tick


def _receipt(row, case, *, action="APPROVE"):
    return OperatorBindingDecision(
        ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
        decision_id="m5-host-approval-" + case,
        operator_ref=OPERATOR, action=action,
    )


def _world_effects(root):
    with sqlite3.connect(root / "world" / "virtual_door.db") as db:
        return db.execute("SELECT COUNT(*) FROM door_effects").fetchone()[0]


def _assert_safe(core, root, *, goal_id, bound):
    assert core.core_execution is None, "M5 must never install CoreDoorExecution"
    assert core.core_autonomy is None, "M5 must never install P3-C scheduler"
    assert core.internal_state.goals.goal_count() == 1, "Only preexisting M4 Goal"
    goal = core.internal_state.goals.get_goal(goal_id)
    assert goal["status"] == "active" and goal["source"] == "m4.approved_operator"
    assert len(core.internal_state.goals.list_goal_transitions(goal_id=goal_id)) == 1
    assert (core.core_decision._binding(goal_id) is not None) == bound
    assert core.core_decision.tasks.list_tasks() == []
    assert _world_effects(root) == 0
    with sqlite3.connect(core.memory_store.database_file) as db:
        assert db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
    try:
        core.runtime.run_core_door_goal(goal_id)
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("M5 unexpectedly installed an executable Core")


def _make_m4_goal(root):
    initial, preview, view, history_ids = _prepare(
        root, "request", current_id=_current_id(),
    )
    gate = M4ApprovalBridge(
        database_file=root / "m4_approval.db",
        preview_gate=preview, goal_store=initial.internal_state.goals,
    )
    draft = _candidate(view)
    assert draft
    row = gate.stage(view, draft)
    approved = gate.decide(M4Decision(
        ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
        decision_id="m4-host-approval-before-m5", action="APPROVE",
        operator_ref=M4_OPERATOR,
    ))
    assert approved["status"] == "approved"
    goal = gate.materialize(row["ticket_id"])
    assert goal["status"] == "active"
    assert initial.core_decision._binding(goal["id"]) is None
    assert initial.core_execution.store.list_operations() == []
    assert _world_effects(root) == 0
    initial.runtime.sleep()
    return row, history_ids


def seed(root, case):
    if case not in CASES:
        raise ValueError("Unknown M5 case")
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("M5 seed requires a fresh empty directory")
    m4row, history_ids = _make_m4_goal(root)
    core = restricted_core(root)
    core.runtime.wake()
    m5 = _m5(core, root)
    event_id, tick = _sense(core, root)
    row = m5.stage(
        m4_ticket_id=m4row["ticket_id"],
        sensor_event_id=event_id, tick=tick,
    )
    assert row["status"] == "staged"
    assert m5.stage(
        m4_ticket_id=m4row["ticket_id"], sensor_event_id=event_id, tick=tick,
    )["ticket_id"] == row["ticket_id"]
    _assert_safe(core, root, goal_id=m4row["goal_id"], bound=False)
    saved = {
        "schema": SCHEMA, "case": case, "m4_ticket_id": m4row["ticket_id"],
        "m4_fingerprint": m4row["fingerprint"],
        "m5_ticket_id": row["ticket_id"], "m5_fingerprint": row["fingerprint"],
        "goal_id": m4row["goal_id"], "history_ids": history_ids,
        "initial_sensor_event_id": event_id,
    }
    with (root / MANIFEST).open("x", encoding="utf-8") as fp:
        json.dump(saved, fp, sort_keys=True, indent=2)
        fp.write("\n")

    if case == "resume_approval":
        core.runtime.sleep()
        return {"phase": "seed", "status": "M5_SEED_PASS", "case": case}
    if case == "rejected":
        assert m5.decide(_receipt(row, case, action="REJECT"))["status"] == "rejected"
        core.runtime.sleep()
        return {"phase": "seed", "status": "M5_SEED_PASS", "case": case}

    assert m5.decide(_receipt(row, case))["status"] == "approved"
    assert m5.decide(_receipt(row, case))["status"] == "approved"
    _assert_safe(core, root, goal_id=m4row["goal_id"], bound=False)
    if case == "source_modified":
        core.memory_store.update_memory(
            json.loads(m4row["draft_json"])["memory_id"],
            content="M5_CHANGED_MEMORY_AFTER_BINDING_APPROVAL",
        )
        core.runtime.sleep()
        return {"phase": "seed", "status": "M5_SEED_PASS", "case": case}
    if case == "world_changed":
        VirtualDoorWorld(root / "world").change_by_environment("closed")
        core.runtime.sleep()
        return {"phase": "seed", "status": "M5_SEED_PASS", "case": case}

    eid2, tick2 = _sense(core, root)
    result = m5.apply(
        row["ticket_id"], sensor_event_id=eid2, tick=tick2,
        cut=case if case in ("before_bind", "after_bind") else None,
    )
    if case in ("before_bind", "after_bind"):
        raise AssertionError("M5 hard-exit hook was not reached")
    assert result["goal_id"] == saved["goal_id"]
    assert m5.ticket(row["ticket_id"])["status"] == "bound"
    _assert_safe(core, root, goal_id=saved["goal_id"], bound=True)
    core.runtime.sleep()
    return {"phase": "seed", "status": "M5_SEED_PASS", "case": case}


def verify(root, case):
    with (root / MANIFEST).open(encoding="utf-8") as fp:
        saved = json.load(fp)
    assert saved["schema"] == SCHEMA and saved["case"] == case
    core = restricted_core(root)
    core.runtime.wake()
    assert _sync(core.event_retrieval)["status"] == "complete"
    m5 = _m5(core, root)
    row = m5.ticket(saved["m5_ticket_id"])
    assert row and row["origin_goal_id"] == saved["goal_id"]
    assert row["fingerprint"] == saved["m5_fingerprint"]
    m4 = m5.m4.get_ticket(saved["m4_ticket_id"])
    assert m4 and m4["status"] == "committed"
    assert m4["fingerprint"] == saved["m4_fingerprint"]
    for eid in saved["history_ids"]:
        assert core.event_retrieval.get(eid)["source"] == "user"
    assert core.core_execution is None and core.core_autonomy is None
    initial_binding = core.core_decision._binding(saved["goal_id"])
    expected_existing = case in ("normal", "after_bind")
    assert (initial_binding is not None) == expected_existing
    assert row["status"] == (
        "bound" if case == "normal" else
        "staged" if case == "resume_approval" else
        "rejected" if case == "rejected" else "approved"
    )
    if case == "resume_approval":
        try:
            e, t = _sense(core, root)
            m5.apply(row["ticket_id"], sensor_event_id=e, tick=t)
        except ValueError as exc:
            assert "separate explicit APPROVE" in str(exc)
        else:
            raise AssertionError("M5 permitted binding before operator decision")
        row = m5.decide(_receipt(row, case))
        assert row["status"] == "approved"

    if case in ("source_modified", "world_changed", "rejected"):
        event, tick = _sense(core, root)
        try:
            m5.apply(row["ticket_id"], sensor_event_id=event, tick=tick)
        except ValueError as exc:
            if case == "source_modified":
                assert "not fresh" in str(exc) or "differs" in str(exc) or "changed" in str(exc)
            elif case == "world_changed":
                assert "sensor event does not match" in str(exc) or "trusted fresh" in str(exc)
            else:
                assert "separate explicit APPROVE" in str(exc)
        else:
            raise AssertionError("M5 denied case produced a Core binding")
        final_bound = False
    else:
        receipt = _receipt(row, case)
        assert m5.decide(receipt)["status"] in ("approved", "bound")
        changed = OperatorBindingDecision(
            ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
            decision_id=receipt.decision_id + "-changed",
            operator_ref=OPERATOR, action="APPROVE",
        )
        try:
            m5.decide(changed)
        except ValueError as exc:
            assert "contradictory" in str(exc)
        else:
            raise AssertionError("M5 changed admission receipt replay was accepted")
        event, tick = _sense(core, root)
        bound = m5.apply(
            row["ticket_id"], sensor_event_id=event, tick=tick,
        )
        assert bound["goal_id"] == saved["goal_id"]
        assert m5.ticket(row["ticket_id"])["status"] == "bound"
        event2, tick2 = _sense(core, root)
        assert m5.apply(
            row["ticket_id"], sensor_event_id=event2, tick=tick2
        )["goal_id"] == saved["goal_id"]
        final_bound = True
    _assert_safe(core, root, goal_id=saved["goal_id"], bound=final_bound)
    assert core.event_retrieval.status()["status"] == "complete"
    core.runtime.sleep()
    return {
        "schema": SCHEMA, "status": "M5_CASE_PASS", "phase": "verify",
        "case": case, "goal_id": saved["goal_id"],
        "m4_ticket_id": saved["m4_ticket_id"],
        "m5_ticket_id": saved["m5_ticket_id"],
        "binding_count": int(final_bound),
        "task_count": 0, "effect_count": 0, "knowledge_count": 0,
        "goal_count": 1, "goal_start_transitions": 1,
        "registered_sensor_checked": True,
        "m4_source_checked": case != "source_modified",
        "m5_distinct_approval": case not in ("rejected", "resume_approval")
            or case == "resume_approval",
        "no_executor_installed": True,
        "auto_core_enabled": False, "operator_authenticated": False,
        "os_exit_cut_tested": case in ("before_bind", "after_bind"),
        "sigkill_tested": False, "godot_tested": False,
        "python": platform.python_version(), "machine": platform.machine(),
    }


def _child(phase, root, case):
    return subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_binding_gate",
         "--phase", phase, "--root", str(root), "--case", case],
        capture_output=True, text=True, timeout=75,
    )


def run_gate():
    cases = []
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="anima-m5-" + case + "-") as d:
            root = Path(d)
            a = _child("seed", root, case)
            expected_code = {"before_bind": 74, "after_bind": 73}.get(case, 0)
            if a.returncode != expected_code:
                raise AssertionError(
                    f"M5 seed {case}: got rc={a.returncode} expected {expected_code}; "
                    f"{a.stderr[-4500:]} {a.stdout[-1200:]}"
                )
            b = _child("verify", root, case)
            if b.returncode != 0:
                raise AssertionError(
                    f"M5 verify {case}: rc={b.returncode}; "
                    f"{b.stderr[-4500:]} {b.stdout[-1200:]}"
                )
            result = json.loads(b.stdout)
            assert result["status"] == "M5_CASE_PASS"
            cases.append(result)
    return {
        "schema": SCHEMA, "status": "M5_TYPED_BINDING_PASS",
        "python": platform.python_version(), "machine": platform.machine(),
        "cases": cases,
        "bound_goals": sum(x["binding_count"] for x in cases),
        "tasks_created": 0, "tools_executed": 0,
        "production_code_changed": False, "llm_used": False,
        "godot_tested": False, "pi_tested": False,
        "operator_authenticated": False, "true_sigkill_tested": False,
        "executor_installed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("main", "seed", "verify"), default="main")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.phase != "main":
        if args.root is None or args.case is None or args.report is not None:
            parser.error("Worker requires --root, --case, no --report")
        result = seed(args.root, args.case) if args.phase == "seed" else verify(
            args.root, args.case,
        )
    else:
        if args.root is not None or args.case is not None:
            parser.error("Root and case are internal-only")
        if args.report is not None:
            out = args.report.expanduser().resolve()
            if out.exists() or out.is_relative_to(Path.cwd().resolve()):
                parser.error("M5 report path must be new and outside the repository")
        result = run_gate()
    raw = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if args.report is not None:
        with args.report.expanduser().resolve().open("x", encoding="utf-8") as fp:
            fp.write(raw)
    print(raw, end="")


if __name__ == "__main__":
    main()
