"""EXP-009 C2 hybrid gates: preserve raw traces, enforce safety invariants.

These tests judge only explicit Core contracts. Other observed states are
retained in JSONL for analysis without imposing a subjective intelligence score.
"""

import json

from labs.exp009.c2_observe import (
    A, B, COOLING, FAN, SUBJECT, TEMP, run_c2_a, run_c2_b,
)


def _by_label(records, label):
    return next(record for record in records if record.get("label") == label)


def _inputs(records):
    return [record for record in records if record["type"] == "input"]


def test_c2_a_mixed_backlog_reopen_and_idempotent_replay(tmp_path):
    report = tmp_path / "traces" / "c2_a.jsonl"
    records = run_c2_a(tmp_path / "anima-a", report_path=report)
    inputs = _inputs(records)
    batch = [record for record in inputs if record["label"].startswith("batch-")]
    ids = [record["admission"]["event_id"] for record in batch]

    assert len(batch) == 36
    assert all(record["admission"]["status"] == "ACCEPTED" for record in batch)
    assert len(set(ids)) == 36
    assert _by_label(records, "before_reopen")["pending"] == 36
    assert _by_label(records, "after_reopen_before_wake")["pending"] == 36
    assert _by_label(records, "after_first_wake")["pending"] == 4
    assert _by_label(records, "after_second_wake")["pending"] == 0

    final = records[-1]
    world = [record for record in final["event_log"]
             if record["type"] == "world.observation"]
    assert [record["id"] for record in world] == ids
    assert all(record["payload"]["occurrence_id"] == batch[index]["raw"]["occurrence_id"]
               for index, record in enumerate(world))
    assert final["pending"] == []
    assert final["memory_count"] == 0
    assert len(final["core_events"]) == 36
    assert all(entry["receipt"]["disposition"] == "forwarded"
               for entry in final["dispatch_receipts"])

    repeated = _by_label(records, "repeat-original")
    conflict = _by_label(records, "identity-conflict")
    unknown = _by_label(records, "unregistered")
    assert repeated["admission"]["status"] == "ALREADY_SEEN"
    assert repeated["admission"]["event_id"] == ids[0]
    assert conflict["admission"]["status"] == "IDENTITY_CONFLICT"
    assert conflict["admission"]["event_id"] == ids[0]
    assert unknown["admission"]["status"] == "REJECTED"
    assert unknown["admission"]["event_id"] is None
    assert final["rejections"] == 2  # Unknown source + occurrence conflict.
    assert final["beliefs"]["temperature"]["status"] == "known"
    assert final["beliefs"]["cooling"]["status"] == "known"

    # Raw output preserves every step and is independently parseable.
    parsed = [json.loads(line) for line in report.read_text(
        encoding="utf-8"
    ).splitlines()]
    assert parsed == json.loads(json.dumps(records))
    assert len(parsed) == len(records)


def test_c2_b_conflict_unknown_stale_and_source_authority(tmp_path):
    records = run_c2_b(tmp_path / "anima-b")
    assert len(_inputs(records)) == 16

    first = _by_label(records, "t10-a")
    conflict = _by_label(records, "t10-b-conflict")
    assert first["beliefs_after"]["temperature"]["status"] == "known"
    assert conflict["beliefs_after"]["temperature"]["status"] == "disputed"
    assert conflict["beliefs_after"]["temperature"]["value"] is None
    assert conflict["beliefs_after"]["temperature"]["evidence_event_ids"] == (
        first["admission"]["event_id"], conflict["admission"]["event_id"]
    )

    resolved = _by_label(records, "t11-a-resolve")
    older = _by_label(records, "t09-b-late")
    assert resolved["beliefs_after"]["temperature"]["value"] == {
        "type": "integer", "value": 70
    }
    assert older["original_event_outcome"]["outcome"] == "HISTORY_ONLY"
    assert older["beliefs_after"]["temperature"]["value"] == {
        "type": "integer", "value": 70
    }

    missing = _by_label(records, "t12-b-unavailable")
    assert missing["beliefs_after"]["temperature"]["status"] == "unknown"
    assert missing["beliefs_after"]["temperature"]["value"] is None
    assert missing["beliefs_after"]["temperature"]["last_known"] == {
        "type": "integer", "value": 70
    }
    assert _by_label(records, "repeat-unavailable")["admission"]["status"] == "ALREADY_SEEN"

    unauthorized = _by_label(records, "registered-no-authority")
    assert unauthorized["admission"]["status"] == "ACCEPTED"
    assert unauthorized["original_event_outcome"]["outcome"] == "REJECTED_UNAUTHORIZED"
    assert unauthorized["dispatch_receipt"]["disposition"] == "filtered"
    assert unauthorized["beliefs_after"]["temperature"] == missing["beliefs_after"]["temperature"]
    assert _by_label(records, "unknown-source")["admission"]["status"] == "REJECTED"
    assert _by_label(records, "occurrence-conflict")["admission"]["status"] == "IDENTITY_CONFLICT"

    cooling_missing = _by_label(records, "cooling-unavailable")
    assert cooling_missing["beliefs_after"]["cooling"]["status"] == "unknown"
    assert cooling_missing["beliefs_after"]["cooling"]["last_known"] == {
        "type": "symbol", "value": "off"
    }
    support = _by_label(records, "t14-b-support")
    assert support["original_event_outcome"]["outcome"] == "ACCEPTED_SUPPORT"
    assert len(support["beliefs_after"]["temperature"]["evidence_event_ids"]) == 2
    late = _by_label(records, "t13-b-late")
    assert late["original_event_outcome"]["outcome"] == "HISTORY_ONLY"
    assert late["beliefs_after"]["temperature"]["status"] == "known"
    assert late["beliefs_after"]["temperature"]["value"] == {
        "type": "integer", "value": 72
    }

    final = records[-1]
    forwarded = [row for row in final["dispatch_receipts"]
                 if row["receipt"]["disposition"] == "forwarded"]
    filtered = [row for row in final["dispatch_receipts"]
                if row["receipt"]["disposition"] == "filtered"]
    world = [row for row in final["event_log"]
             if row["type"] == "world.observation"]
    assert len(world) == len(forwarded)
    assert len(filtered) == 1
    assert final["pending"] == []
    assert final["memory_count"] == 0
    assert final["rejections"] == 2


def test_c2_b_report_keeps_original_inputs_and_raw_state(tmp_path):
    path = tmp_path / "reports" / "c2_b.jsonl"
    records = run_c2_b(tmp_path / "instance", report_path=path)
    parsed = [json.loads(line) for line in path.read_text(
        encoding="utf-8"
    ).splitlines()]
    assert parsed == json.loads(json.dumps(records))
    assert [record["type"] for record in parsed] == (
        ["experiment"] + ["input"] * 16 + ["final"]
    )
    assert parsed[1]["raw"]["payload"]["value"]["value"] == 65
    assert parsed[2]["raw"]["payload"]["value"]["value"] == 73
    assert parsed[-1]["core_events"]
    assert parsed[-1]["belief_history"]["temperature"]
    assert parsed[-1]["event_log"]
    assert "limitations" in parsed[-1]
    assert parsed[-1]["memory_count"] == 0
