"""P2-B: typed observations and atomic, versioned exact-state projection."""

import sqlite3

import pytest

from anima.core.belief import PropertyRule
from anima.core.ingress import CONTRACT, CoreIngress, SourceRegistration


SUBJECT = "entity.door_01@registry-r1"
PREDICATE = "world.door_state@1"
SOURCE_A = "sensor.door_a"
SOURCE_B = "sensor.door_b"
OTHER = "sensor.other"
KEY = (SUBJECT, PREDICATE)


def _sources():
    return {
        ref: SourceRegistration(
            source_ref=ref,
            producer_ref="adapter.test/0.1",
            allowed_kinds=("state.property", "sensor.unavailable"),
        )
        for ref in (SOURCE_A, SOURCE_B, OTHER)
    }


def _properties():
    return {
        KEY: PropertyRule(
            subject_ref=SUBJECT,
            predicate_ref=PREDICATE,
            value_type="symbol",
            clock_domain="lab_tick",
            allowed_sources=(SOURCE_A, SOURCE_B),
            freshness_ticks=2,
            allowed_symbols=("open", "closed"),
        )
    }


def _ingress(tmp_path, **kwargs):
    return CoreIngress(
        tmp_path / "core_state.db",
        sources=_sources(),
        properties=_properties(),
        **kwargs,
    )


def _event(occurrence, *, tick=40, revision=None, value="open", kind="state.property"):
    at = {"domain": "lab_tick", "value": tick}
    payload = {
        "subject_ref": SUBJECT,
        "predicate_ref": PREDICATE,
        "observed_at": at,
        "temporal_scope": {"kind": "instant", "at": dict(at)},
        "source_revision": tick if revision is None else revision,
    }
    if kind == "state.property":
        payload["value"] = {"type": "symbol", "value": value}
    else:
        payload["reason"] = "sensor_offline"
    return {
        "contract": CONTRACT,
        "occurrence_id": occurrence,
        "occurrence_version": 1,
        "kind": kind,
        "payload": payload,
    }


def test_p2b_commits_observation_belief_and_outbox_in_one_transaction(tmp_path):
    ingress = _ingress(tmp_path)
    admitted = ingress.admit(_event("first"), source_ref=SOURCE_A)
    assert admitted.status == "ACCEPTED"
    assert ingress.observation_outcome(admitted.event_id) == {
        "outcome": "ACCEPTED_NEW",
        "reason_code": "ACCEPTED_NEW",
    }
    belief = ingress.read_belief(*KEY, as_of_tick=41)
    assert belief["revision"] == 1
    assert belief["status"] == "known"
    assert belief["freshness"] == "fresh"
    assert belief["value"] == {"type": "symbol", "value": "open"}
    assert belief["last_known"] == belief["value"]
    assert belief["observed_tick"] == 40
    assert belief["evidence_event_ids"] == (admitted.event_id,)
    assert ingress.pending_event_ids() == (admitted.event_id,)
    with sqlite3.connect(tmp_path / "core_state.db") as connection:
        counts = [connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                  for name in ("core_events", "core_outbox", "core_observations",
                               "core_beliefs", "core_belief_revisions")]
    assert counts == [1, 1, 1, 1, 1]


def test_p2b_freshness_is_derived_and_no_timeless_truth_claim(tmp_path):
    ingress = _ingress(tmp_path)
    ingress.admit(_event("first"), source_ref=SOURCE_A)
    assert ingress.read_belief(*KEY)["freshness"] == "undetermined"
    assert ingress.read_belief(*KEY, as_of_tick=42)["freshness"] == "fresh"
    assert ingress.read_belief(*KEY, as_of_tick=43)["freshness"] == "stale"
    assert ingress.read_belief(*KEY, as_of_tick=39)["freshness"] == "undetermined"


def test_p2b_later_revision_replaces_current_but_preserves_history(tmp_path):
    ingress = _ingress(tmp_path)
    first = ingress.admit(_event("first"), source_ref=SOURCE_A)
    second = ingress.admit(_event("second", tick=41, value="closed"), source_ref=SOURCE_A)
    current = ingress.read_belief(*KEY, as_of_tick=41)
    assert current["status"] == "known"
    assert current["revision"] == 2
    assert current["value"]["value"] == "closed"
    assert current["evidence_event_ids"] == (second.event_id,)
    history = ingress.belief_history(*KEY)
    assert [row["event_id"] for row in history] == [first.event_id, second.event_id]
    assert history[1]["reason"] == "UPDATED_LATER"


