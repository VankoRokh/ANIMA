"""E2.4b lab-only viewpoint odometry from *readback-proven* external effects.

This class cannot issue actions. A separate trusted experimental harness acts
on Godot; this class reads the executor-only operation_status ledger and
matches resulting clocks to the next E24 Core-backed Raw observation.

Local origin (0,0) and facing 0 are arbitrary initial-view conventions, NOT
Godot's hidden global grid; a receipt proves a recorded world action, not
permanently authenticated source truth nor independent Stage6 verification.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from typing import Any

from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .egocentric import EgocentricAction
from .e24_working_memory import E24WorkingMemory, E24MemoryError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS e24b_viewpoint_actions(
 operation_id TEXT PRIMARY KEY,
 before_sample_id TEXT NOT NULL REFERENCES e24_raw(sample_id),
 action_json TEXT NOT NULL,
 receipt_json TEXT NOT NULL,
 receipt_sha256 TEXT NOT NULL,
 UNIQUE(before_sample_id)
);
CREATE TABLE IF NOT EXISTS e24b_external_changes(
 fixture_id TEXT PRIMARY KEY,
 before_sample_id TEXT NOT NULL UNIQUE REFERENCES e24_raw(sample_id),
 receipt_json TEXT NOT NULL,
 receipt_sha256 TEXT NOT NULL
);
"""
_KEY = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_EVENT = re.compile(r"lifecycle_evt:[1-9][0-9]*\Z")
_RECEIPT_SCHEMA = "anima.lifecycle.world_receipt/0.1"
_STATUS_SCHEMA = "anima.lifecycle.world_operation_status/0.1"
_EXTERNAL_SCHEMA = "anima.lifecycle.operator_fixture_receipt/0.1"


class E24PoseError(E24MemoryError):
    pass


def _require(ok: bool, label: str) -> None:
    if not ok:
        raise E24PoseError(label)


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _validate_receipt(action: dict, data: Any, before: dict) -> dict:
    _require(type(data) is dict and set(data) == {
        "schema", "world_instance_id", "epoch", "operation_id", "status",
        "effect_applied", "reason", "revision", "tick", "event_id", "replayed",
    }, "invalid Godot receipt shape")
    _require(data["schema"] == _RECEIPT_SCHEMA, "wrong receipt schema")
    for key in ("world_instance_id", "epoch", "operation_id"):
        _require(type(data[key]) is type(action[key]) and data[key] == action[key],
                 "receipt action identity changed")
    _require(data["replayed"] is False, "only original effect receipt is evidence")
    _require(type(data["tick"]) is int and data["tick"] == before["tick"] + 1,
             "receipt tick is not one action after verified observation")
    _require(type(data["revision"]) is int, "noninteger receipt revision")
    _require(type(data["event_id"]) is str and _EVENT.fullmatch(data["event_id"]) is not None,
             "invalid Godot event reference")
    _require(type(data["reason"]) is str, "invalid receipt reason")
    kind = action["action_type"]
    if kind == "world.turn":
        _require(data["status"] == "APPLIED" and data["effect_applied"] is True
                 and data["reason"] == "ok"
                 and data["revision"] == before["revision"] + 1,
                 "turn not verified as one applied effect")
    else:
        _require(kind == "world.step", "pose trail only accepts turn/step")
        if data["status"] == "APPLIED":
            _require(data["effect_applied"] is True and data["reason"] == "ok"
                     and data["revision"] == before["revision"] + 1,
                     "applied step receipt inconsistent")
        elif data["status"] == "BLOCKED":
            _require(data["effect_applied"] is False
                     and data["reason"] == "occupied"
                     and data["revision"] == before["revision"],
                     "blocked step receipt inconsistent")
        else:
            raise E24PoseError("step outcome is unverified")
    return data


