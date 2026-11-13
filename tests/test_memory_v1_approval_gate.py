"""M4 negative / restart acceptance: an approved proposal is NOT action authority."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from anima.cognition.proposals import CognitiveProposal, ProposalKind, ProposalValidator
from labs.virtual_anima_lab.python.m4_approval_bridge import (
    M4ApprovalBridge, OperatorDecision, OPERATOR,
)
from scripts.run_memory_v1_approval_gate import (
    CASES, _decision, _goal_assertion, _invariants, _unbound_never_executes,
    run_gate, seed, verify,
)
from scripts.run_memory_v1_goal_proposal_gate import (
    _candidate, _current_id, _prepare,
)

ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path, kind="request"):
    core, preview, view, _ = _prepare(
        tmp_path, kind, current_id=_current_id(),
    )
    bridge = M4ApprovalBridge(
        database_file=tmp_path / "m4_approval.db",
        preview_gate=preview, goal_store=core.internal_state.goals,
    )
    return core, bridge, view, _candidate(view)


def test_m4_independent_two_process_six_cases():
    gate = run_gate()
    assert gate["status"] == "M4_APPROVED_GOAL_PASS"
    assert [row["case"] for row in gate["cases"]] == list(CASES)
    assert [row["goal_count"] for row in gate["cases"]] == [1, 1, 1, 1, 0, 0]
    assert gate["goals_total"] == 4
    assert gate["tools_executed"] == 0
    assert gate["tasks_created"] == 0
    assert gate["operator_identity_authenticated"] is False
    assert gate["true_sigkill_tested"] is False
    for row in gate["cases"]:
        assert row["status"] == "M4_CASE_PASS"
        assert row["goal_start_transition_count"] == row["goal_count"]
        assert row["task_count"] == row["effect_count"] == row["knowledge_count"] == 0
        assert row["raw_provenance_checked"]
    assert gate["cases"][1]["recovery_after_approval_before_goal"]
    assert gate["cases"][2]["recovery_after_goal_before_ledger"]
    assert gate["cases"][5]["changed_source_rejected"]


@pytest.mark.parametrize("case", ["normal", "approval_resume", "rejected", "source_modified"])
def test_m4_can_recover_same_persisted_ticket_in_new_core(tmp_path, case):
    root = tmp_path / case
    before = seed(root, case)
    assert before["status"] == "M4_SEED_PASS"
    after = verify(root, case)
    assert after["status"] == "M4_CASE_PASS"
    assert after["task_count"] == 0
    assert after["effect_count"] == 0


def test_m4_cannot_materialize_without_operator_decision(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    row = bridge.stage(view, draft)
    assert row["status"] == "reviewed"
    with pytest.raises(ValueError, match="explicit prior APPROVE"):
        bridge.materialize(row["ticket_id"])
    _invariants(core, expected_goals=0)


def test_m4_approval_receipt_exact_fingerprint_and_replay(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    row = bridge.stage(view, draft)
    assert bridge.stage(view, draft)["ticket_id"] == row["ticket_id"]
    good = _decision(row, "manual")
    assert bridge.decide(good)["status"] == "approved"
    assert bridge.decide(good)["status"] == "approved"
    invalid = OperatorDecision(
        ticket_id=row["ticket_id"], fingerprint="f" * 64,
        operator_ref=OPERATOR, decision_id=good.decision_id, action="APPROVE",
    )
    with pytest.raises(ValueError, match="exact proposal fingerprint"):
        bridge.decide(invalid)
    changed = OperatorDecision(
        ticket_id=row["ticket_id"], fingerprint=good.fingerprint,
        operator_ref=OPERATOR, decision_id="m4-edited-decision", action="REJECT",
    )
    with pytest.raises(ValueError, match="conflicting decision"):
        bridge.decide(changed)
    _invariants(core, expected_goals=0)


def test_m4_cannot_restage_same_source_with_altered_draft(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    first = bridge.stage(view, draft)
    changed = dict(draft)
    changed["rationale"] = "new content after review"
    with pytest.raises(ValueError, match="existing ticket differs"):
        bridge.stage(view, changed)
    assert bridge.get_ticket(first["ticket_id"])["status"] == "reviewed"
    _invariants(core, expected_goals=0)


@pytest.mark.parametrize("kind", ["state_only", "conflict"])
def test_m4_does_not_stage_unqualified_m3_proposals(tmp_path, kind):
    core, bridge, view, draft = _fixture(tmp_path, kind=kind)
    with pytest.raises(ValueError, match="REVIEW_REQUIRED"):
        bridge.stage(view, draft)
    _invariants(core, expected_goals=0)


def test_m4_denies_extra_role_and_tool_fields(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    for field in ("role", "tool", "priority", "approval", "goal_id"):
        with pytest.raises(ValueError, match="REVIEW_REQUIRED"):
            bridge.stage(view, {**draft, field: "operator"})
    _invariants(core, expected_goals=0)


def test_m4_rejects_wrong_host_operator(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    row = bridge.stage(view, draft)
    with pytest.raises(ValueError, match="allowlist"):
        OperatorDecision(
            ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
            decision_id="x", operator_ref="fake.operator", action="APPROVE",
        )
    with pytest.raises(TypeError, match="typed operator decision"):
        bridge.decide({"ticket_id": row["ticket_id"], "action": "APPROVE"})
    _invariants(core, expected_goals=0)


def test_m4_refuses_stale_index_between_stage_and_approval(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    row = bridge.stage(view, draft)
    core.runtime.user_input("new unsynced event after M4 review")
    assert core.event_retrieval.status()["status"] == "partial"
    with pytest.raises(ValueError, match="not fresh"):
        bridge.decide(_decision(row, "stale"))
    assert bridge.get_ticket(row["ticket_id"])["status"] == "reviewed"
    _invariants(core, expected_goals=0)


def test_m4_refuses_memory_change_after_approval(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    row = bridge.stage(view, draft)
    bridge.decide(_decision(row, "fresh"))
    core.memory_store.update_memory(draft["memory_id"], content="M4_EVIDENCE_CHANGED")
    with pytest.raises(ValueError, match="not fresh"):
        bridge.materialize(row["ticket_id"])
    _invariants(core, expected_goals=0)


def test_m4_rejects_colliding_goal_id_and_never_overwrites(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    row = bridge.stage(view, draft)
    bridge.decide(_decision(row, "collision"))
    other = core.internal_state.goals.create_goal(
        source="test.other", priority=0,
        description="different goal", success_criterion="not M4",
        reason="collision guard test", public_id=row["goal_id"],
    )
    assert other["description"] == "different goal"
    with pytest.raises(ValueError, match="occupied"):
        bridge.materialize(row["ticket_id"])
    assert core.internal_state.goals.goal_count() == 1
    assert core.internal_state.goals.get_goal(row["goal_id"])["description"] == "different goal"
    assert core.core_decision.tasks.list_tasks() == []
    assert core.core_execution.store.list_operations() == []


def test_m4_materialization_is_replay_safe_and_unbound(tmp_path):
    core, bridge, view, draft = _fixture(tmp_path)
    row = bridge.stage(view, draft)
    approved = bridge.decide(_decision(row, "replay"))
    assert approved["status"] == "approved"
    first = bridge.materialize(row["ticket_id"])
    second = bridge.materialize(row["ticket_id"])
    assert first["id"] == second["id"]
    assert bridge.get_ticket(row["ticket_id"])["status"] == "committed"
    _goal_assertion(core, row)
    _unbound_never_executes(core, row["goal_id"])
    _invariants(core, expected_goals=1)


def test_m4_prod_stage6_is_unchanged():
    validator = ProposalValidator()
    for kind in (ProposalKind.PROPOSE_TASK, ProposalKind.PROPOSE_ACTION,
                 ProposalKind.REQUEST_CONTEXT):
        decision = validator.validate(CognitiveProposal(kind, {"x": "y"}))
        assert not decision.accepted
        assert decision.reason == "proposal_kind_not_enabled"


def test_m4_report_existing_path_is_not_overwritten(tmp_path):
    existing = tmp_path / "immutable.json"
    existing.write_text("PRESERVE", encoding="utf-8")
    p = subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_approval_gate",
         "--report", str(existing)],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert p.returncode != 0
    assert "report must be new" in p.stderr
    assert existing.read_text(encoding="utf-8") == "PRESERVE"


def test_m4_refuses_seed_into_existing_folder(tmp_path):
    folder = tmp_path / "real"
    folder.mkdir()
    record = folder / "user-data.txt"
    record.write_text("UNTOUCHED", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh empty"):
        seed(folder, "normal")
    assert record.read_text(encoding="utf-8") == "UNTOUCHED"
