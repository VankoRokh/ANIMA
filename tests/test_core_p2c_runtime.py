"""P2-C end-to-end: opt-in Core ingress through Runtime and safe legacy replay."""

import json
import sqlite3

import pytest

from anima.core.assembly import build_core
from anima.core.belief import PropertyRule
from anima.core.event_bus import Event
from anima.core.ingress import CONTRACT, SourceRegistration


SUBJECT = "entity.door_01@registry-r1"
PREDICATE = "world.door_state@1"
SOURCE = "sensor.door_01"


def _registries():
    sources = {
        SOURCE: SourceRegistration(
            source_ref=SOURCE,
            producer_ref="adapter.virtual_sensor/0.1",
            allowed_kinds=("state.property", "sensor.unavailable"),
        )
    }
    properties = {
        (SUBJECT, PREDICATE): PropertyRule(
            subject_ref=SUBJECT,
            predicate_ref=PREDICATE,
            value_type="symbol",
            clock_domain="lab_tick",
            allowed_sources=(SOURCE,),
            freshness_ticks=2,
            allowed_symbols=("open", "closed"),
        )
    }
    return sources, properties


def _core(data_dir):
    sources, properties = _registries()
    return build_core(data_dir, sources=sources, properties=properties)


def _event(occurrence="door:40", *, tick=40, value="open", subject=SUBJECT):
    observed = {"domain": "lab_tick", "value": tick}
    return {
        "contract": CONTRACT,
        "occurrence_id": occurrence,
        "occurrence_version": 1,
        "kind": "state.property",
        "payload": {
            "subject_ref": subject,
            "predicate_ref": PREDICATE,
            "observed_at": observed,
            "temporal_scope": {"kind": "instant", "at": dict(observed)},
            "source_revision": tick,
            "value": {"type": "symbol", "value": value},
        },
    }


def test_p2c_runtime_ingests_belief_and_legacy_event_once(tmp_path):
    core = _core(tmp_path)
    admitted = core.runtime.ingest_core_event(_event(), source_ref=SOURCE)
    assert admitted.status == "ACCEPTED"

    belief = core.runtime.read_core_belief(SUBJECT, PREDICATE, as_of_tick=40)
    assert belief["status"] == "known"
    assert belief["freshness"] == "fresh"
    assert belief["value"]["value"] == "open"
    assert belief["evidence_event_ids"] == (admitted.event_id,)
    assert core.core_events.ingress.pending_event_ids() == ()
    assert core.core_events.ingress.dispatch_receipt(admitted.event_id)["disposition"] == "forwarded"

    raw_log = core.event_log.load_events()
    assert len(raw_log) == 1
    assert raw_log[0]["id"] == admitted.event_id
    assert raw_log[0]["type"] == "world.observation"
    assert raw_log[0]["payload"]["observation"]["value"]["value"] == "open"
    assert core.event_processing.get(admitted.event_id)["status"] == "skipped"
    assert core.runtime.snapshot()["state"]["events_processed"] == 1
    assert core.memory.count() == 0

    again = core.runtime.ingest_core_event(_event(), source_ref=SOURCE)
    assert again.status == "ALREADY_SEEN"
    assert again.event_id == admitted.event_id
    assert len(core.event_log.load_events()) == 1
    assert core.runtime.read_core_belief(SUBJECT, PREDICATE)["revision"] == 1


def test_p2c_legacy_cli_lifecycle_is_preserved_with_core_opt_in(tmp_path):
    core = _core(tmp_path)
    core.runtime.ingest_core_event(_event(), source_ref=SOURCE)
    core.runtime.wake()
    core.runtime.user_input("P2-C legacy episode")
    core.runtime.sleep()
    assert [r["type"] for r in core.event_log.load_events()] == [
        "world.observation", "system.wake", "conversation.user", "system.sleep"
    ]
    assert core.runtime.snapshot()["state"]["events_processed"] == 4
    assert core.memory.count() == 1
    assert core.runtime.read_core_belief(SUBJECT, PREDICATE)["revision"] == 1


