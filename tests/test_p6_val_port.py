"""P6 small, offline contract suite: no Godot binary required."""

import pytest

from anima.agent.executor import SandboxToolError
from anima.core.assembly import build_core
from anima.core.door_world import VirtualDoorWorld, door_handlers
from labs.virtual_anima_lab.python.core_port import VALDoorPort, VALPortError
from tests.test_core_p4_acceptance import _registries, _goal, _status, _effects


class FakeVAL:
    def __init__(self):
        self.instance = "a" * 32
        self.epoch = 1
        self.revision = 0
        self.tick = 0
        self.cursor = 0
        self.sample = 0
        self.open = True
        self.visible = True
        self.ledger = {}
        self.calls = []

    def client(self, *args, **kwargs):
        assert kwargs["role"] == "agent"
        assert kwargs["protocol"] == "val.bridge/0.2"
        return FakeClient(self)


class FakeClient:
    def __init__(self, world):
        self.world = world

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def call(self, op, **fields):
        w = self.world
        w.calls.append(op)
        if op == "hello":
            data = {
                "world_instance_id": w.instance,
                "world_version": "p5a-grid/0.1",
                "scenario": "p6_door",
                "source_ref": "lab.sensor.anima.proximity",
                "capabilities": [
                    "observe", "act_door", "door_operation_status",
                ],
            }
        elif op == "observe":
            w.sample += 1
            readings = []
            if w.visible:
                readings.append({
                    "subject_ref": "lab.door.01", "predicate_ref": "state",
                    "typed_value": {"type": "symbol", "value": "open" if w.open else "closed"},
                    "position": {"x": 6, "y": 3},
                })
            data = {
                "schema": "val.observation/0.1",
                "observation_id": f"val_obs:{w.epoch}:{w.sample}",
                "source_ref": "lab.sensor.anima.proximity",
                "producer_ref": "lab.godot",
                "observer_ref": "lab.actor.anima",
                "observed_at": {"epoch": w.epoch, "tick": w.tick},
                "world_revision": w.revision, "event_cursor": w.cursor,
                "visibility": {"type": "manhattan_radius", "radius": 3},
                "self_position": {"x": 6, "y": 4},
                "readings": readings,
            }
        elif op == "act_door":
            assert fields["action"] == {
                "schema": "val.door_action/0.1", "kind": "close_door",
            }
            assert fields["expected_epoch"] == w.epoch
            assert fields["expected_revision"] == w.revision
            assert w.open
            w.open = False
            w.revision += 1
            w.tick += 1
            w.cursor += 1
            key = fields["operation_id"]
            data = {
                "schema": "val.door_receipt/0.1",
                "operation_id": key, "status": "APPLIED",
                "effect_applied": True, "reason": "ok",
                "event_id": f"val_evt:{w.cursor}",
                "world_epoch": w.epoch, "world_revision": w.revision,
                "tick": w.tick, "replayed": False,
            }
            w.ledger[key] = data
        elif op == "door_operation_status":
            receipt = w.ledger.get(fields["operation_id"])
            data = {"found": receipt is not None}
            if receipt is not None:
                data["receipt"] = receipt
        else:
            raise AssertionError(f"unexpected/privileged call: {op}")
        return {
            "protocol": "val.bridge/0.2",
            "id": 1, "ok": True, "tick": w.tick, "epoch": w.epoch,
            "revision": w.revision, "event_seq": w.cursor, "data": data,
        }


def test_external_port_maps_bounded_sensor_only(tmp_path):
    w = FakeVAL()
    port = VALDoorPort(tmp_path, client_factory=w.client)
    first, tick1 = port.sense()
    second, tick2 = port.sense()
    assert (tick1, tick2) == (1, 2)
    assert first["kind"] == "state.property"
    assert first["payload"]["value"] == {"type": "symbol", "value": "open"}
    assert second["payload"]["source_revision"] == 2
    assert "inspect" not in w.calls and "set_door" not in w.calls


def test_out_of_view_does_not_fabricate_closed_door(tmp_path):
    w = FakeVAL()
    w.visible = False
    port = VALDoorPort(tmp_path, client_factory=w.client)
    event, tick = port.sense()
    assert tick == 1
    assert event["kind"] == "sensor.unavailable"
    assert event["payload"]["reason"] == "DOOR_NOT_VISIBLE"
    assert "value" not in event["payload"]


def test_epoch_or_process_change_fails_closed(tmp_path):
    w = FakeVAL()
    port = VALDoorPort(tmp_path, client_factory=w.client)
    port.sense()
    w.epoch += 1
    with pytest.raises(VALPortError, match="changed"):
        port.sense()
    w.epoch -= 1
    w.instance = "b" * 32
    with pytest.raises(VALPortError, match="changed"):
        port.sense()


def test_external_action_and_reconcile_do_not_use_operator_role(tmp_path):
    w = FakeVAL()
    port = VALDoorPort(tmp_path, client_factory=w.client)
    port.sense()
    arguments = {"subject_ref": "entity.door_01@registry-r1"}
    assert port.execute(str(tmp_path), arguments, "op:p6:1") == {
        "operation_id": "op:p6:1", "applied": True,
    }
    assert not w.open
    assert port.reconcile(arguments, "op:p6:1") == (
        "succeeded", {"operation_id": "op:p6:1", "applied": True},
    )
    assert port.reconcile(arguments, "missing") == ("unknown", None)
    assert "set_door" not in w.calls and "inspect" not in w.calls
    with pytest.raises(SandboxToolError, match="registered door"):
        port.execute(str(tmp_path), {"subject_ref": "another.target"}, "bad")


def test_no_action_without_visible_door(tmp_path):
    w = FakeVAL()
    port = VALDoorPort(tmp_path, client_factory=w.client)
    port.sense()
    w.visible = False
    with pytest.raises(SandboxToolError, match="not observed"):
        port.execute(
            str(tmp_path),
            {"subject_ref": "entity.door_01@registry-r1"}, "op:p6:hidden",
        )
    assert "act_door" not in w.calls


def test_injectable_port_retains_legacy_core_goal_and_verification(tmp_path):
    """No production Godot: use the pre-existing trusted Core world through DI."""
    world = VirtualDoorWorld(tmp_path / "world")
    world.seed(state="open", tick=40)
    sources, properties, actions = _registries()
    core = build_core(
        tmp_path / "data",
        sources=sources, properties=properties, goal_actions=actions,
        world_port=world, world_handlers=door_handlers(), auto_core=True,
    )
    core.runtime.wake()
    goal = _goal(core, notify=True)
    assert _status(core, goal) == ("completed", ["completed"])
    assert _effects(core) == 1
    assert core.core_execution._proof(goal) is not None
