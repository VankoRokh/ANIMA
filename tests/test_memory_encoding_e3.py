"""E3: weak-related hypotheses are review triggers, never facts."""

from copy import deepcopy
import json

import pytest

from labs.exp009.episode_link_triage import EpisodeLinkTriage
from labs.exp009.memory_encoding_e2 import run_e2
from labs.exp009.memory_encoding_e3 import (
    KNOWN_ENTITIES, bridge, run_e3,
)


def _book(tmp_path):
    data = run_e2(tmp_path / "e2")
    return EpisodeLinkTriage(data["decisions"],
                             known_entities=KNOWN_ENTITIES), data


def test_e3_reports_false_review_trigger_and_preserves_all_boundaries(tmp_path):
    report = run_e3(tmp_path / "lab", report_path=tmp_path / "e3.json")
    assert json.loads((tmp_path / "e3.json").read_text()) == report
    assert report["production_mutations"] == 0
    assert len(report["initial"]["candidates"]) == 3
    assert all(row["status"] == "unverified"
               for row in report["final"]["candidates"])
    assert all(row["review_state"] == "needs_evidence"
               for row in report["initial"]["candidates"])

    true_metrics = report["metrics_after_true"]
    assert true_metrics["review_ready_precision"] == 1.0
    assert true_metrics["review_ready_recall"] == 1.0
    assert len(true_metrics["ready_pairs"]) == 1
    assert not true_metrics["ready_false_positive_pairs"]

    false_metrics = report["metrics_after_false"]
    assert false_metrics["review_ready_precision"] == 0.5
    assert false_metrics["review_ready_recall"] == 1.0
    assert len(false_metrics["ready_false_positive_pairs"]) == 1
    assert len(false_metrics["ready_pairs"]) == 2
    assert report["final"]["candidates"] == report["after_false_bridge"]["candidates"]


def test_e3_replay_is_idempotent_and_conflicting_event_id_fails(tmp_path):
    book, data = _book(tmp_path)
    first = book.snapshot()
    again = EpisodeLinkTriage(data["decisions"],
                              known_entities=KNOWN_ENTITIES).snapshot()
    assert first == again
    trigger = bridge(3, "Copper calibration decision new hardware supply")
    after = book.observe(trigger)
    assert book.observe(trigger) == after
    assert len(after["bridge_events"]) == 1
    assert len(after["candidates"]) == len(first["candidates"])
    changed = bridge(3, "Different contents with same Event ID")
    with pytest.raises(ValueError, match="Conflicting replay"):
        book.observe(changed)
    assert book.snapshot() == after


def test_e3_forged_source_or_entity_rejected_before_emitting_hypothesis(tmp_path):
    book, data = _book(tmp_path)
    baseline = book.snapshot()
    decisions = deepcopy(data["decisions"])
    proposals = decisions["decision"]["decision"]["possible_related"]
    assert proposals
    proposals[0]["source_event_ids"] = ["ev_forged_source"]
    with pytest.raises(ValueError, match="provenance was forged"):
        EpisodeLinkTriage(decisions, known_entities=KNOWN_ENTITIES)

    with pytest.raises(ValueError, match="Unknown Entity"):
        book.observe(bridge(3, "Copper calibration decision new hardware supply",
                            entity="ent_forged"))
    assert book.snapshot() == baseline


def test_e3_session_and_time_boundary_not_overridden(tmp_path):
    book, data = _book(tmp_path)
    initial = book.snapshot()
    no_entity = bridge(5, "Copper calibration decision new hardware supply",
                       entity=None)
    other_session = bridge(6, "Copper calibration decision new hardware supply",
                           session="session_other")
    outside_window = bridge(
        7, "Copper calibration decision new hardware supply",
        timestamp="2026-11-12T13:07:00+00:00",
    )
    for item in (no_entity, other_session, outside_window):
        result = book.observe(item)
        assert result["candidates"] == initial["candidates"]
    assert len(book.snapshot()["bridge_events"]) == 3


def test_e3_duplicate_proposals_have_stable_candidate_id(tmp_path):
    book, data = _book(tmp_path)
    decisions = deepcopy(data["decisions"])
    decisions["baseline"]["decision"]["possible_related"].append({
        "episode_id": decisions["decision"]["decision"]["episode_id"],
        "source_event_ids": [
            decisions["decision"]["event_id"],
        ],
        "shared_entity_ids": [
            "ent_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        ],
        "status": "unverified",
        "reason": "shared_entity_without_raw_overlap",
    })
    repeated = EpisodeLinkTriage(decisions, known_entities=KNOWN_ENTITIES)
    base_records = book.snapshot()["candidates"]
    repeat_records = repeated.snapshot()["candidates"]
    assert len(repeat_records) == len(base_records)
    assert sorted(row["candidate_id"] for row in repeat_records) == sorted(
        row["candidate_id"] for row in base_records
    )
    # The same undirected candidate may have two distinct proposal event IDs
    # without becoming two independent facts or two relation records.
    assert max(len(row["proposed_by_event_ids"]) for row in repeat_records) == 2
    assert all(row["status"] == "unverified" for row in repeat_records)


def test_e3_no_production_mutation_and_no_auto_proof(tmp_path):
    result = run_e3(tmp_path / "lab")
    for phase in ("initial", "after_true_bridge", "after_false_bridge", "final"):
        assert result[phase]["source_snapshot_sha256"] == result[
            "source_snapshot_sha256"
        ]
        assert all(
            row["status"] != "verified"
            for row in result[phase]["candidates"]
        )
    assert result["final"]["note"].startswith("No truth")
