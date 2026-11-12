"""E4 L1.2 scoped research: frozen comparisons and hostile open challenge."""
from copy import deepcopy
import json

import pytest

from labs.exp009.e4_l0_observation import _load_frozen_inputs
from labs.exp009.e4_l11_association import run_suite as l11
from labs.exp009.e4_l11_challenge_runner import load_challenge
from labs.exp009.e4_l12_association import (
    run_suite as l12, run_case as l12_case, canonical_surface,
)
from labs.exp009.e4_l12_evaluator import evaluate_trace as evaluate_frozen
from labs.exp009.e4_l12_challenge_runner import run_suite as challenge
from labs.exp009.e4_l12_challenge_evaluator import evaluate_trace as evaluate_challenge


def _trace(tmp_path, data):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "raw.json"
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _case(case_id):
    src, _ = load_challenge()
    return deepcopy(next(c for c in src["cases"] if c["id"] == case_id)), src["entities"]


def _disposition(trace, first="e1", second="e2"):
    return next(
        row for row in trace["story_pair_assessments"]
        if row["left_event_key"] == first and row["right_event_key"] == second
    )


def test_l12_open_challenge_all_cases_are_scored(tmp_path):
    report = evaluate_challenge(_trace(tmp_path, challenge()))
    assert report["scope"]["complete_suite"]
    assert report["scope"]["cases"] == 15
    assert report["checks"]["total"] == 16
    assert sum(report["checks"]["by_status"].values()) == 16
    assert report["checks"]["full_e4_conformance"] is False
    assert report["status"] == "OPEN_L12_CHALLENGE_NOT_BLIND_OR_E4_CONFORMANCE"


def test_story_identifier_kind_and_reported_scope():
    x01 = challenge(case_id="E4-X01")["cases"][0]
    row = _disposition(x01)
    assert row["status"] == "insufficient"
    assert row["reason_codes"] == ["cross_kind_identity_unverified"]
    assert row["typed_identifiers"]["left"]["kind"] == "ticket"
    assert row["typed_identifiers"]["right"]["kind"] == "case"
    assert row["authority"] == "source_report_not_world_fact"
    assert row["source_event_ids"] == []
    assert _disposition(challenge(case_id="E4-X05")["cases"][0])["status"] == "same_case_reported"
    distinct = _disposition(challenge(case_id="E4-X04")["cases"][0])
    assert distinct["status"] == "not_same_case_reported"
    assert distinct["namespace_evidence"]["setup_key"] == "distinct_ticket_namespaces"
    assert _disposition(challenge(case_id="E4-X02")["cases"][0])["status"] == "insufficient"
    assert _disposition(challenge(case_id="E4-X03")["cases"][0])["status"] == "insufficient"


def test_conflicting_aliases_keep_both_sources_without_last_write_wins():
    x06 = challenge(case_id="E4-X06")["cases"][0]
    assert len(x06["alias_records"]) == 2
    assert len({r["target_entity_id"] for r in x06["alias_records"]}) == 2
    third = next(m for m in x06["alias_mentions"] if m["event_key"] == "e3")
    assert third["status"] == "insufficient"
    assert third["reason_codes_l12"] == ["competing_scoped_entity_definitions"]
    assert len(third["candidate_source_event_ids"]) == 2
    assert "target_entity_id" not in third
    x07 = challenge(case_id="E4-X07")["cases"][0]
    later = next(m for m in x07["alias_mentions"] if m["event_key"] == "e3")
    assert later["status"] == "scoped_alias_reuse"
    assert later["reason_codes_l12"] == [
        "source_entity_anchor_filters_competing_aliases"
    ]
    assert later["expensive_method_calls"] == 0
    assert len(x07["alias_records"]) == 2


def test_alias_ambiguity_is_not_removed_by_reversing_definitions():
    case, registry = _case("E4-X06")
    case["events"][0]["raw"]["payload"]["text"], case["events"][1]["raw"]["payload"]["text"] = (
        case["events"][1]["raw"]["payload"]["text"],
        case["events"][0]["raw"]["payload"]["text"],
    )
    case["events"][0]["raw"]["references"], case["events"][1]["raw"]["references"] = (
        case["events"][1]["raw"]["references"],
        case["events"][0]["raw"]["references"],
    )
    result = l12_case(dict(case, track=case["topic"]), entity_registry=registry)
    third = next(m for m in result["alias_mentions"] if m["event_key"] == "e3")
    assert third["status"] == "insufficient"
    assert len(third["candidate_source_event_ids"]) == 2


def test_l12_canonical_forms_are_bounded_and_keep_source():
    assert canonical_surface("новой маленькой коробочкой") == "новая маленькая коробочка"
    assert canonical_surface("чёрной коробочкой") == "черная коробочка"
    assert canonical_surface("зелёной коробкой") == "зеленая коробка"
    assert canonical_surface("тяжёлой железной коробкой") == "тяжелая железная коробка"
    assert canonical_surface("надежный мощный блок") == "надежный мощный блок"
    x10 = challenge(case_id="E4-X10")["cases"][0]
    r = x10["alias_records"][0]
    assert r["surface"] == "новой маленькой коробочкой"
    assert r["canonical_l12"] == "новая маленькая коробочка"
    assert r["authority"] == "speaker_intent_only_not_physical_truth"


