from scripts.run_fast_memory_absence_contract_experiment import (
    ABSENCE_CASES,
    ABSENCE_SYSTEM_PROMPT,
    evaluate_response,
    render_d0,
    render_d1,
)


def _case(case_id):
    return next(case for case in ABSENCE_CASES if case["id"] == case_id)


def test_d1_includes_explicit_not_found_status():
    case = _case("unknown_personal_dog")

    system_prompt, user_prompt = render_d1(case)

    assert "MEMORY_STATUS" in system_prompt
    assert "NOT_FOUND" in user_prompt
    assert "FACTS:\n(none)" in user_prompt
    assert "Как зовут мою собаку?" in user_prompt


def test_d1_found_status_preserves_fact():
    case = _case("known_personal_coffee")

    _, user_prompt = render_d1(case)

    assert "FOUND" in user_prompt
    assert "Пользователь предпочитает кофе эспрессо." in user_prompt


def test_d0_does_not_include_memory_status():
    case = _case("unknown_personal_tea")

    _, user_prompt = render_d0(case)

    assert "MEMORY_STATUS" not in user_prompt
    assert "FACTS:\n(none)" in user_prompt


def test_evaluator_distinguishes_unknown_from_hallucination():
    case = _case("unknown_personal_tea")

    good = evaluate_response("Нет информации о предпочтении чая.", case)
    bad = evaluate_response("Ты предпочитаешь улун.", case)

    assert good["passed"] is True
    assert bad["passed"] is False


def test_evaluator_allows_memory_independent_answer():
    case = _case("memory_independent_arithmetic")

    result = evaluate_response("96", case)

    assert result["passed"] is True
