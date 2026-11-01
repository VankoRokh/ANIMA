from scripts.run_deterministic_resolution_boundary_experiment import (
    CASES,
    DETERMINISTIC_RESULT,
    FAST_REQUIRED,
    INSUFFICIENT_DATA,
    resolve_task,
    run_experiment,
)


def _case(case_id):
    return next(case for case in CASES if case["id"] == case_id)


def test_full_boundary_corpus_passes_without_false_determinism():
    result = run_experiment()
    summary = result["summary"]
    assert summary["total"] == 9
    assert summary["passed"] == 9
    assert summary["false_deterministic"] == 0
    assert summary["missed_deterministic"] == 0
    assert result["llm_enabled"] is False
    assert result["production_modified"] is False


def test_exact_fact_is_resolved_without_fast():
    result = resolve_task(_case("exact_fact")["task"])
    assert result["route"] == DETERMINISTIC_RESULT
    assert result["value"] == "gray"


def test_missing_private_fact_stops_as_insufficient_data():
    result = resolve_task(_case("missing_fact")["task"])
    assert result["route"] == INSUFFICIENT_DATA
    assert result["value"] is None


def test_power_compatibility_is_deterministic():
    compatible = resolve_task(_case("power_compatible")["task"])
    insufficient = resolve_task(_case("power_insufficient")["task"])
    assert compatible["route"] == DETERMINISTIC_RESULT
    assert compatible["value"] == "YES"
    assert insufficient["route"] == DETERMINISTIC_RESULT
    assert insufficient["value"] == "NO"
    assert insufficient["derived"]["current_sufficient"] is False
    assert insufficient["derived"]["current_margin_a"] == -0.5


def test_hard_constraints_can_leave_one_action():
    result = resolve_task(_case("single_valid_action")["task"])
    assert result["route"] == DETERMINISTIC_RESULT
    assert result["value"] == "CONNECT_CHARGER"
    assert result["derived"]["valid_options"] == ["CONNECT_CHARGER"]
    assert "CONTINUE" in result["derived"]["rejected_options"]
    assert "SHUTDOWN" in result["derived"]["rejected_options"]


def test_explicit_dominance_rule_can_resolve_safe_choice():
    result = resolve_task(_case("continue_safe_explicit_rule")["task"])
    assert result["route"] == DETERMINISTIC_RESULT
    assert result["value"] == "CONTINUE"


def test_multiple_safe_actions_require_fast():
    result = resolve_task(_case("multiple_safe_actions")["task"])
    assert result["route"] == FAST_REQUIRED
    assert result["value"] is None
    assert result["candidates"] == ["CONTINUE", "CONNECT_CHARGER"]


def test_conflicting_facts_are_not_forced_deterministic():
    result = resolve_task(_case("conflicting_facts")["task"])
    assert result["route"] == FAST_REQUIRED
    assert result["value"] is None
    assert result["candidates"] == ["online", "offline"]


def test_unsupported_open_task_routes_to_fast():
    result = resolve_task(_case("unsupported_open_task")["task"])
    assert result["route"] == FAST_REQUIRED
    assert result["value"] is None
