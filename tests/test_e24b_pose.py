"""E2.4b negative readback/pose reconstruction tests, using disposable Core."""
from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.lifecycle.egocentric import (
    EgocentricAction, E23ObserverPort, VIEW_ACTION_SCHEMA, VIEW_SCHEMA,
)
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import (
    E24WorkingMemory, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)
from labs.virtual_anima_lab.python.lifecycle.e24_pose import E24PoseError, E24PoseTrail

WORLD = "a" * 32
KEY = "z" * 43


def view(seq, revision, tick):
    return {
        "schema": VIEW_SCHEMA, "world_instance_id": WORLD,
        "epoch": 1, "revision": revision, "tick": tick,
        "sample_id": f"worldobs:{WORLD}:1:{seq}", "sample_seq": seq,
        "source_ref": SOURCE, "observer_ref": "lab.actor.anima",
        "coverage": {"kind": "view_cone", "fov_degrees": 90,
                     "range_limit": "none", "occlusion": "opaque_grid_cells"},
        "readings": [
            {"entity_ref": "lab.item.crate", "category": "item",
             "bearing_mdeg": 0, "range_milli_cells": 2000,
             "properties": {"owner": {"status": "absent", "value": None}}},
        ],
    }


def make_action(seq, rev, op, kind, direction):
    return EgocentricAction({
        "schema": VIEW_ACTION_SCHEMA, "world_instance_id": WORLD,
        "epoch": 1, "expected_revision": rev,
        "observation_id": f"worldobs:{WORLD}:1:{seq}",
        "operation_id": op, "action_type": kind,
        "arguments": {"direction": direction},
    })


def receipt(action, *, applied=True, tick=None, revision=None):
    a = action.as_dict()
    before = a["expected_revision"]
    return {
        "schema": "anima.lifecycle.world_receipt/0.1",
        "world_instance_id": WORLD, "epoch": 1,
        "operation_id": a["operation_id"],
        "status": "APPLIED" if applied else "BLOCKED",
        "effect_applied": applied,
        "reason": "ok" if applied else "occupied",
        "revision": (before + int(applied)) if revision is None else revision,
        "tick": (before + 1) if tick is None else tick,
        "event_id": "lifecycle_evt:1", "replayed": False,
    }


def setup(tmp_path, monkeypatch, observations):
    def sense(_observer):
        return observations.pop(0)

    from labs.virtual_anima_lab.python.lifecycle.egocentric import EgocentricView
    monkeypatch.setattr(E23ObserverPort, "observe",
                        lambda _observer: EgocentricView(sense(_observer)))
    core = build_core(
        tmp_path,
        sources={SOURCE: vision_source_registration()},
        properties={(SUBJECT, PREDICATE): vision_digest_rule()},
    )
    return E24WorkingMemory(core, E23ObserverPort(port=46029, observer_key=KEY))


def fake_readback(monkeypatch, status_factory):
    class Client:
        def __init__(self, *args, **kwargs):
            assert kwargs["role"] == "agent"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def call(self, name, **kwargs):
            assert name == "operation_status"
            assert kwargs["auth"] == KEY
            x = kwargs["action"]
            return {"data": status_factory(x)}

    monkeypatch.setattr("labs.virtual_anima_lab.python.lifecycle.e24_pose.LabClient", Client)


def status_for(action, output):
    return {
        "schema": "anima.lifecycle.world_operation_status/0.1",
        "world_instance_id": WORLD, "epoch": 1,
        "operation_id": action["operation_id"],
        "status": "RECORDED", "receipt": output,
    }


def test_turn_step_trajectory_uses_only_verified_effects(tmp_path, monkeypatch):
    memory = setup(tmp_path, monkeypatch, [
        view(1, 0, 0), view(2, 1, 1), view(3, 2, 2),
    ])
    pose = E24PoseTrail(memory, port=46029, executor_key=KEY)
    memory.observe_and_record()
    action1 = make_action(1, 0, "turn1", "world.turn", "right")
    fake_readback(monkeypatch, lambda action: status_for(action, receipt(action1, tick=1)))
    pose.record_verified_external_action(action1)
    pending = pose.reconstruct()
    assert pending["pending_next_sensor"] == ["turn1"]
    assert len(pending["verified_transitions"]) == 0
    assert pending["poses"][0]["relative_heading_quadrants"] == 0
    memory.observe_and_record()
    turned = pose.reconstruct()
    assert turned["poses"][-1]["relative_heading_quadrants"] == 1
    assert turned["poses"][-1]["local_right_steps"] == 0
    action2 = make_action(2, 1, "step1", "world.step", "forward")
    fake_readback(monkeypatch, lambda action: status_for(action, receipt(action2, tick=2)))
    pose.record_verified_external_action(action2)
    memory.observe_and_record()
    resolved = pose.reconstruct()
    assert len(resolved["verified_transitions"]) == 2
    assert resolved["pending_next_sensor"] == []
    assert resolved["poses"][-1]["local_right_steps"] == 1
    assert resolved["poses"][-1]["local_forward_steps"] == 0
    assert resolved["hidden_godot_coordinates_used"] is False
    assert resolved["not_stage6_authorized"] is True
    # Reopening the exact Core identity does not lose verified viewpoint trace.
    reopened = E24WorkingMemory(build_core(
        tmp_path, sources={SOURCE: vision_source_registration()},
        properties={(SUBJECT, PREDICATE): vision_digest_rule()},
    ), E23ObserverPort(port=46029, observer_key=KEY))
    assert E24PoseTrail(reopened, port=46029, executor_key=KEY).reconstruct() == resolved


