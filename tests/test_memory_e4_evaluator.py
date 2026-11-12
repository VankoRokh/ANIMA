"""E4 evaluator adversarial integrity and scoped scoring tests.

Only these tests orchestrate L1. The evaluator module never imports L1 or gold
into the adapter; scoring happens from a completed JSON file.
"""
import json

import pytest

from labs.exp009.e4_l1_association import run_suite as l1
from labs.exp009.e4_evaluator import evaluate_trace


def make_trace(directory, *, suite="positive", case_id=None):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sealed_raw.json"
    path.write_text(json.dumps(l1(suite=suite, case_id=case_id), ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def check(result, case_id, kind):
    case = next(row for row in result["cases"] if row["case_id"] == case_id)
    return next(row for row in case["checks"] if row["kind"] == kind)


def test_e4_evaluator_scores_reported_story_without_world_truth_claim(tmp_path):
    report = evaluate_trace(make_trace(tmp_path, case_id="E4-B03"))
    item = check(report, "E4-B03", "story_pair")
    assert item["status"] == "PASS"
    assert item["evidence_level"] == "L1_REPORTED_RELATION"
    assert report["scope"]["cases"] == 1
    assert not report["scope"]["complete_suite"]
    assert len(report["trace_sha256"]) == 64
    assert report["status"] == "L1_LIMITED_DIAGNOSTIC_NOT_E4_CONFORMANCE"
    assert report["forbidden"]["by_status"]["PASS"] == 0


def test_e4_evaluator_keeps_unknown_goals_recovery_unsupported(tmp_path):
    report = evaluate_trace(make_trace(tmp_path, case_id="E4-R06"))
    assert report["checks"]["total"] == 2
    assert report["checks"]["by_status"]["NOT_SUPPORTED"] == 2
    assert report["checks"]["coverage"] == 0.0
    assert report["checks"]["observed_pass_rate"] is None
    assert report["forbidden"]["by_status"]["NOT_SUPPORTED"] >= 1


def test_e4_evaluator_alias_and_provenance_scoped(tmp_path):
    p = evaluate_trace(make_trace(tmp_path / "alias", case_id="E4-C03"))
    assert check(p, "E4-C03", "alias")["status"] == "PASS"
    assert check(p, "E4-C03", "budget")["status"] == "PASS"
    q = evaluate_trace(make_trace(tmp_path / "evidence", case_id="E4-A04"))
    assert check(q, "E4-A04", "evidence")["status"] == "PASS"
    assert check(q, "E4-A04", "revision")["status"] == "NOT_SUPPORTED"


def test_e4_evaluator_surfaces_actual_negative_error(tmp_path):
    report = evaluate_trace(make_trace(tmp_path, suite="negative", case_id="E4-N04"))
    assert check(report, "E4-N04", "story_pair")["status"] == "FAIL"
    assert report["checks"]["observed_pass_rate"] == 0.0


def test_e4_evaluator_alternative_story_is_a_bounded_choice(tmp_path):
    report = evaluate_trace(make_trace(tmp_path, case_id="E4-B02"))
    row = check(report, "E4-B02", "story_pair")
    assert row["acceptable"] == ["candidate_only", "insufficient"]
    assert row["status"] == "PASS"
    assert row["actual"] in row["acceptable"]


def test_e4_evaluator_missing_story_is_not_observed_not_pass(tmp_path):
    path = make_trace(tmp_path, case_id="E4-B03")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0]["story_pair_assessments"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    outcome = evaluate_trace(path)
    assert check(outcome, "E4-B03", "story_pair")["status"] == "NOT_OBSERVED"


def test_e4_evaluator_rejects_forged_ids_and_provenance(tmp_path):
    path = make_trace(tmp_path / "ids", case_id="E4-A04")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0]["episode_baseline"]["decisions"][0]["event_id"] = "forged"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="event sequence"):
        evaluate_trace(path)

    path = make_trace(tmp_path / "source", case_id="E4-A04")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0]["source_origin_links"][0]["parent_event_id"] = "forged"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Forged or duplicate provenance"):
        evaluate_trace(path)


def test_e4_evaluator_rejects_hidden_controls(tmp_path):
    path = make_trace(tmp_path, case_id="E4-R06")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0]["unsupported_controls"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Hidden or modified unsupported controls"):
        evaluate_trace(path)


def test_e4_evaluator_full_visible_suites_separate_coverage(tmp_path):
    for suite, expected_cases, checks in (
        ("positive", 42, 94), ("negative", 15, 28)
    ):
        report = evaluate_trace(make_trace(tmp_path / suite, suite=suite))
        assert report["scope"]["complete_suite"]
        assert report["scope"]["cases"] == expected_cases
        assert report["checks"]["total"] == checks
        assert sum(report["checks"]["by_status"].values()) == checks
        assert report["checks"]["observed"] < checks
        assert report["forbidden"]["by_status"]["PASS"] == 0
        assert report["checks"]["full_e4_conformance"] is False
        assert all(c["check_metrics"]["total"] > 0 for c in report["cases"])
