"""EXP-009 C1: registered Core observations and persistent state.

Unlike C0, these tests use the real build_core()/Runtime ingress path.
No direct Memory writes, LLM, Godot, or synthetic world authority are used.
The observed Core-to-episodic-Memory boundary is asserted explicitly.
"""

from anima.core.assembly import build_core
from anima.core.belief import PropertyRule
from anima.core.ingress import CONTRACT, SourceRegistration


SUBJECT = "entity.test_rig@exp009"
TEMP = "system.temperature@1"
COOLING = "system.cooling@1"
TEMP_A = "sensor.temperature_a"
TEMP_B = "sensor.temperature_b"
COOLING_SENSOR = "sensor.cooling"
CLOCK = "lab_tick"


def _core(data_dir):
    sources = {
        source: SourceRegistration(
            source_ref=source,
            producer_ref="adapter.exp009/0.1",
            allowed_kinds=("state.property", "sensor.unavailable"),
        )
        for source in (TEMP_A, TEMP_B, COOLING_SENSOR)
    }
    properties = {
        (SUBJECT, TEMP): PropertyRule(
            subject_ref=SUBJECT,
            predicate_ref=TEMP,
            value_type="integer",
            clock_domain=CLOCK,
            allowed_sources=(TEMP_A, TEMP_B),
            freshness_ticks=2,
        ),
        (SUBJECT, COOLING): PropertyRule(
            subject_ref=SUBJECT,
            predicate_ref=COOLING,
            value_type="symbol",
            clock_domain=CLOCK,
            allowed_sources=(COOLING_SENSOR,),
            freshness_ticks=2,
            allowed_symbols=("on", "off"),
        ),
    }
    return build_core(data_dir, sources=sources, properties=properties)


def _observation(occurrence, predicate, *, tick, revision, value=None,
                 unavailable=False):
    observed = {"domain": CLOCK, "value": tick}
    payload = {
        "subject_ref": SUBJECT,
        "predicate_ref": predicate,
        "observed_at": observed,
        "temporal_scope": {"kind": "instant", "at": dict(observed)},
        "source_revision": revision,
    }
    if unavailable:
        payload["reason"] = "sensor_offline"
    elif predicate == TEMP:
        payload["value"] = {"type": "integer", "value": value}
    else:
        payload["value"] = {"type": "symbol", "value": value}
    return {
        "contract": CONTRACT,
        "occurrence_id": occurrence,
        "occurrence_version": 1,
        "kind": "sensor.unavailable" if unavailable else "state.property",
        "payload": payload,
    }


def test_c1_two_properties_survive_reopen_with_bounded_raw_history(tmp_path):
    core = _core(tmp_path)
    identity = core.identity.get()["instance_id"]
    readings = [
        (TEMP_A, _observation("t-a-10", TEMP, tick=10, revision=1, value=65)),
        (COOLING_SENSOR, _observation(
            "cool-10", COOLING, tick=10, revision=1, value="on"
        )),
        (TEMP_B, _observation("t-b-10", TEMP, tick=10, revision=1, value=67)),
    ]
    admitted = [
        core.runtime.ingest_core_event(raw, source_ref=source)
        for source, raw in readings
    ]
    assert [item.status for item in admitted] == ["ACCEPTED"] * 3

    temperature = core.runtime.read_core_belief(SUBJECT, TEMP, as_of_tick=10)
    cooling = core.runtime.read_core_belief(SUBJECT, COOLING, as_of_tick=10)
    assert temperature["status"] == "disputed"
    assert temperature["value"] is None
    assert temperature["evidence_event_ids"] == (
        admitted[0].event_id, admitted[2].event_id
    )
    assert cooling["status"] == "known"
    assert cooling["value"] == {"type": "symbol", "value": "on"}

    raw = core.event_log.load_events()
    assert [event["id"] for event in raw] == [
        item.event_id for item in admitted
    ]
    assert [event["type"] for event in raw] == ["world.observation"] * 3
    assert raw[0]["payload"]["observation"]["value"]["value"] == 65
    assert core.memory.count() == 0  # Raw evidence != episodic Memory.
    assert all(
        core.event_processing.get(item.event_id)["status"] == "skipped"
        for item in admitted
    )
    assert core.core_events.ingress.pending_event_ids() == ()

    reopened = _core(tmp_path)
    assert reopened.identity.get()["instance_id"] == identity
    assert reopened.runtime.read_core_belief(
        SUBJECT, TEMP, as_of_tick=10
    ) == temperature
    assert reopened.runtime.read_core_belief(
        SUBJECT, COOLING, as_of_tick=10
    ) == cooling
    assert reopened.event_log.load_events() == raw
    assert reopened.memory.count() == 0

    duplicate = reopened.runtime.ingest_core_event(
        readings[0][1], source_ref=TEMP_A
    )
    assert duplicate.status == "ALREADY_SEEN"
    assert duplicate.event_id == admitted[0].event_id
    assert len(reopened.event_log.load_events()) == 3
    assert reopened.runtime.read_core_belief(
        SUBJECT, TEMP
    )["revision"] == 2


