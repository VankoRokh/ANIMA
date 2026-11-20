"""E1.1 contract checks; no Godot effects and no release-Core mutation."""
import copy
import pytest
from labs.virtual_anima_lab.python.lifecycle.contracts import (
    WorldAction, WorldObservation, WorldReceipt, WorldOperationStatus,
    WorldContractError, OBSERVATION_SCHEMA, ACTION_SCHEMA, RECEIPT_SCHEMA,
    OPERATION_STATUS_SCHEMA,
)

WORLD = "a" * 32
SAMPLE = f"worldobs:{WORLD}:1:1"


def observation():
    return {"schema": OBSERVATION_SCHEMA, "world_instance_id": WORLD, "epoch": 1,
            "revision": 2, "tick": 9, "sample_seq": 1, "sample_id": SAMPLE,
            "observer_ref": "lab.actor.anima", "source_ref": "lab.sensor.anima.proximity",
            "visibility": {"kind": "manhattan_radius", "radius": 3},
            "self_position": {"x": 3, "y": 3}, "readings": [
                {"subject_ref": "lab.item.box", "predicate_ref": "position", "status": "known",
                 "value": {"type": "grid_cell", "x": 4, "y": 3}, "cell": {"x": 4, "y": 3}},
                {"subject_ref": "lab.item.box", "predicate_ref": "owner", "status": "unknown",
                 "value": None, "cell": {"x": 4, "y": 3}},
                {"subject_ref": "lab.actor.anima", "predicate_ref": "energy", "status": "known",
                 "value": {"type": "integer", "value": 85}, "cell": {"x": 3, "y": 3}},
            ]}


def action():
    return {"schema": ACTION_SCHEMA, "world_instance_id": WORLD, "epoch": 1,
            "expected_revision": 2, "observation_id": SAMPLE,
            "operation_id": "op.demo.1", "action_type": "world.move",
            "arguments": {"direction": "N"}}


def receipt():
    return {"schema": RECEIPT_SCHEMA, "world_instance_id": WORLD, "epoch": 1,
            "operation_id": "op.demo.1", "status": "APPLIED", "effect_applied": True,
            "reason": "ok", "revision": 3, "tick": 10, "event_id": "worldevent.1",
            "replayed": False}


def status():
    return {"schema": OPERATION_STATUS_SCHEMA, "world_instance_id": WORLD,
            "epoch": 1, "operation_id": "op.demo.1", "status": "RECORDED",
            "receipt": receipt()}


def test_valid_dtos_and_deep_immutable_capture():
    for value, cls in [(observation(), WorldObservation), (action(), WorldAction),
                       (receipt(), WorldReceipt), (status(), WorldOperationStatus)]:
        original = copy.deepcopy(value)
        dto = cls(value)
        value.clear()
        assert dto.as_dict() == original
        result = dto.as_dict()
        result.clear()
        assert dto.as_dict() == original
        with pytest.raises(AttributeError):
            dto._json = "rewritten"


def test_unknown_absent_unavailable_are_not_truth_values():
    for state in ("unknown", "absent", "unavailable"):
        data = observation()
        data["readings"][1]["status"] = state
        WorldObservation(data)
        data["readings"][1]["value"] = {"type": "ref", "value": "lab.actor.human"}
        with pytest.raises(WorldContractError):
            WorldObservation(data)


@pytest.mark.parametrize("change", [
    lambda o: o.update(extra="debug_truth"),
    lambda o: o.update(epoch=True),
    lambda o: o.update(sample_seq=2),
    lambda o: o.update(world_instance_id="unknown"),
    lambda o: o["readings"][0]["value"].update(x=5),
    lambda o: o["readings"][0].update(cell={"x": 7, "y": 3}),
    lambda o: o["readings"][0].update(status="unknown"),
    lambda o: o["readings"][2]["value"].update(value=True),
    lambda o: o["readings"].append(copy.deepcopy(o["readings"][0])),
    lambda o: o["visibility"].update(radius=128),
])
def test_invalid_observations_fail_closed(change):
    data = observation()
    change(data)
    with pytest.raises(WorldContractError):
        WorldObservation(data)


@pytest.mark.parametrize("change", [
    lambda a: a.update(action_type="fs.delete"),
    lambda a: a["arguments"].update(path="/etc"),
    lambda a: a.update(observation_id="worldobs:" + "b" * 32 + ":1:1"),
    lambda a: a.update(expected_revision=1.0),
    lambda a: a.update(operation_id=""),
    lambda a: a.update(observation_id=f"worldobs:{WORLD}:1:" + "9" * 600),
    lambda a: a.update(observation_id=f"worldobs:{WORLD}:1:²"),
    lambda a: a["arguments"].update(direction="UP"),
])
def test_invalid_actions_fail_closed(change):
    data = action()
    change(data)
    with pytest.raises(WorldContractError):
        WorldAction(data)


def test_item_capabilities_and_status_identity():
    for kind in ("world.pick", "world.drop"):
        data = action()
        data["action_type"] = kind
        data["arguments"] = {"item_ref": "lab.item.box"}
        WorldAction(data)
    WorldOperationStatus(status())
    unknown = status()
    unknown["status"] = "UNKNOWN"
    unknown["receipt"] = None
    WorldOperationStatus(unknown)
    unknown["receipt"] = receipt()
    with pytest.raises(WorldContractError):
        WorldOperationStatus(unknown)
    wrong = status()
    wrong["receipt"]["operation_id"] = "op.other"
    with pytest.raises(WorldContractError):
        WorldOperationStatus(wrong)


def test_receipt_is_not_independent_proof():
    WorldReceipt(receipt())  # Valid shape, but does not verify movement or Goal completion.
    bad = receipt()
    bad["effect_applied"] = False
    with pytest.raises(WorldContractError):
        WorldReceipt(bad)
