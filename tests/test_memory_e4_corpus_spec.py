"""Static validation of the E4 corpus design; NOT a Core conformance result."""

import json
from datetime import datetime
from pathlib import Path

from anima.core.event_bus import Event


BASE = Path(__file__).resolve().parents[1] / "docs" / "TESTING" / "Fixtures"
ALLOWED_TRACKS = {"A": 5, "B": 6, "C": 6, "D": 5, "U": 6, "R": 8, "P": 6}
ALLOWED_CHECKS = ["alias","authority","budget","episode_pair","evidence","goal","investigation","publication","replay","revision","schedule","story_pair","task","temporal","uncertainty","user"]
ALLOWED_FORBIDDEN = ["assume_alias_globally","auto_merge","auto_story_confirm","duplicate_effect","invent_observation_time","knowledge_confirm","promote_user_intent_to_world_fact","repeat_unbounded","rewrite_raw","starve_primary_task","treat_model_as_truth","unauthorized_external","unsolicited_user_prompt"]


def _load(name):
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def test_e4_design_has_separate_inputs_and_proposed_gold():
    inputs = _load("memory_e4_inputs_v0.json")
    gold = _load("memory_e4_gold_v0.json")
    assert inputs["schema"] == "anima.memory_e4.inputs/0.1"
    assert gold["schema"] == "anima.memory_e4.gold/0.1"
    assert inputs["status"] == "DRAFT_NOT_FROZEN"
    assert gold["status"] == "PROPOSED_NOT_OWNER_ACCEPTED"
    assert inputs["isolation"] == "each_case_independent"
    assert len(inputs["cases"]) == len(gold["cases"]) == 42
    assert {c["id"] for c in inputs["cases"]} == {c["id"] for c in gold["cases"]}
    for track, count in ALLOWED_TRACKS.items():
        assert sum(c["track"] == track for c in inputs["cases"]) == count
    for item in inputs["cases"]:
        assert not any(k in item for k in ("checks", "forbidden", "gold", "expected"))
    assert all(row["oracle_type"] == "safe_system_behavior_not_unobservable_world_truth"
               for row in gold["cases"])


def test_e4_raw_events_validate_and_gold_references_exist():
    inputs = _load("memory_e4_inputs_v0.json")
    gold = {c["id"]: c for c in _load("memory_e4_gold_v0.json")["cases"]}
    global_ids = set()
    registry = set(inputs["entities"].values())
    for case in inputs["cases"]:
        case_keys = set()
        timestamps = []
        for item in case["events"]:
            assert set(item) == {"key", "raw"}
            assert item["key"] not in case_keys
            case_keys.add(item["key"])
            raw = item["raw"]
            Event.validate_record(raw)
            assert raw["id"] not in global_ids
            global_ids.add(raw["id"])
            assert all(ref["id"] in registry for ref in raw["references"])
            timestamps.append(datetime.fromisoformat(raw["timestamp"]))
        assert case_keys
        assert timestamps == sorted(timestamps)
        for control in case["controls"]:
            assert "kind" in control and "at" in control
            assert datetime.fromisoformat(control["at"]).utcoffset() is not None
            if "event_key" in control:
                assert control["event_key"] in case_keys
        oracle = gold[case["id"]]
        assert oracle["track"] == case["track"]
        assert oracle["checks"] and oracle["forbidden"]
        for check in oracle["checks"]:
            assert check["kind"] in ALLOWED_CHECKS and check["expected"]
            for end in ("a", "b"):
                if end in check:
                    assert check[end] in case_keys
        assert set(oracle["forbidden"]) <= set(ALLOWED_FORBIDDEN)


def test_e4_unknown_and_persistent_periodic_review_are_explicit():
    gold = _load("memory_e4_gold_v0.json")["cases"]
    assert any(
        c["id"] == "E4-B05" and any(x["expected"] == "insufficient"
                                 for x in c["checks"])
        for c in gold
    )
    assert any(
        c["id"] == "E4-R03" and any(x["expected"] == "periodic_preflight"
                                 for x in c["checks"])
        for c in gold
    )
    assert any(
        c["id"] == "E4-P04" and "treat_model_as_truth" in c["forbidden"]
        for c in gold
    )