def test_c1_late_evidence_and_sensor_unavailable_do_not_become_false(tmp_path):
    core = _core(tmp_path)
    a = core.runtime.ingest_core_event(
        _observation("temp-20-a", TEMP, tick=20, revision=1, value=65),
        source_ref=TEMP_A,
    )
    b = core.runtime.ingest_core_event(
        _observation("temp-20-b", TEMP, tick=20, revision=1, value=67),
        source_ref=TEMP_B,
    )
    disputed = core.runtime.read_core_belief(SUBJECT, TEMP, as_of_tick=20)
    assert disputed["status"] == "disputed"
    assert disputed["evidence_event_ids"] == (a.event_id, b.event_id)

    later = core.runtime.ingest_core_event(
        _observation("temp-21-a", TEMP, tick=21, revision=2, value=70),
        source_ref=TEMP_A,
    )
    resolved = core.runtime.read_core_belief(SUBJECT, TEMP, as_of_tick=21)
    assert resolved["status"] == "known"
    assert resolved["value"] == {"type": "integer", "value": 70}
    assert resolved["evidence_event_ids"] == (later.event_id,)

    old = core.runtime.ingest_core_event(
        _observation("temp-19-a", TEMP, tick=19, revision=3, value=61),
        source_ref=TEMP_A,
    )
    assert core.core_events.ingress.observation_outcome(
        old.event_id
    )["outcome"] == "HISTORY_ONLY"
    assert core.runtime.read_core_belief(SUBJECT, TEMP) == core.runtime.read_core_belief(
        SUBJECT, TEMP, as_of_tick=None
    )
    assert core.runtime.read_core_belief(SUBJECT, TEMP)["revision"] == 3

    core.runtime.ingest_core_event(
        _observation("cool-20", COOLING, tick=20, revision=1, value="on"),
        source_ref=COOLING_SENSOR,
    )
    missing = core.runtime.ingest_core_event(
        _observation("cool-21", COOLING, tick=21, revision=2,
                     unavailable=True),
        source_ref=COOLING_SENSOR,
    )
    unavailable = core.runtime.read_core_belief(
        SUBJECT, COOLING, as_of_tick=24
    )
    assert unavailable["status"] == "unknown"
    assert unavailable["value"] is None
    assert unavailable["last_known"] == {"type": "symbol", "value": "on"}
    assert unavailable["freshness"] == "stale"
    assert unavailable["evidence_event_ids"] == (missing.event_id,)


def test_c1_source_rejection_identity_conflict_and_pending_recovery(tmp_path):
    first = _core(tmp_path)
    payload = _observation("temp-30", TEMP, tick=30, revision=1, value=65)

    forbidden = first.runtime.ingest_core_event(
        payload, source_ref="sensor.unregistered"
    )
    assert forbidden.status == "REJECTED"
    assert first.event_log.load_events() == []

    admitted = first.core_events.ingress.admit(payload, source_ref=TEMP_A)
    assert admitted.status == "ACCEPTED"
    assert first.core_events.ingress.pending_event_ids() == (admitted.event_id,)
    assert first.event_log.load_events() == []
    assert first.runtime.read_core_belief(SUBJECT, TEMP)["status"] == "known"

    resumed = _core(tmp_path)
    resumed.runtime.wake()  # Drains durable outbox; also writes system.wake.
    assert resumed.core_events.ingress.pending_event_ids() == ()
    assert resumed.core_events.ingress.dispatch_receipt(
        admitted.event_id
    )["disposition"] == "forwarded"
    sensor_records = [
        record for record in resumed.event_log.load_events()
        if record["type"] == "world.observation"
    ]
    assert len(sensor_records) == 1
    assert sensor_records[0]["id"] == admitted.event_id

    conflicting_payload = _observation(
        "temp-30", TEMP, tick=30, revision=1, value=99
    )
    conflict = resumed.runtime.ingest_core_event(
        conflicting_payload, source_ref=TEMP_A
    )
    assert conflict.status == "IDENTITY_CONFLICT"
    assert conflict.event_id == admitted.event_id
    assert resumed.runtime.read_core_belief(
        SUBJECT, TEMP
    )["value"] == {"type": "integer", "value": 65}
    assert resumed.runtime.read_core_belief(SUBJECT, TEMP)["revision"] == 1
    assert len([
        record for record in resumed.event_log.load_events()
        if record["type"] == "world.observation"
    ]) == 1
    assert resumed.memory.count() == 0
