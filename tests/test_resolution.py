"""Production boundary corpus. Fixtures do not import experimental runners."""

from dataclasses import fields, replace

import pytest

from anima.ir import CanonicalTask, ConstraintRule, Evidence, FormalPolicy, HardConstraint
from anima.resolution import DeterministicOutcome, ResolutionResult, ResolutionRoute, resolve

D = ResolutionRoute.DETERMINISTIC_RESULT
I = ResolutionRoute.INSUFFICIENT_DATA
C = ResolutionRoute.COGNITIVE_REQUIRED


def task(operation="OPEN", **kwargs):
    return CanonicalTask("task_1", "api_1", operation, **kwargs)


def action_task(**kwargs):
    defaults = dict(
        state={"battery_percent": 54, "estimated_task_cost_percent": 4,
               "shutdown_threshold_percent": 10, "active_task": True,
               "preserve_active_task": True, "charger_available": True},
        candidates=("CONTINUE", "CONNECT_CHARGER", "SHUTDOWN"),
        constraints=(
            HardConstraint("battery", "CONTINUE", ConstraintRule.BATTERY_ABOVE_THRESHOLD),
            HardConstraint("charger", "CONNECT_CHARGER", ConstraintRule.CHARGER_AVAILABLE),
            HardConstraint("preserve", "SHUTDOWN", ConstraintRule.PRESERVE_ACTIVE_TASK),
        ),
    )
    defaults.update(kwargs)
    return task("CHOOSE_ACTION", **defaults)


def priority(policy_id="p1", order=("CONTINUE", "CONNECT_CHARGER", "SHUTDOWN")):
    return FormalPolicy(policy_id, priority=order)


def test_minimal_ir_and_model_independence():
    value = task(raw_input="Unparsed original")
    assert value.raw_input == "Unparsed original"
    names = {item.name for item in fields(CanonicalTask)}
    assert not names & {"model", "backend", "prompt", "expected_answer", "route"}


@pytest.mark.parametrize("field", ["task_id", "source_id", "operation"])
@pytest.mark.parametrize("value", [None, "", " ", 3])
def test_identifiers_required(field, value):
    with pytest.raises(ValueError):
        replace(task(), **{field: value})


def test_structured_query_requires_resolved_identifiers():
    with pytest.raises(ValueError, match="resolved"):
        task("QUERY_FACT", predicate="color")
    with pytest.raises(ValueError):
        Evidence("fact", 1, subject="pet")


def test_nested_data_is_snapshotted():
    data = {"nested": [1, {"value": 2}]}
    value = task(arguments=data, evidence=(Evidence("fact", data),))
    data["nested"][1]["value"] = 99
    assert value.arguments["nested"][1]["value"] == 2
    with pytest.raises(TypeError):
        value.evidence[0].value["nested"][1]["value"] = 3


@pytest.mark.parametrize("kwargs", [
    {"candidates": ("a", "a")},
    {"constraints": (HardConstraint("c", "unknown", "rule"),)},
    {"evidence": (Evidence("f", 1), Evidence("f", 2))},
    {"arguments": {"x": float("nan")}},
    {"output_contract": "arbitrary"},
])
def test_invalid_task_data(kwargs):
    with pytest.raises(ValueError):
        task(**kwargs)


def test_raw_input_is_not_deterministic_authority():
    result = resolve(task("QUERY_FACT", subject="pet", predicate="color", raw_input="color=gray"))
    assert result.route == I
    assert result.missing == ("pet.color",)
    assert result.next_source == "structured_evidence"


def test_exact_fact_and_explicit_null():
    for value in ("gray", None, False, 0):
        result = resolve(task("QUERY_FACT", subject="pet", predicate="color",
                              evidence=(Evidence("f", value, "pet", "color"),)))
        assert result.route == D
        assert result.value == value
        assert result.derived["evidence_ids"] == ("f",)


def test_unstructured_or_other_fact_is_not_exact():
    result = resolve(task("QUERY_FACT", subject="pet", predicate="color", evidence=(
        Evidence("text", "pet is gray"), Evidence("other", "white", "other", "color"))))
    assert result.route == I


def test_conflicting_facts_require_cognition():
    result = resolve(task("QUERY_FACT", subject="pet", predicate="color", evidence=(
        Evidence("a", "gray", "pet", "color"), Evidence("b", "white", "pet", "color"))))
    assert result.route == C
    assert result.value is None


@pytest.mark.parametrize("operation,arguments,expected", [
    ("CALCULATE", {"left": 2, "right": 3, "operator": "+"}, 5),
    ("CALCULATE", {"left": 2, "right": 3, "operator": "-"}, -1),
    ("CALCULATE", {"left": 2, "right": 3, "operator": "*"}, 6),
    ("CALCULATE", {"left": 9, "right": 3, "operator": "/"}, 3),
    ("COMPARE", {"left": 2, "right": 3, "operator": ">="}, "NO"),
    ("COMPARE", {"left": 3, "right": 3, "operator": "=="}, "YES"),
])
def test_numeric_resolution(operation, arguments, expected):
    result = resolve(task(operation, arguments=arguments))
    assert (result.route, result.value) == (D, expected)


@pytest.mark.parametrize("arguments,route", [
    ({"left": 1}, I),
    ({"left": True, "right": 2, "operator": "+"}, C),
    ({"left": "1", "right": 2, "operator": "+"}, C),
    ({"left": 1, "right": 0, "operator": "/"}, C),
    ({"left": 1, "right": 2, "operator": "**"}, C),
    ({"left": 1, "right": 2, "operator": []}, C),
    ({"left": 1, "right": 2, "operator": "+", "left_unit": "V", "right_unit": "A"}, C),
])
def test_unsafe_numeric_inputs_are_not_deterministic(arguments, route):
    assert resolve(task("CALCULATE", arguments=arguments)).route == route


