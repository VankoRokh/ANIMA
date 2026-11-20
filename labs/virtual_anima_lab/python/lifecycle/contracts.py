"""E1.1 laboratory-only, fail-closed DTOs for a simulated world.

World clock domains are deliberately distinct: world_instance_id identifies a
world process incarnation; epoch identifies a reset; revision changes on world
state mutation; tick advances with simulated time; sample_seq identifies an
observation, independent of tick. None is a UTC timestamp or a Core belief
revision. These DTOs validate format, never authenticate a producer, confer
execution authority, or prove a world effect.
"""
from __future__ import annotations

import json
import re
from typing import Any

OBSERVATION_SCHEMA = "anima.lifecycle.world_observation/0.1"
ACTION_SCHEMA = "anima.lifecycle.world_action/0.1"
RECEIPT_SCHEMA = "anima.lifecycle.world_receipt/0.1"
OPERATION_STATUS_SCHEMA = "anima.lifecycle.world_operation_status/0.1"
_MAX_CLOCK = 2**63 - 1
_REF = re.compile(r"[A-Za-z][A-Za-z0-9._:/-]{0,127}\Z")
_WORLD_ID = re.compile(r"[a-f0-9]{32}\Z")


class WorldContractError(ValueError):
    """Malformed or unsupported world DTO; fail before any effect."""


def _check(ok: bool, message: str) -> None:
    if not ok:
        raise WorldContractError(message)


def _object(value: Any, fields: set[str], label: str) -> dict:
    _check(type(value) is dict and set(value) == fields, f"{label}: exact fields required")
    return value


def _int(value: Any, label: str, *, minimum: int = 0) -> int:
    _check(type(value) is int and minimum <= value <= _MAX_CLOCK, f"{label}: invalid integer")
    return value


def _ref(value: Any, label: str, *, prefix: str | None = None) -> str:
    _check(type(value) is str and _REF.fullmatch(value) is not None, f"{label}: invalid ref")
    if prefix is not None:
        _check(value.startswith(prefix), f"{label}: unsupported namespace")
    return value


def _world_identity(data: dict, *, revision_field: str = "revision") -> None:
    _check(type(data["world_instance_id"]) is str and _WORLD_ID.fullmatch(data["world_instance_id"]) is not None,
           "invalid world_instance_id")
    _int(data["epoch"], "epoch", minimum=1)
    _int(data[revision_field], revision_field)


def _cell(value: Any, label: str) -> tuple[int, int]:
    data = _object(value, {"x", "y"}, label)
    return _int(data["x"], f"{label}.x"), _int(data["y"], f"{label}.y")


def _sample_id(data: dict) -> str:
    return f"worldobs:{data['world_instance_id']}:{data['epoch']}:{data['sample_seq']}"


def _validate_observation(data: Any) -> None:
    fields = {"schema", "world_instance_id", "epoch", "revision", "tick", "sample_seq",
              "sample_id", "observer_ref", "source_ref", "visibility", "self_position", "readings"}
    data = _object(data, fields, "WorldObservation")
    _check(data["schema"] == OBSERVATION_SCHEMA, "observation schema mismatch")
    _world_identity(data)
    _int(data["tick"], "tick")
    _int(data["sample_seq"], "sample_seq", minimum=1)
    _check(data["sample_id"] == _sample_id(data), "sample identity mismatch")
    _check(_ref(data["observer_ref"], "observer_ref") == "lab.actor.anima", "wrong observer")
    _ref(data["source_ref"], "source_ref", prefix="lab.sensor.")
    v = _object(data["visibility"], {"kind", "radius"}, "visibility")
    _check(v["kind"] in ("manhattan_radius", "line_of_sight"), "unsupported visibility kind")
    radius = _int(v["radius"], "radius", minimum=1)
    _check(radius <= 32, "visibility radius too large")
    own = _cell(data["self_position"], "self_position")
    readings = data["readings"]
    _check(type(readings) is list and len(readings) <= 128, "readings limit")
    seen: set[tuple[str, str]] = set()
    for item in readings:
        item = _object(item, {"subject_ref", "predicate_ref", "status", "value", "cell"}, "reading")
        subject = _ref(item["subject_ref"], "subject_ref", prefix="lab.")
        predicate = item["predicate_ref"]
        _check(type(predicate) is str and predicate in ("position", "state", "energy", "owner"),
               "unsupported predicate")
        _check((subject, predicate) not in seen, "duplicate property in one sample")
        seen.add((subject, predicate))
        location = _cell(item["cell"], "reading.cell")
        _check(abs(location[0] - own[0]) + abs(location[1] - own[1]) <= radius,
               "reading outside sensor range")
        status = item["status"]
        _check(type(status) is str and status in ("known", "unknown", "absent", "unavailable"),
               "invalid observation status")
        value = item["value"]
        if status != "known":
            _check(value is None, "non-known observation cannot assert a value")
            continue
        _check(type(value) is dict, "known observation requires typed value")
        if predicate == "position":
            value = _object(value, {"type", "x", "y"}, "position.value")
            _check(value["type"] == "grid_cell", "position type mismatch")
            _check(_cell({"x": value["x"], "y": value["y"]}, "position.value") == location,
                   "position must match same-sample sensor cell")
        elif predicate == "energy":
            value = _object(value, {"type", "value"}, "energy.value")
            _check(value["type"] == "integer" and type(value["value"]) is int
                   and 0 <= value["value"] <= 100, "energy must be an integer percent")
        elif predicate == "owner":
            value = _object(value, {"type", "value"}, "owner.value")
            _check(value["type"] == "ref", "owner type mismatch")
            _ref(value["value"], "owner ref", prefix="lab.")
        else:
            value = _object(value, {"type", "value"}, "state.value")
            _check(value["type"] == "symbol", "state type mismatch")
            _ref(value["value"], "state symbol")


