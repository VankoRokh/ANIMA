"""E1.3 evidence checks: receipts are never sufficient for success."""
import copy

import pytest

from labs.virtual_anima_lab.python.lifecycle.contracts import (
    ACTION_SCHEMA, OBSERVATION_SCHEMA, RECEIPT_SCHEMA,
    WorldAction, WorldObservation, WorldReceipt,
)
from labs.virtual_anima_lab.python.lifecycle.world_verification import verify_world_effect

WORLD = "a" * 32
ACTOR = "lab.actor.anima"
ITEM = "lab.item.crate"


def observation(
    *, position=(3, 5), item=(4, 5), owner=None, epoch=1,
    revision=0, tick=0, sample=1, world=WORLD,
):
    reading = []
    if abs(item[0] - position[0]) + abs(item[1] - position[1]) <= 3:
        reading = [
            {"subject_ref": ITEM, "predicate_ref": "position", "status": "known",
             "value": {"type": "grid_cell", "x": item[0], "y": item[1]},
             "cell": {"x": item[0], "y": item[1]}},
            {"subject_ref": ITEM, "predicate_ref": "owner",
             "status": "known" if owner is not None else "absent",
             "value": {"type": "ref", "value": owner} if owner else None,
             "cell": {"x": item[0], "y": item[1]}},
        ]
    if position == (10, 5):
        reading.append({
            "subject_ref": "lab.zone.delivery", "predicate_ref": "position",
            "status": "known",
            "value": {"type": "grid_cell", "x": 10, "y": 5},
            "cell": {"x": 10, "y": 5},
        })
    return WorldObservation({
        "schema": OBSERVATION_SCHEMA, "world_instance_id": world, "epoch": epoch,
        "revision": revision, "tick": tick, "sample_seq": sample,
        "sample_id": f"worldobs:{world}:{epoch}:{sample}",
        "observer_ref": ACTOR, "source_ref": "lab.sensor.anima.proximity",
        "visibility": {"kind": "line_of_sight", "radius": 3},
        "self_position": {"x": position[0], "y": position[1]},
        "readings": reading,
    })


def action(before, kind="world.move", args=None, operation="op.e13.1"):
    b = before.as_dict()
    if args is None:
        args = {"direction": "E"} if kind == "world.move" else {"item_ref": ITEM}
    return WorldAction({
        "schema": ACTION_SCHEMA,
        "world_instance_id": b["world_instance_id"], "epoch": b["epoch"],
        "expected_revision": b["revision"], "observation_id": b["sample_id"],
        "operation_id": operation, "action_type": kind, "arguments": args,
    })


def receipt(before, act, *, applied=True, revision=None, tick=None, world=None):
    b = before.as_dict()
    return WorldReceipt({
        "schema": RECEIPT_SCHEMA,
        "world_instance_id": world or b["world_instance_id"],
        "epoch": b["epoch"], "operation_id": act.as_dict()["operation_id"],
        "status": "APPLIED" if applied else "BLOCKED",
        "effect_applied": applied, "reason": "ok" if applied else "occupied",
        "revision": b["revision"] + int(applied) if revision is None else revision,
        "tick": b["tick"] + 1 if tick is None else tick,
        "event_id": "lifecycle_evt:7", "replayed": False,
    })


def test_move_requires_fresh_position_and_world_binding():
    before = observation()
    act = action(before)
    rx = receipt(before, act)
    after = observation(position=(4, 5), revision=1, tick=1, sample=2)
    assert verify_world_effect(before, act, rx, after).status == "VERIFIED_SUCCESS"
    for changed, reason in [
        (observation(revision=1, tick=1, sample=2), "MOVE_NOT_OBSERVED"),
        (observation(position=(4, 5), revision=1, tick=1, sample=1), "READBACK_NOT_FRESH"),
        (observation(position=(4, 5), revision=1, tick=1, sample=2, epoch=2),
         "WORLD_OR_EPOCH_MISMATCH"),
        (observation(position=(4, 5), revision=2, tick=2, sample=2),
         "INTERVENING_WORLD_MUTATION"),
    ]:
        proof = verify_world_effect(before, act, rx, changed)
        assert not proof.success and proof.reason == reason


