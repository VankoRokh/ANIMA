"""E2.1 trust/admission regression for an observation-only, Core-bound gateway.

This tests a capability mediation API, not adversarial Python sandboxing:
a hostile OS process with direct loopback access can still spoof operator.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from anima.core.assembly import build_core
from anima.core.ingress import SourceRegistration
from labs.virtual_anima_lab.python.lifecycle.contracts import OBSERVATION_SCHEMA
from labs.virtual_anima_lab.python.lifecycle.core_gateway import (
    CoreBoundObservationGateway, PRODUCER_REF, SOURCE_REF,
    WorldBoundaryError, lifecycle_source_registration,
)

WORLD = "a" * 32
OTHER_WORLD = "b" * 32


def observation(*, world=WORLD, epoch=1, seq=1, revision=0, tick=0,
                source=SOURCE_REF, actor=(3, 5)) -> dict:
    return {
        "schema": OBSERVATION_SCHEMA, "world_instance_id": world,
        "epoch": epoch, "revision": revision, "tick": tick,
        "sample_seq": seq,
        "sample_id": f"worldobs:{world}:{epoch}:{seq}",
        "source_ref": source, "observer_ref": "lab.actor.anima",
        "visibility": {"kind": "line_of_sight", "radius": 3},
        "self_position": {"x": actor[0], "y": actor[1]},
        "readings": [],
    }


def reply(data, *, epoch=1, revision=0, tick=0):
    return {"data": data, "epoch": epoch, "revision": revision, "tick": tick}


def hello(*, world=WORLD, epoch=1, capabilities=None, extra=None):
    result = {
        "ready": True, "world_version": "lifecycle-grid/0.1",
        "world_instance_id": world, "epoch": epoch,
        "capabilities": (
            ["observe", "act", "operation_status"]
            if capabilities is None else capabilities
        ),
    }
    if extra:
        result.update(extra)
    return result


class FakeConnection:
    def __init__(self, welcome, sample, *, calls):
        self._welcome = welcome
        self._sample = sample
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return None

    def call(self, op):
        self._calls.append(op)
        if op == "hello":
            return reply(self._welcome, epoch=self._welcome["epoch"])
        if op == "observe":
            return reply(
                self._sample, epoch=self._sample["epoch"],
                revision=self._sample["revision"], tick=self._sample["tick"],
            )
        raise AssertionError(f"Unexpected network capability: {op}")


class FakeFactory:
    def __init__(self, pairs):
        self._pairs = list(pairs)
        self.calls = []
        self.open_roles = []

    def __call__(self, port, *, role, protocol, timeout):
        self.open_roles.append(role)
        assert role == "agent"
        assert protocol == "val.bridge/0.2"
        assert port == 46029 and timeout == 3
        welcome, obs = self._pairs.pop(0)
        return FakeConnection(welcome, obs, calls=self.calls)


def core_instance(tmp_path, *, reg=None):
    registration = reg or lifecycle_source_registration()
    return build_core(
        tmp_path / "core",
        sources={SOURCE_REF: registration},
        properties={},
    )


def bound(tmp_path, pairs):
    core = core_instance(tmp_path)
    factory = FakeFactory(pairs)
    return CoreBoundObservationGateway(
        core, client_factory=factory,
    ), factory, core


def test_registered_core_gateway_only_reads_and_pins_monotonic_samples(tmp_path):
    gateway, factory, core = bound(tmp_path, [
        (hello(), observation()),
        (hello(), observation(seq=2, tick=1, revision=1)),
    ])
    assert gateway.binding_snapshot() is None
    first = gateway.observe()
    assert first.as_dict()["self_position"] == {"x": 3, "y": 5}
    clone = first.as_dict()
    clone["self_position"]["x"] = 999
    assert first.as_dict()["self_position"] == {"x": 3, "y": 5}
    second = gateway.observe()
    assert second.as_dict()["sample_seq"] == 2
    assert gateway.binding_snapshot() == {
        "world_instance_id": WORLD, "epoch": 1, "sample_seq": 2,
        "revision": 1, "tick": 1,
    }
    assert factory.calls == ["hello", "observe", "hello", "observe"]
    assert factory.open_roles == ["agent", "agent"]
    assert core.runtime.core_execution is None


def test_gateway_never_exports_operator_or_action_capability(tmp_path):
    gateway, factory, _ = bound(tmp_path, [(hello(), observation())])
    for method in ("act", "execute", "move", "pick", "drop", "inspect",
                   "set_obstacle", "operation_status", "client", "connect"):
        assert not hasattr(gateway, method), method
    gateway.observe()
    assert factory.calls == ["hello", "observe"]


@pytest.mark.parametrize("welcome", [
    hello(extra={"seed": 7}),
    hello(extra={"walls": []}),
    hello(capabilities=["observe", "act", "operation_status", "inspect"]),
    hello(capabilities=["observe", "act"]),
    hello(world=OTHER_WORLD),
    {**hello(), "world_version": "p5a-grid/0.1"},
    {**hello(), "ready": 1},
    {**hello(), "epoch": True},
])
def test_unsafe_or_mismatched_handshake_is_rejected(tmp_path, welcome):
    gateway, _, _ = bound(tmp_path, [(welcome, observation())])
    if welcome.get("world_instance_id") == OTHER_WORLD:
        # A different world is legal on FIRST binding when observation agrees;
        # here observation still names the original world and must be rejected.
        pass
    with pytest.raises(WorldBoundaryError):
        gateway.observe()
    assert gateway.binding_snapshot() is None


def test_exact_core_source_registry_is_required(tmp_path):
    with pytest.raises(WorldBoundaryError, match="registered CoreIngress"):
        CoreBoundObservationGateway(build_core(tmp_path / "no-source"))
    wrong = SourceRegistration(
        source_ref=SOURCE_REF, producer_ref="test.unapproved.producer",
        allowed_kinds=("state.property",),
    )
    with pytest.raises(WorldBoundaryError, match="registration"):
        CoreBoundObservationGateway(core_instance(tmp_path, reg=wrong))
    gateway = CoreBoundObservationGateway(core_instance(tmp_path / "safe"))
    assert gateway.binding_snapshot() is None


@pytest.mark.parametrize("bad", [
    observation(source="lab.sensor.attacker.fake"),
    observation(epoch=2),
    observation(world=OTHER_WORLD),
])
def test_sensor_hello_envelope_binding_fail_closed(tmp_path, bad):
    gateway, _, _ = bound(tmp_path, [(hello(), bad)])
    with pytest.raises(WorldBoundaryError):
        gateway.observe()
    assert gateway.binding_snapshot() is None


@pytest.mark.parametrize("bad", [
    observation(seq=1, tick=1),
    observation(seq=2, revision=0, tick=2),
    observation(seq=2, revision=1, tick=0),
    observation(world=OTHER_WORLD, seq=2),
    observation(epoch=2, seq=2),
])
def test_no_rebinding_or_clock_rollback_even_after_failed_read(tmp_path, bad):
    gateway, _, core = bound(tmp_path, [
        (hello(), observation(seq=1, revision=1, tick=1)),
        (hello(world=bad["world_instance_id"], epoch=bad["epoch"]), bad),
    ])
    assert gateway.observe().as_dict()["revision"] == 1
    snapshot = gateway.binding_snapshot()
    with pytest.raises(WorldBoundaryError):
        gateway.observe()
    assert gateway.binding_snapshot() == snapshot


def test_core_reopen_recovers_pin_not_resets_trust(tmp_path):
    gateway, _, core = bound(tmp_path, [
        (hello(), observation(seq=1, tick=1)),
    ])
    gateway.observe()
    fresh_core = build_core(
        core.data_dir,
        sources={SOURCE_REF: lifecycle_source_registration()},
        properties={},
    )
    different_world = FakeFactory([
        (hello(world=OTHER_WORLD), observation(world=OTHER_WORLD, seq=1, tick=0)),
    ])
    recovered = CoreBoundObservationGateway(
        fresh_core, client_factory=different_world,
    )
    assert recovered.binding_snapshot()["world_instance_id"] == WORLD
    with pytest.raises(WorldBoundaryError, match="binding changed"):
        recovered.observe()
    assert recovered.binding_snapshot()["world_instance_id"] == WORLD


def test_core_execution_conflict_fails_closed(tmp_path):
    core = core_instance(tmp_path)
    with pytest.raises(WorldBoundaryError):
        CoreBoundObservationGateway(replace(core, core_execution=object()))
    with pytest.raises(TypeError):
        CoreBoundObservationGateway(object())


def test_binding_does_not_confuse_source_name_with_authentication(tmp_path):
    source = lifecycle_source_registration()
    assert source.source_ref == SOURCE_REF
    assert source.producer_ref == PRODUCER_REF
    assert source.allowed_kinds == ("state.property", "sensor.unavailable")
    # Production verification must come from CoreIngress + E2.2 Raw, not from
    # this user-forgeable string. No event or Goal is written in E2.1.
    gateway, _, core = bound(tmp_path, [(hello(), observation())])
    gateway.observe()
    assert core.core_events.ingress.pending_event_ids(limit=10) == ()
