"""E4 L1.2 source-pointer and cross-session alias safety laboratory.

New challenge copies are deliberately OUTSIDE both pinned/frozen corpora.
A source pointer proves only reported targeting, not truth or Core authority.
"""
from copy import deepcopy

import pytest

from labs.exp009.e4_l0_observation import _load_frozen_inputs
from labs.exp009.e4_l12_association import run_case as run_l12_case
from labs.exp009.e4_l12_target_proof import (
    assess, source_fingerprint, verify_receipt,
)
from labs.exp009.e4_l11_challenge_runner import load_challenge


def _pair_with_correction():
    corpus = _load_frozen_inputs("positive")
    case = deepcopy(next(c for c in corpus["cases"] if c["id"] == "E4-D01"))
    baseline = run_l12_case(case, entity_registry=corpus["entities"])[
        "episode_baseline"]["event_assignments"]
    first, second, correction = [item["raw"] for item in case["events"]]
    prior = case["setup"]["prior_projection"]
    snapshot = {
        "projection_id": prior["id"], "revision": prior["revision"],
        "source_event_ids": [first["id"], second["id"]],
        "source_sha256": {
            raw["id"]: source_fingerprint(raw) for raw in [first, second]
        },
    }
    return case, baseline, snapshot


def _point_to_prior(case):
    left, right, correction = [item["raw"] for item in case["events"]]
    correction["references"].extend([
        {"kind": "event", "id": left["id"]},
        {"kind": "event", "id": right["id"]},
    ])
    return correction


def _verdict(case, baseline, snapshot):
    return assess(case, baseline, expected_snapshot=snapshot)["assessments"][0]


def test_explicit_pointers_and_pinned_snapshot_only_produce_lab_candidate():
    case, baseline, snapshot = _pair_with_correction()
    original = deepcopy(case)
    _point_to_prior(case)
    outcome = assess(case, baseline, expected_snapshot=snapshot)
    row = outcome["assessments"][0]
    assert row["status"] == "source_pointer_candidate_only"
    assert row["source_event_ids"] == snapshot["source_event_ids"]
    assert row["source_sha256"] == snapshot["source_sha256"]
    assert row["target_projection_id"] == snapshot["projection_id"]
    assert row["target_revision"] == snapshot["revision"]
    assert row["binding_method"] == "exact_typed_event_pointer_source_report"
    assert row["core_authority_verified"] is False
    assert row["production_admission"] is False
    assert outcome["memory_store_unchanged"] is True
    assert verify_receipt(case, baseline, row, expected_snapshot=snapshot)["status"] == (
        "receipt_consistent_with_raw_source_only"
    )
    # Adapter changes only the copied correction, not the original fixture.
    assert original["events"][0]["raw"] == case["events"][0]["raw"]
    assert original["events"][1]["raw"] == case["events"][1]["raw"]


def test_no_typed_event_refs_is_not_explicit_targeting():
    case, baseline, snapshot = _pair_with_correction()
    assert _verdict(case, baseline, snapshot)["reason_codes"] == [
        "no_explicit_source_event_pointers"
    ]


@pytest.mark.parametrize("change", ["only_one", "duplicate", "foreign", "third"])
def test_missing_duplicate_wrong_or_extra_pointers_fail_closed(change):
    case, baseline, snapshot = _pair_with_correction()
    correction = _point_to_prior(case)
    original = correction["references"]
    if change == "only_one":
        correction["references"] = original[:-1]
    elif change == "duplicate":
        original[-1]["id"] = original[-2]["id"]
    elif change == "foreign":
        original[-1]["id"] = "ev_00000000-0000-4000-8000-000000079999"
    else:
        original.append({"kind": "event", "id": correction["id"]})
    assert _verdict(case, baseline, snapshot)["reason_codes"] == [
        "wrong_or_ambiguous_typed_source_pointers"
    ]


def test_projection_version_or_fingerprint_mismatch_blocks_target():
    case, baseline, snapshot = _pair_with_correction()
    _point_to_prior(case)
    mismatch = deepcopy(snapshot)
    mismatch["revision"] += 1
    assert _verdict(case, baseline, mismatch)["reason_codes"] == [
        "projection_snapshot_mismatch"
    ]
    mismatch = deepcopy(snapshot)
    mismatch["source_sha256"][case["events"][0]["raw"]["id"]] = "0" * 64
    assert _verdict(case, baseline, mismatch)["reason_codes"] == [
        "projection_snapshot_mismatch"
    ]
    case["events"][0]["raw"]["payload"]["text"] = "Подменённый источник."
    assert _verdict(case, baseline, snapshot)["reason_codes"] == [
        "projection_snapshot_mismatch"
    ]


