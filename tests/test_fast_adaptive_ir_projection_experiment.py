from scripts.run_fast_adaptive_ir_projection_experiment import (
    TASKS,
    evaluate_response,
    project_task,
    render_adaptive,
    render_verbose,
)


def _task(task_id):
    return next(task for task in TASKS if task["task_id"] == task_id)


def test_corpus_has_two_cases_per_complexity_level():
    counts = {}
    for task in TASKS:
        counts[task["level"]] = counts.get(task["level"], 0) + 1
    assert counts == {
        "S1_FACT": 2,
        "S2_COMPARE": 2,
        "S3_CHOOSE": 2,
        "S4_CONFLICT": 2,
    }


def test_fact_projection_keeps_only_answer_bearing_fields():
    projection = project_task(_task("s1_pet_color"))
    assert projection == {
        "task": "QUERY_FACT",
        "goal": "return pet_barsik.color",
        "subject": "pet_barsik",
        "field": "color",
        "value": "gray",
    }
    rendered = str(projection)
    assert "provenance" not in rendered
    assert "confidence" not in rendered
    assert "raw_text" not in rendered


def test_compare_projection_keeps_values_and_rule_without_audit_metadata():
    projection = project_task(_task("s2_power_compatible"))
    assert projection["task"] == "COMPARE"
    assert projection["values"]["power_supply.max_current_a"] == 3
    assert projection["values"]["device.required_current_a"] == 2
    assert "rule" in projection
    rendered = str(projection)
    assert "provenance" not in rendered
    assert "trace_id" not in rendered


def test_choose_projection_keeps_state_constraints_and_options():
    projection = project_task(_task("s3_connect_charger"))
    assert projection["task"] == "CHOOSE_ACTION"
    assert projection["state"]["battery_percent"] == 18
    assert "do_not_interrupt_active_task" in projection["constraints"]
    assert "CONNECT_CHARGER" in projection["options"]
    assert "facts" not in projection


def test_conflict_projection_exposes_epistemic_metadata_only_when_needed():
    projection = project_task(_task("s4_newer_high_confidence"))
    assert projection["task"] == "RESOLVE_CONFLICT"
    assert projection["subject"] == "user"
    assert projection["field"] == "location"
    assert len(projection["evidence"]) == 2
    assert projection["evidence"][0]["confidence"] == 0.98
    assert projection["evidence"][1]["observed_at"].startswith("2026-11-01")
    assert projection["evidence"][1]["provenance"] == ["conversation_current"]


def test_adaptive_render_is_shorter_than_verbose_for_every_case():
    for task in TASKS:
        _, verbose = render_verbose(task)
        _, adaptive = render_adaptive(task)
        assert len(adaptive) < len(verbose), task["task_id"]


def test_evaluator_requires_exact_internal_result_protocol():
    task = _task("s3_connect_charger")
    assert evaluate_response("RESULT=CONNECT_CHARGER", task)["passed"] is True
    assert evaluate_response("CONNECT_CHARGER", task)["passed"] is False
    assert evaluate_response("RESULT=CONNECT_CHARGER\nBecause...", task)["passed"] is False
