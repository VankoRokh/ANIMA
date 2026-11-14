"""M6-B2 deterministic laboratory gate; simulated VAL transport, NOT real Godot."""
from __future__ import annotations

from dataclasses import replace
import json
import multiprocessing
from pathlib import Path
import sqlite3

import pytest

from anima.agent.executor import SandboxToolError
from anima.core.door_world import DOOR_SOURCE, DOOR_SUBJECT
from anima.core.ingress import CONTRACT
from labs.virtual_anima_lab.python.contracts import (
    SOURCE as GODOT_SOURCE, PRODUCER as GODOT_PRODUCER, OBSERVATION_SCHEMA,
)
from labs.virtual_anima_lab.python.core_port import VALDoorPort
from labs.virtual_anima_lab.python.m6b1_godot_migration import (
    M6B1Migration, OperatorMigrationDecision, OPERATOR as B1_OPERATOR,
)
from labs.virtual_anima_lab.python.m6b2_godot_execution import (
    M6B2Admission, M6B2GuardedHandler, OperatorGodotExecutionDecision,
    OPERATOR as B2_OPERATOR,
)
from labs.virtual_anima_lab.python.m5_binding_admission import restricted_core
from scripts.run_memory_v1_binding_gate import _m5, seed as m5_seed


def _file(port):
    return port.root.parent / "fake_p6_world.json"


def _read(port):
    return json.loads(_file(port).read_text(encoding="utf-8"))


def _write(port, value):
    _file(port).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


class _MockClient:
    def __init__(self, port):
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def call(self, command, **_):
        if command != "hello":
            raise AssertionError("fake B2 transport only implements hello")
        world = _read(self.port)
        return {
            "epoch": world["epoch"],
            "data": {
                "world_instance_id": world["instance"],
                "world_version": "p5a-grid/0.1",
                "scenario": "p6_door",
                "source_ref": GODOT_SOURCE,
                "capabilities": [
                    "observe", "act_door", "door_operation_status",
                ],
            },
        }


def _fake_client(port):
    return _MockClient(port)


def _fake_sense(port):
    world = _read(port)
    world["counter"] += 1
    _write(port, world)
    obs_id = "fake_val_obs_" + str(world["counter"])
    original = {
        "schema": OBSERVATION_SCHEMA,
        "source_ref": GODOT_SOURCE, "producer_ref": GODOT_PRODUCER,
        "observation_id": obs_id, "world_revision": world["revision"],
        "observed_at": {"epoch": world["epoch"], "tick": world["counter"]},
    }
    seq = port._next_sample(world["instance"], original)
    at = {"domain": "lab_sample", "value": seq}
    return {
        "contract": CONTRACT,
        "occurrence_id": f"p6:{world['instance']}:{obs_id}",
        "occurrence_version": 1, "kind": "state.property",
        "payload": {
            "subject_ref": DOOR_SUBJECT,
            "predicate_ref": "world.door_state@1",
            "observed_at": at,
            "temporal_scope": {"kind": "instant", "at": at},
            "source_revision": seq,
            "value": {"type": "symbol", "value": world["state"]},
        },
    }, seq


def _fake_execute(
    port, root, arguments, operation_id, *,
    expected_world_instance=None, expected_epoch=None, expected_revision=None,
):
    assert Path(root) == port.root
    assert arguments == {"subject_ref": DOOR_SUBJECT}
    world = _read(port)
    if (world["instance"] != expected_world_instance
            or world["epoch"] != expected_epoch
            or world["revision"] != expected_revision
            or world["state"] != "open"):
        raise SandboxToolError(
            "SIMULATED_WORLD_CHANGED", "pinned pre-effect state changed",
            effect_possible=False,
        )
    world["state"] = "closed"
    world["revision"] += 1
    world["effect_operations"].append(operation_id)
    _write(port, world)
    return {"operation_id": operation_id, "applied": True}


