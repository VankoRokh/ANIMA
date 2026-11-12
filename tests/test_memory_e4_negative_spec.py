"""E4 negative-development corpus static checks, not a live Core E4 test."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from anima.core.event_bus import Event

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "docs" / "TESTING" / "Fixtures"
TRACKS = {"A_B": 2, "A_D": 1, "B": 2, "C": 2, "C_P": 1,
          "D_R": 1, "B_D": 1, "R": 3, "R_U": 1, "P_R": 1}


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_e4_negatives_are_isolated_valid_events_and_gold_is_separate():
    pos = _load("memory_e4_inputs_v0.json")
    inp = _load("memory_e4_negative_inputs_v0.json")
    gold = _load("memory_e4_negative_gold_v0.json")
    assert inp["schema"] == "anima.memory_e4.negative_inputs/0.1"
    assert gold["schema"] == "anima.memory_e4.negative_gold/0.1"
    assert "NOT_HOLDOUT" in inp["status"]
    assert gold["status"] == "FROZEN_PROVISIONAL_DEV_GOLD_V0"
    assert len(inp["cases"]) == len(gold["cases"]) == 15
    assert {x["id"] for x in inp["cases"]} == {x["id"] for x in gold["cases"]}
    for track, count in TRACKS.items():
        assert sum(x["track"] == track for x in inp["cases"]) == count
    assert set(TRACKS) == {x["track"] for x in inp["cases"]}
    reg = set(inp["entities"].values())
    seen_ids = {e["raw"]["id"] for c in pos["cases"] for e in c["events"]}
    pos_ids = {c["id"] for c in pos["cases"]}
    oracle = {c["id"]: c for c in gold["cases"]}
    for case in inp["cases"]:
        assert not {"checks", "expected", "forbidden", "gold"} & set(case)
        keys, prior = set(), set()
        last_time = None
        for row in case["events"]:
            assert set(row) == {"key", "raw"}
            assert row["key"] not in keys
            keys.add(row["key"])
            raw = row["raw"]
            Event.validate_record(raw)
            assert raw["id"] not in seen_ids
            seen_ids.add(raw["id"])
            t = datetime.fromisoformat(raw["timestamp"])
            assert last_time is None or t >= last_time
            last_time = t
            for link in raw["references"]:
                if link["kind"] == "entity":
                    assert link["id"] in reg
                elif link["kind"] == "event":
                    assert link["id"] in prior
                else:
                    raise AssertionError("Unsupported reference kind")
            prior.add(raw["id"])
        for control in case["controls"]:
            assert control["kind"]
            assert datetime.fromisoformat(control["at"]).utcoffset() is not None
        gold_case = oracle[case["id"]]
        assert gold_case["paired_with"] in pos_ids
        assert gold_case["oracle_type"] == "safe_system_behavior_not_unobservable_world_truth"
        assert gold_case["checks"] and gold_case["forbidden"]
        for check in gold_case["checks"]:
            assert check["kind"] and check["expected"]
            for ref in ("a", "b", "after_event_key"):
                if ref in check:
                    assert check[ref] in keys


def _git_blob_sha1(data):
    prefix = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(prefix + data).hexdigest()


def test_e4_candidate_manifest_pins_exact_json_files():
    m = _load("memory_e4_frozen_manifest_v0.json")
    assert m["status"] == "FROZEN_DESIGN_BASELINE_V0"
    assert m["owner_approved"] is False
    assert m["production_conformance"] is False
    assert m["blind_holdout"] == "NOT_CREATED"
    assert m["root_cases"] == 42
    assert m["negative_dev_cases"] == 15
    expected = {
        "docs/TESTING/Fixtures/memory_e4_inputs_v0.json",
        "docs/TESTING/Fixtures/memory_e4_gold_v0.json",
        "docs/TESTING/Fixtures/memory_e4_negative_inputs_v0.json",
        "docs/TESTING/Fixtures/memory_e4_negative_gold_v0.json",
    }
    assert set(m["pinned_files"]) == expected
    for path, record in m["pinned_files"].items():
        data = (ROOT / path).read_bytes()
        assert len(data) == record["bytes"]
        assert _git_blob_sha1(data) == record["git_blob_sha1"]
