"""E4 isolated durable-derived journal tests; no production Memory writes."""
from copy import deepcopy
import sqlite3

import pytest

from labs.exp009.e4_l0_observation import _load_frozen_inputs
from labs.exp009.e4_revision_journal_lab import (
    DerivedRevisionJournal, IntegrityFault, RevisionConflict, SimulatedCrash,
)


def events():
    suite = _load_frozen_inputs("positive")
    source = next(x for x in suite["cases"] if x["id"] == "E4-D01")
    return [deepcopy(x["raw"]) for x in source["events"]]


def setup_journal(tmp_path):
    path = tmp_path / "isolated_derived_lab.db"
    j = DerivedRevisionJournal(path)
    e1, e2, e3 = events()
    assert j.append_event("stream", e1)["stream_version"] == 1
    assert j.append_event("stream", e2)["stream_version"] == 2
    initial = {e1["id"]: "shadow_group_old",
               e2["id"]: "shadow_group_old"}
    seed = j.record_revision(
        projection_id="proj_d01", stream_id="stream",
        expected_head=0, expected_source_version=2,
        source_event_ids=[e1["id"], e2["id"]],
        assignments=initial, operation_key="seed_01",
    )
    assert seed["revision"] == 1
    return j, path, (e1, e2, e3)


def revision_request(e1, e2, e3, **changes):
    request = dict(
        projection_id="proj_d01", stream_id="stream",
        expected_head=1, expected_source_version=3,
        source_event_ids=[e1["id"], e2["id"], e3["id"]],
        assignments={e1["id"]: "shadow_group_old",
                     e2["id"]: "lab_episode_split"},
        correction_event_id=e3["id"],
        operation_key="split_01",
    )
    request.update(changes)
    return request


def test_atomic_versioned_replay_reopen_and_history_preserves_raw(tmp_path):
    j, path, (e1, e2, e3) = setup_journal(tmp_path)
    assert j.append_event("stream", e3)["stream_version"] == 3
    revision = j.record_revision(**revision_request(e1, e2, e3))
    assert revision == {"projection_id": "proj_d01", "revision": 2,
                        "status": "committed"}
    reopened = DerivedRevisionJournal(path)
    head = reopened.read_revision("proj_d01")
    assert head["head_revision"] == 2
    assert head["eligible_for_lab_preflight"]
    assert head["record"]["source_event_ids"] == [e1["id"], e2["id"], e3["id"]]
    assert head["record"]["assignments"][e2["id"]] == "lab_episode_split"
    assert head["record"]["authority"] == "LAB_DERIVED_ONLY"
    first = reopened.read_revision("proj_d01", 1)
    assert first["record"]["assignments"][e2["id"]] == "shadow_group_old"
    assert first["is_head"] is False
    assert reopened.versions("proj_d01") == [1, 2]
    assert reopened.publication_guard("proj_d01", expected_revision=2) == {
        "status": "lab_preflight_only", "revision": 2,
        "authority": "NO_CORE_PUBLISH_PERMISSION",
    }
    with pytest.raises(RevisionConflict):
        reopened.publication_guard("proj_d01", expected_revision=1)


def test_duplicate_event_id_is_no_op_but_conflicting_payload_rejected(tmp_path):
    j, _, (e1, e2, e3) = setup_journal(tmp_path)
    outcome = j.append_event("stream", e2)
    assert outcome["status"] == "duplicate"
    assert j.stream_version("stream") == 2
    altered = deepcopy(e2)
    altered["payload"]["text"] = "Произвольно переписанный исходный Event"
    with pytest.raises(IntegrityFault, match="Raw Event identity"):
        j.append_event("stream", altered)
    assert j.stream_version("stream") == 2


def test_crash_before_event_commit_rolls_back_and_after_commit_is_durable(tmp_path):
    j, path, (_, _, e3) = setup_journal(tmp_path)
    with pytest.raises(SimulatedCrash, match="before commit"):
        j.append_event("stream", e3, cut="before_commit")
    assert DerivedRevisionJournal(path).stream_version("stream") == 2
    with pytest.raises(SimulatedCrash, match="after commit"):
        j.append_event("stream", e3, cut="after_commit")
    new = DerivedRevisionJournal(path)
    assert new.stream_version("stream") == 3
    assert new.append_event("stream", e3)["status"] == "duplicate"
    assert new.stream_version("stream") == 3


