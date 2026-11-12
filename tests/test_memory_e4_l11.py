"""E4 L1.1: regression and predeclared adversarial counterexamples.

Inline alterations exist only in test memory, not frozen fixture files.
"""
from copy import deepcopy
import json

import pytest

from labs.exp009.e4_l0_observation import _load_frozen_inputs
from labs.exp009.e4_l1_association import run_suite as l1_suite
from labs.exp009.e4_l11_association import (
    run_case as l11_case,
    run_suite as l11_suite,
    normalize_feminine_alias,
)
from labs.exp009.e4_l11_evaluator import evaluate_trace


def _case(suite, case_id):
    inp = _load_frozen_inputs(suite)
    return deepcopy(next(c for c in inp["cases"] if c["id"] == case_id)), inp["entities"]


def _raw(tmp_path, suite="positive", case_id=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "e4_l11_raw.json"
    path.write_text(json.dumps(l11_suite(suite=suite, case_id=case_id),
                               ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _check(report, case_id, kind, expected=None):
    row = next(x for x in report["cases"] if x["case_id"] == case_id)
    return next(x for x in row["checks"]
                if x["kind"] == kind
                and (expected is None or x["expected"] == expected))


def test_d01_revises_only_derived_episode_view_and_retains_shadow(tmp_path):
    a = l11_suite(case_id="E4-D01")["cases"][0]
    b = l1_suite(case_id="E4-D01")["cases"][0]
    assert a["episode_baseline"] == b["episode_baseline"]
    view = a["episode_view"]
    assert view["status"] == "lab_revised_derived_view"
    proposal = view["revision_proposals"][0]
    assert proposal["old_revision"] == 1
    assert proposal["new_revision"] == 2
    assert proposal["raw_events_modified"] is False
    assert proposal["status"] == "materialized_in_lab_view_only"
    assert view["base_assignments"] != view["effective_assignments"]
    report = evaluate_trace(_raw(tmp_path, case_id="E4-D01"))
    assert _check(report, "E4-D01", "episode_pair")["status"] == "PASS"
    assert _check(report, "E4-D01", "revision", "resegment_without_raw_change")["status"] == "PASS"
    assert _check(report, "E4-D01", "revision", "versioned_resegmentation")["status"] == "PASS"


def test_no_split_without_exact_separate_trial_ids_or_user_correction():
    case, reg = _case("positive", "E4-D01")
    case["events"][1]["raw"]["payload"]["text"] = "Pi5 перегрелся в тесте A."
    assert not l11_case(case, entity_registry=reg)["episode_view"]["revision_proposals"]
    case, reg = _case("positive", "E4-D01")
    case["events"][2]["raw"]["payload"]["text"] = "Это были два этапа одного испытания."
    assert not l11_case(case, entity_registry=reg)["episode_view"]["revision_proposals"]
    case, reg = _case("positive", "E4-D01")
    case["events"][2]["raw"]["source"] = "unknown.relay"
    assert not l11_case(case, entity_registry=reg)["episode_view"]["revision_proposals"]


def test_no_versioned_split_without_valid_prior_projection():
    case, reg = _case("positive", "E4-D01")
    case["setup"].pop("prior_projection")
    view = l11_case(case, entity_registry=reg)["episode_view"]
    assert view["status"] == "identical_to_L0_shadow"
    assert not view["revision_proposals"]
    case, reg = _case("positive", "E4-D01")
    case["setup"]["prior_projection"]["source_event_ids"][0] = "forged"
    assert not l11_case(case, entity_registry=reg)["episode_view"]["revision_proposals"]


def test_alias_normalization_is_grammatical_and_stays_scoped(tmp_path):
    assert normalize_feminine_alias("чёрной коробочкой") == "черная коробочка"
    assert normalize_feminine_alias("чёрная коробочка") == "черная коробочка"
    assert normalize_feminine_alias("большой коробкой") == "большая коробка"
    assert normalize_feminine_alias("коробочка") == "коробочка"
    assert normalize_feminine_alias("другой блок") != "черная коробочка"
    report = evaluate_trace(_raw(tmp_path, case_id="E4-U05"))
    assert _check(report, "E4-U05", "alias")["status"] == "PASS"
    assert _check(report, "E4-U05", "uncertainty")["status"] == "NOT_SUPPORTED"
    assert l11_suite(case_id="E4-C02")["cases"][0]["alias_records"] == []


def test_incident_marker_is_not_shared_topic_or_unsafe_entity_merge(tmp_path):
    row = l11_suite(suite="negative", case_id="E4-N01")["cases"][0]
    pair = next(x for x in row["story_pair_assessments"]
                if x["left_event_key"] == "e1" and x["right_event_key"] == "e2")
    assert pair["status"] == "same_case_reported"
    assert pair["authority"] == "source_report_not_world_fact"
    assert row["episode_baseline"]["event_assignments"] == (
        row["episode_view"]["effective_assignments"]
    )
    report = evaluate_trace(_raw(tmp_path, suite="negative", case_id="E4-N01"))
    assert _check(report, "E4-N01", "story_pair")["status"] == "PASS"
    case, reg = _case("negative", "E4-N01")
    for event in case["events"]:
        event["raw"]["payload"]["text"] = (
            event["raw"]["payload"]["text"].replace("A9", "")
        )
    projected = l11_case(case, entity_registry=reg)
    pair = projected["story_pair_assessments"][0]
    assert pair["status"] == "insufficient"


def test_namespaces_need_verified_disjoint_precondition(tmp_path):
    report = evaluate_trace(_raw(tmp_path, suite="negative", case_id="E4-N04"))
    assert _check(report, "E4-N04", "story_pair")["status"] == "PASS"
    case, reg = _case("negative", "E4-N04")
    del case["setup"]["distinct_ticket_namespaces"]
    result = l11_case(case, entity_registry=reg)
    assert result["story_pair_assessments"][0]["status"] == "insufficient"
    relay = l11_suite(suite="negative", case_id="E4-N05")["cases"][0]
    assert relay["story_pair_assessments"][0]["status"] == "insufficient"


def test_untrusted_relay_duplicate_ticket_id_stays_insufficient():
    # Separate *messages* from one unknown relay do not establish that the
    # ticket namespace, source independence or case identity is reliable.
    case, reg = _case("negative", "E4-N05")
    case["events"][0]["raw"]["source"] = "unknown.relay"
    case["events"][1]["raw"]["source"] = "unknown.relay"
    result = l11_case(case, entity_registry=reg)
    assert result["story_pair_assessments"][0]["status"] == "insufficient"
    assert result["story_pair_assessments"][0]["source_event_ids"] == []


def test_evaluator_rejects_forged_revision_or_alias_normalization(tmp_path):
    path = _raw(tmp_path / "revision", case_id="E4-D01")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0]["episode_view"]["revision_proposals"][0]["trigger_event_id"] = "forged"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Revision has no qualifying"):
        evaluate_trace(path)

    path = _raw(tmp_path / "alias", case_id="E4-U05")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0]["alias_records"][0]["surface_canonical"] = "fake entity"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Alias source phrase"):
        evaluate_trace(path)


def test_all_l11_frozen_cases_deterministic_and_read_only(tmp_path):
    for suite, expected_cases, expected_checks in (
        ("positive", 42, 94), ("negative", 15, 28)
    ):
        result = l11_suite(suite=suite)
        assert len(result["cases"]) == expected_cases
        assert all(row["memory_store_unchanged"] for row in result["cases"])
        assert all(row["semantic_conformance"] == "NOT_ASSESSED" for row in result["cases"])
        report = evaluate_trace(_raw(tmp_path / suite, suite=suite))
        assert report["scope"]["complete_suite"]
        assert report["checks"]["total"] == expected_checks
        assert report["forbidden"]["by_status"]["PASS"] == 0
        assert report["checks"]["full_e4_conformance"] is False
    assert l11_suite(case_id="E4-D01") == l11_suite(case_id="E4-D01")
