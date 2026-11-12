"""Visible E4 L1.1 challenge corpus integrity and independent diagnostic tests."""
import json

import pytest

from labs.exp009.e4_l11_challenge_runner import load_challenge, run_suite
from labs.exp009.e4_l11_challenge_evaluator import evaluate


def test_challenge_inputs_are_new_and_gold_separate():
    d, _ = load_challenge()
    assert len(d["cases"]) == 15
    assert {c["id"] for c in d["cases"]} == {
        f"E4-X{i:02d}" for i in range(1, 16)
    }
    assert sum(len(c["events"]) for c in d["cases"]) == 36
    assert all("checks" not in c and "gold" not in c for c in d["cases"])


def test_challenge_records_real_failures_without_inflating_pass(tmp_path):
    raw = tmp_path / "trace.json"
    raw.write_text(json.dumps(run_suite(), ensure_ascii=False), encoding="utf-8")
    result = evaluate(raw)
    assert result["scope"]["cases"] == 15
    assert result["scope"]["complete_suite"]
    assert result["checks"]["total"] == 16
    assert sum(result["checks"]["by_status"].values()) == 16
    assert result["checks"]["full_e4_conformance"] is False
    assert result["status"] == "OPEN_VISIBLE_CHALLENGE_NOT_BLIND_OR_E4_CONFORMANCE"


def test_challenge_forgeries_are_rejected(tmp_path):
    raw = tmp_path / "trace.json"
    data = run_suite(case_id="E4-X05")
    data["cases"][0]["story_pair_assessments"][0]["source_event_ids"] = ["forged"]
    raw.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Story source"):
        evaluate(raw)


def test_open_development_runner_does_not_embed_oracle_labels():
    case = run_suite(case_id="E4-X01")
    assert case["gold_visible"] is False
    assert case["status"] == "VISIBLE_DEVELOPMENT_RAW_NOT_CONFORMANCE"
    assert case["cases"][0]["semantic_conformance"] == "NOT_ASSESSED"
