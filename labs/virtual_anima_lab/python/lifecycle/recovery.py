"""E1.4 lab-only retrieval of a world operation receipt after a lost response.

RECORDED is a recovered *world claim*, not independently verified effect proof.
UNKNOWN is NOT permission to issue the same action again. Never retry blindly.
Neither these DTOs nor the untrusted loopback role supply Core authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    WorldAction, WorldContractError, WorldOperationStatus, WorldReceipt,
)


@dataclass(frozen=True, slots=True)
class OperationReconciliation:
    state: str  # "RECORDED" or "UNKNOWN"
    operation_id: str
    receipt: WorldReceipt | None

    @property
    def safe_to_reissue(self) -> bool:
        # Even when no ledger record was found, the effect may have occurred.
        return False


def reconcile_world_status(
    action: WorldAction, status: WorldOperationStatus,
) -> OperationReconciliation:
    """Validate status for the exact intended world, epoch and operation."""
    expected = action.as_dict()
    resolved = status.as_dict()
    for key in ("world_instance_id", "epoch", "operation_id"):
        if resolved[key] != expected[key]:
            raise WorldContractError(f"operation lookup {key} does not match intent")
    if resolved["status"] == "UNKNOWN":
        return OperationReconciliation("UNKNOWN", expected["operation_id"], None)
    original_receipt = WorldReceipt(resolved["receipt"])
    if original_receipt.as_dict()["replayed"]:
        raise WorldContractError("ledger status cannot claim replay as original receipt")
    return OperationReconciliation("RECORDED", expected["operation_id"],
                                   original_receipt)


def query_world_operation(client, action: WorldAction) -> OperationReconciliation:
    """Request only a status; never execute an action as implicit fallback.

    Transport failure is propagated to the caller; it is not equivalent to a
    successful UNKNOWN lookup. The client must be connected to a lab world.
    """
    data = action.as_dict()
    envelope = client.call(
        "operation_status", world_instance_id=data["world_instance_id"],
        epoch=data["epoch"], operation_id=data["operation_id"],
    )
    status = WorldOperationStatus(envelope["data"])
    return reconcile_world_status(action, status)


__all__ = ["OperationReconciliation", "reconcile_world_status", "query_world_operation"]
