"""P5-B Lab-only typed DTO validators. NOT ANIMA Core/Stage7 validators.

The external world is the truth owner. These rules reject malformed bridge
payloads before a future trusted P6 adapter considers registering evidence.
They do NOT authenticate the process or give source/system authority.
"""
from __future__ import annotations

from typing import Any

try:
    from .lab_client import _exact_protocol_integer
except ImportError:  # Direct script invocation from this directory.
    from lab_client import _exact_protocol_integer


class LabContractError(ValueError):
    """A well-formed JSON document violates the versioned Lab DTO."""


OBSERVATION_SCHEMA = "val.observation/0.1"
ACTION_SCHEMA = "val.action/0.1"
RECEIPT_SCHEMA = "val.receipt/0.1"
SOURCE = "lab.sensor.anima.proximity"
PRODUCER = "lab.godot"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LabContractError(message)


def _natural(value: Any, field: str) -> int:
    normalized = _exact_protocol_integer(value)
    _require(normalized is not None, f"{field} must be a nonnegative exact integer")
    return normalized


def _grid(value: Any, field: str) -> tuple[int, int]:
    _require(type(value) is dict, f"{field} must be a grid-cell object")
    _require(set(value) == {"x", "y"}, f"{field} grid-cell fields")
    x = _natural(value["x"], field + ".x")
    y = _natural(value["y"], field + ".y")
    _require(x < 12 and y < 8, f"{field} outside current P5-B world")
    return x, y


def validate_observation(data: Any, envelope: dict[str, Any]) -> dict[str, Any]:
    _require(type(data) is dict, "observation must be object")
    _require(set(data) == {
        "schema", "observation_id", "source_ref", "producer_ref", "observer_ref",
        "observed_at", "world_revision", "event_cursor", "visibility",
        "self_position", "readings",
    }, "observation field set")
    _require(data["schema"] == OBSERVATION_SCHEMA, "observation schema mismatch")
    _require(data["source_ref"] == SOURCE, "unregistered source reference")
    _require(data["producer_ref"] == PRODUCER, "producer reference mismatch")
    _require(data["observer_ref"] == "lab.actor.anima", "observation actor mismatch")
    clock = data["observed_at"]
    _require(type(clock) is dict and set(clock) == {"epoch", "tick"}, "clock fields")
    epoch = _natural(clock["epoch"], "observed_at.epoch")
    tick = _natural(clock["tick"], "observed_at.tick")
    revision = _natural(data["world_revision"], "world_revision")
    cursor = _natural(data["event_cursor"], "event_cursor")
    _require(epoch > 0, "epoch must be positive")
    for field, lhs, rhs in (
        ("epoch", epoch, envelope.get("epoch")),
        ("tick", tick, envelope.get("tick")),
        ("revision", revision, envelope.get("revision")),
        ("event_seq", cursor, envelope.get("event_seq")),
    ):
        _require(lhs == _natural(rhs, field), f"observation {field} vs envelope")
    obs_id = data["observation_id"]
    _require(
        type(obs_id) is str and obs_id.startswith(f"val_obs:{epoch}:")
        and obs_id[len(f"val_obs:{epoch}:"):].isdigit(),
        "observation ID must bind epoch",
    )
    visibility = data["visibility"]
    _require(
        type(visibility) is dict and visibility == {
            "type": "manhattan_radius", "radius": 3,
        },
        "visibility boundary mismatch",
    )
    origin = _grid(data["self_position"], "self_position")
    readings = data["readings"]
    _require(type(readings) is list and len(readings) <= 128, "readings bound")
    unique: set[tuple[str, str]] = set()
    for item in readings:
        _require(type(item) is dict, "reading must be object")
        _require({"subject_ref", "predicate_ref", "typed_value"} <= item.keys(),
                 "reading missing typed fields")
        subject, predicate = item["subject_ref"], item["predicate_ref"]
        _require(type(subject) is str and subject.startswith("lab."),
                 "bad subject reference")
        _require(type(predicate) is str and predicate in ("position", "state"),
                 "unsupported predicate")
        key = (subject, predicate)
        _require(key not in unique, "duplicate reading for one property")
        unique.add(key)
        typed = item["typed_value"]
        _require(type(typed) is dict, "typed value not object")
        if predicate == "state":
            _require(
                subject == "lab.door.01"
                and typed in (
                    {"type": "symbol", "value": "open"},
                    {"type": "symbol", "value": "closed"},
                ),
                "invalid typed door state",
            )
            _require(set(item) == {"subject_ref", "predicate_ref", "typed_value", "position"},
                     "door reading fields")
            position = _grid(item["position"], "door.position")
        else:
            _require(set(typed) == {"type", "x", "y"} and typed["type"] == "grid_cell",
                     "invalid typed position")
            _require(set(item) == {"subject_ref", "predicate_ref", "typed_value"},
                     "position reading fields")
            position = _grid({"x": typed["x"], "y": typed["y"]}, "typed position")
        _require(sum(abs(a - b) for a, b in zip(origin, position)) <= 3,
                 "out-of-range reading leaks world truth")
    return data


def validate_receipt(data: Any, *, action_id: str) -> dict[str, Any]:
    _require(type(data) is dict, "receipt must be object")
    _require(set(data) == {
        "schema", "operation_id", "status", "effect_applied", "reason",
        "position", "event_id", "world_epoch", "world_revision", "tick", "replayed",
    }, "receipt field set")
    _require(data["schema"] == RECEIPT_SCHEMA, "receipt schema")
    _require(data["operation_id"] == action_id, "receipt action ID mismatch")
    _require(data["status"] in ("APPLIED", "BLOCKED"), "receipt status")
    _require(type(data["effect_applied"]) is bool, "effect_applied must be bool")
    _require(data["effect_applied"] == (data["status"] == "APPLIED"),
             "effect and status inconsistent")
    _require(type(data["reason"]) is str and data["reason"] in (
        "ok", "wall", "other_actor", "closed_door",
    ), "receipt reason invalid")
    _require((data["reason"] == "ok") == data["effect_applied"],
             "receipt reason/effect mismatch")
    _grid(data["position"], "receipt.position")
    _require(type(data["event_id"]) is str and data["event_id"].startswith("val_evt:"),
             "receipt missing source world event")
    for key in ("world_epoch", "world_revision", "tick"):
        _natural(data[key], key)
    _require(type(data["replayed"]) is bool, "receipt replay marker")
    return data


def validate_events_page(data: Any, *, after_seq: int) -> dict[str, Any]:
    _require(type(data) is dict and set(data) == {
        "events", "next_cursor", "has_more",
    }, "events page fields")
    _require(type(data["has_more"]) is bool, "events has_more")
    events = data["events"]
    _require(type(events) is list and len(events) <= 8, "events page size")
    cursor = _natural(after_seq, "after_seq")
    for event in events:
        _require(type(event) is dict and set(event) == {
            "event_id", "event_seq", "epoch", "revision", "tick",
            "actor", "event", "details",
        }, "event fields")
        seq = _natural(event["event_seq"], "event_seq")
        _require(seq > cursor and event["event_id"] == f"val_evt:{seq}",
                 "event monotonic identity")
        cursor = seq
        _natural(event["epoch"], "event.epoch")
        _natural(event["revision"], "event.revision")
        _natural(event["tick"], "event.tick")
        _require(type(event["actor"]) is str and bool(event["actor"]), "event actor")
        _require(type(event["event"]) is str and bool(event["event"]), "event type")
        _require(type(event["details"]) is dict, "event details")
    _require(_natural(data["next_cursor"], "next_cursor") == cursor,
             "events page cursor mismatch")
    return data
