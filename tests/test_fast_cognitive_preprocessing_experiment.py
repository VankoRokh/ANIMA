from scripts.run_fast_cognitive_preprocessing_experiment import (
    CASES,
    TARGET_IDS,
    derive_runtime_features,
    evaluate_response,
    extract_result_value,
    project_with_derived_state,
)


def _case(task_id):
    return next(task for task in CASES if task["task_id"] == task_id)


def test_corpus_is_exactly_the_three_semantic_failures_from_test_j():
    assert tuple(task["task_id"] for task in CASES) == TARGET_IDS
    assert TARGET_IDS == (
        "s2_power_insufficient",
        "s3_connect_charger",
        "s3_continue_safe",
    )


def test_power_preprocessing_computes_checks_without_final_answer():
    task = _case("s2_power_insufficient")
    derived = derive_runtime_features(task)

    assert derived["voltage_match"] is True
    assert derived["current_sufficient"] is False
    assert derived["current_margin_a"] == -0.5
    assert "NO" not in derived.values()
    assert "YES" not in derived.values()


def test_connect_charger_preprocessing_exposes_risk_and_charger_state():
    task = _case("s3_connect_charger")
    derived = derive_runtime_features(task)

    assert derived["battery_margin_percent"] == 8.0
    assert derived["battery_trend"] == "discharging"
    assert derived["battery_risk"] == "HIGH"
    assert derived["charger_usable"] is True
    assert derived["active_task_requires_preservation"] is True
    assert "CONNECT_CHARGER" not in derived.values()


def test_continue_preprocessing_exposes_safe_completion_without_action():
    task = _case("s3_continue_safe")
    derived = derive_runtime_features(task)

    assert derived["projected_battery_after_task_percent"] == 82.0
    assert derived["margin_after_task_percent"] == 72.0
    assert derived["completion_safety"] == "SAFE"
    assert derived["active_task_requires_preservation"] is True
    assert "CONTINUE" not in derived.values()


def test_derived_projection_keeps_original_projection_and_adds_only_derived_block():
    task = _case("s2_power_insufficient")
    projection = project_with_derived_state(task)

    assert projection["task"] == "COMPARE"
    assert projection["values"]["power_supply.max_current_a"] == 1.5
    assert projection["derived"]["current_sufficient"] is False
    assert "expected" not in projection


def test_result_parser_accepts_bracketed_and_plain_protocol_forms():
    bracketed = extract_result_value("RESULT=<NO>")
    plain = extract_result_value("RESULT=NO")

    assert bracketed == {
        "protocol_ok": True,
        "value": "NO",
        "bracketed": True,
    }
    assert plain == {
        "protocol_ok": True,
        "value": "NO",
        "bracketed": False,
    }


def test_evaluator_separates_semantics_from_format():
    bracketed = evaluate_response("RESULT=<NO>", "NO")
    plain = evaluate_response("RESULT=NO", "NO")
    wrong = evaluate_response("RESULT=<YES>", "NO")

    assert bracketed["semantic_pass"] is True
    assert bracketed["canonical_format"] is True
    assert plain["semantic_pass"] is True
    assert plain["canonical_format"] is False
    assert wrong["semantic_pass"] is False
    assert wrong["protocol_ok"] is True


def test_result_parser_rejects_explanations_and_multiline_output():
    assert extract_result_value("RESULT=<NO> because current is low")["protocol_ok"] is False
    assert extract_result_value("RESULT=<NO>\nextra")["protocol_ok"] is False