def test_correction_target_rejects_unrelated_statement_but_allows_scoped_lab():
    wrong = challenge(case_id="E4-X11")["cases"][0]
    assert wrong["episode_view"]["revision_proposals"] == []
    assert wrong["episode_view"]["base_assignments"] == wrong["episode_view"]["effective_assignments"]
    assert wrong["correction_target_assessments"][0]["status"] == "rejected_unbound"
    assert wrong["correction_target_assessments"][0]["production_admission"] is False
    scoped = challenge(case_id="E4-X12")["cases"][0]
    assert len(scoped["episode_view"]["revision_proposals"]) == 1
    evidence = scoped["correction_target_assessments"][0]
    assert evidence["binding_method"] == "explicit_trial_labels_lab_only"
    assert evidence["status"] == "lab_scoped_candidate"
    assert evidence["production_admission"] is False
    d01 = l12(case_id="E4-D01")["cases"][0]
    assert d01["correction_target_assessments"][0]["binding_method"] == "bounded_deictic_lab_only"


def test_intervening_competitor_blocks_deictic_revision():
    case, registry = _case("E4-X12")
    case["events"][2]["raw"]["payload"]["text"] = (
        "Это были два независимых испытания; их нельзя объединять."
    )
    extra = deepcopy(case["events"][2])
    extra["key"] = "competing"
    extra["raw"]["id"] = "ev_00000000-0000-4000-8000-000000099771"
    extra["raw"]["timestamp"] = "2026-11-08T10:03:00+00:00"
    extra["raw"]["payload"]["text"] = "Pi5 перегрелся в тесте C."
    case["events"].insert(2, extra)
    result = l12_case(dict(case, track=case["topic"]), entity_registry=registry)
    assert result["episode_view"]["revision_proposals"] == []
    assert result["correction_target_assessments"][0]["status"] == "rejected_unbound"


def test_l12_rejects_forged_kind_and_correction_admission(tmp_path):
    raw = challenge(case_id="E4-X01")
    raw["cases"][0]["story_pair_assessments"][0]["typed_identifiers"]["left"]["kind"] = "case"
    with pytest.raises(ValueError, match="typed identifier provenance"):
        evaluate_challenge(_trace(tmp_path / "kind", raw))
    raw = challenge(case_id="E4-X12")
    raw["cases"][0]["correction_target_assessments"][0]["production_admission"] = True
    with pytest.raises(ValueError, match="CorrectionTarget or production authority"):
        evaluate_challenge(_trace(tmp_path / "admission", raw))


def test_l12_rejects_forged_alias_cache_selection(tmp_path):
    raw = challenge(case_id="E4-X06")
    mention = next(m for m in raw["cases"][0]["alias_mentions"] if m["event_key"] == "e3")
    record = raw["cases"][0]["alias_records"][-1]
    mention.update(
        status="scoped_alias_reuse", target_entity_id=record["target_entity_id"],
        source_event_id=record["source_event_id"], expensive_method_calls=0,
    )
    with pytest.raises(ValueError, match="Unresolved alias conflict"):
        evaluate_challenge(_trace(tmp_path, raw))


def test_l12_full_frozen_corpus_deterministic_and_not_e4_acceptance(tmp_path):
    for suite, expected_cases, expected_checks in [
        ("positive", 42, 94), ("negative", 15, 28)
    ]:
        raw = l12(suite=suite)
        assert raw["gold_visible"] is False
        assert len(raw["cases"]) == expected_cases
        assert all(r["memory_store_unchanged"] for r in raw["cases"])
        report = evaluate_frozen(_trace(tmp_path / suite, raw), suite=suite)
        assert report["checks"]["total"] == expected_checks
        assert report["scope"]["complete_suite"]
        assert report["forbidden"]["by_status"]["PASS"] == 0
        assert report["checks"]["full_e4_conformance"] is False
    assert l12(case_id="E4-D01") == l12(case_id="E4-D01")
    # Legacy L1.1 adapter remains a distinct, unchanged baseline.
    assert l11(case_id="E4-D01")["cases"][0]["level"] == "L1_1_CONSERVATIVE_REVISABLE_LAB"


def test_no_correction_or_alias_authority_promotion_on_partial_source():
    # The user can decline to name any referent or target. The adapter must
    # return an explicit negative observation, never fake certainty.
    case, reg = _case("E4-X11")
    case["events"][2]["raw"]["payload"]["text"] = "Я не помню, какие именно были тесты."
    out = l12_case(dict(case, track=case["topic"]), entity_registry=reg)
    assert out["episode_view"]["revision_proposals"] == []
    assert out["memory_store_unchanged"] is True
    assert out["semantic_conformance"] == "NOT_ASSESSED"
