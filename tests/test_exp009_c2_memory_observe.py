"""EXP-009 C2-C: gate provenance and budgets, preserve raw retrieval outcomes."""

import json

import pytest

from labs.exp009.c2_memory_observe import (
    BUDGETS, MATCHED, QUERIES, TOTAL, corpus, run_c2_c,
)


def _query(records, qid, k):
    return next(
        item for item in records
        if item["type"] == "query"
        and item["query_id"] == qid
        and item["top_k"] == k
    )


def _all_queries(records):
    return [record for record in records if record["type"] == "query"]


def test_c2_c_controlled_100_uses_real_memory_and_bounded_context(tmp_path):
    report = tmp_path / "reports" / "controlled_100.jsonl"
    records = run_c2_c(
        tmp_path / "controlled", mode="controlled_100", report_path=report
    )
    final = records[-1]
    assert final["inputs"] == TOTAL
    assert final["memory_count"] == TOTAL
    assert len(final["memories"]) == TOTAL
    assert len(final["events"]) == TOTAL
    assert all(len(link["event_ids"]) == 1 for link in final["source_links"])
    assert len(_all_queries(records)) == len(QUERIES) * len(BUDGETS)

    exact = _query(records, "marker_first", 3)
    expected_memory = records[1]["created_memory_id"]
    assert exact["retrieval"]["results"][0]["id"] == expected_memory
    assert "exp009case000" in exact["selected_source_markers"]
    assert exact["fixture_source_recall"] is not None
    assert _query(records, "no_match", 3)["retrieval"]["results"] == []

    for record in _all_queries(records):
        assert len(record["retrieval"]["results"]) <= record["top_k"]
        assert record["retrieval"]["stats"]["returned"] == len(
            record["retrieval"]["results"]
        )
        assert all(
            len(row["source_events"]) >= 1 for row in record["provenance"]
        )
        for consumer in ("FAST", "DEEP"):
            bundle = record["context"][consumer]
            used = bundle["selection_stats"]
            assert used["items_used"] <= record["top_k"]
            assert used["chars_used"] <= 1200
            assert (
                len(bundle["memories"]) + len(bundle["knowledge"])
                + len(bundle["events"])
            ) == used["items_used"]
        assert record["context"]["FAST"]["events"] == []

    loaded = [
        json.loads(line) for line in report.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert loaded == json.loads(json.dumps(records))
    assert loaded[0]["mode"] == "controlled_100"
    assert loaded[-1]["type"] == "final"


def test_c2_c_matched_corpus_and_runtime_use_same_inputs(tmp_path):
    controlled = run_c2_c(
        tmp_path / "controlled20", mode="controlled_20"
    )
    actual = run_c2_c(tmp_path / "runtime20", mode="runtime_20")
    controlled_inputs = [r for r in controlled if r["type"] == "input"]
    natural_inputs = [r for r in actual if r["type"] == "input"]
    assert len(controlled_inputs) == len(natural_inputs) == len(MATCHED)
    assert [
        (r["index"], r["marker"], r["text"])
        for r in controlled_inputs
    ] == [
        (r["index"], r["marker"], r["text"])
        for r in natural_inputs
    ] == [
        (r["index"], r["marker"], r["text"])
        for r in corpus(MATCHED)
    ]
    assert controlled[-1]["memory_count"] == len(MATCHED)
    assert 1 <= actual[-1]["memory_count"] <= len(MATCHED)
    assert all(input_row["processing"]["status"] == "done"
               for input_row in natural_inputs)
    assert len([
        item for item in actual[-1]["events"]
        if item["type"] == "conversation.user"
    ]) == len(MATCHED)

    source_events = {
        event_id for item in actual[-1]["source_links"]
        for event_id in item["event_ids"]
    }
    assert all(
        item["source_event_id"] in source_events
        for item in natural_inputs
    )
    assert all(
        "source_event_id" in row for row in natural_inputs
    )
    assert len(_all_queries(actual)) == len(QUERIES) * len(BUDGETS)
    assert all(
        0 <= row["fixture_source_recall"] <= 1
        for row in _all_queries(actual)
        if row["fixture_source_recall"] is not None
    )


def test_c2_c_reports_do_not_overwrite_prior_observations(tmp_path):
    path = tmp_path / "first.jsonl"
    run_c2_c(tmp_path / "a", mode="controlled_20", report_path=path)
    initial = path.read_bytes()
    with pytest.raises(FileExistsError):
        run_c2_c(tmp_path / "b", mode="controlled_20", report_path=path)
    assert path.read_bytes() == initial
