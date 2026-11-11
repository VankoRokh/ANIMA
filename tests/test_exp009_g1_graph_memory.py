"""EXP-009 G1: invariant gates for a lab-only graph, not semantic QA."""

import json

import pytest

from labs.exp009.c2_graph_compare import (
    CHAR_BUDGETS, DEPTHS, ITEM_BUDGETS, QUERIES, run_g1,
)
from labs.exp009.graph_memory_probe import GraphMemoryProbe


def _case(records, query_id, depth, *, items=10, chars=1200):
    return next(
        record for record in records
        if record["type"] == "comparison"
        and record["query_id"] == query_id
        and record["max_depth"] == depth
        and record["max_items"] == items
        and record["max_chars"] == chars
    )


def _compare(records):
    return [item for item in records if item["type"] == "comparison"]


def test_g1_finds_raw_evidence_without_mutating_existing_memory(tmp_path):
    report = tmp_path / "out" / "graph_vs_existing.jsonl"
    records = run_g1(tmp_path / "state", report_path=report)
    final = records[-1]
    snapshot = final["graph_snapshot"]
    node_by_id = {node["id"]: node for node in snapshot["nodes"]}
    assert len(node_by_id) == len(snapshot["nodes"])
    assert len(final["inputs"]) == final["input_count"] == 20
    assert len(final["actual_source_links"]) == final["memory_count"]
    assert len(final["event_log"]) == final["raw_event_count"]
    assert len(node_by_id) == (
        final["raw_event_count"] + final["memory_count"]
    )

    raw_event_ids = {event["id"] for event in final["event_log"]}
    assert raw_event_ids == {
        node["id"] for node in snapshot["nodes"]
        if node["kind"] == "event"
    }
    assert all(
        node["content"] == memory["content"]
        for memory in final["memories"]
        for node in [node_by_id[memory["id"]]]
    )
    assert all(
        node["id"] in raw_event_ids
        for node in snapshot["nodes"] if node["kind"] == "event"
    )

    true_links = {
        (item["memory_id"], event_id)
        for item in final["actual_source_links"]
        for event_id in item["event_ids"]
    }
    has_source = {
        (edge["source_id"], edge["target_id"])
        for edge in snapshot["edges"]
        if edge["relation"] == "has_source"
    }
    member_of = {
        (edge["target_id"], edge["source_id"])
        for edge in snapshot["edges"]
        if edge["relation"] == "member_of"
    }
    assert len(true_links) == 20
    assert true_links == has_source == member_of
    assert len(snapshot["edges"]) == len(true_links) * 2
    assert all(
        edge["source_id"] in node_by_id
        and edge["target_id"] in node_by_id
        for edge in snapshot["edges"]
    )

    # Historical limitation: direct marker absent from Memory summary,
    # but its *real* raw Event is addressable by a separate lexical index.
    baseline = _case(records, "early_marker", 0)
    assert baseline["baseline_retrieval"]["results"] == []
    assert baseline["graph_source_event_hits"] == ["exp009case000"]
    assert baseline["graph_literal_hits"] == ["exp009case000"]
    assert baseline["graph"]["selected"][0]["kind"] == "event"
    assert _case(records, "no_match", 2)["graph"]["selected"] == []

    deep = _case(records, "early_marker", 2)
    assert any(
        node["kind"] == "memory" for node in deep["graph"]["visited"]
    )
    assert any(
        node["depth"] == 2 and node["kind"] == "event"
        for node in deep["graph"]["visited"]
    )
    assert [
        json.loads(line)
        for line in report.read_text(encoding="utf-8").splitlines()
    ] == json.loads(json.dumps(records))


def test_g1_graph_and_real_context_obey_all_limits(tmp_path):
    records = run_g1(tmp_path / "run")
    assert len(_compare(records)) == (
        len(QUERIES) * len(DEPTHS)
        * len(ITEM_BUDGETS) * len(CHAR_BUDGETS)
    )
    nodes = {
        node["id"]: node for node in records[-1]["graph_snapshot"]["nodes"]
    }
    for item in _compare(records):
        graph = item["graph"]
        stats = graph["stats"]
        assert stats["items_used"] == len(graph["selected"])
        assert stats["items_used"] <= item["max_items"]
        assert stats["chars_used"] <= item["max_chars"]
        assert stats["visited"] <= graph["budget"]["visits"]
        assert all(node["depth"] <= item["max_depth"]
                   for node in graph["visited"])
        assert all(
            selected["id"] in nodes and
            selected["content"] == nodes[selected["id"]]["content"]
            for selected in graph["selected"]
        )
        visited_ids = {node["id"] for node in graph["visited"]}
        assert all(
            item["via_id"] is None or item["via_id"] in visited_ids
            for item in graph["visited"]
        )
        assert all(
            item["via_relation"] == "fts_seed" if item["depth"] == 0
            else item["via_relation"] in {"member_of", "has_source"}
            for item in graph["visited"]
        )
        assert all(
            marker in item["targets"]
            for marker in item["graph_source_event_hits"]
        )
        assert len(item["baseline_retrieval"]["results"]) <= item["max_items"]
        for consumer in ("FAST", "DEEP"):
            bundle = item["baseline_context"][consumer]
            used = bundle["selection_stats"]
            assert used["items_used"] <= item["max_items"]
            assert used["chars_used"] <= item["max_chars"]
            if consumer == "FAST":
                assert not bundle["events"]


def test_g1_graph_bounds_inputs_and_preserves_outputs(tmp_path):
    graph = GraphMemoryProbe(tmp_path / "graph.db")
    assert graph.search("nonexistentzzzxxyy")["fts_seeds"] == []
    assert graph.search("a")["selected"] == []
    assert graph.search('" OR exp009case000 --')["selected"] == []
    for limits in (
        {"max_depth": -1}, {"max_depth": 4},
        {"max_depth": True}, {"max_items": 0},
        {"max_chars": 0}, {"max_visits": 101},
    ):
        with pytest.raises(ValueError):
            graph.search("anything", **limits)
    with pytest.raises(ValueError):
        graph.search(None)
    report = tmp_path / "report.jsonl"
    run_g1(tmp_path / "once", report_path=report)
    before = report.read_bytes()
    with pytest.raises(FileExistsError):
        run_g1(tmp_path / "twice", report_path=report)
    assert report.read_bytes() == before
