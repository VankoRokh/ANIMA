from scripts.run_fast_structured_ir_model_experiment import (
    CASES,
    IR_SYSTEM_PROMPT,
    RAW_SYSTEM_PROMPT,
    evaluate_response,
    prepare_case,
    render_ir,
    render_raw,
)


def test_all_model_cases_resolve_to_exact_semantic_facts():
    prepared = [prepare_case(case) for case in CASES]
    assert len(prepared) == len(CASES)
    for case in prepared:
        assert case["memory_outcome"] == "FOUND"
        assert case["request"]["route"] == "MEMORY_LOOKUP"
        assert case["request"]["subject"] == case["fact"]["subject"]
        assert case["request"]["predicate"] == case["fact"]["predicate"]


def test_raw_renderer_preserves_conversational_question_and_fact():
    case = prepare_case(CASES[0])
    system_prompt, user_prompt = render_raw(case)
    assert system_prompt == RAW_SYSTEM_PROMPT
    assert case["query"] in user_prompt
    assert case["raw_fact"] in user_prompt
    assert "FACTS:" in user_prompt
    assert "QUESTION:" in user_prompt


def test_ir_renderer_uses_structured_request_and_exact_evidence():
    case = prepare_case(CASES[1])
    system_prompt, user_prompt = render_ir(case)
    assert system_prompt == IR_SYSTEM_PROMPT
    assert "schema=anima.ir.query.v0" in user_prompt
    assert "subject=pet_barsik" in user_prompt
    assert "predicate=color" in user_prompt
    assert "status=FOUND" in user_prompt
    assert "value=gray" in user_prompt
    assert "provenance=mem_barsik_color" in user_prompt
    assert case["query"] not in user_prompt


def test_pronoun_case_is_resolved_before_ir_reaches_model():
    case = next(case for case in CASES if case["id"] == "pronoun_with_context")
    prepared = prepare_case(case)
    assert prepared["request"]["subject"] == "pet_barsik"
    assert prepared["request"]["entity_resolution"]["source"] == "working_context_pronoun"
    _, user_prompt = render_ir(prepared)
    assert "subject=pet_barsik" in user_prompt
    assert "Какого цвета он?" not in user_prompt


def test_evaluator_accepts_semantic_answer_and_rejects_schema_leak():
    case = prepare_case(CASES[1])
    good = evaluate_response("Барсик серый.", case)
    leaked = evaluate_response("subject=pet_barsik predicate=color gray", case)
    wrong = evaluate_response("Барсик рыжий.", case)
    assert good["passed"] is True
    assert leaked["passed"] is False
    assert leaked["schema_leak"] is True
    assert wrong["passed"] is False