@pytest.mark.parametrize("stage", ["after_legacy_append", "after_legacy_projection"])
def test_p2c_crash_between_legacy_steps_recovers_without_duplicate(tmp_path, stage):
    first = _core(tmp_path)

    def fail(at, event_id):
        if at == stage:
            raise RuntimeError(f"controlled {stage} failure")

    first.core_events.fault_hook = fail
    with pytest.raises(RuntimeError, match=f"controlled {stage}"):
        first.runtime.ingest_core_event(_event(), source_ref=SOURCE)

    pending = first.core_events.ingress.pending_event_ids()
    assert len(pending) == 1
    event_id = pending[0]
    assert len(first.event_log.load_events()) == 1
    assert first.core_events.ingress.dispatch_receipt(event_id) is None

    second = _core(tmp_path)
    second.runtime.wake()  # recovery handles outstanding Core durable intent
    assert second.core_events.ingress.pending_event_ids() == ()
    assert second.core_events.ingress.dispatch_receipt(event_id)["disposition"] == "forwarded"
    assert len([x for x in second.event_log.load_events() if x["id"] == event_id]) == 1
    assert second.event_processing.get(event_id)["status"] == "skipped"
    assert second.runtime.snapshot()["state"]["events_processed"] == 2
    assert second.runtime.read_core_belief(SUBJECT, PREDICATE)["revision"] == 1
    second.runtime.sleep()


def test_p2c_crash_before_legacy_append_keeps_pending_and_resumes(tmp_path):
    first = _core(tmp_path)
    def fail(at, event_id):
        if at == "after_legacy_append":
            # Simulate I/O crash before any log bytes persist by stopping
            # before the dispatcher explicitly writes: use EventLog.write fault.
            pass

    original_write = first.event_log.write

    def fail_write(event):
        raise RuntimeError("controlled legacy write failure")

    first.event_log.write = fail_write
    with pytest.raises(RuntimeError, match="controlled legacy write failure"):
        first.runtime.ingest_core_event(_event(), source_ref=SOURCE)
    assert first.event_log.load_events() == []
    assert len(first.core_events.ingress.pending_event_ids()) == 1
    first.event_log.write = original_write

    second = _core(tmp_path)
    second.runtime.wake()
    assert second.core_events.ingress.pending_event_ids() == ()
    assert len([r for r in second.event_log.load_events()
                if r["type"] == "world.observation"]) == 1
    assert second.runtime.read_core_belief(SUBJECT, PREDICATE)["revision"] == 1


def test_p2c_core_only_admission_replayed_on_next_runtime_wake(tmp_path):
    first = _core(tmp_path)
    pending = first.core_events.ingress.admit(_event(), source_ref=SOURCE)
    assert pending.status == "ACCEPTED"
    assert first.event_log.load_events() == []
    assert first.core_events.ingress.pending_event_ids() == (pending.event_id,)

    second = _core(tmp_path)
    second.runtime.wake()
    assert second.core_events.ingress.pending_event_ids() == ()
    assert second.core_events.ingress.dispatch_receipt(pending.event_id)["disposition"] == "forwarded"
    assert second.runtime.snapshot()["state"]["events_processed"] == 2
    assert second.runtime.read_core_belief(SUBJECT, PREDICATE)["status"] == "known"


def test_p2c_rejected_observation_does_not_enter_legacy_history(tmp_path):
    core = _core(tmp_path)
    invalid = core.runtime.ingest_core_event(
        _event(subject="entity.unregistered"), source_ref=SOURCE
    )
    assert invalid.status == "ACCEPTED"  # raw journal, not belief truth
    assert core.core_events.ingress.observation_outcome(invalid.event_id)["outcome"] == "REJECTED_INVALID"
    assert core.core_events.ingress.dispatch_receipt(invalid.event_id)["disposition"] == "filtered"
    assert core.event_log.load_events() == []
    assert core.runtime.read_core_belief(SUBJECT, PREDICATE)["revision"] == 0
    assert core.core_events.ingress.pending_event_ids() == ()