def _validate_external(receipt: Any, before: dict) -> dict:
    """Operator intervention proof; never include hidden target coordinates."""
    _require(type(receipt) is dict and set(receipt) == {
        "schema", "fixture_id", "world_instance_id", "epoch",
        "before_sample_id", "kind", "status", "revision",
        "tick", "event_id", "replayed",
    }, "invalid operator fixture proof shape")
    _require(receipt["schema"] == _EXTERNAL_SCHEMA
             and receipt["kind"] == "item_relocated"
             and receipt["status"] == "APPLIED"
             and receipt["replayed"] is False, "unproven external intervention")
    _require(type(receipt["fixture_id"]) is str
             and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", receipt["fixture_id"])
             is not None, "invalid fixture identifier")
    _require(receipt["world_instance_id"] == before["world_instance_id"]
             and type(receipt["epoch"]) is int
             and receipt["epoch"] == before["epoch"]
             and receipt["before_sample_id"] == before["sample_id"],
             "operator intervention not bound to prior Core-backed Raw")
    _require(type(receipt["revision"]) is int
             and receipt["revision"] == before["revision"] + 1
             and type(receipt["tick"]) is int
             and receipt["tick"] == before["tick"] + 1,
             "external revision/tick not contiguous with Raw")
    _require(type(receipt["event_id"]) is str
             and _EVENT.fullmatch(receipt["event_id"]) is not None,
             "invalid operator event evidence")
    return receipt


