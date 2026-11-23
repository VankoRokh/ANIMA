"""E2.5c laboratory Godot handler for native Stage6 SandboxExecutor.

The only world-effect socket is inside an explicitly injected, typed Stage6
SandboxHandler; neither the policy nor the human HUD knows executor credential.
On an ambiguous network failure, effect_possible=True. Reconciliation is
read-only and deliberately refuses automatic retries on unknown results.
"""
from __future__ import annotations

from anima.agent.executor import SandboxHandler, SandboxToolError
from anima.agent.tools import ToolDescriptor, ToolRegistry
from anima.execution.store import ExecutionStore
from anima.execution.sandbox import SandboxExecutor
from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .egocentric import EgocentricAction, VIEW_ACTION_SCHEMA
from .e24_pose import _validate_receipt, E24PoseError

VERSION = "0.1"


def _arguments_schema(kind: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "world_instance_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
            "epoch": {"type": "integer", "minimum": 1},
            "observation_id": {"type": "string", "minLength": 20, "maxLength": 120},
            "expected_revision": {"type": "integer", "minimum": 0},
            "pre_tick": {"type": "integer", "minimum": 0},
            "direction": {"type": "string", "enum": ["left", "right"]
                          if kind == "world.turn" else ["forward"]},
        },
        "required": [
            "world_instance_id", "epoch", "observation_id", "expected_revision",
            "pre_tick", "direction",
        ],
        "additionalProperties": False,
    }


_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "operation_id": {"type": "string", "minLength": 5},
        "status": {"type": "string", "enum": ["APPLIED", "BLOCKED"]},
        "effect_applied": {"type": "boolean"},
        "revision": {"type": "integer", "minimum": 0},
        "tick": {"type": "integer", "minimum": 0},
        "event_id": {"type": "string", "minLength": 8},
        "reason": {"type": "string"},
    },
    "required": [
        "operation_id", "status", "effect_applied", "revision", "tick",
        "event_id", "reason",
    ],
    "additionalProperties": False,
}


def stage6_spatial_registry() -> ToolRegistry:
    return ToolRegistry([
        ToolDescriptor(
            name=kind, version=VERSION,
            description="Single verified egocentric laboratory world effect",
            input_schema=_arguments_schema(kind), output_schema=_OUTPUT_SCHEMA,
            effect_class="reversible_write", idempotency="keyed",
            timeout_seconds=5.0,
        )
        for kind in ("world.turn", "world.step")
    ])


def _typed_action(kind: str, args: dict, op: str) -> EgocentricAction:
    return EgocentricAction({
        "schema": VIEW_ACTION_SCHEMA,
        "world_instance_id": args["world_instance_id"],
        "epoch": args["epoch"],
        "observation_id": args["observation_id"],
        "expected_revision": args["expected_revision"],
        "operation_id": op, "action_type": kind,
        "arguments": {"direction": args["direction"]},
    })


def _read_back(kind: str, args: dict, op: str, *, port: int, key: str):
    act = _typed_action(kind, args, op)
    with LabClient(port, role="agent", protocol=PROTOCOL_V2) as client:
        status = client.call(
            "operation_status", auth=key,
            operation_id=op, world_instance_id=args["world_instance_id"],
            epoch=args["epoch"], action=act.as_dict(),
        )["data"]
    if (type(status) is not dict
            or status.get("status") != "RECORDED"
            or status.get("operation_id") != op
            or status.get("world_instance_id") != args["world_instance_id"]
            or status.get("epoch") != args["epoch"]):
        raise SandboxToolError(
            "UNCERTAIN_OPERATION", "world effect was not readback-proven",
            effect_possible=True,
        )
    receipt = _validate_receipt(
        act.as_dict(), status.get("receipt"),
        {"tick": args["pre_tick"], "revision": args["expected_revision"]},
    )
    return {
        "operation_id": receipt["operation_id"],
        "status": receipt["status"], "effect_applied": receipt["effect_applied"],
        "revision": receipt["revision"], "tick": receipt["tick"],
        "event_id": receipt["event_id"], "reason": receipt["reason"],
    }


def _world_effect(kind: str, args: dict, op: str, *, port: int, key: str):
    act = _typed_action(kind, args, op)
    try:
        with LabClient(port, role="agent", protocol=PROTOCOL_V2) as client:
            receipt = client.call(
                "act", auth=key, action=act.as_dict(),
            )["data"]
        _validate_receipt(
            act.as_dict(), receipt,
            {"tick": args["pre_tick"], "revision": args["expected_revision"]},
        )
        return {
            "operation_id": receipt["operation_id"],
            "status": receipt["status"], "effect_applied": receipt["effect_applied"],
            "revision": receipt["revision"], "tick": receipt["tick"],
            "event_id": receipt["event_id"], "reason": receipt["reason"],
        }
    except (E24PoseError, OSError, KeyError, ValueError, RuntimeError) as exc:
        # If the socket died after Godot applied the effect, never assert
        # effect_possible=False just because no response reached Python.
        raise SandboxToolError(
            "UNVERIFIED_WORLD_EFFECT", type(exc).__name__,
            effect_possible=True,
        ) from exc


def stage6_godot_executor(*, root, store: ExecutionStore,
                          port: int, executor_key: str):
    from functools import partial
    registry = stage6_spatial_registry()
    handlers = {}
    for kind in ("world.turn", "world.step"):
        def execute(_root, arguments, operation_id, *, _kind=kind):
            return _world_effect(
                _kind, arguments, operation_id,
                port=port, key=executor_key,
            )

        def reconcile(_root, arguments, operation_id, *, _kind=kind):
            try:
                return "succeeded", _read_back(
                    _kind, arguments, operation_id,
                    port=port, key=executor_key,
                )
            except (SandboxToolError, E24PoseError, OSError, ValueError, RuntimeError):
                # Deliberately unsupported by SandboxExecutor: fail closed.
                # In-memory Godot ledger disappearance is ambiguous; no retry.
                return "unknown", None

        handlers[(kind, VERSION)] = SandboxHandler(
            execute=execute, reconcile=reconcile, replay_output=None,
        )
    return registry, SandboxExecutor(
        root=root, registry=registry, store=store, handlers=handlers,
    )


__all__ = ["stage6_godot_executor", "stage6_spatial_registry", "VERSION"]
