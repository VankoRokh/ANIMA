"""EXP-009 C2-C/F: hard provenance/ledger/budget gates, no quality thresholds."""

import json

import pytest

from labs.exp009.c2_memory_forensics import (
    CONTEXT_CHAR_BUDGETS,
    CONTEXT_ITEM_BUDGETS,
    PROBES,
    VARIANTS,
    run_c2_cf,
)
from labs.exp009.c2_memory_observe import MATCHED, corpus


def _steps(records):
    return [record for record in records if record["type"] == "step"]


def _probes(records):
    return [record for record in records if record["type"] == "context_probe"]


def _assert_integrity(records):
    steps = _steps(records)
    final = records[-1]
    assert len(steps) == len(MATCHED)
    assert final["input_count"] == len(MATCHED)
    assert final["memory_count"] == len(final["memory_snapshot"])
    assert len(final["source_markers"]) == len(MATCHED)
    assert len(final["original_input_event_ids"]) == len(MATCHED)
    assert len(set(final["original_input_event_ids"])) == len(MATCHED)
    assert set(final["original_input_event_ids"]) <= {
        event["id"] for event in final["all_events"]
    }

    all_links = [
        event_id for entry in final["memory_snapshot"]
        for event_id in entry["source_event_ids"]
    ]
    assert sorted(all_links) == sorted(final["original_input_event_ids"])
    assert final["raw_source_event_ids"] == sorted(all_links)
    assert all(
        entry["missing_source_event_ids"] == []
        for entry in final["memory_snapshot"]
    )
    assert all(
        entry["content_chars"] <= records[0]["composer_limit"]
        for entry in final["memory_snapshot"]
    )

    for ordinal, step in enumerate(steps, start=1):
        assert step["ordinal"] == ordinal
        assert step["processing_ledger"]["status"] == "done"
        assert step["input"]["marker"] == corpus(MATCHED)[ordinal - 1]["marker"]
        assert step["composer_preview_matches_stored"]
        assert len(step["new_event_ids"]) == 1
        assert step["new_event_ids"][0] == step["original_event"]["id"]
        assert len(step["marker_retrieval"]) == ordinal
        assert len(step["memory_snapshot"]) >= 1
        for entry in step["memory_snapshot"]:
            assert not entry["missing_source_event_ids"]
            assert entry["content_chars"] <= records[0]["composer_limit"]
        assert all(
            set(entry["content_markers"]) <= set(entry["source_markers"])
            for entry in step["memory_snapshot"]
        )

    assert len(_probes(records)) == (
        len(PROBES) * len(CONTEXT_ITEM_BUDGETS)
        * len(CONTEXT_CHAR_BUDGETS) * 2
    )
    raw_event_ids = {event["id"] for event in final["all_events"]}
    for probe in _probes(records):
        context = probe["context"]
        stats = context["selection_stats"]
        assert stats["items_used"] <= probe["max_items"]
        assert stats["chars_used"] <= probe["max_chars"]
        assert stats["items_used"] == (
            len(context["memories"]) + len(context["knowledge"])
            + len(context["events"])
        )
        assert probe["max_items"] in CONTEXT_ITEM_BUDGETS
        assert probe["max_chars"] in CONTEXT_CHAR_BUDGETS
        assert len(probe["retrieval"]["results"]) <= 10
        assert all(
            item["record"]["id"] in raw_event_ids
            for item in context["events"]
        )
        if probe["consumer"] == "FAST":
            assert context["events"] == []


def test_c2_cf_plain_reproduces_and_instruments_overflow(tmp_path):
    report = tmp_path / "report" / "plain.jsonl"
    records = run_c2_cf(
        tmp_path / "runtime", variant="plain", report_path=report
    )
    _assert_integrity(records)
    steps = _steps(records)
    # The original C2-C synthetic corpus crosses the 512-char boundary
    # when exp009case018 is appended after the first seven messages.
    assert steps[6]["pre_composition_chars"] == 451
    assert steps[7]["pre_composition_chars"] == 515
    assert steps[7]["composer_preview"]["truncated"] is True
    assert steps[7]["input"]["marker"] == "exp009case018"

    # We gate raw serialization, not particular retrieval scores/recall.
    assert [
        json.loads(line)
        for line in report.read_text(encoding="utf-8").splitlines()
    ] == json.loads(json.dumps(records))


def test_c2_cf_sentence_boundaries_are_a_control_not_a_new_composer(tmp_path):
    plain = run_c2_cf(tmp_path / "plain", variant="plain")
    delimited = run_c2_cf(
        tmp_path / "delimited", variant="sentence_delimited"
    )
    _assert_integrity(plain)
    _assert_integrity(delimited)

    rows = corpus(MATCHED)
    for a, b, row in zip(_steps(plain), _steps(delimited), rows):
        assert a["input"]["text"] == b["input"]["text"] == row["text"]
        assert a["input"]["submitted_text"] == row["text"]
        assert b["input"]["submitted_text"] == row["text"] + "."
    assert {r["variant"] for r in (plain[-1], delimited[-1])} == set(VARIANTS)

    # Whether punctuation increases retention is an observation, not a gate.
    assert all(
        marker in plain[-1]["source_markers"]
        and marker in delimited[-1]["source_markers"]
        for marker in (r["marker"] for r in rows)
    )


def test_c2_cf_refuses_overwrite(tmp_path):
    report = tmp_path / "original.jsonl"
    run_c2_cf(tmp_path / "first", variant="plain", report_path=report)
    content = report.read_bytes()
    with pytest.raises(FileExistsError):
        run_c2_cf(tmp_path / "second", variant="plain", report_path=report)
    assert report.read_bytes() == content