def _fake_reconcile(port, arguments, operation_id):
    assert arguments == {"subject_ref": DOOR_SUBJECT}
    world = _read(port)
    if operation_id in world["effect_operations"]:
        return "succeeded", {"operation_id": operation_id, "applied": True}
    return "unknown", None


def _fake_reconcile_tool(port, root, arguments, operation_id):
    return _fake_reconcile(port, arguments, operation_id)


def _fake_replay(port, root, arguments, operation_id):
    result, evidence = _fake_reconcile(port, arguments, operation_id)
    if result != "succeeded":
        raise SandboxToolError("UNKNOWN", "no prior effect", effect_possible=False)
    return evidence


@pytest.fixture
def fake_val(monkeypatch):
    monkeypatch.setattr(VALDoorPort, "sense", _fake_sense)
    monkeypatch.setattr(VALDoorPort, "_client", _fake_client)
    monkeypatch.setattr(VALDoorPort, "execute", _fake_execute)
    monkeypatch.setattr(VALDoorPort, "reconcile", _fake_reconcile)
    monkeypatch.setattr(VALDoorPort, "reconcile_tool", _fake_reconcile_tool)
    monkeypatch.setattr(VALDoorPort, "replay_output", _fake_replay)


def _fixture(root):
    assert m5_seed(root, "normal")["status"] == "M5_SEED_PASS"
    world_path = root / "fake_p6_world.json"
    world_path.write_text(json.dumps({
        "instance": "a" * 32, "epoch": 0, "revision": 0,
        "state": "open", "counter": 0, "effect_operations": [],
    }), encoding="utf-8")
    core = restricted_core(root)
    m5 = _m5(core, root)
    port = VALDoorPort(root / "p6_port", port=46019)
    b1 = M6B1Migration(root=root, m5=m5, port=port)
    m5ticket = json.loads((root / "m5_manifest.json").read_text())["m5_ticket_id"]
    reviewed = b1.stage(m5ticket)
    b1.decide(OperatorMigrationDecision(
        ticket_id=reviewed["ticket_id"], fingerprint=reviewed["fingerprint"],
        decision_id="fake-b1-approved", action="APPROVE",
        operator_ref=B1_OPERATOR,
    ))
    return M6B2Admission(root=root, b1=b1), reviewed


def _decision(ticket, *, action="APPROVE"):
    return OperatorGodotExecutionDecision(
        ticket_id=ticket["ticket_id"], fingerprint=ticket["fingerprint"],
        decision_id="fake-b2-" + action, action=action, operator_ref=B2_OPERATOR,
    )


def test_m6b2_typed_host_approval_is_not_m6a_or_b1():
    row = _decision({"ticket_id": "m6b2_fake", "fingerprint": "b" * 64})
    assert row.action == "APPROVE"
    assert replace(row, action="REJECT").action == "REJECT"
    with pytest.raises(ValueError, match="unknown laboratory"):
        replace(row, operator_ref=B1_OPERATOR)
    with pytest.raises(ValueError, match="APPROVE or REJECT"):
        replace(row, action="APPROVE_AND_EXECUTE")
    with pytest.raises(ValueError, match="fingerprint"):
        replace(row, fingerprint="not-a-hash")