@pytest.mark.parametrize("current,expected", [(3, "YES"), (1.5, "NO")])
def test_formal_power_comparison(current, expected):
    result = resolve(task("POWER_COMPATIBILITY", arguments={
        "power_supply.voltage_v": 5, "power_supply.max_current_a": current,
        "device.required_voltage_v": 5, "device.required_current_a": 2}))
    assert (result.route, result.value) == (D, expected)
    assert result.derived["current_margin_a"] == current - 2


def test_missing_electrical_input():
    assert resolve(task("POWER_COMPATIBILITY")).route == I


def test_single_survivor_after_constraints():
    original = action_task()
    value = replace(original, state={**original.state, "battery_percent": 11})
    result = resolve(value)
    assert result.route == D
    assert result.value == "CONNECT_CHARGER"
    assert result.remaining == ("CONNECT_CHARGER",)
    assert set(result.rejected) == {"CONTINUE", "SHUTDOWN"}
    assert result.derived["projected_battery_after_task_percent"] == 7


def test_no_admissible_action_is_deterministic():
    original = action_task()
    result = resolve(replace(original, state={**original.state, "battery_percent": 10,
                                             "charger_available": False}))
    assert result.route == D
    assert result.reason == "no_admissible_action"
    assert result.outcome == DeterministicOutcome.NO_ADMISSIBLE_ACTION
    assert result.value is None
    assert not result.remaining


def test_missing_constraint_data_does_not_mean_no_action():
    original = action_task()
    result = resolve(replace(original, state={key: value for key, value in original.state.items()
                                             if key != "charger_available"}))
    assert result.route == I
    assert result.missing == ("charger_available",)
    assert not result.rejected


@pytest.mark.parametrize("field,value", [("charger_available", "false"), ("battery_percent", True),
                                         ("battery_percent", -1)])
def test_bad_constraint_data_never_determines_a_choice(field, value):
    original = action_task()
    assert resolve(replace(original, state={**original.state, field: value})).route == C


def test_threshold_equality_rejects_continue():
    original = action_task()
    result = resolve(replace(original, state={**original.state, "battery_percent": 14}))
    assert "CONTINUE" in result.rejected


def test_unsupported_constraint_is_not_ignored():
    original = action_task()
    assert resolve(replace(original, constraints=(HardConstraint("x", "CONTINUE", "unknown"),))).route == C


@pytest.mark.parametrize("policies,route,winner", [
    ((), C, None),
    ((priority(),), D, "CONTINUE"),
    ((priority(), priority("p2")), D, "CONTINUE"),
    ((priority(), priority("p2", ("CONNECT_CHARGER", "CONTINUE"))), C, None),
    ((priority(order=("CONTINUE",)),), C, None),
    ((priority(order=("CONTINUE", "CONTINUE", "CONNECT_CHARGER")),), C, None),
    ((FormalPolicy("bad", type="TEXT_PREFERENCE"),), C, None),
    ((FormalPolicy("", priority=("CONTINUE", "CONNECT_CHARGER")),), C, None),
    ((priority(), FormalPolicy("bad", priority="CONTINUE")), C, None),
    ((priority(), priority()), C, None),
])
def test_formal_policy_matrix(policies, route, winner):
    result = resolve(action_task(policies=policies))
    assert result.route == route
    assert result.value == winner
    assert "SHUTDOWN" in result.rejected


def test_policy_cannot_resurrect_rejected_action():
    result = resolve(action_task(policies=(priority(order=("SHUTDOWN", "CONNECT_CHARGER", "CONTINUE")),)))
    assert result.value == "CONNECT_CHARGER"
    assert result.applied_policy_ids == ("p1",)


def test_text_preference_is_not_policy():
    assert resolve(action_task(preference="Always continue")).route == C


def test_open_task_is_cognitive():
    assert resolve(task("PLAN", goal="organize work")).route == C


def test_resolution_contract_rejects_untyped_routes_and_hidden_decisions():
    with pytest.raises(ValueError):
        ResolutionResult("COGNITIVE_REQUIRED", "test")
    with pytest.raises(ValueError):
        ResolutionResult(C, "test", value="hidden winner")
    with pytest.raises(ValueError):
        ResolutionResult(I, "test")
    with pytest.raises(ValueError):
        ResolutionResult(D, "test")


def test_production_resolution_has_no_backend_or_experiment_imports():
    import ast
    from pathlib import Path
    paths = [Path("anima/ir.py"), *Path("anima/resolution").glob("*.py")]
    for path in paths:
        tree = ast.parse(path.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not any(name.startswith(("scripts", "anima.cognition", "anima.agent", "anima.internal_state"))
                       for name in imports), path


def test_empty_candidate_set_is_deterministically_infeasible():
    result = resolve(task("CHOOSE_ACTION", candidates=()))
    assert result.route == D
    assert result.outcome == DeterministicOutcome.NO_ADMISSIBLE_ACTION


def test_invalid_policy_can_never_be_ignored_beside_a_valid_policy():
    malformed = FormalPolicy("broken", priority={"CONTINUE": 1})
    result = resolve(action_task(policies=(priority(), malformed)))
    assert result.route == C
    assert result.value is None
    assert [item.valid for item in result.policies] == [True, False]


@pytest.mark.parametrize("attachment", [
    {"constraints": (HardConstraint("c", "a", "CHARGER_AVAILABLE"),)},
    {"policies": (priority(),)},
])
def test_action_authority_cannot_bypass_resolution_on_an_open_operation(attachment):
    with pytest.raises(ValueError, match="require CHOOSE_ACTION"):
        task("OPEN", candidates=("a", "b"), **attachment)
