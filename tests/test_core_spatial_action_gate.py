"""E2.5c native Goal/Task/Stage6 action gate: negative and crash-boundary tests.

Disposable Core only; does not connect to real Godot. Live Godot acceptance is
in the separate stage6_visual_live_gate using actual SandboxExecutor processes.
"""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

from anima.core.assembly import build_core
from anima.core.spatial_action_gate import (
    CoreSpatialActionGateway, CoreSpatialAdmissionError, SpatialSourceProof,
)
from anima.execution.contracts import ExecutionReceipt, thaw
from anima.execution.store import ExecutionStore
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import (
    E24WorkingMemory, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)
from labs.virtual_anima_lab.python.lifecycle.egocentric import (
    E23ObserverPort, EgocentricView, VIEW_SCHEMA,
)
from labs.virtual_anima_lab.python.lifecycle.stage6_world import (
    stage6_godot_executor, VERSION,
)

WORLD = "a" * 32
KEY = "v" * 43


def sensor(seq, *, revision=None, tick=None):
    return EgocentricView({
        "schema": VIEW_SCHEMA, "world_instance_id": WORLD,
        "epoch": 1, "sample_seq": seq,
        "sample_id": f"worldobs:{WORLD}:1:{seq}",
        "revision": seq - 1 if revision is None else revision,
        "tick": seq - 1 if tick is None else tick,
        "source_ref": SOURCE, "observer_ref": "lab.actor.anima",
        "coverage": {"kind": "view_cone", "fov_degrees": 90,
                     "range_limit": "none", "occlusion": "opaque_grid_cells"},
        "readings": [{
            "entity_ref": "lab.item.crate", "category": "item",
            "bearing_mdeg": 0, "range_milli_cells": 1500,
            "properties": {"owner": {"status": "absent", "value": None}},
        }],
    })


def prepare_env(tmp_path, monkeypatch):
    iterator = iter([sensor(1), sensor(2)])
    monkeypatch.setattr(E23ObserverPort, "observe", lambda _: next(iterator))
    core = build_core(
        tmp_path, sources={SOURCE: vision_source_registration()},
        properties={(SUBJECT, PREDICATE): vision_digest_rule()},
    )
    memory = E24WorkingMemory(
        core, E23ObserverPort(port=46029, observer_key=KEY),
    )
    record = memory.observe_and_record()
    goal = core.internal_state.create_goal(
        source="lab.visual", source_id="visual-test-case",
        priority=1.0, description="One verified aligned approach step",
        success_criterion="Core-backed Raw confirms step after sight",
        reason="Human-selected isolated test",
    )
    store = ExecutionStore(core.data_dir / "execution.db")
    registry, executor = stage6_godot_executor(
        root=core.data_dir, store=store, port=46029,
        executor_key=KEY,
    )
    gate = CoreSpatialActionGateway(
        core=core, store=store, registry=registry, executor=executor,
        allowed_capabilities={
            "world.turn": ("world.turn", VERSION),
            "world.step": ("world.step", VERSION),
        },
        source_ref=SOURCE,
        producer_ref="lab.world.lifecycle.egocentric_adapter",
        subject_ref=SUBJECT, predicate_ref=PREDICATE,
    )
    proof = SpatialSourceProof(
        sample_id=record.sample_id,
        core_event_id=record.core_event_id,
        raw_json=memory.raw_evidence(record.sample_id).canonical_json,
    )
    return core, memory, goal, store, gate, proof


def test_admit_only_after_canonical_provenance_and_native_goal(tmp_path, monkeypatch):
    core, mem, goal, store, gate, proof = prepare_env(tmp_path, monkeypatch)
    prepared = gate.prepare(
        goal_id=goal["id"], proof=proof,
        tool_kind="world.turn", direction="right", reason="SEARCH_NEW_VIEW",
    )
    assert prepared.source_event_id == proof.core_event_id
    assert store.get_operation(prepared.operation_id)["status"] == "prepared"
    assert gate.tasks.get_task(prepared.task_id).status == "active"
    assert gate.goals.get_goal(goal["id"])["status"] == "active"
    spec = store.load_verification_spec(prepared.operation_id)
    assert spec.criterion_kind == "world.egocentric_transition"
    assert thaw(spec.parameters)["before_sample_id"] == proof.sample_id
    assert prepared.action.to_dict()["arguments"]["observation_id"] == proof.sample_id
    gate.before_effect(prepared, proof=proof)
    with pytest.raises(CoreSpatialAdmissionError, match="existing spatial Task"):
        gate.prepare(
            goal_id=goal["id"], proof=proof,
            tool_kind="world.turn", direction="left", reason="second",
        )
    assert len(store.list_operations(goal_id=goal["id"])) == 1


