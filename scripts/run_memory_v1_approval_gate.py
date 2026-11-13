"""M4 notebook acceptance: M3 source-backed proposal -> explicit approval -> ONE unbound Goal.

Six synthetic, isolated two-process cases. os._exit cut points are simulated
worker interruption, NOT SIGKILL/power loss. No Godot, LLM or real authorization.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile

from labs.virtual_anima_lab.python.m4_approval_bridge import (
    M4ApprovalBridge, OperatorDecision, OPERATOR, SCHEMA,
)
from scripts.run_memory_v1_goal_proposal_gate import (
    QUERY, _candidate, _core, _current_id, _gate, _prepare, _sync,
)

CASES = ("normal", "before_goal", "after_goal", "approval_resume",
         "rejected", "source_modified")
MANIFEST = "m4_manifest.json"


def _bridge(core, root):
    return M4ApprovalBridge(
        database_file=root / "m4_approval.db",
        preview_gate=_gate(core), goal_store=core.internal_state.goals,
    )


def _decision(row, case, *, action="APPROVE"):
    return OperatorDecision(
        ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
        decision_id="m4-local-operator-receipt-" + case,
        operator_ref=OPERATOR, action=action,
    )


def _effects(core):
    with sqlite3.connect(core.core_execution.world.path) as db:
        return db.execute("SELECT COUNT(*) FROM door_effects").fetchone()[0]


def _invariants(core, *, expected_goals):
    assert core.internal_state.goals.goal_count() == expected_goals
    assert core.core_decision.tasks.list_tasks() == []
    assert core.core_execution.store.list_operations() == []
    assert _effects(core) == 0
    assert core.core_execution.world.current()["state"] == "open"
    with sqlite3.connect(core.memory_store.database_file) as db:
        assert db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
    assert core.core_autonomy is None


def _goal_assertion(core, row):
    goal = core.internal_state.goals.get_goal(row["goal_id"])
    assert goal is not None
    assert goal["source"] == "m4.approved_operator"
    assert goal["priority"] == 1.0
    assert goal["description"] == "Ensure the virtual door is closed"
    assert goal["success_criterion"] == "Registered door sensor independently verifies closed"
    assert goal["status"] == "active"
    transition = core.internal_state.goals.list_goal_transitions(goal_id=row["goal_id"])
    assert len(transition) == 1
    assert transition[0]["id"] == row["transition_id"]
    assert transition[0]["from_status"] is None
    assert transition[0]["to_status"] == "active"
    assert transition[0]["source_id"] == row["ticket_id"]
    assert core.core_decision._binding(row["goal_id"]) is None
    return goal


def _unbound_never_executes(core, goal_id):
    observed = core.runtime.run_core_door_goal(goal_id)
    assert observed.outcome == "DEFERRED", observed
    assert observed.reason_code == "UNBOUND_GOAL", observed


def seed(root, case):
    if case not in CASES:
        raise ValueError("Unsupported M4 case")
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("M4 seed requires a fresh empty isolated directory")
    current = _current_id()
    core, preview, view, history_ids = _prepare(root, "request", current_id=current)
    assert core.internal_state.goals.goal_count() == 0
    bridge = M4ApprovalBridge(
        database_file=root / "m4_approval.db",
        preview_gate=preview, goal_store=core.internal_state.goals,
    )
    draft = _candidate(view)
    assert draft is not None
    row = bridge.stage(view, draft)
    assert row["status"] == "reviewed"
    assert bridge.stage(view, draft)["ticket_id"] == row["ticket_id"]
    assert core.internal_state.goals.goal_count() == 0
    if case == "normal":
        # Detect modified proposal with same origin before approving it.
        altered = dict(draft)
        altered["rationale"] = "Hostile replacement of earlier rationale"
        try:
            bridge.stage(view, altered)
        except ValueError:
            pass
        else:
            raise AssertionError("M4 accepted a changed proposal for an existing origin")

    manifest = {
        "schema": SCHEMA, "case": case, "ticket_id": row["ticket_id"],
        "fingerprint": row["fingerprint"],
        "goal_id": row["goal_id"], "transition_id": row["transition_id"],
        "history_ids": history_ids, "current_event_id": current,
        "source_event_id": draft["source_event_id"],
        "memory_id": draft["memory_id"],
        "model_used": False,
    }
    with (root / MANIFEST).open("x", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    if case == "approval_resume":
        _invariants(core, expected_goals=0)
        return {"phase": "seed", "status": "M4_SEED_PASS", "case": case}

    if case == "rejected":
        rejected = bridge.decide(_decision(row, case, action="REJECT"))
        assert rejected["status"] == "rejected"
        try:
            bridge.materialize(row["ticket_id"])
        except ValueError:
            pass
        else:
            raise AssertionError("M4 materialized rejected ticket")
        _invariants(core, expected_goals=0)
        return {"phase": "seed", "status": "M4_SEED_PASS", "case": case}

    # Approved ticket is a durable record but still no Core Goal.
    approved = bridge.decide(_decision(row, case))
    assert approved["status"] == "approved"
    assert bridge.decide(_decision(row, case))["status"] == "approved"
    assert core.internal_state.goals.goal_count() == 0
    if case == "source_modified":
        core.memory_store.update_memory(
            draft["memory_id"], content="M4_CHANGED_SOURCE_AFTER_APPROVAL"
        )
        _invariants(core, expected_goals=0)
        return {"phase": "seed", "status": "M4_SEED_PASS", "case": case}

    cut = case if case in ("before_goal", "after_goal") else None
    result = bridge.materialize(
        row["ticket_id"], cut=cut,
    )
    if cut is not None:
        raise AssertionError("M4 cut hook did not hard exit")
    assert result["id"] == row["goal_id"]
    assert bridge.get_ticket(row["ticket_id"])["status"] == "committed"
    _goal_assertion(core, row)
    _invariants(core, expected_goals=1)
    return {"phase": "seed", "status": "M4_SEED_PASS", "case": case}


def verify(root, case):
    with (root / MANIFEST).open(encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["case"] == case and saved["schema"] == SCHEMA
    core = _core(root)  # independent fresh Python interpreter and same persistent DBs
    core.runtime.wake()
    assert _sync(core.event_retrieval)["status"] == "complete"
    bridge = _bridge(core, root)
    row = bridge.get_ticket(saved["ticket_id"])
    assert row is not None
    assert row["fingerprint"] == saved["fingerprint"]
    assert row["goal_id"] == saved["goal_id"]
    assert row["transition_id"] == saved["transition_id"]
    assert saved["current_event_id"] not in saved["history_ids"]
    for event_id in saved["history_ids"]:
        raw = core.event_retrieval.get(event_id)
        assert raw["type"] == "conversation.user"
        assert raw["source"] == "user"
    before = core.internal_state.goals.goal_count()
    before_transitions = core.internal_state.goals.list_goal_transitions(
        goal_id=row["goal_id"]
    )
    if case == "normal":
        assert before == 1
        assert len(before_transitions) == 1
        assert row["status"] == "committed"
    elif case == "before_goal":
        assert before == 0 and before_transitions == []
        assert row["status"] == "approved"
    elif case == "after_goal":
        assert before == 1 and len(before_transitions) == 1
        assert row["status"] == "approved"  # deliberately missing ledger receipt
    else:
        assert before == 0 and before_transitions == []

    if case == "approval_resume":
        assert row["status"] == "reviewed"
        try:
            bridge.materialize(row["ticket_id"])
        except ValueError:
            pass
        else:
            raise AssertionError("Unapproved ticket created a Goal")
        decision = _decision(row, case)
        approved = bridge.decide(decision)
        assert approved["status"] == "approved"
        assert bridge.decide(decision)["status"] == "approved"
    if case == "rejected":
        assert row["status"] == "rejected"
        try:
            bridge.decide(_decision(row, case, action="APPROVE"))
        except ValueError:
            pass
        else:
            raise AssertionError("Rejected ticket was approved later")
        try:
            bridge.materialize(row["ticket_id"])
        except ValueError:
            pass
        else:
            raise AssertionError("Rejected ticket created a Goal")
    elif case == "source_modified":
        assert row["status"] == "approved"
        try:
            bridge.materialize(row["ticket_id"])
        except ValueError as exc:
            assert "not fresh" in str(exc)
        else:
            raise AssertionError("Changed Memory was accepted after approval")
    else:
        # Replay the identical receipt, but a changed approval cannot replace it.
        decision = _decision(row, case)
        assert bridge.decide(decision)["status"] in ("approved", "committed")
        altered = OperatorDecision(
            ticket_id=decision.ticket_id, fingerprint=decision.fingerprint,
            decision_id=decision.decision_id + "-replayed-changed",
            operator_ref=decision.operator_ref, action="APPROVE",
        )
        try:
            bridge.decide(altered)
        except ValueError:
            pass
        else:
            raise AssertionError("M4 accepted changed approval receipt")
        completed = bridge.materialize(row["ticket_id"])
        assert completed["id"] == saved["goal_id"]
        assert bridge.materialize(row["ticket_id"])["id"] == saved["goal_id"]
        final_row = bridge.get_ticket(row["ticket_id"])
        assert final_row["status"] == "committed"
        _goal_assertion(core, final_row)
        _unbound_never_executes(core, row["goal_id"])

    goals = 0 if case in ("rejected", "source_modified") else 1
    if case in ("rejected", "source_modified"):
        assert core.internal_state.goals.goal_count() == 0
    _invariants(core, expected_goals=goals)
    assert len(core.internal_state.goals.list_goal_transitions(
        goal_id=row["goal_id"]
    )) == goals
    assert core.event_retrieval.status()["status"] == "complete"
    return {
        "phase": "verify", "status": "M4_CASE_PASS", "case": case,
        "ticket_id": row["ticket_id"], "fingerprint": row["fingerprint"],
        "goal_id": row["goal_id"] if goals else None,
        "operator_approval_recorded": case not in ("approval_resume","rejected")
            or case == "approval_resume",
        "goal_count": goals, "goal_start_transition_count": goals,
        "goal_unbound": True if goals else None,
        "task_count": 0, "effect_count": 0, "knowledge_count": 0,
        "operator_identity_authenticated": False,
        "raw_provenance_checked": True,
        "index_status": "complete",
        "recovery_after_goal_before_ledger": case == "after_goal",
        "recovery_after_approval_before_goal": case == "before_goal",
        "changed_source_rejected": case == "source_modified",
        "stage6_changed": False,
        "python": platform.python_version(), "machine": platform.machine(),
    }


def _child(phase, root, case):
    cmd = [
        sys.executable, "-m", "scripts.run_memory_v1_approval_gate",
        "--phase", phase, "--root", str(root), "--case", case,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=60,
    )


def run_gate():
    rows = []
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="anima-m4-" + case + "-") as tmp:
            root = Path(tmp)
            child1 = _child("seed", root, case)
            expected = {"before_goal": 74, "after_goal": 73}.get(case, 0)
            if child1.returncode != expected:
                raise AssertionError(
                    f"M4 {case} seed rc={child1.returncode} expected {expected}; "
                    f"out={child1.stdout[-1700:]}; err={child1.stderr[-5000:]}"
                )
            child2 = _child("verify", root, case)
            if child2.returncode != 0:
                raise AssertionError(
                    f"M4 {case} verify rc={child2.returncode}: "
                    f"out={child2.stdout[-1700:]}; err={child2.stderr[-5000:]}"
                )
            payload = json.loads(child2.stdout)
            assert payload["status"] == "M4_CASE_PASS"
            rows.append(payload)
    return {
        "schema": SCHEMA, "status": "M4_APPROVED_GOAL_PASS",
        "machine": platform.machine(), "python": platform.python_version(),
        "cases": rows, "goals_total": sum(x["goal_count"] for x in rows),
        "tools_executed": 0, "tasks_created": 0,
        "production_code_changed": False,
        "llm_used": False, "godot_tested": False, "pi_tested": False,
        "true_sigkill_tested": False, "operator_identity_authenticated": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("main", "seed", "verify"),
                        default="main")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.phase != "main":
        if args.root is None or args.case is None or args.report is not None:
            parser.error("Worker mode requires --root --case and no report")
        result = seed(args.root, args.case) if args.phase == "seed" else verify(
            args.root, args.case
        )
    else:
        if args.root is not None or args.case is not None:
            parser.error("M4 --root and --case are internal-only")
        if args.report is not None:
            dest = args.report.expanduser().resolve()
            if dest.exists() or dest.is_relative_to(Path.cwd().resolve()):
                parser.error("M4 report must be new and outside repository")
        result = run_gate()
    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.report is not None:
        with args.report.expanduser().resolve().open("x", encoding="utf-8") as fp:
            fp.write(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