class E24PoseTrail:
    """Readback-only experiment; no direct Godot act(), no arbitrary paths."""

    def __init__(self, memory: E24WorkingMemory, *, port: int, executor_key: str):
        if type(memory) is not E24WorkingMemory:
            raise TypeError("E2.4b requires exact E24WorkingMemory")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("invalid lab port")
        if type(executor_key) is not str or _KEY.fullmatch(executor_key) is None:
            raise ValueError("strong guarded executor key required")
        self._memory = memory
        self._port = port
        self._executor_key = executor_key
        with closing(self._memory._connect()) as db:
            db.executescript(_SCHEMA)

    def record_verified_external_action(self, action: EgocentricAction) -> dict:
        """Capture only a readback-proven action; never send a world effect."""
        if type(action) is not EgocentricAction:
            raise TypeError("typed lab action required")
        act = action.as_dict()
        self._memory.world_model()  # Full Raw/Core/derived integrity gate.
        with closing(self._memory._connect()) as db:
            last = db.execute("SELECT sample_id FROM e24_raw ORDER BY sample_seq DESC LIMIT 1").fetchone()
            _require(last is not None, "missing pre-action sensor Raw")
            pending = db.execute(
                "SELECT operation_id FROM e24b_viewpoint_actions "
                "WHERE before_sample_id=?", (last["sample_id"],),
            ).fetchone()
            if pending is not None:
                # Only one verified action can occur between adjacent sensor views.
                _require(pending["operation_id"] == act["operation_id"],
                         "multiple effects without an intermediate Raw view")
        before = self._memory.raw_evidence(last["sample_id"]).as_dict()
        _require(act["world_instance_id"] == before["world_instance_id"]
                 and act["epoch"] == before["epoch"]
                 and act["observation_id"] == before["sample_id"]
                 and act["expected_revision"] == before["revision"],
                 "action does not target newest verified view")
        with LabClient(self._port, role="agent", protocol=PROTOCOL_V2) as client:
            status = client.call(
                "operation_status", auth=self._executor_key,
                operation_id=act["operation_id"],
                world_instance_id=act["world_instance_id"],
                epoch=act["epoch"], action=act,
            )["data"]
        _require(type(status) is dict and set(status) == {
            "schema", "world_instance_id", "epoch", "operation_id", "status", "receipt",
        }, "invalid operation status response")
        _require(status["schema"] == _STATUS_SCHEMA
                 and status["world_instance_id"] == act["world_instance_id"]
                 and type(status["epoch"]) is int and status["epoch"] == act["epoch"]
                 and status["operation_id"] == act["operation_id"]
                 and status["status"] == "RECORDED",
                 "operation is not verified as recorded in active world ledger")
        receipt = _validate_receipt(act, status["receipt"], before)
        payload = _canonical(receipt)
        with closing(self._memory._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                prior = db.execute(
                    "SELECT before_sample_id,action_json,receipt_json,receipt_sha256 "
                    "FROM e24b_viewpoint_actions WHERE operation_id=?",
                    (act["operation_id"],),
                ).fetchone()
                if prior is not None:
                    _require(prior["before_sample_id"] == last["sample_id"]
                             and prior["action_json"] == _canonical(act)
                             and prior["receipt_json"] == payload
                             and prior["receipt_sha256"] == _sha(payload),
                             "conflicting recorded viewpoint action")
                else:
                    db.execute(
                        "INSERT INTO e24b_viewpoint_actions VALUES (?,?,?,?,?)",
                        (act["operation_id"], last["sample_id"],
                         _canonical(act), payload, _sha(payload)),
                    )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return json.loads(payload)

    def record_operator_world_change(self, receipt: dict) -> dict:
        """Trusted lab harness records a world intervention, not an ANIMA act.

        The caller must possess operator authority to obtain this Godot
        receipt. This lab-only trust is NOT cryptographic source attestation.
        """
        self._memory.world_model()
        with closing(self._memory._connect()) as db:
            last = db.execute(
                "SELECT sample_id FROM e24_raw ORDER BY sample_seq DESC LIMIT 1"
            ).fetchone()
            _require(last is not None, "missing pre-fixture Core Raw")
            pending = db.execute(
                "SELECT 1 FROM e24b_viewpoint_actions WHERE before_sample_id=?",
                (last["sample_id"],),
            ).fetchone()
            _require(pending is None, "cannot interleave unknown agent effect and fixture")
        before = self._memory.raw_evidence(last["sample_id"]).as_dict()
        _validate_external(receipt, before)
        body = _canonical(receipt)
        with closing(self._memory._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                earlier = db.execute(
                    "SELECT before_sample_id,receipt_json,receipt_sha256 "
                    "FROM e24b_external_changes WHERE fixture_id=?",
                    (receipt["fixture_id"],),
                ).fetchone()
                if earlier is not None:
                    _require(earlier["before_sample_id"] == before["sample_id"]
                             and earlier["receipt_json"] == body
                             and earlier["receipt_sha256"] == _sha(body),
                             "conflicting operator proof")
                else:
                    db.execute(
                        "INSERT INTO e24b_external_changes VALUES(?,?,?,?)",
                        (receipt["fixture_id"], before["sample_id"], body, _sha(body)),
                    )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return json.loads(body)

    def reconstruct(self) -> dict:
        """Reconstruct local viewpoint relative to first verified sensor view.

        Never infer a movement from a requested action; a recorded, applied
        receipt AND the next captured Core-backed view must agree on clocks.
        """
        self._memory.world_model()
        with closing(self._memory._connect()) as db:
            samples = db.execute(
                "SELECT sample_id FROM e24_raw ORDER BY sample_seq"
            ).fetchall()
            actions = db.execute("SELECT * FROM e24b_viewpoint_actions").fetchall()
            external = db.execute("SELECT * FROM e24b_external_changes").fetchall()
        views = [self._memory.raw_evidence(x["sample_id"]).as_dict() for x in samples]
        action_by_sample = {}
        for row in actions:
            _require(row["before_sample_id"] not in action_by_sample,
                     "duplicate action anchored to one Raw sample")
            _require(_sha(row["receipt_json"]) == row["receipt_sha256"],
                     "viewpoint action receipt modified after readback")
            try:
                action = EgocentricAction(json.loads(row["action_json"])).as_dict()
                receipt = json.loads(row["receipt_json"])
            except (ValueError, TypeError) as error:
                raise E24PoseError("invalid recorded viewpoint evidence") from error
            _require(row["operation_id"] == action["operation_id"],
                     "operation ID differs from sealed action")
            action_by_sample[row["before_sample_id"]] = (action, receipt)
        external_by_sample = {}
        for row in external:
            _require(_sha(row["receipt_json"]) == row["receipt_sha256"],
                     "operator proof modified")
            try:
                receipt = json.loads(row["receipt_json"])
            except (ValueError, TypeError) as error:
                raise E24PoseError("malformed operator proof") from error
            _require(row["fixture_id"] == receipt.get("fixture_id"),
                     "operator fixture identifier mismatched")
            _require(row["before_sample_id"] not in external_by_sample
                     and row["before_sample_id"] not in action_by_sample,
                     "two world interventions without an intermediate Raw")
            external_by_sample[row["before_sample_id"]] = receipt
        heading = 0  # 0=facing initial forward; 1=right; 2=back; 3=left
        right = 0
        forward = 0
        poses = []
        effects = []
        external_effects = []
        for index, view in enumerate(views):
            if index == 0:
                poses.append(self._entry(view, right, forward, heading))
                continue
            before = views[index - 1]
            external_receipt = external_by_sample.pop(before["sample_id"], None)
            recorded = action_by_sample.pop(before["sample_id"], None)
            _require(external_receipt is None or recorded is None,
                     "operator and agent changed same observation interval")
            if external_receipt is not None:
                _validate_external(external_receipt, before)
                _require(view["revision"] == external_receipt["revision"]
                         and view["tick"] == external_receipt["tick"],
                         "new Raw does not support operator event clocks")
                external_effects.append({
                    "kind": "world_fixture_change",
                    "fixture_id": external_receipt["fixture_id"],
                    "event_id": external_receipt["event_id"],
                    "before_sample_id": before["sample_id"],
                    "after_sample_id": view["sample_id"],
                    "verified_clocks": True,
                    "no_agent_pose_effect": True,
                })
                poses.append(self._entry(view, right, forward, heading))
                continue
            if recorded is None:
                _require(
                    view["revision"] == before["revision"]
                    and view["tick"] == before["tick"],
                    "world state advanced without a verified viewpoint action",
                )
                poses.append(self._entry(view, right, forward, heading))
                continue
            action, receipt = recorded
            _require(action["observation_id"] == before["sample_id"]
                     and action["expected_revision"] == before["revision"]
                     and action["world_instance_id"] == view["world_instance_id"]
                     and action["epoch"] == view["epoch"],
                     "recorded action not bound to adjacent sensor views")
            _validate_receipt(action, receipt, before)
            _require(view["revision"] == receipt["revision"]
                     and view["tick"] == receipt["tick"]
                     and view["sample_seq"] > before["sample_seq"],
                     "next world Raw did not confirm effect clocks")
            if action["action_type"] == "world.turn":
                heading = (heading + (1 if action["arguments"]["direction"] == "right" else -1)) % 4
            elif receipt["effect_applied"]:
                # Forward movement in the *local origin's* arbitrary frame.
                dr, df = ((0, 1), (1, 0), (0, -1), (-1, 0))[heading]
                right += dr
                forward += df
            effects.append({
                "operation_id": action["operation_id"], "event_id": receipt["event_id"],
                "before_sample_id": before["sample_id"],
                "after_sample_id": view["sample_id"],
                "action_type": action["action_type"],
                "status": receipt["status"], "effect_applied": receipt["effect_applied"],
                "verified_clocks": True,
            })
            poses.append(self._entry(view, right, forward, heading))
        # A readback-proven action without subsequent Raw remains explicitly
        # pending, never treated as a confirmed pose transition.
        pending = []
        last_sample = views[-1]
        for sample_id, proof in external_by_sample.items():
            _require(sample_id == last_sample["sample_id"],
                     "orphaned operator change")
            _validate_external(proof, last_sample)
            pending.append(proof["fixture_id"])
        for sample_id, (action, receipt) in action_by_sample.items():
            _require(sample_id == last_sample["sample_id"]
                     and action["observation_id"] == sample_id,
                     "orphaned world action not linked to sensor history")
            _validate_receipt(action, receipt, last_sample)
            pending.append(action["operation_id"])
        return {
            "schema": "anima.lab.relative_viewpoint_trail/0.1",
            "world_instance_id": views[-1]["world_instance_id"],
            "epoch": views[-1]["epoch"],
            "origin": "arbitrary_first_observation",
            "poses": poses,
            "verified_transitions": effects,
            "verified_external_changes": external_effects,
            "pending_next_sensor": pending,
            "hidden_godot_coordinates_used": False,
            "not_stage6_authorized": True,
        }

    @staticmethod
    def _entry(view: dict, right: int, forward: int, heading: int) -> dict:
        return {
            "sample_id": view["sample_id"], "source_ref": view["source_ref"],
            "local_right_steps": right,
            "local_forward_steps": forward,
            "relative_heading_quadrants": heading,
            "frame": "first_observation_not_global",
            "basis": "readback_action_plus_raw_clocks",
        }


__all__ = ["E24PoseTrail", "E24PoseError"]
