"""Lab P5-B protocol/DTO unit tests. No Godot, Core or network required."""

from __future__ import annotations

import json
import socketserver
import threading
from copy import deepcopy

import pytest

from labs.virtual_anima_lab.python.contracts import (
    LabContractError,
    validate_events_page,
    validate_observation,
    validate_receipt,
)
from labs.virtual_anima_lab.python.lab_client import (
    LabClient,
    LabProtocolError,
    PROTOCOL_V2,
)


@pytest.fixture
def observed():
    envelope = {
        "protocol": PROTOCOL_V2,
        "id": 1,
        "ok": True,
        "tick": 3,
        "epoch": 1,
        "revision": 2,
        "event_seq": 7,
    }
    data = {
        "schema": "val.observation/0.1",
        "observation_id": "val_obs:1:12",
        "source_ref": "lab.sensor.anima.proximity",
        "producer_ref": "lab.godot",
        "observer_ref": "lab.actor.anima",
        "observed_at": {"epoch": 1, "tick": 3},
        "world_revision": 2,
        "event_cursor": 7,
        "visibility": {"type": "manhattan_radius", "radius": 3},
        "self_position": {"x": 8, "y": 5},
        "readings": [
            {
                "subject_ref": "lab.door.01",
                "predicate_ref": "state",
                "typed_value": {"type": "symbol", "value": "closed"},
                "position": {"x": 6, "y": 4},
            },
            {
                "subject_ref": "lab.actor.human",
                "predicate_ref": "position",
                "typed_value": {"type": "grid_cell", "x": 8, "y": 4},
            },
        ],
    }
    return envelope, data


def test_val_p5b_typed_observation_and_provenance(observed):
    envelope, data = observed
    assert validate_observation(data, envelope) is data
    assert data["source_ref"] != data["observer_ref"]


@pytest.mark.parametrize(
    "mutation",
    ["source", "clock", "revision", "future_event", "radius",
     "fake_door", "distant_human", "duplicate", "missing_field"],
)
def test_val_p5b_observation_validator_fails_closed(observed, mutation):
    envelope, raw = observed
    data = deepcopy(raw)
    if mutation == "source":
        data["source_ref"] = "lab.operator"
    elif mutation == "clock":
        data["observed_at"]["tick"] = 4
    elif mutation == "revision":
        data["world_revision"] = 99
    elif mutation == "future_event":
        data["event_cursor"] = 999
    elif mutation == "radius":
        data["visibility"]["radius"] = 1000
    elif mutation == "fake_door":
        data["readings"][0]["typed_value"]["value"] = "unknown"
    elif mutation == "distant_human":
        data["readings"][1]["typed_value"].update({"x": 2, "y": 2})
    elif mutation == "duplicate":
        data["readings"].append(deepcopy(data["readings"][1]))
    elif mutation == "missing_field":
        data.pop("producer_ref")
    with pytest.raises(LabContractError):
        validate_observation(data, envelope)


@pytest.fixture
def receipt():
    return {
        "schema": "val.receipt/0.1",
        "operation_id": "p5b:101",
        "status": "APPLIED",
        "effect_applied": True,
        "reason": "ok",
        "position": {"x": 8, "y": 5},
        "event_id": "val_evt:12",
        "world_epoch": 1,
        "world_revision": 3,
        "tick": 8,
        "replayed": False,
    }


def test_val_p5b_receipt_is_result_not_verification(receipt):
    assert validate_receipt(receipt, action_id="p5b:101") is receipt
    assert "verified_goal" not in receipt
    blocked = {**receipt, "status": "BLOCKED", "effect_applied": False,
               "reason": "closed_door"}
    assert validate_receipt(blocked, action_id="p5b:101") is blocked


@pytest.mark.parametrize(
    "mutation",
    ["id", "wrong_status", "bad_boolean", "unknown_reason",
     "malformed_event_id", "extra_authority"],
)
def test_val_p5b_receipt_rejects_unverified_claims(receipt, mutation):
    bad = deepcopy(receipt)
    if mutation == "id":
        bad["operation_id"] = "another"
    elif mutation == "wrong_status":
        bad["status"] = "VERIFIED_SUCCESS"
    elif mutation == "bad_boolean":
        bad["effect_applied"] = "true"
    elif mutation == "unknown_reason":
        bad["reason"] = "hallucinated"
    elif mutation == "malformed_event_id":
        bad["event_id"] = "no-proof"
    elif mutation == "extra_authority":
        bad["goal_completed"] = True
    with pytest.raises(LabContractError):
        validate_receipt(bad, action_id="p5b:101")


def _event(seq: int):
    return {
        "event_id": f"val_evt:{seq}",
        "event_seq": seq, "epoch": 1, "revision": 2, "tick": 3,
        "actor": "anima", "event": "move", "details": {"moved": True},
    }


def test_val_p5b_event_page_has_monotonic_cursor():
    page = {
        "events": [_event(4), _event(5)],
        "next_cursor": 5,
        "has_more": True,
    }
    assert validate_events_page(page, after_seq=3) is page
    empty = {"events": [], "next_cursor": 5, "has_more": False}
    assert validate_events_page(empty, after_seq=5) is empty


@pytest.mark.parametrize("violation", ["duplicate", "cursor", "bad_id", "truncated"])
def test_val_p5b_event_page_rejects_inconsistent_history(violation):
    page = {
        "events": [_event(4), _event(5)],
        "next_cursor": 5, "has_more": True,
    }
    if violation == "duplicate":
        page["events"][1]["event_seq"] = 4
    elif violation == "cursor":
        page["next_cursor"] = 100
    elif violation == "bad_id":
        page["events"][1]["event_id"] = "val_evt:13"
    elif violation == "truncated":
        page["events"] = [_event(x) for x in range(4, 13)]
        page["next_cursor"] = 12
    with pytest.raises(LabContractError):
        validate_events_page(page, after_seq=3)


class _V2Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            request = json.loads(line)
            envelope = {
                "protocol": PROTOCOL_V2, "id": float(request["id"]),
                "ok": True, "tick": 1.0,
                "epoch": 1.0, "revision": 0.0, "event_seq": 5.0,
                "data": {"ready": True},
            }
            if request["op"] == "bad_revision":
                envelope["revision"] = 0.25
            elif request["op"] == "wrong_protocol":
                envelope["protocol"] = "val.bridge/0.1"
            self.wfile.write((json.dumps(envelope) + "\n").encode())


@pytest.fixture
def v2_bridge():
    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = _Server(("127.0.0.1", 0), _V2Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_val_p5b_client_normalizes_integral_godot_envelope(v2_bridge):
    with LabClient(v2_bridge, protocol=PROTOCOL_V2) as client:
        result = client.call("hello")
    assert result["id"] == 1
    assert all(type(result[field]) is int for field in (
        "id", "epoch", "revision", "event_seq", "tick",
    ))


@pytest.mark.parametrize("op", ["bad_revision", "wrong_protocol"])
def test_val_p5b_client_rejects_broken_versioned_envelope(v2_bridge, op):
    with LabClient(v2_bridge, protocol=PROTOCOL_V2) as client:
        with pytest.raises(LabProtocolError):
            client.call(op)


def test_val_p5b_client_rejects_unregistered_protocol(v2_bridge):
    with pytest.raises(ValueError, match="unsupported"):
        LabClient(v2_bridge, protocol="val.bridge/9.0")
