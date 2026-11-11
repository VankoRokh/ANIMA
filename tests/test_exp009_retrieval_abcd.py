"""EXP-009 A/B/C/D: paired frozen-snapshot retrieval contract tests."""

import json

import pytest

from labs.exp009.c2_retrieval_abcd import (
    BUDGETS, METHODS, PairedIndex, lexical_query, run_abcd,
)


def _comparison(records, qid, method, *, items=10, chars=1200):
    return next(
        row for row in records if row["type"] == "comparison"
        and row["query_id"] == qid and row["method"] == method
        and row["max_items"] == items and row["max_chars"] == chars
    )


def test_abcd_reuses_one_snapshot_and_preserves_production_sources(tmp_path):
    report = tmp_path / "report" / "retrieval_abcd.jsonl"
    records = run_abcd(tmp_path / "state", report_path=report)
    header, final = records[0], records[-1]
    assert header["events"] == final["direct_id_lookups"] == 20
    assert header["links"] == 20
    assert header["queries"] == 32  # 8 G1 + 20 exact + 4 extra
    assert final["comparison_count"] == 32 * len(BUDGETS) * len(METHODS)
    assert final["raw_events_unchanged"] is True
    assert final["memories_unchanged"] is True
    assert final["snapshot_hash"] == header["snapshot_hash"]

    snapshot = next(
        item["snapshot"] for item in records if item["type"] == "snapshot"
    )
    assert all(
        event["event_type"] == "conversation.user"
        and event["source"] == "user"
        and event["timestamp"]
        for event in snapshot["events"]
    )
    assert all(
        memory["created_at"] and memory["updated_at"]
        for memory in snapshot["memories"]
    )

    cases = [row for row in records if row["type"] == "comparison"]
    assert {row["snapshot_hash"] for row in cases} == {header["snapshot_hash"]}
    assert len([row for row in records
                if row["type"] == "production_reference"]) == 8
    assert [json.loads(line) for line in report.read_text().splitlines()] == (
        json.loads(json.dumps(records))
    )
    with pytest.raises(FileExistsError):
        run_abcd(tmp_path / "different_state", report_path=report)


def test_abcd_raw_event_reachable_without_compacted_memory_marker(tmp_path):
    records = run_abcd(tmp_path)
    case_a = _comparison(records, "early_marker", "A")
    case_b = _comparison(records, "early_marker", "B")
    case_c = _comparison(records, "early_marker", "C")
    case_d = _comparison(records, "early_marker", "D")
    event_id = next(row["event_id"] for row in records
                    if row["type"] == "input"
                    and row["marker"] == "exp009case000")

    assert case_a["selected_event_ids"] == []
    assert event_id in case_b["selected_event_ids"]
    assert event_id in case_c["selected_event_ids"]
    assert event_id in case_d["selected_event_ids"]
    assert case_b["recall_at_k"] == 1.0
    for method in METHODS:
        assert _comparison(records, "no_match", method)["no_match_pass"]
    # The adversarial negative intentionally shares "telemetry" with real
    # Events: lexical matches here are measured false positives, NOT a
    # successful no-match. Do not suppress them or rewrite the gold.
    adversarial = [
        _comparison(records, "negative_unseen", method)
        for method in METHODS
    ]
    assert any(item["no_match_pass"] is False for item in adversarial)
    assert all(
        item["false_positive_count"] == len(item["selected"])
        for item in adversarial
    )


def test_abcd_packing_and_per_query_gold_are_identical(tmp_path):
    records = run_abcd(tmp_path)
    comparisons = [row for row in records if row["type"] == "comparison"]
    gold_by_query = {}
    source_links = next(
        row["snapshot"]["links"] for row in records if row["type"] == "snapshot"
    )
    reverse_links = {
        (event_id, memory_id)
        for memory_id, events in source_links.items()
        for event_id in events
    }
    for row in comparisons:
        query_id = row["query_id"]
        gold = tuple(row["target_event_ids"])
        assert gold_by_query.setdefault(query_id, gold) == gold
        assert row["items_used"] <= row["max_items"]
        assert row["chars_used"] <= row["max_chars"]
        assert len(row["rendered_context"]) == row["chars_used"]
        packed = json.loads(row["rendered_context"])
        assert len(packed) == len(row["selected"])
        assert packed == [
            {key: node[key] for key in ("content", "id", "kind", "via")}
            for node in row["selected"]
        ]
        assert set(row["hits"]).issubset(gold)
        if row["category"] == "exact_marker":
            assert len(gold) == 1
        if row["method"] != "D":
            assert all(node["via"] == "fts" for node in row["selected"])
        if row["method"] == "D":
            assert all(node["via"] == "fts" or
                       node["via"].startswith("source:")
                       for node in row["selected"])
            for node in row["selected"]:
                if not node["via"].startswith("source:"):
                    continue
                parent = node["via"].removeprefix("source:")
                edge = (parent, node["id"])
                if parent in source_links:
                    assert node["id"] in source_links[parent]
                else:
                    assert edge in reverse_links


def test_lab_index_is_idempotent_and_refuses_mixed_snapshots(tmp_path):
    original = {
        "events": [
            {"id": "ev_a", "content": "exp009case000 temperature 82"},
            {"id": "ev_b", "content": "exp009case001 cooling fan failed"},
        ],
        "memories": [{"id": "mem_a", "content": "cooling incident"}],
        "links": {"mem_a": ["ev_a", "ev_b"]},
    }
    path = tmp_path / "lab.sqlite"
    first = PairedIndex(path, original)
    event = first.lookup_event("ev_a")
    assert event["content"].endswith("temperature 82")
    assert first.lookup_event("does_not_exist") is None
    before = first.search("cooling", method="D", max_items=3, max_chars=1200)
    again = PairedIndex(path, original)
    after = again.search("cooling", method="D", max_items=3, max_chars=1200)
    assert before["selected"] == after["selected"]
    assert before["rendered_context"] == after["rendered_context"]
    assert first.snapshot_hash == again.snapshot_hash

    changed = {**original, "links": {"mem_a": ["ev_a"]}}
    with pytest.raises(ValueError, match="different frozen snapshots"):
        PairedIndex(path, changed)

    forged = {**original, "links": {"mem_a": ["ev_a", "ev_unknown"]}}
    with pytest.raises(ValueError, match="Unknown source Event"):
        PairedIndex(tmp_path / "forged.db", forged)

    duplicate = {**original, "links": {"mem_a": ["ev_a", "ev_a"]}}
    with pytest.raises(ValueError, match="Duplicate source evidence"):
        PairedIndex(tmp_path / "duplicate.db", duplicate)


def test_parser_is_safe_and_budgets_are_enforced(tmp_path):
    original = {
        "events": [{"id": "ev_a", "content": "exp009case000 temperature 82"}],
        "memories": [{"id": "mem_a", "content": "incident heat"}],
        "links": {"mem_a": ["ev_a"]},
    }
    index = PairedIndex(tmp_path / "fts.db", original)
    for query in ("'", '" OR 1=1 --', "a", "слово", "exp009case000"):
        assert lexical_query(query) is None or isinstance(
            lexical_query(query), str
        )
        for method in METHODS:
            result = index.search(
                query, method=method, max_items=1, max_chars=256,
            )
            assert result["items_used"] <= 1
            assert result["chars_used"] <= 256
            assert result["rendered_context"].startswith("[")
    with pytest.raises(ValueError):
        index.search("heat", method="E", max_items=1, max_chars=256)
    for bad in (0, True, -1):
        with pytest.raises(ValueError):
            index.search("heat", method="D", max_items=bad, max_chars=256)