@pytest.mark.parametrize("attack", [
    "forged_bytes", "other_event", "forged_id", "wrong_direction",
    "unregistered_tool",
])
def test_malicious_or_inconsistent_proposal_fails_closed(tmp_path, monkeypatch, attack):
    core, mem, goal, store, gate, proof = prepare_env(tmp_path, monkeypatch)
    params = {
        "goal_id": goal["id"], "proof": proof,
        "tool_kind": "world.turn", "direction": "right",
        "reason": "SEARCH_NEW_VIEW",
    }
    if attack == "forged_bytes":
        params["proof"] = replace(proof, raw_json=proof.raw_json + " ")
    if attack == "other_event":
        params["proof"] = replace(proof, core_event_id="ev_not_canonical")
    if attack == "forged_id":
        params["proof"] = replace(proof, sample_id="worldobs:bad:1:1")
    if attack == "wrong_direction":
        params["direction"] = "forward"
    if attack == "unregistered_tool":
        params["tool_kind"] = "fs.delete"
    with pytest.raises(CoreSpatialAdmissionError):
        gate.prepare(**params)
    assert store.list_operations(goal_id=goal["id"]) == []
    assert gate.tasks.list_tasks(goal_id=goal["id"]) == []


def test_spatial_gate_rejects_capability_aliasing(tmp_path, monkeypatch):
    core, mem, goal, store, gate, proof = prepare_env(tmp_path, monkeypatch)
    with pytest.raises(CoreSpatialAdmissionError, match="alias is forbidden"):
        CoreSpatialActionGateway(
            core=core, store=store, registry=gate.registry, executor=gate.executor,
            allowed_capabilities={
                "world.turn": ("world.step", VERSION),
                "world.step": ("world.step", VERSION),
            },
            source_ref=SOURCE,
            producer_ref="lab.world.lifecycle.egocentric_adapter",
            subject_ref=SUBJECT, predicate_ref=PREDICATE,
        )
    assert store.list_operations(goal_id=goal["id"]) == []


def test_cancelled_goal_cannot_prepare_or_execute(tmp_path, monkeypatch):
    core, mem, goal, store, gate, proof = prepare_env(tmp_path, monkeypatch)
    prepared = gate.prepare(
        goal_id=goal["id"], proof=proof,
        tool_kind="world.turn", direction="right", reason="search",
    )
    core.internal_state.goals.transition_goal(
        goal["id"], to_status="cancelled", reason="operator cancel",
    )
    with pytest.raises(CoreSpatialAdmissionError, match="binding drifted"):
        gate.before_effect(prepared, proof=proof)
    assert store.get_operation(prepared.operation_id)["status"] == "prepared"


def test_new_raw_revokes_stale_action_preconditions(tmp_path, monkeypatch):
    core, mem, goal, store, gate, proof = prepare_env(tmp_path, monkeypatch)
    prepared = gate.prepare(
        goal_id=goal["id"], proof=proof,
        tool_kind="world.turn", direction="right", reason="search",
    )
    mem.observe_and_record()
    with pytest.raises(CoreSpatialAdmissionError, match="stale"):
        gate.before_effect(prepared, proof=proof)


def test_corroborated_stage6_finishes_task_but_never_goal_automatically(
    tmp_path, monkeypatch,
):
    core, mem, goal, store, gate, before = prepare_env(tmp_path, monkeypatch)
    prepared = gate.prepare(
        goal_id=goal["id"], proof=before,
        tool_kind="world.turn", direction="right", reason="search",
    )
    store.transition_operation(
        prepared.operation_id, "executing", reason="test worker start",
    )
    store.transition_operation(
        prepared.operation_id, "succeeded", reason="test worker success",
    )
    result = {
        "operation_id": prepared.operation_id,
        "status": "APPLIED", "effect_applied": True,
        "revision": 1, "tick": 1, "event_id": "lifecycle_evt:1",
        "reason": "ok",
    }
    receipt = ExecutionReceipt.create(
        action=prepared.action, status="succeeded",
        output=result,
        started_at="2026-11-24T00:00:00+00:00",
        finished_at="2026-11-24T00:00:01+00:00",
    )
    after_record = mem.observe_and_record()
    after = SpatialSourceProof(
        sample_id=after_record.sample_id,
        core_event_id=after_record.core_event_id,
        raw_json=mem.raw_evidence(after_record.sample_id).canonical_json,
    )
    with pytest.raises(CoreSpatialAdmissionError, match="readback contradicts"):
        gate.finish_verified(
            prepared, before_proof=before, after_proof=after,
            receipt=receipt, readback={**result, "revision": 99},
        )
    assert gate.tasks.get_task(prepared.task_id).status == "active"
    assert gate.finish_verified(
        prepared, before_proof=before, after_proof=after,
        receipt=receipt, readback=result,
    ) == "VERIFIED_EFFECT"
    assert gate.tasks.get_task(prepared.task_id).status == "completed"
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    with pytest.raises(CoreSpatialAdmissionError, match="identity changed after effect"):
        gate.finish_verified(
            prepared, before_proof=before, after_proof=after,
            receipt=receipt, readback=result,
        )


