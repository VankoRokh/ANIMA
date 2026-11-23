"""E2.3 opt-in egocentric sensor DTO and trusted observer port.

Lab-only: never grants action authority, never exposes Godot world truth,
and is NOT yet the E2.2 durable full-Raw/Core ingestion path.
"""
from __future__ import annotations

import json
import re
from typing import Any

from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .contracts import WorldContractError, _SealedDTO, _check, _int, _object, _ref, _world_identity

VIEW_SCHEMA = "anima.lifecycle.egocentric_observation/0.1"
VIEW_ACTION_SCHEMA = "anima.lifecycle.egocentric_action/0.1"
_FOV = 90
_WORLD_ID = re.compile(r"[a-f0-9]{32}\Z")
_KEY = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_SURFACE_ID = re.compile(r"lab\.(surface|obstacle)\.[a-f0-9]{24}\Z")
_CATEGORIES = {"surface", "obstacle", "item", "zone", "landmark"}


def _validate_view(value: Any) -> None:
    data = _object(value, {
        "schema", "world_instance_id", "epoch", "revision", "tick",
        "sample_seq", "sample_id", "observer_ref", "source_ref", "coverage", "readings",
    }, "EgocentricView")
    _check(data["schema"] == VIEW_SCHEMA, "view schema")
    _check(type(data["world_instance_id"]) is str and
           _WORLD_ID.fullmatch(data["world_instance_id"]) is not None, "view world ID")
    _int(data["epoch"], "epoch", minimum=1)
    _int(data["revision"], "revision")
    _int(data["tick"], "tick")
    _int(data["sample_seq"], "sample_seq", minimum=1)
    _check(data["sample_id"] ==
           f"worldobs:{data['world_instance_id']}:{data['epoch']}:{data['sample_seq']}",
           "view sample identity")
    _check(data["observer_ref"] == "lab.actor.anima" and
           data["source_ref"] == "lab.sensor.anima.proximity", "view source binding")
    cov = _object(data["coverage"],
                  {"kind", "fov_degrees", "range_limit", "occlusion"}, "coverage")
    _check(cov == {"kind": "view_cone", "fov_degrees": _FOV,
                   "range_limit": "none", "occlusion": "opaque_grid_cells"}, "view coverage")
    rows = data["readings"]
    _check(type(rows) is list and len(rows) <= 128, "view readings count")
    refs = set()
    for row in rows:
        row = _object(row, {
            "entity_ref", "category", "bearing_mdeg", "range_milli_cells", "properties",
        }, "view reading")
        category = row["category"]
        _check(type(category) is str and category in _CATEGORIES, "reading category")
        entity = _ref(row["entity_ref"], "reading entity", prefix="lab.")
        _check(entity not in refs, "duplicate view entity")
        refs.add(entity)
        if category in ("surface", "obstacle") and entity != "lab.obstacle.shortcut":
            _check(_SURFACE_ID.fullmatch(entity) is not None and
                   entity.startswith("lab." + category + "."), "opaque object identity")
        else:
            allowed = {"item": "lab.item.crate", "zone": "lab.zone.delivery",
                       "landmark": "lab.landmark.marker", "obstacle": "lab.obstacle.shortcut"}
            _check(entity == allowed.get(category), "view entity category")
        bearing = row["bearing_mdeg"]
        distance = row["range_milli_cells"]
        _check(type(bearing) is int and -45_000 <= bearing <= 45_000, "reading outside view cone")
        _check(type(distance) is int and 1 <= distance <= 100_000, "invalid relative distance")
        props = row["properties"]
        _check(type(props) is dict, "invalid reading properties")
        if category == "item":
            _check(set(props) == {"owner"}, "item requires owner")
            owner = _object(props["owner"], {"status", "value"}, "item owner")
            _check(owner["status"] in ("known", "absent"), "owner status")
            if owner["status"] == "known":
                _check(owner["value"] == "lab.actor.anima", "untrusted owner")
            else:
                _check(owner["value"] is None, "absent owner must lack value")
        else:
            _check(not props, "unexpected properties in view")


def _validate_ego_action(value: Any) -> None:
    action = _object(value, {
        "schema", "world_instance_id", "epoch", "expected_revision",
        "observation_id", "operation_id", "action_type", "arguments",
    }, "E2.3 action")
    _check(action["schema"] == VIEW_ACTION_SCHEMA, "E2.3 action schema")
    _check(type(action["world_instance_id"]) is str and
           _WORLD_ID.fullmatch(action["world_instance_id"]) is not None, "E2.3 world ID")
    _int(action["epoch"], "epoch", minimum=1)
    _int(action["expected_revision"], "expected_revision")
    _ref(action["operation_id"], "operation_id")
    _check(type(action["observation_id"]) is str and
           action["observation_id"].startswith(
               f"worldobs:{action['world_instance_id']}:{action['epoch']}:"),
           "E2.3 observation identity")
    op = action["action_type"]
    args = _object(action["arguments"], {"direction"}, "E2.3 arguments")
    _check((op == "world.turn" and args["direction"] in ("left", "right")) or
           (op == "world.step" and args["direction"] == "forward"), "E2.3 action type")


class EgocentricView(_SealedDTO):
    _validator = staticmethod(_validate_view)

    @property
    def sample_id(self) -> str:
        return self.as_dict()["sample_id"]


class EgocentricAction(_SealedDTO):
    _validator = staticmethod(_validate_ego_action)


class E23ObserverPort:
    """A guarded sensor-only port with in-process world/epoch/clock pinning.

    Distinct from the durable E2.2 gateway: no CoreIngress, no persistence;
    the trust boundary is lab-controlled, not hardened against same-UID code.
    """

    def __init__(self, *, port: int, observer_key: str):
        if type(observer_key) is not str or _KEY.fullmatch(observer_key) is None:
            raise ValueError("E2.3 observer requires a strong guarded key")
        self.port = port
        self._key = observer_key
        self._world: str | None = None
        self._epoch: int | None = None
        self._last_sample = 0

    def observe(self) -> EgocentricView:
        with LabClient(self.port, role="agent", protocol=PROTOCOL_V2) as client:
            hello = client.call("hello", auth=self._key)["data"]
            _check(hello.get("auth_mode") == "guarded" and
                   hello.get("capabilities") == ["observe_view"], "unsafe sensor capabilities")
            _check(type(hello.get("world_instance_id")) is str and
                   _WORLD_ID.fullmatch(hello["world_instance_id"]) is not None, "hello world")
            _int(hello.get("epoch"), "hello epoch", minimum=1)
            if self._world is not None:
                _check((hello["world_instance_id"], hello["epoch"]) ==
                       (self._world, self._epoch), "view world/epoch changed")
            observed = client.call("observe_view", auth=self._key)["data"]
        view = EgocentricView(observed)
        item = view.as_dict()
        _check((item["world_instance_id"], item["epoch"]) ==
               (hello["world_instance_id"], hello["epoch"]), "view/hello mismatch")
        _check(item["sample_seq"] > self._last_sample, "view sample cursor not monotonic")
        self._world, self._epoch = item["world_instance_id"], item["epoch"]
        self._last_sample = item["sample_seq"]
        return view


__all__ = ["VIEW_SCHEMA", "VIEW_ACTION_SCHEMA", "EgocentricView",
           "EgocentricAction", "E23ObserverPort"]