def test_crash_before_revision_commit_no_partial_head_and_retry(tmp_path):
    j, path, (e1, e2, e3) = setup_journal(tmp_path)
    j.append_event("stream", e3)
    with pytest.raises(SimulatedCrash, match="before commit"):
        j.record_revision(**revision_request(e1, e2, e3), cut="before_commit")
    other = DerivedRevisionJournal(path)
    assert other.versions("proj_d01") == [1]
    assert other.read_revision("proj_d01")["head_revision"] == 1
    assert other.record_revision(**revision_request(e1, e2, e3))["revision"] == 2
    assert other.versions("proj_d01") == [1, 2]


def test_crash_after_revision_commit_replay_is_idempotent(tmp_path):
    j, path, (e1, e2, e3) = setup_journal(tmp_path)
    j.append_event("stream", e3)
    with pytest.raises(SimulatedCrash, match="after commit"):
        j.record_revision(**revision_request(e1, e2, e3), cut="after_commit")
    restored = DerivedRevisionJournal(path)
    assert restored.read_revision("proj_d01")["head_revision"] == 2
    outcome = restored.record_revision(**revision_request(e1, e2, e3))
    assert outcome["status"] == "idempotent_replay"
    assert restored.versions("proj_d01") == [1, 2]


def test_operation_key_collision_with_different_request_is_rejected(tmp_path):
    j, _, (e1, e2, e3) = setup_journal(tmp_path)
    j.append_event("stream", e3)
    j.record_revision(**revision_request(e1, e2, e3))
    with pytest.raises(IntegrityFault, match="Operation key reused"):
        j.record_revision(**revision_request(
            e1, e2, e3, assignments={
                e1["id"]: "different", e2["id"]: "something_else"
            }))
    assert j.versions("proj_d01") == [1, 2]


def test_stale_source_stream_blocks_publication_without_rewriting_history(tmp_path):
    j, _, (e1, e2, e3) = setup_journal(tmp_path)
    j.append_event("stream", e3)
    j.record_revision(**revision_request(e1, e2, e3))
    more = deepcopy(e3)
    more["id"] = "ev_00000000-0000-4000-8000-000000099001"
    more["timestamp"] = "2026-11-01T12:08:00+00:00"
    more["payload"]["text"] = "Новый журнал: нужно пересмотреть источник."
    assert j.append_event("stream", more)["stream_version"] == 4
    head = j.read_revision("proj_d01")
    assert head["fresh_source_snapshot"] is False
    assert not head["eligible_for_lab_preflight"]
    with pytest.raises(RevisionConflict, match="stale"):
        j.publication_guard("proj_d01", expected_revision=2)
    assert j.record_revision(**revision_request(e1, e2, e3))["status"] == (
        "idempotent_replay"
    )
    assert j.versions("proj_d01") == [1, 2]


def test_compare_and_swap_rejects_old_head_and_source_epoch(tmp_path):
    j, _, (e1, e2, e3) = setup_journal(tmp_path)
    j.append_event("stream", e3)
    j.record_revision(**revision_request(e1, e2, e3))
    with pytest.raises(RevisionConflict, match="Projection head"):
        j.record_revision(**revision_request(e1, e2, e3, operation_key="stale_claim"))
    with pytest.raises(RevisionConflict, match="Source stream"):
        j.record_revision(**revision_request(
            e1, e2, e3, expected_head=2, expected_source_version=2,
            operation_key="stale_source"
        ))


