"""P2-A event ingress contracts: durable receipt, scoped dedupe and rollback."""

import sqlite3

import pytest

from anima.core.ingress import CONTRACT, CoreIngress, SourceRegistration


SOURCE = "sensor.door_01"


def _sources():
    return {
        SOURCE: SourceRegistration(
            source_ref=SOURCE,
            producer_ref="adapter.virtual_sensor/0.1",
            allowed_kinds=("state.property", "sensor.unavailable"),
        ),
        "sensor.window_01": SourceRegistration(
            source_ref="sensor.window_01",
            producer_ref="adapter.virtual_sensor/0.1",
            allowed_kinds=("state.property",),
        ),
    }


def _event(occurrence="reading-1", *, value="open", version=1):
    return {
        "contract": CONTRACT,
        "occurrence_id": occurrence,
        "occurrence_version": version,
        "kind": "state.property",
        "payload": {
            "entity": "entity.door_01",
            "predicate": "world.door_state",
            "value": {"type": "symbol", "value": value},
            "observed_at": {"clock": "lab_tick", "tick": 40},
        },
    }


def _ingress(tmp_path, *, fault_hook=None):
    return CoreIngress(
        tmp_path / "core_state.db",
        sources=_sources(),
        fault_hook=fault_hook,
    )


def test_p2a_accepts_event_and_dispatch_intent_atomically(tmp_path):
    ingress = _ingress(tmp_path)
    result = ingress.admit(_event(), source_ref=SOURCE)

    assert result.status == "ACCEPTED"
    assert result.event_id.startswith("ev_")
    assert ingress.pending_event_ids() == (result.event_id,)
    stored = ingress.get_event(result.event_id)
    assert stored["source_ref"] == SOURCE
    assert stored["producer_ref"] == "adapter.virtual_sensor/0.1"
    assert stored["kind"] == "state.property"
    assert stored["payload"]["value"]["value"] == "open"
    assert stored["received_at"].endswith("+00:00")

    with sqlite3.connect(tmp_path / "core_state.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM core_events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM core_outbox").fetchone()[0] == 1


def test_p2a_replay_survives_reopen_and_does_not_repeat_outbox(tmp_path):
    first = _ingress(tmp_path)
    accepted = first.admit(_event(), source_ref=SOURCE)
    second = _ingress(tmp_path)
    repeated = second.admit(_event(), source_ref=SOURCE)

    assert repeated.status == "ALREADY_SEEN"
    assert repeated.event_id == accepted.event_id
    assert second.pending_event_ids() == (accepted.event_id,)
    assert second.rejection_count() == 0


def test_p2a_canonical_json_ignores_payload_key_order(tmp_path):
    ingress = _ingress(tmp_path)
    a = _event()
    b = _event()
    b["payload"] = dict(reversed(tuple(b["payload"].items())))
    first = ingress.admit(a, source_ref=SOURCE)
    second = ingress.admit(b, source_ref=SOURCE)
    assert second.status == "ALREADY_SEEN"
    assert second.event_id == first.event_id


def test_p2a_same_occurrence_conflicting_content_is_not_overwritten(tmp_path):
    ingress = _ingress(tmp_path)
    accepted = ingress.admit(_event(), source_ref=SOURCE)
    conflict = ingress.admit(_event(value="closed"), source_ref=SOURCE)

    assert conflict.status == "IDENTITY_CONFLICT"
    assert conflict.event_id == accepted.event_id
    assert conflict.reason_code == "IDENTITY_CONFLICT"
    assert ingress.get_event(accepted.event_id)["payload"]["value"]["value"] == "open"
    assert ingress.pending_event_ids() == (accepted.event_id,)
    assert ingress.rejection_count() == 1


def test_p2a_versions_and_sources_are_distinct_occurrences(tmp_path):
    ingress = _ingress(tmp_path)
    first = ingress.admit(_event(), source_ref=SOURCE)
    second = ingress.admit(_event(version=2, value="closed"), source_ref=SOURCE)
    third = ingress.admit(_event(), source_ref="sensor.window_01")

    assert len({first.event_id, second.event_id, third.event_id}) == 3
    assert len(ingress.pending_event_ids()) == 3


@pytest.mark.parametrize(
    "raw",
    [
        {"contract": CONTRACT},
        {**_event(), "received_at": "2020-01-01T00:00:00+00:00"},
        {**_event(), "event_id": "ev_attacker"},
        {**_event(), "occurrence_version": True},
        {**_event(), "kind": "unregistered.kind"},
        {**_event(), "payload": {"measurement": 0.1}},
        {**_event(), "payload": {"too_big": "x" * 17_000}},
        {**_event(), "payload": {"unsupported": object()}},
    ],
)
def test_p2a_invalid_envelopes_are_rejected_without_event_mutation(tmp_path, raw):
    ingress = _ingress(tmp_path)
    result = ingress.admit(raw, source_ref=SOURCE)
    assert result.status == "REJECTED"
    assert result.reason_code == "INVALID_ENVELOPE"
    assert ingress.pending_event_ids() == ()
    assert ingress.rejection_count() == 1


def test_p2a_unknown_source_is_denied_and_audited(tmp_path):
    ingress = _ingress(tmp_path)
    denied = ingress.admit(_event(), source_ref="sensor.forged")
    assert denied.status == "REJECTED"
    assert denied.reason_code == "UNKNOWN_SOURCE"
    assert ingress.pending_event_ids() == ()
    assert ingress.rejection_count() == 1


def test_p2a_input_mutation_after_admission_does_not_change_stored_event(tmp_path):
    ingress = _ingress(tmp_path)
    external = _event()
    result = ingress.admit(external, source_ref=SOURCE)
    external["payload"]["value"]["value"] = "closed"
    assert ingress.get_event(result.event_id)["payload"]["value"]["value"] == "open"


def test_p2a_fault_between_event_and_commit_rolls_back_outbox_and_event(tmp_path):
    def fail(_event_id):
        raise RuntimeError("fault after insert before commit")

    faulting = _ingress(tmp_path, fault_hook=fail)
    with pytest.raises(RuntimeError, match="fault after insert"):
        faulting.admit(_event(), source_ref=SOURCE)

    reopened = _ingress(tmp_path)
    assert reopened.pending_event_ids() == ()
    with sqlite3.connect(tmp_path / "core_state.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM core_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM core_outbox").fetchone()[0] == 0

    accepted = reopened.admit(_event(), source_ref=SOURCE)
    assert accepted.status == "ACCEPTED"


def test_p2a_does_not_write_legacy_history_or_boot_core_runtime(tmp_path):
    ingress = _ingress(tmp_path)
    ingress.admit(_event(), source_ref=SOURCE)
    assert not (tmp_path / "events.jsonl").exists()
    assert not (tmp_path / "memory.db").exists()
    assert not (tmp_path / "state.json").exists()