def _validate_action(data: Any) -> None:
    data = _object(data, {"schema", "world_instance_id", "epoch", "expected_revision",
                          "observation_id", "operation_id", "action_type", "arguments"}, "WorldAction")
    _check(data["schema"] == ACTION_SCHEMA, "action schema mismatch")
    _world_identity(data, revision_field="expected_revision")
    _ref(data["operation_id"], "operation_id")
    _check(type(data["observation_id"]) is str
           and data["observation_id"].startswith(f"worldobs:{data['world_instance_id']}:{data['epoch']}:")
           and data["observation_id"].rsplit(":", 1)[-1].isdigit()
           and int(data["observation_id"].rsplit(":", 1)[-1]) > 0,
           "action must reference observation in its world epoch")
    action = data["action_type"]
    _check(type(action) is str and action in ("world.move", "world.pick", "world.drop"),
           "action is not an allowed world capability")
    args = data["arguments"]
    if action == "world.move":
        args = _object(args, {"direction"}, "move.arguments")
        _check(type(args["direction"]) is str and args["direction"] in ("N", "S", "E", "W"),
               "unsupported movement direction")
    else:
        args = _object(args, {"item_ref"}, "item.arguments")
        _ref(args["item_ref"], "item_ref", prefix="lab.item.")


def _validate_receipt(data: Any) -> None:
    data = _object(data, {"schema", "world_instance_id", "epoch", "operation_id",
                          "status", "effect_applied", "reason", "revision", "tick",
                          "event_id", "replayed"}, "WorldReceipt")
    _check(data["schema"] == RECEIPT_SCHEMA, "receipt schema mismatch")
    _world_identity(data)
    _int(data["tick"], "tick")
    _ref(data["operation_id"], "operation_id")
    _ref(data["event_id"], "event_id")
    _check(data["status"] in ("APPLIED", "BLOCKED") and type(data["status"]) is str,
           "receipt status")
    _check(type(data["effect_applied"]) is bool and data["effect_applied"] == (data["status"] == "APPLIED"),
           "receipt effect/status mismatch")
    _check(type(data["reason"]) is str and 1 <= len(data["reason"]) <= 128,
           "receipt reason")
    _check(type(data["replayed"]) is bool, "receipt replay marker")


def _validate_operation_status(data: Any) -> None:
    data = _object(data, {"schema", "world_instance_id", "epoch", "operation_id",
                          "status", "receipt"}, "WorldOperationStatus")
    _check(data["schema"] == OPERATION_STATUS_SCHEMA, "status schema mismatch")
    _check(type(data["world_instance_id"]) is str and _WORLD_ID.fullmatch(data["world_instance_id"]) is not None,
           "status world ID")
    _int(data["epoch"], "epoch", minimum=1)
    _ref(data["operation_id"], "operation_id")
    _check(type(data["status"]) is str and data["status"] in ("RECORDED", "UNKNOWN"),
           "operation lookup state")
    if data["status"] == "UNKNOWN":
        _check(data["receipt"] is None, "UNKNOWN cannot assert effect")
    else:
        _validate_receipt(data["receipt"])
        _check(all(data[k] == data["receipt"][k] for k in
                   ("world_instance_id", "epoch", "operation_id")), "status/receipt identity mismatch")


class _SealedDTO:
    __slots__ = ("_json",)
    _validator = None

    def __init__(self, value: Any) -> None:
        self._validator(value)
        # Capturing the canonical bytes makes later caller mutation irrelevant.
        self._json = json.dumps(value, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False)

    def __setattr__(self, key, value):
        if hasattr(self, "_json"):
            raise AttributeError("sealed world DTO is immutable")
        object.__setattr__(self, key, value)

    @property
    def canonical_json(self) -> str:
        return self._json

    def as_dict(self) -> dict:
        return json.loads(self._json)


class WorldObservation(_SealedDTO):
    _validator = staticmethod(_validate_observation)

    @property
    def sample_id(self) -> str:
        return self.as_dict()["sample_id"]


class WorldAction(_SealedDTO):
    _validator = staticmethod(_validate_action)


class WorldReceipt(_SealedDTO):
    _validator = staticmethod(_validate_receipt)


class WorldOperationStatus(_SealedDTO):
    _validator = staticmethod(_validate_operation_status)


__all__ = ["WorldObservation", "WorldAction", "WorldReceipt", "WorldOperationStatus",
           "WorldContractError", "OBSERVATION_SCHEMA", "ACTION_SCHEMA", "RECEIPT_SCHEMA",
           "OPERATION_STATUS_SCHEMA"]
