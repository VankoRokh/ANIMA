"""M6-B1 offline negatives: strict mapping != permission to execute Godot."""
from dataclasses import replace
from pathlib import Path
import json

import pytest

from anima.core.door_world import DOOR_PRODUCER, DOOR_SOURCE
from labs.virtual_anima_lab.python.m6b1_godot_migration import (
    M6B1Migration, OperatorMigrationDecision, OPERATOR, SCHEMA,
    _source_map, validate_frozen_mapping,
)
from labs.virtual_anima_lab.python.core_port import VALDoorPort
from labs.virtual_anima_lab.python.m5_binding_admission import restricted_core
from scripts.run_memory_v1_binding_gate import _m5, seed as m5_seed


def test_m6b1_source_mapping_explicitly_not_equivalent():
    frozen = _source_map()
    assert validate_frozen_mapping(frozen)
    assert frozen["origin"]["producer_ref"] == DOOR_PRODUCER
    assert frozen["origin"]["clock_domain"] == "lab_tick"
    assert frozen["godot_adapter"]["source_ref"] == DOOR_SOURCE
    assert frozen["godot_adapter"]["producer_ref"] == "adapter.val_door_port/0.1"
    assert frozen["godot_adapter"]["clock_domain"] == "lab_sample"
    assert frozen["godot_raw"]["source_ref"] == "lab.sensor.anima.proximity"
    assert frozen["godot_raw"]["producer_ref"] == "lab.godot"
    assert frozen["godot_raw"]["clock_domain"] == "epoch_tick"
    assert frozen["same_source_authority"] is False
    assert frozen["clock_conversion_authorized"] is False
    assert frozen["target_p2_registered"] is False
    assert frozen["execution_permission"] is False


@pytest.mark.parametrize("location,value", [
    (("origin","producer_ref"), "adapter.val_door_port/0.1"),
    (("origin","clock_domain"), "lab_sample"),
    (("godot_adapter","producer_ref"), DOOR_PRODUCER),
    (("godot_adapter","clock_domain"), "lab_tick"),
    (("godot_raw","source_ref"), DOOR_SOURCE),
    (("godot_raw","producer_ref"), "fake.agent"),
    (("godot_adapter","source_ref"), "external.hidden"),
    (("godot_raw","clock_domain"), "lab_tick"),
    (("same_source_authority",), True),
    (("clock_conversion_authorized",), True),
    (("target_p2_registered",), True),
    (("execution_permission",), True),
])
def test_m6b1_any_producer_clock_authority_drift_fails_closed(location,value):
    mapping = _source_map()
    obj = mapping
    for key in location[:-1]:
        obj = obj[key]
    obj[location[-1]] = value
    with pytest.raises(ValueError, match="mapping changed"):
        validate_frozen_mapping(mapping)


def test_m6b1_reject_unknown_extra_authorization_field():
    forged = _source_map()
    forged["approval"] = {"role": "operator", "tool": "world.door.close"}
    with pytest.raises(ValueError, match="mapping changed"):
        validate_frozen_mapping(forged)


def test_m6b1_typed_operator_receipt_validation():
    receipt = OperatorMigrationDecision(
        ticket_id="m6b1_test", fingerprint="a" * 64,
        decision_id="r1", operator_ref=OPERATOR, action="APPROVE",
    )
    assert receipt.action == "APPROVE"
    assert replace(receipt,action="REJECT").action == "REJECT"
    with pytest.raises(ValueError, match="unknown laboratory"):
        OperatorMigrationDecision(
            ticket_id="t", fingerprint="a" * 64,
            decision_id="r1", operator_ref="test.operator.m6a",
            action="APPROVE",
        )
    with pytest.raises(ValueError, match="APPROVE or REJECT"):
        replace(receipt, action="BIND_AND_EXECUTE")
    with pytest.raises(ValueError, match="fingerprint"):
        replace(receipt, fingerprint="not-a-digest")


def test_m6b1_bad_source_and_unbound_goal_do_not_stage_without_godot(tmp_path):
    assert m5_seed(tmp_path, "normal")["status"] == "M5_SEED_PASS"
    core = restricted_core(tmp_path)
    gate = _m5(core, tmp_path)
    port = VALDoorPort(tmp_path / "p6_port", port=46019)
    preflight = M6B1Migration(root=tmp_path, m5=gate, port=port)
    assert core.core_execution is None
    assert core.core_autonomy is None
    assert "assemble" not in dir(preflight)
    assert "execute_approved" not in dir(preflight)
    with pytest.raises(ValueError, match="bound M5"):
        preflight.stage("m5_" + "0" * 64)
    assert core.internal_state.goals.goal_count() == 1
    assert core.core_decision.tasks.list_tasks() == []


def test_m6b1_no_dangerous_old_m6a_permission_migration():
    value = _source_map()
    assert value["execution_permission"] is False
    assert value["same_source_authority"] is False
    assert "m6a" not in SCHEMA.lower()
