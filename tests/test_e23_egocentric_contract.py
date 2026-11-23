"""E2.3 negative DTO and guarded observer boundary tests; no live Godot required."""
from __future__ import annotations

from copy import deepcopy

import pytest

from labs.virtual_anima_lab.python.lifecycle.contracts import WorldContractError
from labs.virtual_anima_lab.python.lifecycle.egocentric import (
    EgocentricAction, EgocentricView, E23ObserverPort,
    VIEW_SCHEMA, VIEW_ACTION_SCHEMA,
)

W = "a" * 32
KEY = "o" * 43


def sample():
    return {
        "schema": VIEW_SCHEMA, "world_instance_id": W,
        "epoch": 1, "revision": 0, "tick": 0,
        "sample_seq": 1, "sample_id": f"worldobs:{W}:1:1",
        "observer_ref": "lab.actor.anima",
        "source_ref": "lab.sensor.anima.vision",
        "coverage": {"kind": "view_cone", "fov_degrees": 90,
                     "range_limit": "none", "occlusion": "opaque_grid_cells"},
        "readings": [{
            "entity_ref": "lab.surface." + "1" * 24, "category": "surface",
            "bearing_mdeg": -45000, "range_milli_cells": 1414, "properties": {},
        }],
    }


def action(kind="world.turn", direction="left"):
    return {
        "schema": VIEW_ACTION_SCHEMA, "world_instance_id": W,
        "epoch": 1, "expected_revision": 0,
        "observation_id": f"worldobs:{W}:1:1",
        "operation_id": "op_123", "action_type": kind,
        "arguments": {"direction": direction},
    }


def test_view_canonical_and_sealed():
    source = sample()
    view = EgocentricView(source)
    source["readings"][0]["bearing_mdeg"] = 0
    assert view.as_dict()["readings"][0]["bearing_mdeg"] == -45000
    with pytest.raises(AttributeError):
        view._json = "{}"
    assert EgocentricView(view.as_dict()).canonical_json == view.canonical_json


@pytest.mark.parametrize("change", [
    lambda s: s.update(self_position={"x": 3, "y": 5}),
    lambda s: s["readings"][0].update(cell={"x": 3, "y": 5}),
    lambda s: s["readings"][0].update(entity_ref="lab.wall.3.4"),
    lambda s: s["readings"][0].update(entity_ref="lab.surface.3.4"),
    lambda s: s["readings"][0].update(entity_ref="lab.surface." + "f" * 24,
                                      bearing_mdeg=45_001),
    lambda s: s["readings"][0].update(range_milli_cells=0),
    lambda s: s["coverage"].update(fov_degrees=360),
    lambda s: s["coverage"].update(kind="full_map"),
    lambda s: s.update(sample_id=f"worldobs:{W}:1:2"),
    lambda s: s.update(sample_seq=True),
    lambda s: s.update(readings=s["readings"] * 2),
    lambda s: s["readings"][0].update(properties={"owner": {"status": "known", "value": W}}),
])
def test_view_rejects_absolute_leaks_and_forgery(change):
    value = sample()
    change(value)
    with pytest.raises(WorldContractError):
        EgocentricView(value)


def test_item_owner_status_and_unknown_not_absence():
    value = sample()
    value["readings"] = [{
        "entity_ref": "lab.item.crate", "category": "item",
        "bearing_mdeg": 10_000, "range_milli_cells": 5000,
        "properties": {"owner": {"status": "absent", "value": None}},
    }]
    EgocentricView(value)
    value["readings"][0]["properties"]["owner"] = {"status": "unknown", "value": None}
    with pytest.raises(WorldContractError):
        EgocentricView(value)
    value["readings"][0]["properties"]["owner"] = {
        "status": "known", "value": "lab.actor.anima",
    }
    EgocentricView(value)


def test_versioned_turn_step_and_disallowed_action():
    EgocentricAction(action())
    EgocentricAction(action("world.step", "forward"))
    for kind, direction in [("world.turn", "forward"),
                            ("world.step", "left"), ("world.move", "N")]:
        with pytest.raises(WorldContractError):
            EgocentricAction(action(kind, direction))
    invalid = action()
    invalid["schema"] = "anima.lifecycle.world_action/0.1"
    with pytest.raises(WorldContractError):
        EgocentricAction(invalid)


def test_observer_requires_guarded_key():
    with pytest.raises(ValueError):
        E23ObserverPort(port=46029, observer_key="weak")


def test_observer_pins_world_epoch_and_rejects_stale_sample(monkeypatch):
    calls = {"index": 0, "epoch": 1, "caps": ["observe_view"]}

    class Client:
        def __init__(self, *args, **kwargs):
            assert kwargs["role"] == "agent"
            assert kwargs["protocol"] == "val.bridge/0.2"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def call(self, name, **kwargs):
            assert kwargs == {"auth": KEY}
            if name == "hello":
                return {"data": {"world_instance_id": W, "epoch": calls["epoch"],
                                 "auth_mode": "guarded", "capabilities": calls["caps"]}}
            assert name == "observe_view"
            value = sample()
            value["epoch"] = calls["epoch"]
            value["sample_seq"] = calls["index"] + 1
            value["sample_id"] = f"worldobs:{W}:{calls['epoch']}:{calls['index'] + 1}"
            return {"data": value}

    monkeypatch.setattr(
        "labs.virtual_anima_lab.python.lifecycle.egocentric.LabClient", Client
    )
    port = E23ObserverPort(port=46029, observer_key=KEY)
    assert port.observe().as_dict()["sample_seq"] == 1
    with pytest.raises(WorldContractError, match="cursor"):
        port.observe()
    calls["index"] = 1
    assert port.observe().as_dict()["sample_seq"] == 2
    calls["epoch"] = 2
    with pytest.raises(WorldContractError, match="epoch"):
        port.observe()


def test_observer_refuses_legacy_unsafe_capability(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def call(self, name, **kwargs):
            assert name == "hello"
            return {"data": {"world_instance_id": W, "epoch": 1, "auth_mode": "guarded",
                             "capabilities": ["observe", "observe_view"]}}

    monkeypatch.setattr(
        "labs.virtual_anima_lab.python.lifecycle.egocentric.LabClient", Client
    )
    with pytest.raises(WorldContractError, match="capabilities"):
        E23ObserverPort(port=46029, observer_key=KEY).observe()