def test_p2c_legacy_id_collision_is_fail_closed(tmp_path):
    core = _core(tmp_path)
    admitted = core.core_events.ingress.admit(_event(), source_ref=SOURCE)
    core.event_log.write(Event(
        "world.observation",
        {"forged": True},
        source="core.ingress",
        event_id=admitted.event_id,
        timestamp=core.core_events.ingress.get_event(admitted.event_id)["received_at"],
    ))
    with pytest.raises(ValueError, match="identity conflict"):
        core.runtime.wake()
    assert core.core_events.ingress.dispatch_receipt(admitted.event_id) is None
    assert core.core_events.ingress.pending_event_ids() == (admitted.event_id,)
    assert core.runtime.read_core_belief(SUBJECT, PREDICATE)["revision"] == 1


def test_p2c_dispatch_receipt_idempotent_and_conflict_guarded(tmp_path):
    core = _core(tmp_path)
    admitted = core.runtime.ingest_core_event(_event(), source_ref=SOURCE)
    ingress = core.core_events.ingress
    assert ingress.acknowledge_dispatch(admitted.event_id, disposition="forwarded") is False
    with pytest.raises(ValueError, match="acknowledgment conflict"):
        ingress.acknowledge_dispatch(admitted.event_id, disposition="filtered")
    with pytest.raises(ValueError, match="Unknown Core outbox"):
        ingress.acknowledge_dispatch("ev_missing", disposition="filtered")
    assert ingress.pending_event_ids() == ()


def test_p2c_bounded_drain_preserves_pending_work(tmp_path):
    core = _core(tmp_path)
    ids = [
        core.core_events.ingress.admit(
            _event(f"door:{40+i}", tick=40+i, value=("open" if i % 2 == 0 else "closed")),
            source_ref=SOURCE,
        ).event_id
        for i in range(5)
    ]
    first = core.core_events.drain(max_events=2)
    assert [turn.event_id for turn in first] == ids[:2]
    assert core.core_events.ingress.pending_event_ids() == tuple(ids[2:])
    assert len(core.event_log.load_events()) == 2
    second = core.core_events.drain(max_events=3)
    assert [turn.event_id for turn in second] == ids[2:]
    assert core.core_events.ingress.pending_event_ids() == ()
    assert len(core.event_log.load_events()) == 5


def test_p2c_opt_in_preserves_default_legacy_runtime(tmp_path):
    core = build_core(tmp_path)
    assert core.core_events is None
    with pytest.raises(RuntimeError, match="not configured"):
        core.runtime.ingest_core_event(_event(), source_ref=SOURCE)
    with pytest.raises(RuntimeError, match="not configured"):
        core.runtime.read_core_belief(SUBJECT, PREDICATE)
    assert not (tmp_path / "core_state.db").exists()
    core.runtime.wake()
    core.runtime.sleep()
    assert core.runtime.snapshot()["state"]["events_processed"] == 2


def test_p2c_schema_upgrade_preserves_v2_journal_and_belief(tmp_path):
    core = _core(tmp_path)
    admitted = core.core_events.ingress.admit(_event(), source_ref=SOURCE)
    with sqlite3.connect(tmp_path / "core_state.db") as connection:
        connection.execute("DROP TABLE core_dispatch_receipts")
        connection.execute("UPDATE schema_meta SET value='2' WHERE key='schema_version'")
    reopened = _core(tmp_path)
    assert reopened.core_events.ingress.get_event(admitted.event_id) is not None
    assert reopened.runtime.read_core_belief(SUBJECT, PREDICATE)["revision"] == 1
    assert reopened.core_events.ingress.pending_event_ids() == (admitted.event_id,)
    reopened.runtime.wake()
    assert reopened.core_events.ingress.pending_event_ids() == ()
    with sqlite3.connect(tmp_path / "core_state.db") as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "3"


def test_p2c_raw_invalid_source_stays_out_of_legacy_memory(tmp_path):
    core = _core(tmp_path)
    result = core.runtime.ingest_core_event(_event(), source_ref="sensor.forged")
    assert result.status == "REJECTED"
    assert core.core_events.ingress.pending_event_ids() == ()
    assert core.event_log.load_events() == []
    assert core.memory.count() == 0