def test_pick_and_drop_and_delivery_use_item_ownership_sensor():
    before = observation()
    pick = action(before, "world.pick")
    carrying = observation(position=(3, 5), item=(3, 5), owner=ACTOR,
                           revision=1, tick=1, sample=2)
    proof = verify_world_effect(before, pick, receipt(before, pick), carrying)
    assert proof.success and not proof.delivery_verified
    not_picked = observation(position=(3, 5), item=(4, 5), owner=None,
                             revision=1, tick=1, sample=2)
    assert verify_world_effect(before, pick, receipt(before, pick),
                               not_picked).reason == "PICK_NOT_OBSERVED"

    before_drop = observation(position=(10, 5), item=(10, 5), owner=ACTOR,
                              revision=7, tick=7, sample=8)
    drop = action(before_drop, "world.drop")
    after_drop = observation(position=(10, 5), item=(10, 5), owner=None,
                             revision=8, tick=8, sample=9)
    proof = verify_world_effect(before_drop, drop, receipt(before_drop, drop),
                                after_drop)
    assert proof.success and proof.delivery_verified
    forged_drop = observation(position=(10, 5), item=(10, 5), owner=ACTOR,
                              revision=8, tick=8, sample=9)
    assert not verify_world_effect(
        before_drop, drop, receipt(before_drop, drop), forged_drop
    ).success


def test_blocked_and_lost_or_forged_receipts_fail_closed():
    before = observation()
    act = action(before)
    blocked = receipt(before, act, applied=False)
    after = observation(tick=1, sample=2)
    assert verify_world_effect(before, act, blocked, after).status == "VERIFIED_BLOCKED"
    # The world says BLOCKED, but sensor sees a moved actor.
    suspicious = observation(position=(4, 5), tick=1, sample=2)
    assert verify_world_effect(before, act, blocked, suspicious).status == "UNVERIFIED"
    # The world claims APPLIED, but post-state has not changed.
    fake = receipt(before, act, applied=True)
    assert verify_world_effect(before, act, fake, observation(revision=1, tick=1, sample=2)).status == "UNVERIFIED"
    # Receipt is structurally valid but from the wrong world.
    wrong_world = receipt(before, act, world="b" * 32)
    assert verify_world_effect(before, act, wrong_world, suspicious).reason == "WORLD_OR_EPOCH_MISMATCH"
    # Mismatched operation means the receipt cannot prove this action.
    bad = copy.deepcopy(fake.as_dict())
    bad["operation_id"] = "op.other"
    assert verify_world_effect(before, act, WorldReceipt(bad), suspicious).reason == "OPERATION_MISMATCH"


def test_stale_intent_and_carried_item_loss():
    before = observation(position=(3, 5), item=(3, 5), owner=ACTOR)
    act = action(before)
    changed = observation(position=(4, 5), item=(3, 5), owner=ACTOR,
                          revision=1, tick=1, sample=2)
    assert verify_world_effect(before, act, receipt(before, act),
                               changed).reason == "CARRIED_ITEM_LOST"
    src = act.as_dict()
    src["expected_revision"] = 1
    assert verify_world_effect(before, WorldAction(src), receipt(before, act),
                               changed).reason == "INTENT_NOT_BOUND_TO_BEFORE"


def test_same_sample_and_mutated_receipt_cannot_establish_success():
    before = observation()
    act = action(before)
    data = receipt(before, act).as_dict()
    data["replayed"] = True
    after = observation(position=(4, 5), revision=1, tick=1, sample=2)
    # E1.3 must not certify replay as new effect evidence; replay belongs to E1.4.
    assert verify_world_effect(before, act, WorldReceipt(data), after).status == "UNVERIFIED"