def test_blocked_step_does_not_move_local_pose(tmp_path, monkeypatch):
    memory = setup(tmp_path, monkeypatch, [view(1, 0, 0), view(2, 0, 1)])
    pose = E24PoseTrail(memory, port=46029, executor_key=KEY)
    memory.observe_and_record()
    action = make_action(1, 0, "blocked1", "world.step", "forward")
    fake_readback(monkeypatch, lambda x: status_for(x, receipt(action, applied=False, tick=1)))
    pose.record_verified_external_action(action)
    memory.observe_and_record()
    model = pose.reconstruct()
    assert model["poses"][-1]["local_forward_steps"] == 0
    assert model["verified_transitions"][0]["effect_applied"] is False


def test_without_action_readback_state_change_is_not_local_motion(tmp_path, monkeypatch):
    memory = setup(tmp_path, monkeypatch, [view(1, 0, 0), view(2, 1, 1)])
    pose = E24PoseTrail(memory, port=46029, executor_key=KEY)
    memory.observe_and_record()
    memory.observe_and_record()
    with pytest.raises(E24PoseError, match="without a verified"):
        pose.reconstruct()


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(status="UNKNOWN", receipt=None),
    lambda s: s["receipt"].update(event_id="x"),
    lambda s: s["receipt"].update(replayed=True),
    lambda s: s["receipt"].update(revision=77),
    lambda s: s["receipt"].update(tick=77),
    lambda s: s["receipt"].update(effect_applied=False),
    lambda s: s.update(world_instance_id="b" * 32),
    lambda s: s.update(schema="unknown"),
])
def test_malicious_or_stale_readback_rejected(tmp_path, monkeypatch, mutation):
    memory = setup(tmp_path, monkeypatch, [view(1, 0, 0)])
    pose = E24PoseTrail(memory, port=46029, executor_key=KEY)
    memory.observe_and_record()
    action = make_action(1, 0, "turn1", "world.turn", "right")
    fake = status_for(action.as_dict(), receipt(action, tick=1))
    mutation(fake)
    fake_readback(monkeypatch, lambda _: fake)
    with pytest.raises(E24PoseError):
        pose.record_verified_external_action(action)
    assert pose.reconstruct()["pending_next_sensor"] == []


def test_trajectory_refuses_corrupt_recorded_receipt(tmp_path, monkeypatch):
    memory = setup(tmp_path, monkeypatch, [view(1, 0, 0), view(2, 1, 1)])
    pose = E24PoseTrail(memory, port=46029, executor_key=KEY)
    memory.observe_and_record()
    action = make_action(1, 0, "turn1", "world.turn", "right")
    fake_readback(monkeypatch, lambda x: status_for(x, receipt(action, tick=1)))
    pose.record_verified_external_action(action)
    memory.observe_and_record()
    with sqlite3.connect(memory._file) as db:
        db.execute("UPDATE e24b_viewpoint_actions SET receipt_json='{}'")
    with pytest.raises(E24PoseError, match="receipt modified"):
        pose.reconstruct()


def test_next_raw_must_match_verified_receipt_clocks(tmp_path, monkeypatch):
    memory = setup(tmp_path, monkeypatch, [view(1, 0, 0), view(2, 0, 1)])
    pose = E24PoseTrail(memory, port=46029, executor_key=KEY)
    memory.observe_and_record()
    action = make_action(1, 0, "turn1", "world.turn", "right")
    fake_readback(monkeypatch, lambda x: status_for(x, receipt(action, tick=1)))
    pose.record_verified_external_action(action)
    memory.observe_and_record()
    with pytest.raises(E24PoseError, match="did not confirm"):
        pose.reconstruct()


def test_no_unknown_second_action_without_observation(tmp_path, monkeypatch):
    memory = setup(tmp_path, monkeypatch, [view(1, 0, 0)])
    pose = E24PoseTrail(memory, port=46029, executor_key=KEY)
    memory.observe_and_record()
    action = make_action(1, 0, "turn1", "world.turn", "right")
    fake_readback(monkeypatch, lambda x: status_for(x, receipt(action, tick=1)))
    pose.record_verified_external_action(action)
    with pytest.raises(E24PoseError, match="multiple effects"):
        pose.record_verified_external_action(
            make_action(1, 0, "turn2", "world.turn", "right")
        )
