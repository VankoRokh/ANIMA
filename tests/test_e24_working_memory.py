"""E2.4 isolated Raw→Core pointer→materialized working memory tests.

No production Core profile, real Godot, model, executor or user data.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.lifecycle.egocentric import (
    E23ObserverPort, EgocentricView, VIEW_SCHEMA,
)
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import (
    E24WorkingMemory, E24MemoryError, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)

WORLD = "a" * 32
WORLD2 = "b" * 32
SURFACE = "lab.surface." + "0" * 24
KEY = "o" * 43


def sample(number: int, *, item: bool, epoch=1, world=WORLD, revision=None,
           item_owner="absent"):
    data = {
        "schema": VIEW_SCHEMA, "world_instance_id": world,
        "epoch": epoch, "revision": number - 1 if revision is None else revision,
        "tick": number - 1, "sample_seq": number,
        "sample_id": f"worldobs:{world}:{epoch}:{number}",
        "observer_ref": "lab.actor.anima",
        "source_ref": SOURCE,
        "coverage": {"kind": "view_cone", "fov_degrees": 90,
                     "range_limit": "none", "occlusion": "opaque_grid_cells"},
        "readings": [{
            "entity_ref": SURFACE, "category": "surface",
            "bearing_mdeg": 0, "range_milli_cells": 2000, "properties": {},
        }],
    }
    if item:
        data["readings"].append({
            "entity_ref": "lab.item.crate", "category": "item",
            "bearing_mdeg": 30_000, "range_milli_cells": 1000,
            "properties": {"owner": {
                "status": item_owner,
                "value": None if item_owner == "absent" else "lab.actor.anima",
            }},
        })
    return EgocentricView(data)


def core(root):
    return build_core(
        root,
        sources={SOURCE: vision_source_registration()},
        properties={(SUBJECT, PREDICATE): vision_digest_rule()},
    )


def observer():
    return E23ObserverPort(port=46029, observer_key=KEY)


def fake_sensing(monkeypatch, views):
    it = iter(views)
    monkeypatch.setattr(E23ObserverPort, "observe", lambda _self: next(it))


def db_query(root, sql, args=()):
    with sqlite3.connect(root / "e24_working_memory.db") as db:
        return db.execute(sql, args).fetchall()


def db_mutate(root, sql, args=()):
    with sqlite3.connect(root / "e24_working_memory.db") as db:
        db.execute(sql, args)


def test_memory_retrieves_prior_object_without_claiming_absence(tmp_path, monkeypatch):
    fake_sensing(monkeypatch, [sample(1, item=False),
                               sample(2, item=True),
                               sample(3, item=False)])
    instance = core(tmp_path)
    service = E24WorkingMemory(instance, observer())
    records = [service.observe_and_record() for _ in range(3)]
    assert len({r.core_event_id for r in records}) == 3
    assert len(instance.event_log.load_events()) == 3
    assert db_query(tmp_path, "SELECT COUNT(*) FROM e24_processed")[0][0] == 3
    assert db_query(tmp_path, "SELECT COUNT(*) FROM e24_co_seen")[0][0] == 1

    memory = service.world_model(memory_enabled=True)
    no_memory = service.world_model(memory_enabled=False)
    remembered = {x["entity_ref"]: x for x in memory["entities"]}
    current = {x["entity_ref"]: x for x in no_memory["entities"]}
    assert "lab.item.crate" in remembered
    assert "lab.item.crate" not in current
    assert remembered["lab.item.crate"]["current_observation"] == "not_observed"
    assert remembered["lab.item.crate"]["current_relative_geometry_verified"] is False
    assert remembered["lab.item.crate"]["last_seen_sample"] == records[1].sample_id
    assert remembered["lab.item.crate"]["last_seen_properties"]["owner"]["status"] == "absent"
    assert any(
        edge["kind"] == "co_observed" and edge["evidence_count"] == 1 and
        edge["relative_frame"] == "same_observer_view_not_global" and
        type(edge["last_relative_bearing_mdeg"]) is int
        for edge in memory["relations"]
    )
    assert no_memory["historical_samples"] == 1
    assert memory["historical_samples"] == 3
    assert memory["limitations"]["not_observed_does_not_mean_absent"]
    # Exact Raw is bound to Core event, not fabricated from a model summary.
    original = service.raw_evidence(records[1].sample_id)
    assert any(row["entity_ref"] == "lab.item.crate"
               for row in original.as_dict()["readings"])
    assert hashlib.sha256(original.canonical_json.encode()).hexdigest() == records[1].raw_sha256
    assert instance.core_events.ingress.dispatch_receipt(
        records[1].core_event_id
    )["disposition"] == "forwarded"
    # Core reopen + a new service instance do not lose working memory.
    reopened = E24WorkingMemory(core(tmp_path), observer())
    assert reopened.world_model() == memory
    assert len(reopened._core.event_log.load_events()) == 3
    assert reopened.recover() == ()
    assert db_query(tmp_path, "SELECT COUNT(*) FROM e24_mentions")[0][0] == 4


def test_observed_property_revision_is_not_promoted_to_knowledge(tmp_path, monkeypatch):
    fake_sensing(monkeypatch, [
        sample(1, item=True, item_owner="absent"),
        sample(2, item=True, item_owner="known"),
        sample(3, item=False),
    ])
    instance = core(tmp_path)
    service = E24WorkingMemory(instance, observer())
    for _ in range(3):
        service.observe_and_record()
    model = service.world_model()
    changes = model["observed_revisions"]
    assert len(changes) == 1
    assert changes[0]["entity_ref"] == "lab.item.crate"
    assert changes[0]["predicate_ref"] == "owner"
    assert changes[0]["previous"]["status"] == "absent"
    assert changes[0]["current"]["status"] == "known"
    assert changes[0]["interpretation"] == "changed_report_not_confirmed_knowledge"
    assert model["limitations"]["observed_property_changes_are_not_knowledge"]
    assert service.world_model(memory_enabled=False)["observed_revisions"] == []
    assert instance.memory_store.count() == 0


@pytest.mark.parametrize("cut", [
    "after_raw_commit", "after_core_admit", "after_core_link",
    "after_projection_commit",
])
def test_all_crash_cuts_resume_same_core_event(tmp_path, monkeypatch, cut):
    fake_sensing(monkeypatch, [sample(1, item=True)])
    first_core = core(tmp_path)

    def fail(stage, sample_id):
        if stage == cut:
            raise RuntimeError("cut:" + stage)

    service = E24WorkingMemory(first_core, observer(), fault_hook=fail)
    with pytest.raises(RuntimeError, match="cut:"):
        service.observe_and_record()
    rows = db_query(
        tmp_path, "SELECT sample_id,raw_json,raw_sha256,core_event_id FROM e24_raw",
    )
    assert len(rows) == 1
    assert rows[0][1] == sample(1, item=True).canonical_json
    assert hashlib.sha256(rows[0][1].encode()).hexdigest() == rows[0][2]
    first_core_id = db_query(
        tmp_path, "SELECT core_id FROM e24_binding"
    )[0][0]
    recovered_core = core(tmp_path)
    assert recovered_core.identity.get()["instance_id"] == first_core_id
    recovered = E24WorkingMemory(recovered_core, observer())
    recovered.recover()
    memory = recovered.world_model()
    assert memory["historical_samples"] == 1
    assert len(recovered_core.event_log.load_events()) == 1
    assert len(recovered_core.core_events.ingress.pending_event_ids()) == 0
    assert len(db_query(tmp_path, "SELECT * FROM e24_mentions")) == 2
    recovered.recover()
    assert len(recovered_core.event_log.load_events()) == 1
    assert len(db_query(tmp_path, "SELECT * FROM e24_co_seen")) == 1


@pytest.mark.parametrize("field,tamper", [
    ("raw_json", '{"schema":"forged"}'),
    ("raw_sha256", "0" * 64),
    ("core_event_id", "ev_not_real"),
])
def test_tampered_source_or_core_pointer_fails_closed(tmp_path, monkeypatch, field, tamper):
    fake_sensing(monkeypatch, [sample(1, item=True)])
    service = E24WorkingMemory(core(tmp_path), observer())
    service.observe_and_record()
    db_mutate(tmp_path, f"UPDATE e24_raw SET {field}=?", (tamper,))
    with pytest.raises(E24MemoryError):
        service.world_model()
    with pytest.raises(E24MemoryError):
        service.recover()


def test_tampered_derived_proof_or_binding_fails_closed(tmp_path, monkeypatch):
    fake_sensing(monkeypatch, [sample(1, item=True)])
    service = E24WorkingMemory(core(tmp_path), observer())
    service.observe_and_record()
    db_mutate(tmp_path, "UPDATE e24_processed SET raw_sha256=?", ("0" * 64,))
    with pytest.raises(E24MemoryError):
        service.world_model()
    db_mutate(tmp_path, "UPDATE e24_processed SET raw_sha256="
              "(SELECT raw_sha256 FROM e24_raw)")
    db_mutate(tmp_path, "UPDATE e24_binding SET core_id='other'")
    with pytest.raises(E24MemoryError):
        E24WorkingMemory(core(tmp_path), observer()).recover()


@pytest.mark.parametrize("table,mutation", [
    ("e24_mentions", "UPDATE e24_mentions SET range_milli_cells=99999"),
    ("e24_co_seen", "DELETE FROM e24_co_seen"),
])
def test_materialized_memory_cannot_forge_facts(tmp_path, monkeypatch, table, mutation):
    fake_sensing(monkeypatch, [sample(1, item=True)])
    service = E24WorkingMemory(core(tmp_path), observer())
    service.observe_and_record()
    db_mutate(tmp_path, mutation)
    with pytest.raises(E24MemoryError, match="materialized world memory"):
        service.world_model()


def test_unfinished_raw_never_reaches_public_memory(tmp_path, monkeypatch):
    fake_sensing(monkeypatch, [sample(1, item=True)])
    service = E24WorkingMemory(core(tmp_path), observer(),
                               fault_hook=lambda stage, _: (
                                   (_ for _ in ()).throw(RuntimeError("power cut"))
                                   if stage == "after_raw_commit" else None
                               ))
    with pytest.raises(RuntimeError, match="power cut"):
        service.observe_and_record()
    with pytest.raises(E24MemoryError):
        service.world_model()
    with pytest.raises(E24MemoryError):
        service.raw_evidence(sample(1, item=True).sample_id)


def test_world_epoch_change_cannot_merge_with_old_memory(tmp_path, monkeypatch):
    fake_sensing(monkeypatch, [sample(1, item=False),
                               sample(2, item=True, epoch=2),
                               sample(2, item=True, world=WORLD2)])
    service = E24WorkingMemory(core(tmp_path), observer())
    service.observe_and_record()
    with pytest.raises(E24MemoryError, match="world/epoch/Core"):
        service.observe_and_record()
    with pytest.raises(E24MemoryError, match="world/epoch/Core"):
        service.observe_and_record()
    assert db_query(tmp_path, "SELECT COUNT(*) FROM e24_raw")[0][0] == 1
    assert len(service._core.event_log.load_events()) == 1


def test_core_must_register_exact_vision_source(tmp_path):
    from anima.core.ingress import SourceRegistration
    bad_core = build_core(
        tmp_path, sources={SOURCE: SourceRegistration(
            SOURCE, "lab.world.forged", ("state.property",),
        )}, properties={(SUBJECT, PREDICATE): vision_digest_rule()},
    )
    with pytest.raises(E24MemoryError, match="registered exactly"):
        E24WorkingMemory(bad_core, observer())


def test_no_automatic_promotion_to_episodic_or_knowledge(tmp_path, monkeypatch):
    fake_sensing(monkeypatch, [sample(1, item=True)])
    instance = core(tmp_path)
    service = E24WorkingMemory(instance, observer())
    service.observe_and_record()
    assert instance.memory_store.count() == 0
    # Claims of confirmed Knowledge or auton Goals are not part of E2.4.
    assert instance.core_decision is None
    assert instance.core_execution is None
    assert instance.core_autonomy is None