def test_p2b_replay_after_restart_does_not_create_new_evidence(tmp_path):
    first = _ingress(tmp_path)
    admitted = first.admit(_event("initial"), source_ref=SOURCE_A)
    reopened = _ingress(tmp_path)
    repeated = reopened.admit(_event("initial"), source_ref=SOURCE_A)
    assert repeated.status == "ALREADY_SEEN"
    assert repeated.event_id == admitted.event_id
    assert reopened.read_belief(*KEY, as_of_tick=40)["revision"] == 1
    assert len(reopened.belief_history(*KEY)) == 1


def test_p2b_rejected_same_occurrence_conflict_preserves_original(tmp_path):
    ingress = _ingress(tmp_path)
    first = ingress.admit(_event("initial"), source_ref=SOURCE_A)
    second = ingress.admit(_event("initial", value="closed"), source_ref=SOURCE_A)
    assert second.status == "IDENTITY_CONFLICT"
    assert second.event_id == first.event_id
    assert ingress.read_belief(*KEY, as_of_tick=40)["value"]["value"] == "open"
    assert len(ingress.belief_history(*KEY)) == 1


def test_p2b_same_time_distinct_sensors_conflict_without_ranking(tmp_path):
    ingress = _ingress(tmp_path)
    first = ingress.admit(_event("a", tick=40, value="open"), source_ref=SOURCE_A)
    second = ingress.admit(_event("b", tick=40, value="closed"), source_ref=SOURCE_B)
    belief = ingress.read_belief(*KEY, as_of_tick=40)
    assert belief["revision"] == 2
    assert belief["status"] == "disputed"
    assert belief["value"] is None
    assert belief["evidence_event_ids"] == (first.event_id, second.event_id)
    assert ingress.observation_outcome(second.event_id)["outcome"] == "MARKED_DISPUTED"
    later = ingress.admit(_event("a-later", tick=41, value="closed"), source_ref=SOURCE_A)
    resolved = ingress.read_belief(*KEY, as_of_tick=41)
    assert resolved["status"] == "known"
    assert resolved["value"]["value"] == "closed"
    assert resolved["evidence_event_ids"] == (later.event_id,)


def test_p2b_same_time_independent_support_preserves_evidence_refs(tmp_path):
    ingress = _ingress(tmp_path)
    a = ingress.admit(_event("a"), source_ref=SOURCE_A)
    b = ingress.admit(_event("b"), source_ref=SOURCE_B)
    belief = ingress.read_belief(*KEY, as_of_tick=40)
    assert belief["status"] == "known"
    assert belief["revision"] == 2
    assert belief["evidence_event_ids"] == (a.event_id, b.event_id)
    assert ingress.observation_outcome(b.event_id)["outcome"] == "ACCEPTED_SUPPORT"


def test_p2b_late_event_and_nonmonotonic_source_revision_are_history_only(tmp_path):
    ingress = _ingress(tmp_path)
    latest = ingress.admit(_event("latest", tick=42), source_ref=SOURCE_A)
    old = ingress.admit(_event("old", tick=41, value="closed"), source_ref=SOURCE_A)
    assert ingress.observation_outcome(old.event_id)["outcome"] == "HISTORY_ONLY"
    wrong_revision = ingress.admit(
        _event("source-old", tick=43, revision=41, value="closed"),
        source_ref=SOURCE_A,
    )
    assert ingress.observation_outcome(wrong_revision.event_id) == {
        "outcome": "HISTORY_ONLY", "reason_code": "SOURCE_REVISION_NOT_NEWER"
    }
    assert ingress.read_belief(*KEY, as_of_tick=43)["value"]["value"] == "open"
    assert ingress.read_belief(*KEY, as_of_tick=43)["revision"] == 1
    assert latest.event_id in ingress.read_belief(*KEY)["evidence_event_ids"]


def test_p2b_duplicate_source_revision_does_not_inflate_support(tmp_path):
    ingress = _ingress(tmp_path)
    a = ingress.admit(_event("a", tick=40), source_ref=SOURCE_A)
    b = ingress.admit(_event("b", tick=40), source_ref=SOURCE_A)
    assert a.event_id != b.event_id
    assert ingress.observation_outcome(b.event_id)["outcome"] == "HISTORY_ONLY"
    assert ingress.read_belief(*KEY)["revision"] == 1