def test_foreign_sources_and_untrusted_correction_denied(tmp_path):
    j, _, (e1, e2, e3) = setup_journal(tmp_path)
    foreign = deepcopy(e3)
    foreign["id"] = "ev_00000000-0000-4000-8000-000000099002"
    j.append_event("other", foreign)
    j.append_event("stream", e3)
    with pytest.raises(RevisionConflict, match="foreign"):
        j.record_revision(**revision_request(
            e1, e2, e3,
            source_event_ids=[e1["id"], e2["id"], foreign["id"]],
            correction_event_id=foreign["id"], operation_key="foreign_try"
        ))
    # A new projection cannot treat foreign sources as its own.
    relay = deepcopy(e3)
    relay["id"] = "ev_00000000-0000-4000-8000-000000099003"
    relay["source"] = "unknown.relay"
    j.append_event("stream", relay)
    with pytest.raises(RevisionConflict, match="Correction not later source-user"):
        j.record_revision(**revision_request(
            e1, e2, e3, expected_source_version=4,
            source_event_ids=[e1["id"], e2["id"], relay["id"]],
            correction_event_id=relay["id"], operation_key="relay_try"
        ))


def test_tampered_sqlite_raw_or_projection_is_detected(tmp_path):
    j, path, (e1, e2, e3) = setup_journal(tmp_path)
    j.append_event("stream", e3)
    j.record_revision(**revision_request(e1, e2, e3))
    with sqlite3.connect(path) as con:
        con.execute("UPDATE raw_events SET body='{}' WHERE event_id=?", (e1["id"],))
    with pytest.raises(IntegrityFault, match="Source integrity"):
        DerivedRevisionJournal(path).read_revision("proj_d01")
    # Second independent database simulates a tampered derived row.
    j2, path2, (e1b, e2b, e3b) = setup_journal(tmp_path / "again")
    with sqlite3.connect(path2) as con:
        con.execute("UPDATE projection_revisions SET record='{}' "
                    "WHERE projection_id='proj_d01' AND revision=1")
    with pytest.raises(IntegrityFault, match="Derived record"):
        DerivedRevisionJournal(path2).read_revision("proj_d01")


def test_empty_or_untrusted_implicit_assignment_not_accepted(tmp_path):
    j, _, (e1, e2, e3) = setup_journal(tmp_path)
    j.append_event("stream", e3)
    with pytest.raises(ValueError, match="Malformed"):
        j.record_revision(**revision_request(e1, e2, e3, assignments={}))
    with pytest.raises(RevisionConflict, match="must alter"):
        j.record_revision(**revision_request(
            e1, e2, e3, operation_key="no_change",
            assignments={e1["id"]: "shadow_group_old",
                         e2["id"]: "shadow_group_old"}
        ))

def test_lab_journal_does_not_verify_semantic_target_scope(tmp_path):
    """A reliable storage commit can still persist a semantically wrong split.

    This is a *known gap* exposed by the independently scored X11 challenge:
    storage must never be treated as the Core's evidence admission policy.
    """
    from labs.exp009.e4_l11_challenge_runner import load_challenge
    challenge, _ = load_challenge()
    case = next(x for x in challenge["cases"] if x["id"] == "E4-X11")
    e1, e2, irrelevant_correction = [x["raw"] for x in case["events"]]
    j = DerivedRevisionJournal(tmp_path / "lab_no_semantic_authority.db")
    for raw in (e1, e2):
        j.append_event("stream", raw)
    j.record_revision(
        projection_id="proj_challenge", stream_id="stream",
        expected_head=0, expected_source_version=2,
        source_event_ids=[e1["id"], e2["id"]],
        assignments={e1["id"]: "same", e2["id"]: "same"},
        operation_key="seed",
    )
    j.append_event("stream", irrelevant_correction)
    stored = j.record_revision(
        projection_id="proj_challenge", stream_id="stream",
        expected_head=1, expected_source_version=3,
        source_event_ids=[e1["id"], e2["id"], irrelevant_correction["id"]],
        assignments={e1["id"]: "same", e2["id"]: "split"},
        correction_event_id=irrelevant_correction["id"],
        operation_key="accepted_without_semantic_scope_validation",
    )
    assert stored["status"] == "committed"
    assert j.read_revision("proj_challenge")["record"]["authority"] == "LAB_DERIVED_ONLY"
