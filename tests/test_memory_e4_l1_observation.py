"""E4 L1 visible deterministic observation checks; no frozen-gold imports."""
from labs.exp009.e4_l0_observation import run_suite as run_l0
from labs.exp009.e4_l1_association import run_suite as run_l1


def c(id, suite="positive"):
    return run_l1(case_id=id, suite=suite)["cases"][0]


def link(case, a, b):
    return next(row for row in case["story_pair_assessments"]
                if (row["left_event_key"], row["right_event_key"]) == (a, b))


def test_l1_explicit_ticket_continuation_is_only_reported():
    row = c("E4-B03")
    decision = link(row, "e1", "e2")
    assert decision["status"] == "same_case_reported"
    assert len(decision["source_event_ids"]) == 2
    assert decision["authority"] == "source_report_not_world_fact"


def test_l1_unresolved_and_separate_ticket_namespaces():
    assert link(c("E4-B05"), "e1", "e2")["status"] == "insufficient"
    assert link(c("E4-N04", "negative"), "e1", "e2")["status"] == "insufficient"
    assert link(c("E4-N05", "negative"), "e1", "e2")["status"] == "insufficient"


def test_l1_explicit_shared_incident_no_episode_merge_claim():
    row = c("E4-B04")
    decision = link(row, "e1", "e2")
    assert decision["status"] == "same_case_reported"
    assert len(decision["source_event_ids"]) == 1
    assert row["memory_store_unchanged"]
    assert "Episode_resegmentation" in row["unsupported_capabilities"]


def test_l1_scoped_speaker_alias_reuse_requires_source():
    row = c("E4-C03")
    assert len(row["alias_records"]) == 1
    assert row["alias_records"][0]["surface"] == "psu"
    assert row["alias_records"][0]["status"] == "speaker_intent_confirmed_in_scope"
    uses = [item for item in row["alias_mentions"]
            if item["event_key"] == "e1" and item["status"] == "scoped_alias_reuse"]
    assert len(uses) == 1
    assert uses[0]["source_event_id"] == row["alias_records"][0]["source_event_id"]
    assert uses[0]["expensive_method_calls"] == 0
    assert c("E4-C02")["alias_records"] == []


def test_l1_derived_pointer_not_independent_witness():
    assert len(c("E4-A04")["source_origin_links"]) == 1
    assert c("E4-N03", "negative")["source_origin_links"] == []


def test_l1_recovery_and_scheduling_not_faked():
    row = c("E4-R06")
    assert "CrashRecovery" in row["unsupported_capabilities"]
    assert [x["kind"] for x in row["unsupported_controls"]] == [
        "execution.claim", "execution.crash", "runtime.restart", "time.tick",
    ]


def test_l1_all_frozen_cases_deterministic_and_read_only():
    for suite, expected in (("positive", 42), ("negative", 15)):
        first = run_l1(suite=suite)
        assert len(first["cases"]) == expected
        assert first["gold_visible"] is False
        assert all(x["memory_store_unchanged"] for x in first["cases"])
        assert all(x["semantic_conformance"] == "NOT_ASSESSED"
                   for x in first["cases"])
    assert run_l1(case_id="E4-B01") == run_l1(case_id="E4-B01")
    assert (c("E4-B01")["episode_baseline"]["episodes"]
            == run_l0(case_id="E4-B01")["cases"][0]["episodes"])
