"""EXP-009 E2: ambiguous suggestions do not become facts or merges."""

import json

from labs.exp009.memory_encoding_e2 import run_e2


def test_e2_reports_true_and_false_entity_candidates_without_merge(tmp_path):
    result = run_e2(tmp_path / "run", report_path=tmp_path / "e2.json")
    assert result["type"] == "exp009.shadow-encoding.e2/0.1"
    assert result["memory_unchanged"]
    assert result["episode_count"] == 7
    assert result["gold_related"] == [["decision", "baseline"]]
    assert result["suggested_pairs"] == [
        ["decision", "baseline"],
        ["distractor", "baseline"],
        ["distractor", "decision"],
    ]
    assert result["hits"] == [["decision", "baseline"]]
    assert result["false_candidates"] == [
        ["distractor", "baseline"],
        ["distractor", "decision"],
    ]
    assert result["missed"] == []
    assert result["candidate_precision"] == 1 / 3
    assert result["candidate_recall"] == 1.0
    assert json.loads((tmp_path / "e2.json").read_text()) == result


def test_e2_possible_links_are_unverified_and_replay_safe(tmp_path):
    result = run_e2(tmp_path / "run")
    decisions = result["decisions"]
    for item in decisions.values():
        row = item["decision"]
        assert row["action"] == "new_episode"
        assert len(row["source_event_ids"]) == 1
        for possible in row["possible_related"]:
            assert possible["status"] == "unverified"
            assert possible["reason"] == "shared_entity_without_raw_overlap"
            assert possible["source_event_ids"]
            assert possible["shared_entity_ids"]
    assert len(decisions["decision"]["decision"]["possible_related"]) == 1
    assert len(decisions["distractor"]["decision"]["possible_related"]) == 2
    # Hard boundaries must not even produce weak suggestions.
    for name in (
        "baseline", "different_entity", "different_session",
        "time_boundary", "no_entity_paraphrase",
    ):
        assert decisions[name]["decision"]["possible_related"] == []


def test_e2_does_not_mutate_parent_episode_sources_on_weak_link(tmp_path):
    result = run_e2(tmp_path / "run")
    baseline = result["decisions"]["baseline"]["decision"]
    decision = result["decisions"]["decision"]["decision"]
    distractor = result["decisions"]["distractor"]["decision"]
    assert baseline["episode_id"] != decision["episode_id"]
    assert decision["episode_id"] != distractor["episode_id"]
    assert baseline["source_event_ids"] == [
        result["decisions"]["baseline"]["event_id"]
    ]
    assert decision["source_event_ids"] == [
        result["decisions"]["decision"]["event_id"]
    ]