def test_m6b2_b1_approval_does_not_install_executor(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    assert row["status"] == "staged"
    assert gate.b1.m5.core.core_execution is None
    assert gate.b1.m5.core.core_autonomy is None
    assert gate.b1.m5.core.internal_state.goals.goal_count() == 1
    assert gate.b1.m5.core.core_decision.tasks.list_tasks() == []
    assert gate._target().decision.tasks.list_tasks() == []
    assert gate._target().operations.list_operations() == []
    assert gate._target().ingress.sources[DOOR_SOURCE].producer_ref == (
        "adapter.val_door_port/0.1"
    )
    assert gate.b1.m5.core.core_events.ingress.sources[DOOR_SOURCE].producer_ref == (
        "adapter.virtual_door_sensor/0.1"
    )
    assert gate._target().ingress.database_file != (
        gate.b1.m5.core.core_events.ingress.database_file
    )
    assert gate._target().decision.goals is gate.b1.m5.core.internal_state.goals
    with pytest.raises(ValueError, match="APPROVE required"):
        gate.assemble(row["ticket_id"])
    assert _read(gate.port)["effect_operations"] == []


def test_m6b2_rejected_ticket_never_installs_executor(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    assert gate.decide(_decision(row, action="REJECT"))["status"] == "rejected"
    with pytest.raises(ValueError, match="APPROVE required"):
        gate.assemble(row["ticket_id"])
    with pytest.raises(ValueError, match="conflicting"):
        gate.decide(_decision(row))
    assert _read(gate.port)["effect_operations"] == []


def test_m6b2_only_new_approval_installs_guarded_target(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    assert gate.decide(_decision(row))["status"] == "approved"
    assert gate.decide(_decision(row))["status"] == "approved"
    target = gate.assemble(row["ticket_id"])
    assert target.execution is not None
    assert target.decision.goals is gate.b1.m5.core.internal_state.goals
    assert gate.b1.m5.core.core_execution is None
    assert gate.b1.m5.core.core_decision.tasks.list_tasks() == []
    assert target.operations.list_operations() == []
    guard = target.execution.executor.handlers[("world.door.close", "0.1")]
    assert isinstance(guard.execute, M6B2GuardedHandler)
    assert _read(gate.port)["effect_operations"] == []


def test_m6b2_guard_needs_real_persisted_operation(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    guard = M6B2GuardedHandler(tmp_path, row["ticket_id"], gate.port.port)
    with pytest.raises(SandboxToolError, match="canonical operation"):
        guard(gate.port.root, {"subject_ref": DOOR_SUBJECT}, "fake-op")
    assert gate.get(row["ticket_id"])["status"] == "approved"
    assert _read(gate.port)["effect_operations"] == []



def test_m6b2_rejects_replaced_godot_instance(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    changed = _read(gate.port)
    changed["instance"] = "b" * 32
    _write(gate.port, changed)
    with pytest.raises(ValueError, match="instance|epoch|changed|replaced"):
        gate.assemble(row["ticket_id"])
    assert _read(gate.port)["effect_operations"] == []


def test_m6b2_replayed_sample_is_not_fresh(tmp_path, fake_val, monkeypatch):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    previous = json.loads(row["snapshot_json"])["admission_sample"]["lab_sample"]
    monkeypatch.setattr(
        VALDoorPort, "sense", lambda _: ({"unused": "replay"}, previous),
    )
    with pytest.raises(ValueError, match="stale Godot sample"):
        gate.assemble(row["ticket_id"])
    assert _read(gate.port)["effect_operations"] == []


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="simulated subprocess transport fixture requires POSIX fork",
)
def test_m6b2_lying_tool_receipt_never_completes_goal(
    tmp_path, fake_val, monkeypatch,
):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    target = gate.assemble(row["ticket_id"])
    # Worker reports success but does NOT change the independent fake world.
    monkeypatch.setattr(
        VALDoorPort, "execute",
        lambda self, root, args, operation_id, **pins: {
            "operation_id": operation_id, "applied": True,
        },
    )
    turn = gate.execute_approved(row["ticket_id"], target)
    assert turn.outcome == "UNVERIFIED"
    assert len(_read(gate.port)["effect_operations"]) == 0
    assert gate.b1.m5.core.internal_state.goals.get_goal(row["goal_id"])["status"] == "active"
    assert gate.get(row["ticket_id"])["status"] == "claimed"
    assert len(target.operations.list_operations()) == 1
    # The claimed permit cannot run a second tool even when the first lies.
    recovered = M6B2Admission.reopen(tmp_path, port_num=gate.port.port)
    again = recovered.execute_approved(
        row["ticket_id"], recovered.assemble(row["ticket_id"]),
    )
    assert again.outcome != "VERIFIED_SUCCESS"
    assert len(_read(gate.port)["effect_operations"]) == 0

def test_m6b2_rejects_changed_world_revision_pre_effect(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    world = _read(gate.port)
    world["revision"] += 1
    _write(gate.port, world)
    with pytest.raises(ValueError, match="revision"):
        gate.assemble(row["ticket_id"])
    assert _read(gate.port)["effect_operations"] == []


def test_m6b2_rejects_source_ledger_mutation(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    sample = json.loads(row["snapshot_json"])["admission_sample"]["lab_sample"]
    with sqlite3.connect(gate.port.database_file) as db:
        db.execute(
            "UPDATE sample_log SET payload_json=? WHERE sample_seq=?",
            ('{"tampered":true}', sample),
        )
    with pytest.raises(ValueError, match="sample ledger changed"):
        gate.assemble(row["ticket_id"])
    assert _read(gate.port)["effect_operations"] == []


def test_m6b2_rejects_target_binding_mutation(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    with sqlite3.connect(gate.target_root / "core_work.db") as db:
        db.execute(
            "UPDATE core_goal_bindings SET expected_json=? WHERE goal_id=?",
            ('{"type":"symbol","value":"open"}', row["goal_id"]),
        )
    with pytest.raises(ValueError, match="target P3-A binding changed"):
        gate.assemble(row["ticket_id"])
    assert _read(gate.port)["effect_operations"] == []


def test_m6b2_rejects_original_m5_binding_mutation(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    with sqlite3.connect(tmp_path / "runtime" / "core_work.db") as db:
        db.execute(
            "UPDATE core_goal_bindings SET expected_json=? WHERE goal_id=?",
            ('{"type":"symbol","value":"open"}', row["goal_id"]),
        )
    with pytest.raises(ValueError, match="M5 existing Core binding is different"):
        gate.assemble(row["ticket_id"])
    assert _read(gate.port)["effect_operations"] == []


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="simulated subprocess transport fixture requires POSIX fork",
)
def test_m6b2_one_fake_effect_and_readback_not_tool_receipt(tmp_path, fake_val):
    gate, origin = _fixture(tmp_path)
    row = gate.stage(origin["ticket_id"])
    gate.decide(_decision(row))
    target = gate.assemble(row["ticket_id"])
    turn = gate.execute_approved(row["ticket_id"], target)
    assert turn.outcome == "VERIFIED_SUCCESS", turn
    assert gate.get(row["ticket_id"])["status"] == "claimed"
    assert len(_read(gate.port)["effect_operations"]) == 1
    assert gate.b1.m5.core.internal_state.goals.get_goal(row["goal_id"])["status"] == "completed"
    assert len(target.operations.list_operations()) == 1
    assert len(target.decision.tasks.list_tasks()) == 1
    assert gate.b1.m5.core.core_decision.tasks.list_tasks() == []
    # Initial B1 OPEN/revision preflight is no longer valid after an effect.
    with pytest.raises(ValueError):
        gate.b1.revalidate(origin["ticket_id"])
    recovered = M6B2Admission.reopen(tmp_path, port_num=gate.port.port)
    recovery_target = recovered.assemble(row["ticket_id"])
    repeat = recovered.execute_approved(row["ticket_id"], recovery_target)
    assert repeat.outcome in ("RECOVERED_VERIFIED_SUCCESS", "VERIFIED_SUCCESS")
    assert len(_read(gate.port)["effect_operations"]) == 1
    guard = M6B2GuardedHandler(tmp_path, row["ticket_id"], gate.port.port)
    with pytest.raises(SandboxToolError, match="already claimed"):
        guard(gate.port.root, {"subject_ref": DOOR_SUBJECT},
              recovered.get(row["ticket_id"])["operation_id"])
    assert len(_read(gate.port)["effect_operations"]) == 1
