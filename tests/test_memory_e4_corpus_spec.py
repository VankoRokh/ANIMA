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
            for reference in raw["references"]:
                if reference["kind"] == "entity":
                    assert reference["id"] in registry
                elif reference["kind"] == "event":
                    # Explicit provenance can point to an earlier raw Event in
                    # this isolated case, but not to an unrelated Entity or
                    # a fabricated Event ID.
                    prior_event_ids = {
                        earlier["raw"]["id"]
                        for earlier in case["events"]
                        if earlier["key"] in case_keys
                        and earlier["raw"]["id"] != raw["id"]
                    }
                    assert reference["id"] in prior_event_ids
                else:
                    raise AssertionError("Unknown E4 raw reference kind")
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
            if "acceptable" in check:
                allowed = check["acceptable"]
                assert isinstance(allowed, list) and check["expected"] in allowed
                assert len(allowed) == len(set(allowed))
                assert all(isinstance(value, str) and value for value in allowed)
            for end in ("a", "b", "after_event_key"):
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


def test_e4_ab_gold_does_not_infer_story_from_entity_alone():
    inputs = {case["id"]: case for case in _load("memory_e4_inputs_v0.json")["cases"]}
    gold = {case["id"]: case for case in _load("memory_e4_gold_v0.json")["cases"]}

    def expected(case_id, kind):
        return [check["expected"] for check in gold[case_id]["checks"]
                if check["kind"] == kind]

    assert expected("E4-A02", "story_pair") == ["insufficient"]
    assert expected("E4-B06", "story_pair") == ["insufficient"]
    assert expected("E4-A05", "story_pair") == ["not_same_case"]
    assert expected("E4-B03", "story_pair") == ["same_case_reported"]
    assert inputs["E4-B04"]["setup"]["episode_scope"] == "device_process"

    raw = {row["key"]: row["raw"] for row in inputs["E4-A04"]["events"]}
    assert raw["e2"]["type"] == "derived.projection"
    assert {"kind": "event", "id": raw["e1"]["id"]} in raw["e2"]["references"]
    assert expected("E4-A04", "evidence") == ["same_origin_not_independent"]


def test_e4_cd_gold_has_source_grounded_aliases_and_versions():
    inputs = {c["id"]: c for c in _load("memory_e4_inputs_v0.json")["cases"]}
    gold = {c["id"]: c for c in _load("memory_e4_gold_v0.json")["cases"]}
    c03 = inputs["E4-C03"]
    assert c03["events"][0]["key"] == "e0"
    assert c03["setup"]["known_aliases"][0]["source_event_id"] == c03["events"][0]["raw"]["id"]
    assert c03["setup"]["known_aliases"][0]["version"] == 1
    assert any(x["expected"] == "same_case_reported" for x in gold["E4-C01"]["checks"])
    c05 = inputs["E4-C05"]
    ids = {c["id"] for c in c05["setup"]["derived_links"]}
    assert {"link_c05_affected", "link_c05_unaffected"} == ids
    revision = [x for x in gold["E4-C05"]["checks"]
                if x["expected"] == "recheck_dependent_links"][0]
    assert revision["affected_link_ids"] == ["link_c05_affected"]
    assert revision["unchanged_link_ids"] == ["link_c05_unaffected"]
    distinct = inputs["E4-C06"]["setup"]["distinct_registered_power_supplies"]
    assert len(set(distinct)) == 2
    assert all(event["raw"]["type"] == "device.temperature"
               for event in inputs["E4-D04"]["events"])
    assert not inputs["E4-D04"]["setup"]["clock_mapping_available"]
    d05 = inputs["E4-D05"]
    cmd = d05["controls"][0]
    assert cmd["based_on_source_snapshot_rev"] < cmd["current_source_snapshot_rev"]
    assert cmd["based_on_source_event_ids"] == [d05["events"][0]["raw"]["id"]]
    assert cmd["current_source_event_ids"] == [e["raw"]["id"] for e in d05["events"]]


def test_e4_urp_preconditions_separate_admission_from_due_time():
    inputs = {c["id"]: c for c in _load("memory_e4_inputs_v0.json")["cases"]}
    gold = {c["id"]: c for c in _load("memory_e4_gold_v0.json")["cases"]}
    for case_id in ("E4-U06", "E4-R01", "E4-R06", "E4-R07"):
        state = inputs[case_id]["setup"]["core_state"]
        assert state["admitted_by"] == "Core"
        assert state["goal_id"].startswith("goal_")
        assert state["task_id"].startswith("task_")
    assert inputs["E4-U06"]["setup"]["attempt"]["task_id"] == inputs["E4-U06"]["setup"]["core_state"]["task_id"]
    assert any(check["expected"] == "eligible_for_preflight"
               for check in gold["E4-R02"]["checks"])
    assert len([ctl for ctl in inputs["E4-R04"]["controls"]
                if ctl.get("occurrence_key") == "o1"]) == 2
    assert len([ctl for ctl in inputs["E4-R04"]["controls"]
                if ctl.get("occurrence_key") == "o2"]) == 1
    assert any(ctl["kind"] == "core.resume" for ctl in inputs["E4-R07"]["controls"])
    p05 = inputs["E4-P05"]["events"]
    assert p05[1]["raw"]["type"] == "derived.summary"
    assert {"kind": "event", "id": p05[0]["raw"]["id"]} in p05[1]["raw"]["references"]
    assert any(q["expected"] == "periodic_attempts_not_independent"
               for q in gold["E4-P06"]["checks"])
