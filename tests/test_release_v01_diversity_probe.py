"""R-08 diversity probe: only integrity is gated; semantics remain diagnostic."""

import pytest

from scripts.run_release_v01_diversity_probe import (
    TOPICS,
    generate_corpus,
    run_probe,
)


def test_diverse_corpus_is_reproducible_and_all_topics_present():
    first = generate_corpus(events=64, seed=7)
    assert first == generate_corpus(events=64, seed=7)
    assert first != generate_corpus(events=64, seed=9)
    labeled = generate_corpus(events=64, seed=7, mode="labeled")
    assert labeled != first
    assert [row["marker"] for row in labeled] == [
        row["marker"] for row in first
    ]
    assert [row["topic"] for row in labeled] == [
        row["topic"] for row in first
    ]
    assert all("Номер " not in row["text"] for row in first)
    assert all("Номер " in row["text"] for row in labeled)
    assert len(first) == 64
    assert set(row["topic"] for row in first) == set(TOPICS)
    assert len(set(row["marker"] for row in first)) == 64
    assert len(set(row["text"] for row in first)) == 64
    assert any("English" in row["text"] for row in first)
    assert any("двер" in row["text"] for row in first)


@pytest.mark.parametrize("events", [0, 31, 1001, True, 32.5])
def test_events_are_bounded(events):
    with pytest.raises(ValueError, match="events"):
        generate_corpus(events=events)


@pytest.mark.parametrize("seed", [-1, 1_000_001, True])
def test_seed_is_bounded(seed):
    with pytest.raises(ValueError, match="seed"):
        generate_corpus(events=32, seed=seed)


@pytest.mark.parametrize("mode", ["plain", "labeled"])
def test_diverse_ingestion_reopen_search_and_raw_diagnostic_report(mode):
    result = run_probe(events=32, seed=7, mode=mode)
    assert result["mode"] == mode
    assert result["integrity_status"] == "PASS"
    assert result["semantic_quality_status"] == "NOT_SCORED"
    assert result["performance_status"] == "MEASURED_NOT_SLO_GATED"
    assert result["events"] == 32
    assert set(result["topic_distribution"]) == set(TOPICS)
    assert result["raw_source_links"] == "ALL_ACCOUNTED"
    assert result["index_complete"] is True
    assert result["identity_reopen"] is True
    assert result["raw_marker_probes_passed"] == len(TOPICS) * 2
    assert result["negative_search_empty"] is True
    # The curated fixture uses stable, distinct subject prefixes.
    # This is a structural test, not a semantic comprehension score.
    assert result["memory_count"] == len(TOPICS)
    assert result["memories_crossing_topics"] == 0
    assert result["model_calls"] == 0
    assert result["report_latency_ms"]["p95"] > 0
    assert len(result["context_responses"]) == len(TOPICS)
    for row in result["context_responses"]:
        bundle = row["raw_context_response"]
        assert bundle["selection_stats"]["items_used"] <= 4
        assert bundle["selection_stats"]["chars_used"] <= 900
        assert bundle["selection_stats"]["items_used"] >= 1
    for row in result["raw_probes"]:
        assert row["raw_search_response"]["coverage"]["status"] == "complete"
        assert any(
            item["id"] == row["expected_event_id"]
            and item["record"]["payload"]["text"] == row["original_text"]
            for item in row["raw_search_response"]["results"]
        )


def test_invalid_corpus_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        generate_corpus(events=32, mode="unknown")


@pytest.mark.parametrize("mode", ["plain", "labeled"])
def test_160_event_topic_purity_regression(mode):
    """Fixed eight-subject synthetic fixture: structural grouping only."""
    result = run_probe(events=160, seed=7, mode=mode)
    assert result["integrity_status"] == "PASS"
    assert result["memory_count"] == len(TOPICS)
    assert result["memories_crossing_topics"] == 0
    assert result["raw_marker_probes_passed"] == 2 * len(TOPICS)
    assert result["raw_source_links"] == "ALL_ACCOUNTED"
    assert all(
        row["raw_context_response"]["selection_stats"]["items_used"] >= 1
        for row in result["context_responses"]
    )
