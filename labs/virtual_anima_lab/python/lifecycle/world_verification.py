"""E1.3 isolated readback verification of three *virtual* world actions.

An APPLIED receipt is evidence of a transport response, NOT of a world effect.
Only a new independently requested WorldObservation can support VERIFIED_SUCCESS.
Neither the verifier nor its caller can grant Core permissions or complete a Goal.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import WorldAction, WorldObservation, WorldReceipt

_ACTOR = "lab.actor.anima"
_ITEM = "lab.item.crate"
_DELIVERY = "lab.zone.delivery"
_DELTAS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}


@dataclass(frozen=True, slots=True)
class WorldEffectProof:
    status: str  # VERIFIED_SUCCESS / VERIFIED_BLOCKED / UNVERIFIED
    reason: str
    operation_id: str
    before_sample: str
    after_sample: str
    delivery_verified: bool = False

    @property
    def success(self) -> bool:
        return self.status == "VERIFIED_SUCCESS"


def _property(obs: dict, subject: str, predicate: str) -> dict | None:
    return next(
        (row for row in obs["readings"]
         if row["subject_ref"] == subject and row["predicate_ref"] == predicate),
        None,
    )


def _position(obs: dict, subject: str) -> tuple[int, int] | None:
    record = _property(obs, subject, "position")
    if record is None or record["status"] != "known":
        return None
    value = record["value"]
    return (value["x"], value["y"])


def _own_status(obs: dict) -> tuple[str, str | None]:
    record = _property(obs, _ITEM, "owner")
    if record is None:
        return ("unobserved", None)
    if record["status"] == "known":
        return ("known", record["value"]["value"])
    return (record["status"], None)


def verify_world_effect(
    before: WorldObservation,
    action: WorldAction,
    receipt: WorldReceipt,
    after: WorldObservation,
) -> WorldEffectProof:
    """Fail closed: same process/epoch, newer sample and fresh matching readback.

    This is a laboratory evidence check, not producer authentication.
    A forged or stale sensor stream requires a separately trusted boundary in E2.
    """
    b, a, r, t = (item.as_dict() for item in (before, action, receipt, after))
    op = a["operation_id"]

    def proof(status: str, reason: str, *, delivered: bool = False) -> WorldEffectProof:
        return WorldEffectProof(status, reason, op, b["sample_id"], t["sample_id"],
                                delivery_verified=delivered)

    world = b["world_instance_id"]
    epoch = b["epoch"]
    if any(x["world_instance_id"] != world or x["epoch"] != epoch for x in (a, r, t)):
        return proof("UNVERIFIED", "WORLD_OR_EPOCH_MISMATCH")
    if a["observation_id"] != b["sample_id"] or a["expected_revision"] != b["revision"]:
        return proof("UNVERIFIED", "INTENT_NOT_BOUND_TO_BEFORE")
    if r["operation_id"] != op:
        return proof("UNVERIFIED", "OPERATION_MISMATCH")
    if (t["sample_seq"] <= b["sample_seq"] or
            t["sample_id"] == b["sample_id"] or
            t["tick"] <= b["tick"] or
            r["tick"] > t["tick"]):
        return proof("UNVERIFIED", "READBACK_NOT_FRESH")
    # Exclusive post-operation world state: no intervening state mutation is allowed.
    if r["revision"] != t["revision"]:
        return proof("UNVERIFIED", "INTERVENING_WORLD_MUTATION")
    expected_revision = b["revision"] + (1 if r["effect_applied"] else 0)
    if r["revision"] != expected_revision:
        return proof("UNVERIFIED", "RECEIPT_REVISION_INCONSISTENT")

    old_position = (b["self_position"]["x"], b["self_position"]["y"])
    new_position = (t["self_position"]["x"], t["self_position"]["y"])
    kind = a["action_type"]
    item_before, item_after = _position(b, _ITEM), _position(t, _ITEM)
    owner_before, owner_after = _own_status(b), _own_status(t)

    if r["status"] == "BLOCKED":
        if old_position != new_position:
            return proof("UNVERIFIED", "BLOCKED_BUT_ACTOR_MOVED")
        # If the item was observed before, it must still be observed unchanged.
        if item_before is not None and (item_after != item_before or
                                        owner_after != owner_before):
            return proof("UNVERIFIED", "BLOCKED_BUT_ITEM_CHANGED")
        if kind != "world.move" and item_before is None:
            return proof("UNVERIFIED", "BLOCKED_ITEM_STATE_UNOBSERVED")
        return proof("VERIFIED_BLOCKED", "NO_MUTATION_OBSERVED")

    if kind == "world.move":
        dx, dy = _DELTAS[a["arguments"]["direction"]]
        expected = (old_position[0] + dx, old_position[1] + dy)
        if new_position != expected:
            return proof("UNVERIFIED", "MOVE_NOT_OBSERVED")
        if owner_before == ("known", _ACTOR) and (
            item_after != new_position or owner_after != ("known", _ACTOR)
        ):
            return proof("UNVERIFIED", "CARRIED_ITEM_LOST")
        return proof("VERIFIED_SUCCESS", "MOVE_OBSERVED")

    if new_position != old_position:
        return proof("UNVERIFIED", "ITEM_ACTION_MOVED_ACTOR")
    if a["arguments"]["item_ref"] != _ITEM:
        return proof("UNVERIFIED", "WRONG_ITEM")
    if kind == "world.pick":
        if (item_before is None or
                abs(item_before[0] - old_position[0]) +
                abs(item_before[1] - old_position[1]) > 1 or
                owner_before != ("absent", None)):
            return proof("UNVERIFIED", "PICK_PRECONDITION_NOT_OBSERVED")
        if item_after != old_position or owner_after != ("known", _ACTOR):
            return proof("UNVERIFIED", "PICK_NOT_OBSERVED")
        return proof("VERIFIED_SUCCESS", "PICK_OWNERSHIP_OBSERVED")

    if owner_before != ("known", _ACTOR) or item_before != old_position:
        return proof("UNVERIFIED", "DROP_PRECONDITION_NOT_OBSERVED")
    if item_after != new_position or owner_after != ("absent", None):
        return proof("UNVERIFIED", "DROP_NOT_OBSERVED")
    delivered = _position(t, _DELIVERY) == new_position
    return proof("VERIFIED_SUCCESS", "DROP_OBSERVED", delivered=delivered)


__all__ = ["WorldEffectProof", "verify_world_effect"]