def test_p2b_unavailable_is_not_false_and_preserves_last_known(tmp_path):
    ingress = _ingress(tmp_path)
    ingress.admit(_event("open", tick=40), source_ref=SOURCE_A)
    unavailable = ingress.admit(
        _event("gone", tick=41, kind="sensor.unavailable"),
        source_ref=SOURCE_A,
    )
    belief = ingress.read_belief(*KEY, as_of_tick=41)
    assert belief["revision"] == 2
    assert belief["status"] == "unknown"
    assert belief["value"] is None
    assert belief["last_known"]["value"] == "open"
    assert ingress.observation_outcome(unavailable.event_id)["outcome"] == "MARKED_UNKNOWN"


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda event: event["payload"].update({"unexpected": True}), "INVALID_OBSERVATION"),
        (lambda event: event["payload"]["value"].update({"value": "unlisted"}), "INVALID_OBSERVATION"),
        (lambda event: event["payload"].update({"subject_ref": "entity.unknown"}), "UNREGISTERED_PROPERTY"),
        (lambda event: event["payload"]["observed_at"].update({"domain": "other_clock"}), "INVALID_OBSERVATION"),
        (lambda event: event["payload"]["temporal_scope"].update({"kind": "interval"}), "INVALID_OBSERVATION"),
        (lambda event: event["payload"].update({"source_revision": -1}), "INVALID_OBSERVATION"),
        (lambda event: event["payload"]["value"].update({"type": "boolean", "value": True}), "INVALID_OBSERVATION"),
    ],
)
def test_p2b_invalid_world_claim_is_not_projected(tmp_path, mutate, reason):
    ingress = _ingress(tmp_path)
    raw = _event("invalid")
    mutate(raw)
    admitted = ingress.admit(raw, source_ref=SOURCE_A)
    assert admitted.status == "ACCEPTED"  # raw event is not accepted world truth
    outcome = ingress.observation_outcome(admitted.event_id)
    assert outcome["outcome"] == "REJECTED_INVALID"
    assert outcome["reason_code"] == reason
    assert ingress.belief_history(*KEY) == ()
    assert ingress.read_belief(*KEY)["status"] == "unknown"


def test_p2b_registered_source_without_property_authority_is_not_trusted(tmp_path):
    ingress = _ingress(tmp_path)
    admitted = ingress.admit(_event("forgery"), source_ref=OTHER)
    assert admitted.status == "ACCEPTED"
    assert ingress.observation_outcome(admitted.event_id) == {
        "outcome": "REJECTED_UNAUTHORIZED",
        "reason_code": "SOURCE_NOT_AUTHORIZED",
    }
    assert ingress.belief_history(*KEY) == ()


def test_p2b_fault_between_event_and_projection_commit_rolls_back_all(tmp_path):
    def crash(_event_id):
        raise RuntimeError("controlled projection crash")

    ingress = _ingress(tmp_path, fault_hook=crash)
    with pytest.raises(RuntimeError, match="controlled projection crash"):
        ingress.admit(_event("crash"), source_ref=SOURCE_A)

    reopened = _ingress(tmp_path)
    with sqlite3.connect(tmp_path / "core_state.db") as connection:
        for table in ("core_events", "core_outbox", "core_observations",
                      "core_observation_outcomes", "core_beliefs", "core_belief_revisions"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert reopened.read_belief(*KEY)["revision"] == 0
    assert reopened.admit(_event("crash"), source_ref=SOURCE_A).status == "ACCEPTED"


def test_p2b_upgrades_p2a_schema_without_losing_prior_events(tmp_path):
    db = tmp_path / "core_state.db"
    legacy = CoreIngress(db, sources=_sources())
    old = legacy.admit(_event("old"), source_ref=SOURCE_A)
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE schema_meta SET value='1' WHERE key='schema_version'")
    upgraded = _ingress(tmp_path)
    assert upgraded.get_event(old.event_id) is not None
    assert upgraded.pending_event_ids() == (old.event_id,)
    assert upgraded.read_belief(*KEY)["revision"] == 0
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "2"


def test_p2b_projection_is_opt_in_and_does_not_touch_legacy_store(tmp_path):
    ingress = CoreIngress(tmp_path / "core_state.db", sources=_sources())
    admitted = ingress.admit(_event("raw"), source_ref=SOURCE_A)
    assert admitted.status == "ACCEPTED"
    with pytest.raises(RuntimeError, match="not enabled"):
        ingress.read_belief(*KEY)
    assert not (tmp_path / "events.jsonl").exists()
    assert not (tmp_path / "memory.db").exists()
