"""M6-A: single-use third permission and guarded Core action do not leak authority."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from anima.agent.executor import SandboxToolError
from anima.core.door_world import DOOR_SUBJECT, DOOR_TOOL, DOOR_VERSION
from labs.virtual_anima_lab.python.m6_execution_admission import (
    M6Admission, M6GuardedDoorHandler, OperatorExecutionDecision,
    OPERATOR, guarded_handlers, observed,
)
from scripts.run_memory_v1_execution_gate import (
    CASES, _effects, _m6, _new_sensor, _receipt, run_gate, seed, verify,
)
from scripts.run_memory_v1_binding_gate import seed as m5_seed

ROOT = Path(__file__).resolve().parents[1]


def _stage(root):
    assert m5_seed(root, "normal")["status"] == "M5_SEED_PASS"
    manifest = json.loads((root / "m5_manifest.json").read_text())
    gate = _m6(root)
    eid, tick = observed(gate.core, root)
    ticket = gate.stage(
        m5_ticket_id=manifest["m5_ticket_id"],
        sensor_event_id=eid, tick=tick,
    )
    return gate, ticket, manifest


def test_m6_seven_cases_cross_process_recovery():
    data = run_gate()
    assert data["status"] == "M6_EXECUTION_ADMISSION_PASS"
    assert [x["case"] for x in data["cases"]] == list(CASES)
    assert [x["world_effect_count"] for x in data["cases"]] == [1, 0, 1, 0, 0, 0, 0]
    assert [x["goal_completed"] for x in data["cases"]] == [True, False, True, False, False, False, False]
    assert data["effect_total"] == 2
    for row in data["cases"]:
        assert row["status"] == "M6_CASE_PASS"
        assert row["no_duplicate_effect"]
        assert row["independent_sensor_only"]
        assert row["auto_core_enabled"] is False
    assert data["godot_tested"] is False
    assert data["operator_authenticated"] is False


@pytest.mark.parametrize("case", ["normal", "no_approval", "rejected", "source_modified", "world_changed"])
def test_m6_persistent_admission_roundtrip(tmp_path, case):
    root = tmp_path / case
    start = seed(root, case)
    assert start["status"] == "M6_SEED_PASS"
    check = verify(root, case)
    assert check["status"] == "M6_CASE_PASS"


def test_m6_cannot_assemble_before_third_approval(tmp_path):
    gate, ticket, manifest = _stage(tmp_path)
    eid, tick = observed(gate.core, tmp_path)
    with pytest.raises(ValueError, match="execution APPROVE"):
        gate.assemble(ticket["ticket_id"], event_id=eid, tick=tick)
    assert gate.core.core_execution is None
    assert _effects(tmp_path) == 0


def test_m6_explicit_third_receipt_binds_exact_fingerprint(tmp_path):
    gate, ticket, manifest = _stage(tmp_path)
    receipt = _receipt(ticket, "test")
    assert gate.decide(receipt)["status"] == "approved"
    assert gate.decide(receipt)["status"] == "approved"
    with pytest.raises(ValueError, match="approval fingerprint"):
        gate.decide(OperatorExecutionDecision(
            ticket_id=ticket["ticket_id"], fingerprint="f"*64,
            operator_ref=OPERATOR, action="APPROVE",
            decision_id=receipt.decision_id,
        ))
    with pytest.raises(ValueError, match="conflicting or altered"):
        gate.decide(OperatorExecutionDecision(
            ticket_id=ticket["ticket_id"], fingerprint=ticket["fingerprint"],
            operator_ref=OPERATOR, action="REJECT", decision_id="different",
        ))
    with pytest.raises(TypeError, match="typed third host"):
        gate.decide({"action": "APPROVE"})
    assert _effects(tmp_path) == 0


def test_m6_uses_new_sensor_not_stale_review_tick(tmp_path):
    gate, ticket, _ = _stage(tmp_path)
    gate.decide(_receipt(ticket, "stale"))
    stage = json.loads(ticket["snapshot_json"])["sensor"]
    with pytest.raises(ValueError, match="NEW live registered sensor tick"):
        gate.assemble(
            ticket["ticket_id"],
            event_id=stage["event_id"], tick=stage["tick"],
        )
    assert _effects(tmp_path) == 0


def test_m6_rejects_unauthorized_or_noncanonical_direct_handler(tmp_path):
    gate, ticket, _ = _stage(tmp_path)
    handler = M6GuardedDoorHandler(tmp_path, ticket["ticket_id"])
    with pytest.raises(SandboxToolError):
        handler(tmp_path/"world", {"subject_ref": DOOR_SUBJECT}, "xop_" + "0"*36)
    gate.decide(_receipt(ticket, "bad-operation"))
    with pytest.raises(SandboxToolError):
        handler(tmp_path/"world", {"subject_ref": DOOR_SUBJECT}, "xop_" + "0"*36)
    assert gate.ticket(ticket["ticket_id"])["status"] == "approved"
    assert _effects(tmp_path) == 0


def test_m6_rejects_second_tool_invocation_after_claim(tmp_path):
    report = seed(tmp_path, "normal")
    assert report["status"] == "M6_SEED_PASS"
    manifest = json.loads((tmp_path / "m6_manifest.json").read_text())
    gate = _m6(tmp_path)
    record = gate.ticket(manifest["m6_ticket_id"])
    assert record["status"] == "claimed"
    handler = M6GuardedDoorHandler(tmp_path, record["ticket_id"])
    with pytest.raises(SandboxToolError):
        handler(tmp_path/"world", {"subject_ref": DOOR_SUBJECT}, record["operation_id"])
    assert _effects(tmp_path) == 1


def test_m6_rejects_drift_in_original_m5_binding(tmp_path):
    gate, ticket, _ = _stage(tmp_path)
    gate.decide(_receipt(ticket, "drift"))
    # No implicit rebind allowed; modify only this isolated DB to simulate corruption.
    with sqlite3.connect(tmp_path/"runtime"/"core_work.db") as db:
        db.execute(
            "UPDATE core_goal_bindings SET expected_json=? WHERE goal_id=?",
            ('{"type":"symbol","value":"open"}', ticket["goal_id"]),
        )
        db.commit()
    eid, tick = observed(gate.core, tmp_path)
    with pytest.raises(ValueError, match="binding is different"):
        gate.assemble(ticket["ticket_id"], event_id=eid, tick=tick)
    assert _effects(tmp_path) == 0


def test_m6_different_source_or_p6_adapter_is_not_equivalent(tmp_path):
    gate, ticket, _ = _stage(tmp_path)
    assert gate.m5._trusted_registry()["property"]["clock_domain"] == "lab_tick"
    assert gate.m5._trusted_registry()["producer"] == "adapter.virtual_door_sensor/0.1"
    assert "adapter.val_door_port/0.1" != gate.m5._trusted_registry()["producer"]
    # Exact producer / clock cannot be replaced in already reviewed M5/M6.
    assert gate.core.core_events.ingress.sources["sensor.door_01"].producer_ref == (
        "adapter.virtual_door_sensor/0.1"
    )


def test_m6_report_does_not_overwrite_user_file(tmp_path):
    destination = tmp_path/"original.json"
    destination.write_text("KEEP", encoding="utf-8")
    p = subprocess.run([
        sys.executable, "-m", "scripts.run_memory_v1_execution_gate",
        "--report", str(destination),
    ],cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert p.returncode != 0
    assert "report must be new" in p.stderr
    assert destination.read_text(encoding="utf-8") == "KEEP"


def test_m6_rejects_preexisting_directory(tmp_path):
    root = tmp_path/"has-data"
    root.mkdir()
    proof = root/"user.txt"
    proof.write_text("DO NOT TOUCH")
    with pytest.raises(ValueError, match="fresh empty"):
        seed(root, "normal")
    assert proof.read_text() == "DO NOT TOUCH"
