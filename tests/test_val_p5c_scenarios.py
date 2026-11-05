"""P5-C fixture and replay-contract unit tests; no Godot/Core dependencies."""

from copy import deepcopy

import pytest

from labs.virtual_anima_lab.python.scenario_runner import (
    ScenarioError,
    _assert_step,
    _canonical,
    load_suite,
    validate_suite,
)


def test_p5c_four_scripted_world_variants_load():
    suite = load_suite()
    assert suite["schema"] == "val.scenario_suite/0.1"
    assert len(suite["scenarios"]) == 4
    assert {case["world"] for case in suite["scenarios"]} == {
        "base", "detour", "clutter",
    }
    assert {case["id"] for case in suite["scenarios"]} == {
        "noise_and_obstacle", "door_intervention",
        "detour_injection", "clutter_reset",
    }


@pytest.mark.parametrize("damage", [
    "duplicate_id", "unknown_world", "negative_seed", "boolean_seed",
    "wrong_suite_version", "too_many_steps", "missing_step_field",
    "agent_operator_spoof", "unknown_operator", "act_before_observe",
    "unexpected_read_args", "malformed_obstacle", "malformed_noise",
    "invalid_expectation", "hidden_unbounded_fields", "act_after_reset",
])
def test_p5c_fixture_rejects_malformed_or_privilege_escalation(damage):
    suite = deepcopy(load_suite())
    scenarios = suite["scenarios"]
    first = scenarios[0]
    step = first["steps"][0]
    if damage == "duplicate_id":
        scenarios[1]["id"] = first["id"]
    elif damage == "unknown_world":
        first["world"] = "god_mode"
    elif damage == "negative_seed":
        first["seed"] = -1
    elif damage == "boolean_seed":
        first["seed"] = True
    elif damage == "wrong_suite_version":
        suite["schema"] = "val.scenario_suite/9.0"
    elif damage == "too_many_steps":
        first["steps"] = [deepcopy(step) for _ in range(65)]
    elif damage == "missing_step_field":
        step.pop("role")
    elif damage == "agent_operator_spoof":
        step["op"] = "set_obstacle"
    elif damage == "unknown_operator":
        step["role"] = "operator"
        step["op"] = "shutdown"
    elif damage == "act_before_observe":
        step["op"] = "act"
        step["args"] = {"direction": "N"}
    elif damage == "unexpected_read_args":
        step["args"] = {"debug": True}
    elif damage == "malformed_obstacle":
        first["steps"][5]["args"]["at"]["x"] = 100
    elif damage == "malformed_noise":
        first["steps"][1]["args"]["label"] = "evil\nworld"
    elif damage == "invalid_expectation":
        step["expect"]["revision_delta"] = True
    elif damage == "hidden_unbounded_fields":
        step["expect"]["full_world"] = True
    elif damage == "act_after_reset":
        first["steps"] = [
            deepcopy(first["steps"][0]),
            {"role": "operator", "op": "reset", "args": {}, "expect": {"ok": True}},
            {"role": "agent", "op": "act", "args": {"direction": "E"},
             "expect": {"ok": True}},
        ]
    with pytest.raises(ScenarioError):
        validate_suite(suite)


def test_p5c_replay_digest_input_is_order_stable_and_detects_changes():
    base = [{"response": {"revision": 1, "ok": True},
             "request": {"direction": "W"}}]
    same = [{"request": {"direction": "W"},
             "response": {"ok": True, "revision": 1}}]
    change = [{"request": {"direction": "W"},
               "response": {"ok": True, "revision": 2}}]
    assert _canonical(base) == _canonical(same)
    assert _canonical(base) != _canonical(change)


def test_p5c_expected_observation_checks_visible_bounded_subjects():
    step = {
        "role": "agent", "op": "observe", "args": {},
        "expect": {
            "ok": True, "present": ["lab.door.01"],
            "absent": ["lab.obstacle.7.5"],
            "states": {"lab.door.01": "closed"},
            "revision_delta": 0,
        },
    }
    previous = {"revision": 4, "event_seq": 3}
    result = {
        "ok": True, "revision": 4, "event_seq": 4,
        "data": {"readings": [{
            "subject_ref": "lab.door.01",
            "typed_value": {"type": "symbol", "value": "closed"},
        }]},
    }
    _assert_step(step, result, previous, name="test")
    bad = deepcopy(result)
    bad["data"]["readings"][0]["typed_value"]["value"] = "open"
    with pytest.raises(ScenarioError, match="wrong sensed state"):
        _assert_step(step, bad, previous, name="test")


def test_p5c_rejected_command_requires_precise_error():
    step = {
        "role": "agent", "op": "act", "args": {"direction": "W"},
        "expect": {"ok": False, "error": "STALE_WORLD", "revision_delta": 0},
    }
    previous = {"revision": 4, "event_seq": 3}
    reply = {
        "ok": False, "error": "STALE_WORLD",
        "revision": 4, "event_seq": 3,
    }
    _assert_step(step, reply, previous, name="test")
    reply["error"] = "FORBIDDEN"
    with pytest.raises(ScenarioError):
        _assert_step(step, reply, previous, name="test")
