"""E1.4: UNKNOWN is not absence of effect; receipts are not proof."""
from __future__ import annotations

import copy

import pytest

from labs.virtual_anima_lab.python.lifecycle.contracts import (
    ACTION_SCHEMA, OPERATION_STATUS_SCHEMA, RECEIPT_SCHEMA,
    WorldAction, WorldContractError, WorldOperationStatus, WorldReceipt,
)
from labs.virtual_anima_lab.python.lifecycle.recovery import (
    query_world_operation, reconcile_world_status,
)

WORLD = "a" * 32


def action() -> WorldAction:
    return WorldAction({
        "schema": ACTION_SCHEMA, "world_instance_id": WORLD,
        "epoch": 1, "expected_revision": 2,
        "observation_id": f"worldobs:{WORLD}:1:4",
        "operation_id": "op.e14.1", "action_type": "world.move",
        "arguments": {"direction": "E"},
    })


def receipt() -> dict:
    return {
        "schema": RECEIPT_SCHEMA, "world_instance_id": WORLD,
        "epoch": 1, "operation_id": "op.e14.1",
        "status": "APPLIED", "effect_applied": True, "reason": "ok",
        "revision": 3, "tick": 5, "event_id": "lifecycle_evt:123",
        "replayed": False,
    }


def lookup(*, state="RECORDED", receipt_data=None) -> WorldOperationStatus:
    return WorldOperationStatus({
        "schema": OPERATION_STATUS_SCHEMA,
        "world_instance_id": WORLD, "epoch": 1, "operation_id": "op.e14.1",
        "status": state,
        "receipt": (receipt() if receipt_data is None else receipt_data)
        if state == "RECORDED" else None,
    })


def test_reconciliation_recovers_original_record_but_not_independent_effect():
    intent = action()
    resolved = reconcile_world_status(intent, lookup())
    assert resolved.state == "RECORDED"
    assert resolved.receipt == WorldReceipt(receipt()) or (
        resolved.receipt.as_dict() == receipt()
    )
    assert resolved.safe_to_reissue is False


def test_missing_status_is_never_permission_to_retry():
    result = reconcile_world_status(action(), lookup(state="UNKNOWN"))
    assert result.state == "UNKNOWN"
    assert result.receipt is None
    assert not result.safe_to_reissue


@pytest.mark.parametrize("key,value", [
    ("world_instance_id", "b" * 32),
    ("epoch", 2),
    ("operation_id", "op.other"),
])
def test_status_wrong_identity_fails_closed(key, value):
    data = lookup().as_dict()
    data[key] = value
    if data["status"] == "RECORDED":
        # A malformed paired identity is not even a valid DTO.
        with pytest.raises(WorldContractError):
            reconcile_world_status(action(), WorldOperationStatus(data))
    data["status"] = "UNKNOWN"
    data["receipt"] = None
    with pytest.raises(WorldContractError):
        reconcile_world_status(action(), WorldOperationStatus(data))


def test_replayed_receipt_cannot_masquerade_as_original_record():
    data = receipt()
    data["replayed"] = True
    with pytest.raises(WorldContractError, match="replay"):
        reconcile_world_status(action(), lookup(receipt_data=data))


def test_status_does_not_allow_fake_applied_proof_from_id_alone():
    status = lookup()
    result = reconcile_world_status(action(), status)
    assert result.receipt.as_dict()["status"] == "APPLIED"
    assert not result.safe_to_reissue
    # No WorldObservation was supplied. No independent effect proof exists.
    assert not hasattr(result, "verified_success")


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, op, **kwargs):
        self.calls.append((op, kwargs))
        return {"data": self.response}


def test_query_only_uses_operation_status_no_implicit_action_replay():
    client = _FakeClient(lookup().as_dict())
    result = query_world_operation(client, action())
    assert result.state == "RECORDED"
    assert client.calls == [("operation_status", {
        "world_instance_id": WORLD, "epoch": 1,
        "operation_id": "op.e14.1",
    })]


def test_status_malformed_fails_closed():
    corrupt = lookup().as_dict()
    corrupt["receipt"]["world_instance_id"] = "b" * 32
    with pytest.raises(WorldContractError):
        WorldOperationStatus(corrupt)
