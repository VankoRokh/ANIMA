"""M5 negative gates: 2nd approval, genuine P2 sensor, immutable action, no tools."""
from pathlib import Path
import json
import subprocess
import sys
from types import MappingProxyType

import pytest

from anima.cognition.proposals import CognitiveProposal, ProposalKind, ProposalValidator
from anima.core.door_world import VirtualDoorWorld, DOOR_SUBJECT
from anima.execution.contracts import ActionSpec
from labs.virtual_anima_lab.python.m4_approval_bridge import (
    M4ApprovalBridge, OPERATOR as M4_OPERATOR,
)
from labs.virtual_anima_lab.python.m5_binding_admission import (
    M5BindingAdmission, OperatorBindingDecision, OPERATOR, REGISTRY_KEY,
    restricted_core,
)
from scripts.run_memory_v1_binding_gate import (
    CASES, _m4, _m5, _make_m4_goal, _receipt, _sense, _assert_safe,
    run_gate, seed, verify,
)
from scripts.run_memory_v1_integrated_decision_gate import _core

ROOT = Path(__file__).resolve().parents[1]


def _fixture(root):
    row, history = _make_m4_goal(root)
    core = restricted_core(root)
    core.runtime.wake()
    gate = _m5(core, root)
    evidence, tick = _sense(core, root)
    ticket = gate.stage(
        m4_ticket_id=row["ticket_id"],
        sensor_event_id=evidence, tick=tick,
    )
    return core, gate, row, ticket, history


def test_m5_seven_isolated_two_process_replay_cases():
    result = run_gate()
    assert result["status"] == "M5_TYPED_BINDING_PASS"
    assert [case["case"] for case in result["cases"]] == list(CASES)
    assert [case["binding_count"] for case in result["cases"]] == [
        1, 1, 1, 1, 0, 0, 0,
    ]
    assert result["bound_goals"] == 4
    assert result["tools_executed"] == result["tasks_created"] == 0
    assert result["executor_installed"] is False
    assert result["operator_authenticated"] is False
    for row in result["cases"]:
        assert row["status"] == "M5_CASE_PASS"
        assert row["goal_count"] == 1
        assert row["goal_start_transitions"] == 1
        assert row["effect_count"] == row["task_count"] == row["knowledge_count"] == 0
        assert row["no_executor_installed"] is True
        assert row["auto_core_enabled"] is False


@pytest.mark.parametrize("case", ["normal", "resume_approval", "rejected", "world_changed"])
def test_m5_can_reopen_same_real_goal_with_restricted_core(tmp_path, case):
    root = tmp_path / case
    start = seed(root, case)
    assert start["status"] == "M5_SEED_PASS"
    result = verify(root, case)
    assert result["status"] == "M5_CASE_PASS"


def test_m5_refuses_execution_capable_core_even_with_valid_m4(tmp_path):
    m4row, _ = _make_m4_goal(tmp_path)
    executable = _core(tmp_path)
    executable.runtime.wake()
    with pytest.raises(ValueError, match="refuses executor"):
        M5BindingAdmission(
            database_file=tmp_path / "m5_binding.db",
            core=executable, m4=_m4(executable, tmp_path),
        )
    executable.runtime.sleep()


def test_m5_rejects_unregistered_sensor_id_and_fake_memories(tmp_path):
    core, gate, m4row, ticket, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match="sensor event not found"):
        gate.stage(
            m4_ticket_id=m4row["ticket_id"],
            sensor_event_id="ev_" + "0" * 36, tick=40,
        )
    with pytest.raises(ValueError, match="committed M4"):
        gate.stage(
            m4_ticket_id="m4_" + "f" * 64,
            sensor_event_id=json.loads(ticket["snapshot_json"])["sensor"]["event_id"],
            tick=json.loads(ticket["snapshot_json"])["sensor"]["tick"],
        )
    _assert_safe(core, tmp_path, goal_id=m4row["goal_id"], bound=False)


def test_m5_no_binding_without_second_operator_approval(tmp_path):
    core, gate, m4row, ticket, _ = _fixture(tmp_path)
    assert ticket["status"] == "staged"
    event_id, tick = _sense(core, tmp_path)
    with pytest.raises(ValueError, match="separate explicit APPROVE"):
        gate.apply(ticket["ticket_id"], sensor_event_id=event_id, tick=tick)
    with pytest.raises(TypeError, match="typed separate host"):
        gate.decide({"action": "APPROVE", "ticket_id": ticket["ticket_id"]})
    with pytest.raises(ValueError, match="allowlist"):
        OperatorBindingDecision(
            ticket_id=ticket["ticket_id"],
            fingerprint=ticket["fingerprint"],
            decision_id="fake", operator_ref=M4_OPERATOR, action="APPROVE",
        )
    _assert_safe(core, tmp_path, goal_id=m4row["goal_id"], bound=False)


def test_m5_changed_receipt_and_fingerprint_are_denied(tmp_path):
    core, gate, m4row, ticket, _ = _fixture(tmp_path)
    authorized = _receipt(ticket, "unit")
    assert gate.decide(authorized)["status"] == "approved"
    assert gate.decide(authorized)["status"] == "approved"
    with pytest.raises(ValueError, match="exact binding fingerprint"):
        gate.decide(OperatorBindingDecision(
            ticket_id=ticket["ticket_id"], fingerprint="f" * 64,
            decision_id=authorized.decision_id, operator_ref=OPERATOR, action="APPROVE",
        ))
    with pytest.raises(ValueError, match="contradictory"):
        gate.decide(OperatorBindingDecision(
            ticket_id=ticket["ticket_id"], fingerprint=ticket["fingerprint"],
            decision_id="receipt-substituted", operator_ref=OPERATOR, action="REJECT",
        ))
    _assert_safe(core, tmp_path, goal_id=m4row["goal_id"], bound=False)