def test_source_scope_type_and_time_are_gated():
    for field, value, expected in [
        ("source", "unknown.relay", "unverified_source_authority"),
        ("session_id", "another_session", "outside_bounded_session_scope"),
        ("timestamp", "2026-10-01T00:00:00+00:00",
         "correction_not_later_than_sources"),
        ("type", "source.relay", "unverified_source_authority"),
    ]:
        case, baseline, snapshot = _pair_with_correction()
        correction = _point_to_prior(case)
        correction[field] = value
        assert _verdict(case, baseline, snapshot)["reason_codes"] == [expected]


def test_no_explicit_separation_statement_has_no_source_candidate():
    case, baseline, snapshot = _pair_with_correction()
    correction = _point_to_prior(case)
    correction["payload"]["text"] = "Вот те два события, но я не уверен."
    assert _verdict(case, baseline, snapshot)["reason_codes"] == [
        "pointers_without_explicit_separation_report"
    ]


def test_unmerged_baseline_or_forged_receipt_cannot_be_promoted():
    case, baseline, snapshot = _pair_with_correction()
    _point_to_prior(case)
    bad_baseline = dict(baseline)
    bad_baseline[snapshot["source_event_ids"][1]] = "new_unverified_episode"
    assert _verdict(case, bad_baseline, snapshot)["reason_codes"] == [
        "source_pair_not_merged_in_L0"
    ]
    row = _verdict(case, baseline, snapshot)
    forged = dict(row, production_admission=True)
    with pytest.raises(ValueError, match="not supported"):
        verify_receipt(case, baseline, forged, expected_snapshot=snapshot)
    modified = dict(row, trigger_sha256="f" * 64)
    with pytest.raises(ValueError, match="not supported"):
        verify_receipt(case, baseline, modified, expected_snapshot=snapshot)


def test_duplicate_raw_event_ids_are_rejected():
    case, baseline, snapshot = _pair_with_correction()
    _point_to_prior(case)
    case["events"][2]["raw"]["id"] = case["events"][0]["raw"]["id"]
    with pytest.raises(ValueError, match="Duplicate"):
        assess(case, baseline, expected_snapshot=snapshot)


def _alias_case():
    corpus, _ = load_challenge()
    case = deepcopy(next(c for c in corpus["cases"] if c["id"] == "E4-X07"))
    return case, corpus["entities"]


def test_cross_session_ambient_context_no_longer_confirms_alias_reuse():
    case, registry = _alias_case()
    later = case["events"][2]["raw"]
    later["session_id"] = "second_unverified_session"
    later["references"] = [
        x for x in later["references"]
        if x["id"] != registry["pi_psu_secondary"]
    ]
    result = run_l12_case(dict(case, track=case["topic"]),
                          entity_registry=registry)
    mention = next(x for x in result["alias_mentions"]
                   if x["event_key"] == "e3")
    assert mention["status"] == "insufficient"
    assert mention["reason_codes_l12"] == [
        "cross_session_context_not_target_bound"
    ]
    # Remember the source-backed candidate, but do not select an Entity.
    assert mention["candidate_source_event_ids"]
    assert "target_entity_id" not in mention


def test_cross_session_explicit_target_entity_allows_scoped_user_reuse():
    case, registry = _alias_case()
    case["events"][2]["raw"]["session_id"] = "second_unverified_session"
    result = run_l12_case(dict(case, track=case["topic"]),
                          entity_registry=registry)
    mention = next(x for x in result["alias_mentions"]
                   if x["event_key"] == "e3")
    assert mention["status"] == "scoped_alias_reuse"
    assert mention["target_entity_id"] == registry["pi_psu_secondary"]
    assert mention["expensive_method_calls"] == 0
    assert result["memory_store_unchanged"] is True


def test_old_session_alone_cannot_populate_unknown_target():
    case, registry = _alias_case()
    case["events"] = [case["events"][1], case["events"][2]]
    later = case["events"][-1]["raw"]
    later["session_id"] = "fresh_unverified_session"
    later["references"] = [{"kind": "entity", "id": registry["pi"]}]
    result = run_l12_case(dict(case, track=case["topic"]),
                          entity_registry=registry)
    mention = next(m for m in result["alias_mentions"]
                   if m["event_key"] == "e3")
    assert mention["status"] == "insufficient"


def test_open_raw_binding_probe_has_only_scoped_source_decisions():
    from labs.exp009.e4_l12_source_probe import run_probe

    data = run_probe()
    cases = data["cases"]
    assert cases["without_explicit_pointers"]["status"] == "rejected_or_insufficient"
    assert cases["two_exact_pointers_and_snapshot"]["status"] == "source_pointer_candidate_only"
    assert cases["one_pointer"]["status"] == "rejected_or_insufficient"
    assert cases["altered_original_event"]["reason_codes"] == [
        "projection_snapshot_mismatch"
    ]
    assert cases["cross_session_ambient_alias"]["status"] == "insufficient"
    assert data["core_authority_verified"] is False
    assert data["production_admission"] is False
    assert data["memory_store_unchanged"] is True