def test_wrong_core_goal_or_source_cannot_admit(tmp_path, monkeypatch):
    core, mem, goal, store, gate, proof = prepare_env(tmp_path, monkeypatch)
    other = core.internal_state.create_goal(
        source="untrusted.model", source_id="fake-goal",
        priority=99, description="attempt elevated action",
        success_criterion="unknown", reason="test",
    )
    with pytest.raises(CoreSpatialAdmissionError, match="registered Goal"):
        gate.prepare(
            goal_id=other["id"], proof=proof,
            tool_kind="world.step", direction="forward", reason="attack",
        )
    assert store.list_operations(goal_id=other["id"]) == []


# CA-01: neither admission nor finalization may trust caller-owned DTO IDs.
def _second_prepared(core, gate, proof):
    goal = core.internal_state.create_goal(
        source="lab.visual", source_id="visual-test-case-second",
        priority=1.0, description="Second independent Goal",
        success_criterion="Second bounded action", reason="CA-01 regression",
    )
    return gate.prepare(
        goal_id=goal["id"], proof=proof,
        tool_kind="world.turn", direction="left", reason="second",
    )


def _cross_wire(first, second, field):
    if field == "goal_task":
        return replace(first, goal_id=second.goal_id, task_id=second.task_id)
    return replace(first, **{field: getattr(second, field)})


@pytest.mark.parametrize("field", [
    "goal_id", "task_id", "operation_id", "action", "spec", "goal_task",
])
@pytest.mark.parametrize("cancelled", [False, True])
def test_ca01_cross_wired_execution_never_dispatches(
    tmp_path, monkeypatch, field, cancelled,
):
    core, mem, goal, store, gate, proof = prepare_env(tmp_path, monkeypatch)
    first = gate.prepare(
        goal_id=goal["id"], proof=proof,
        tool_kind="world.turn", direction="right", reason="first",
    )
    second = _second_prepared(core, gate, proof)
    if cancelled:
        gate.goals.transition_goal(
            first.goal_id, to_status="cancelled", reason="CA-01 cancel",
        )
    calls = []
    monkeypatch.setattr(
        type(gate.executor), "execute", lambda self, action: calls.append(action),
    )
    with pytest.raises(CoreSpatialAdmissionError, match="binding drifted"):
        gate.execute_once(_cross_wire(first, second, field), proof=proof)
    assert calls == []
    for prepared in (first, second):
        assert store.get_operation(prepared.operation_id)["status"] == "prepared"
        assert gate.tasks.get_task(prepared.task_id).status == "active"
    if not cancelled:
        gate.execute_once(first, proof=proof)
        assert calls == [first.action]


@pytest.mark.parametrize("field", [
    "goal_id", "task_id", "operation_id", "action", "spec", "goal_task",
])
@pytest.mark.parametrize("cancelled", [False, True])
def test_ca01_cross_wired_finalization_never_completes_another_task(
    tmp_path, monkeypatch, field, cancelled,
):
    core, mem, goal, store, gate, before = prepare_env(tmp_path, monkeypatch)
    first = gate.prepare(
        goal_id=goal["id"], proof=before,
        tool_kind="world.turn", direction="right", reason="first",
    )
    second = _second_prepared(core, gate, before)
    store.transition_operation(first.operation_id, "executing", reason="test start")
    store.transition_operation(first.operation_id, "succeeded", reason="test success")
    result = {
        "operation_id": first.operation_id,
        "status": "APPLIED", "effect_applied": True,
        "revision": 1, "tick": 1, "event_id": "lifecycle_evt:1",
        "reason": "ok",
    }
    receipt = ExecutionReceipt.create(
        action=first.action, status="succeeded", output=result,
        started_at="2026-11-24T00:00:00+00:00",
        finished_at="2026-11-24T00:00:01+00:00",
    )
    record = mem.observe_and_record()
    after = SpatialSourceProof(
        sample_id=record.sample_id, core_event_id=record.core_event_id,
        raw_json=mem.raw_evidence(record.sample_id).canonical_json,
    )
    if cancelled:
        gate.goals.transition_goal(
            first.goal_id, to_status="cancelled", reason="CA-01 cancel",
        )
    def finish(prepared):
        return gate.finish_verified(
            prepared, before_proof=before, after_proof=after,
            receipt=receipt, readback=result,
        )

    with pytest.raises(CoreSpatialAdmissionError, match="identity changed after effect"):
        finish(_cross_wire(first, second, field))
    assert gate.tasks.get_task(first.task_id).status == "active"
    assert gate.tasks.get_task(second.task_id).status == "active"
    assert store.get_operation(first.operation_id)["status"] == "succeeded"
    assert store.get_operation(second.operation_id)["status"] == "prepared"
    if cancelled:
        with pytest.raises(CoreSpatialAdmissionError, match="identity changed after effect"):
            finish(first)
        assert gate.tasks.get_task(first.task_id).status == "active"
    else:
        assert finish(first) == "VERIFIED_EFFECT"
        assert gate.tasks.get_task(first.task_id).status == "completed"
    assert gate.tasks.get_task(second.task_id).status == "active"
