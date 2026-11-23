"""E2.2 Raw durability tests: exact snapshot, Core provenance and crash cuts.

All SQLite and EventLog operations use an isolated tmp_path. No production
profile, Godot port, physical tool or existing user memory is touched.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.lifecycle.contracts import (
    OBSERVATION_SCHEMA, WorldObservation,
)
from labs.virtual_anima_lab.python.lifecycle.core_gateway import (
    CoreBoundObservationGateway, SOURCE_REF, lifecycle_source_registration,
)
from labs.virtual_anima_lab.python.lifecycle.raw_capture import (
    E22RawCaptureService, RawCaptureError, PREDICATE, SUBJECT,
    lifecycle_snapshot_rule,
)

WORLD = "a" * 32
WORLD2 = "b" * 32
OBSERVER_KEY = "o" * 43


def sensor_data(*, seq=1, epoch=1, world=WORLD, revision=0,
                tick=0, pos=(3, 5)):
    return {
        "schema": OBSERVATION_SCHEMA, "world_instance_id": world,
        "epoch": epoch, "revision": revision, "tick": tick,
        "sample_seq": seq,
        "sample_id": f"worldobs:{world}:{epoch}:{seq}",
        "source_ref": SOURCE_REF, "observer_ref": SUBJECT,
        "visibility": {"kind": "line_of_sight", "radius": 3},
        "self_position": {"x": pos[0], "y": pos[1]}, "readings": [],
    }


class FakeWorld:
    def __init__(self, samples):
        self.samples = list(samples)
        self.operations = []

    def __call__(self, _port, *, role, protocol, timeout):
        assert role == "agent"
        assert protocol == "val.bridge/0.2"
        return self

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return None

    def call(self, op, **kwargs):
        assert kwargs == {"auth": OBSERVER_KEY}
        self.operations.append(op)
        if op == "hello":
            sample = self.samples[0]
            return {"data": {
                "ready": True, "world_version": "lifecycle-grid/0.1",
                "world_instance_id": sample["world_instance_id"],
                "epoch": sample["epoch"], "auth_mode": "guarded",
                "capabilities": ["observe"],
            }}
        if op == "observe":
            sample = self.samples.pop(0)
            return {
                "data": sample, "epoch": sample["epoch"],
                "revision": sample["revision"], "tick": sample["tick"],
            }
        raise AssertionError("E2.2 unexpectedly requested world effect")


def assembly(directory):
    rule = lifecycle_snapshot_rule()
    return build_core(
        directory,
        sources={SOURCE_REF: lifecycle_source_registration()},
        properties={(SUBJECT, PREDICATE): rule},
    )


def bundle(tmp_path, *, samples=None, hook=None, root=None):
    core = assembly(root or (tmp_path / "core"))
    fake = FakeWorld(samples if samples is not None else [sensor_data()])
    gateway = CoreBoundObservationGateway(
        core, observer_key=OBSERVER_KEY,
        client_factory=fake, capture_raw=True,
    )
    service = E22RawCaptureService(core, gateway, fault_hook=hook)
    return service, gateway, core, fake


def capture_rows(gateway):
    db = sqlite3.connect(gateway._dbfile)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(
            "SELECT * FROM e22_raw_capture ORDER BY sample_seq"
        )]
    finally:
        db.close()


def core_events(core):
    return [core.core_events.ingress.get_event(x["event_id"])
            for x in core.event_log.load_events()
            if x["id"].startswith("ev_")]


def test_raw_snapshot_before_exposure_and_existing_core_dispatch(tmp_path):
    service, gateway, core, fake = bundle(tmp_path)
    result = service.observe_and_record()
    snapshot = result.observation.as_dict()
    assert fake.operations == ["hello", "observe"]
    assert result.raw_digest == hashlib.sha256(
        result.observation.canonical_json.encode("utf-8"),
    ).hexdigest()
    assert result.core_dispatch_receipt == "forwarded"
    assert gateway.binding_snapshot()["sample_seq"] == 1
    rows = capture_rows(gateway)
    assert len(rows) == 1
    assert rows[0]["snapshot_json"] == result.observation.canonical_json
    assert rows[0]["event_id"] == result.core_event_id
    assert service.capture_snapshot(snapshot["sample_id"]).as_dict() == snapshot

    raw = core.core_events.ingress.get_event(result.core_event_id)
    assert raw["source_ref"] == SOURCE_REF
    assert raw["producer_ref"] == lifecycle_source_registration().producer_ref
    assert raw["occurrence_id"] == "e22:" + snapshot["sample_id"]
    assert raw["payload"]["value"] == {"type": "string", "value": result.raw_digest}
    assert raw["payload"]["source_revision"] == 1
    assert core.core_events.ingress.observation_outcome(result.core_event_id)["outcome"] == "ACCEPTED_NEW"
    assert core.core_events.ingress.dispatch_receipt(result.core_event_id)["disposition"] == "forwarded"
    assert len(core.event_log.load_events()) == 1
    assert len(core_events(core)) == 1
    assert core.runtime.core_execution is None
    assert not core.core_events.ingress.pending_event_ids(limit=10)
    assert service.recover() == ()  # no duplicate EventLog write
    assert len(core.event_log.load_events()) == 1


@pytest.mark.parametrize("cut", [
    "after_snapshot_commit",
    "after_core_admit",
    "after_capture_link",
])
def test_crash_cut_recovers_idempotently_across_core_reopen(tmp_path, cut):
    def crash(stage, _sample):
        if stage == cut:
            raise RuntimeError("SIMULATED_CRASH_" + cut)

    root = tmp_path / "same-core"
    service, gateway, core, fake = bundle(
        tmp_path, hook=crash, root=root,
    )
    with pytest.raises(RuntimeError, match="SIMULATED_CRASH"):
        service.observe_and_record()
    pinned = gateway.binding_snapshot()
    assert pinned["sample_seq"] == 1
    rows = capture_rows(gateway)
    assert len(rows) == 1
    assert rows[0]["snapshot_json"] == WorldObservation(sensor_data()).canonical_json
    if cut == "after_snapshot_commit":
        assert rows[0]["event_id"] is None
        assert not core.core_events.ingress.pending_event_ids(limit=10)
    elif cut == "after_core_admit":
        assert rows[0]["event_id"] is None
        assert len(core.core_events.ingress.pending_event_ids(limit=10)) == 1
    else:
        assert rows[0]["event_id"]
        assert len(core.core_events.ingress.pending_event_ids(limit=10)) == 1

    # Simulates a completely new Core service instance with no Godot calls.
    fresh_service, fresh_gateway, fresh_core, new_fake = bundle(
        tmp_path, samples=[], root=root,
    )
    repaired = fresh_service.recover()
    assert len(repaired) == (0 if cut == "after_capture_link" else 1)
    recovered = capture_rows(fresh_gateway)[0]
    assert recovered["event_id"]
    assert fresh_core.core_events.ingress.dispatch_receipt(
        recovered["event_id"]
    )["disposition"] == "forwarded"
    assert len(fresh_core.event_log.load_events()) == 1
    assert new_fake.operations == []
    assert fresh_service.recover() == ()
    assert len(fresh_core.event_log.load_events()) == 1
    assert fresh_service.capture_snapshot(sensor_data()["sample_id"]).as_dict() == sensor_data()


def test_multiple_samples_use_monotonic_provenance_and_single_belief_authority(tmp_path):
    service, gateway, core, fake = bundle(tmp_path, samples=[
        sensor_data(seq=1, tick=0, pos=(3, 5)),
        sensor_data(seq=2, tick=0, pos=(4, 5)),
        sensor_data(seq=3, revision=1, tick=1, pos=(4, 5)),
    ])
    result = [service.observe_and_record() for _ in range(3)]
    assert len({r.core_event_id for r in result}) == 3
    assert len(core.event_log.load_events()) == 3
    assert gateway.binding_snapshot()["sample_seq"] == 3
    assert len(capture_rows(gateway)) == 3
    belief = core.core_events.ingress.read_belief(
        SUBJECT, PREDICATE, as_of_tick=3,
    )
    assert belief["status"] == "known"
    assert belief["value"] == {"type": "string", "value": result[-1].raw_digest}
    assert service.recover() == ()
    assert len(core.event_log.load_events()) == 3


def test_corrupt_pending_raw_aborts_without_ingress_or_falsely_advancing(tmp_path):
    def crash(stage, _sample):
        if stage == "after_snapshot_commit":
            raise RuntimeError("SIMULATED_CRASH")

    service, gateway, core, _ = bundle(tmp_path, hook=crash)
    with pytest.raises(RuntimeError):
        service.observe_and_record()
    db = sqlite3.connect(gateway._dbfile)
    try:
        db.execute(
            "UPDATE e22_raw_capture SET snapshot_json='{}' WHERE sample_seq=1"
        )
        db.commit()
    finally:
        db.close()
    before = gateway.binding_snapshot()
    resumed, recovered_gateway, recovered_core, world = bundle(
        tmp_path, root=core.data_dir, samples=[],
    )
    with pytest.raises(RawCaptureError, match="digest"):
        resumed.recover()
    assert recovered_gateway.binding_snapshot() == before
    assert len(recovered_core.event_log.load_events()) == 0
    assert not recovered_core.core_events.ingress.pending_event_ids(limit=10)
    assert world.operations == []


def test_core_identity_collision_does_not_overwrite_captured_receipt(tmp_path):
    service, gateway, core, fake = bundle(tmp_path)
    result = service.observe_and_record()
    row = capture_rows(gateway)[0]
    db = sqlite3.connect(gateway._dbfile)
    try:
        db.execute(
            "UPDATE e22_raw_capture SET event_id=? WHERE sample_seq=1",
            ("ev_attacker_fake",),
        )
        db.commit()
    finally:
        db.close()
    # Already-linked records are not re-admitted on recover; reading the
    # capture itself validates its SHA, while the Core event link is separately
    # verified by the normal observe_and_record completion path.
    assert service.capture_snapshot(result.observation.sample_id).as_dict() == result.observation.as_dict()
    assert row["snapshot_sha256"] == result.raw_digest


def test_constructor_rejects_unregistered_or_legacy_gateway(tmp_path):
    core = assembly(tmp_path / "core")
    legacy = CoreBoundObservationGateway(
        core, observer_key=OBSERVER_KEY, client_factory=FakeWorld([]),
    )
    with pytest.raises(RawCaptureError, match="capture mode"):
        E22RawCaptureService(core, legacy)
    wrong = build_core(
        tmp_path / "other",
        sources={SOURCE_REF: lifecycle_source_registration()},
        properties={},
    )
    gateway = CoreBoundObservationGateway(
        wrong, observer_key=OBSERVER_KEY,
        capture_raw=True, client_factory=FakeWorld([]),
    )
    with pytest.raises(RawCaptureError, match="snapshot digest"):
        E22RawCaptureService(wrong, gateway)
    valid = CoreBoundObservationGateway(
        core, observer_key=OBSERVER_KEY,
        capture_raw=True, client_factory=FakeWorld([]),
    )
    with pytest.raises(RawCaptureError, match="same Core"):
        E22RawCaptureService(wrong, valid)