def test_m5_rejects_sensor_world_already_closed(tmp_path):
    m4row, _ = _make_m4_goal(tmp_path)
    core = restricted_core(tmp_path)
    core.runtime.wake()
    gate = _m5(core, tmp_path)
    VirtualDoorWorld(tmp_path / "world").change_by_environment("closed")
    ev, tick = _sense(core, tmp_path)
    with pytest.raises(ValueError, match="sensor event does not match"):
        gate.stage(m4_ticket_id=m4row["ticket_id"], sensor_event_id=ev, tick=tick)
    _assert_safe(core, tmp_path, goal_id=m4row["goal_id"], bound=False)


def test_m5_trusted_action_registry_cannot_be_swapped_after_approval(tmp_path):
    core, gate, m4row, ticket, _ = _fixture(tmp_path)
    gate.decide(_receipt(ticket, "registry"))
    core.core_decision.actions = MappingProxyType({
        REGISTRY_KEY: ActionSpec(
            candidate_id="different",
            tool="world.door.close", tool_version="0.1",
            arguments={"subject_ref": DOOR_SUBJECT},
        ),
    })
    event, tick = _sense(core, tmp_path)
    with pytest.raises(ValueError, match="system action registry was changed"):
        gate.apply(ticket["ticket_id"], sensor_event_id=event, tick=tick)
    _assert_safe(core, tmp_path, goal_id=m4row["goal_id"], bound=False)


def test_m5_rejects_duplicate_stage_with_new_sensor_and_same_goal(tmp_path):
    core, gate, m4row, ticket, _ = _fixture(tmp_path)
    ev2, tick2 = _sense(core, tmp_path)
    with pytest.raises(ValueError, match="cannot replace previously reviewed binding"):
        gate.stage(
            m4_ticket_id=m4row["ticket_id"],
            sensor_event_id=ev2, tick=tick2,
        )
    _assert_safe(core, tmp_path, goal_id=m4row["goal_id"], bound=False)


def test_m5_refuses_changed_historical_memory_after_m5_approval(tmp_path):
    core, gate, m4row, ticket, _ = _fixture(tmp_path)
    gate.decide(_receipt(ticket, "history"))
    original = json.loads(m4row["draft_json"])["memory_id"]
    core.memory_store.update_memory(original, content="M5_CHANGED_RAW_MEMORY_CONTENT")
    ev, tick = _sense(core, tmp_path)
    with pytest.raises(ValueError, match="not fresh"):
        gate.apply(ticket["ticket_id"], sensor_event_id=ev, tick=tick)
    _assert_safe(core, tmp_path, goal_id=m4row["goal_id"], bound=False)


def test_m5_conflicting_core_binding_fails_closed(tmp_path):
    core, gate, m4row, ticket, _ = _fixture(tmp_path)
    gate.decide(_receipt(ticket, "binding"))
    from anima.core.goal_decision import GoalCriterion
    from anima.core.door_world import DOOR_PREDICATE
    # Existing Core can represent a conflicting allowed property value.
    assert core.core_decision.bind(GoalCriterion(
        goal_id=m4row["goal_id"], subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE,
        expected={"type": "symbol", "value": "open"},
    ))
    ev, tick = _sense(core, tmp_path)
    with pytest.raises(ValueError, match="existing Core binding is different"):
        gate.apply(ticket["ticket_id"], sensor_event_id=ev, tick=tick)
    assert core.core_decision.tasks.list_tasks() == []
    assert core.core_execution is None


def test_m5_binding_replay_will_not_execute_when_sensor_changes(tmp_path):
    core, gate, m4row, ticket, _ = _fixture(tmp_path)
    gate.decide(_receipt(ticket, "drift"))
    ev, tick = _sense(core, tmp_path)
    assert gate.apply(ticket["ticket_id"], sensor_event_id=ev, tick=tick)
    VirtualDoorWorld(tmp_path / "world").change_by_environment("closed")
    ev2, t2 = _sense(core, tmp_path)
    with pytest.raises(ValueError, match="sensor event does not match"):
        gate.apply(ticket["ticket_id"], sensor_event_id=ev2, tick=t2)
    _assert_safe(core, tmp_path, goal_id=m4row["goal_id"], bound=True)


def test_m5_prod_stage6_model_proposal_validator_unchanged():
    validator = ProposalValidator()
    for kind in (ProposalKind.PROPOSE_ACTION, ProposalKind.PROPOSE_TASK,
                 ProposalKind.REQUEST_CONTEXT):
        result = validator.validate(CognitiveProposal(kind, {"tool": "anything"}))
        assert result.accepted is False
        assert result.reason == "proposal_kind_not_enabled"


def test_m5_existing_report_refused_without_side_effects(tmp_path):
    destination = tmp_path / "protected.json"
    destination.write_text("KEEP", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_binding_gate",
         "--report", str(destination)],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode != 0
    assert "report path must be new" in proc.stderr
    assert destination.read_text(encoding="utf-8") == "KEEP"


def test_m5_refuses_seed_into_existing_directory(tmp_path):
    d = tmp_path / "protected"
    d.mkdir()
    sentinel = d / "private.txt"
    sentinel.write_text("KEEP", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh empty"):
        seed(d, "normal")
    assert sentinel.read_text(encoding="utf-8") == "KEEP"
