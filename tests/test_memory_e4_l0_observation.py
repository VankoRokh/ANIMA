"""E4 read-only observation L0 integration contract (no gold scoring)."""

import json

import pytest

from labs.exp009.e4_l0_observation import _load_frozen_inputs, run_suite


def test_l0_shadow_returns_deterministic_traces_without_gold():
    a = run_suite(case_id="E4-A03")
    b = run_suite(case_id="E4-A03")
    assert a == b
    assert a["schema"] == "anima.e4.shadow_observation_l0/0.1"
    case = a["cases"][0]
    assert case["case_id"] == "E4-A03"
    assert case["memory_store_unchanged"] is True
    assert len(case["decisions"]) == 3
    assert all(x["decision"]["event_id"] == x["event_id"]
               for x in case["decisions"])
    assert case["semantic_conformance"] == "NOT_ASSESSED"


def test_l0_controls_are_explicitly_unsupported_and_not_executed():
    trace = run_suite(suite="negative", case_id="E4-N12")["cases"][0]
    assert trace["memory_store_unchanged"]
    assert "CrashRecovery" in trace["unsupported_capabilities"]
    assert {x["kind"] for x in trace["unsupported_controls"]} == {
        "execution.effect", "runtime.crash", "runtime.restart",
        "execution.recover",
    }
    assert trace["semantic_conformance"] == "NOT_ASSESSED"


def test_l0_frozen_manifest_and_case_boundaries():
    inputs = _load_frozen_inputs("positive")
    assert len(inputs["cases"]) == 42
    trace = run_suite(case_id="E4-A04")["cases"][0]
    assert len(trace["decisions"]) == 2
    assert trace["decisions"][1]["decision"]["action"] == "skip"
    assert trace["decisions"][1]["decision"]["reasons"] == [
        "selection:event_type"
    ]
    with pytest.raises(ValueError, match="Unknown E4 case ID"):
        run_suite(case_id="NO_SUCH_CASE")
