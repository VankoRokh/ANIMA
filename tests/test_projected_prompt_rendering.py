import json

import pytest

from anima.cognition.contracts import CognitiveView
from anima.cognition.fast import ProjectedFastRequest
from anima.cognition.fast_llm import render_fast_prompts


def render(view):
    return render_fast_prompts(ProjectedFastRequest(
        input_source_id="render-test", cognitive_view=CognitiveView("FAST", view)
    ))


def test_text_protocol_follows_input_without_candidate_or_contract_instructions():
    view = {"operation": "OPEN", "output_contract": "text",
            "input": "Reply exactly AMBER29", "evidence": [{"value": "AMBER29"}]}
    system, user = render(view)
    for label in ("candidate", "CHOOSE_ACTION", "output_contract", "text"):
        assert label not in system
    assert "Выполни инструкцию задачи из поля input напрямую" in system
    assert "не являются текстом ответа" in system
    assert "без префиксов, суффиксов, меток, объяснений" in system
    assert "дополнительного текста и дополнительной пунктуации" in system
    assert json.loads(user.removeprefix("TASK_VIEW:\n")) == view


@pytest.mark.parametrize("operation,contract", [
    ("CHOOSE_ACTION", "text"), ("OPEN", "candidate"),
])
def test_candidate_protocol_is_selected_before_inference(operation, contract):
    view = {"operation": operation, "output_contract": contract,
            "candidates": ["CONTINUE", "WAIT"]}
    system, user = render(view)
    assert "Верни ровно один разрешённый ID из candidates" in system
    assert "только сам ID: без объяснений, имён служебных полей" in system
    assert "дополнительной пунктуации и окружающего текста" in system
    assert "Если запрошен точный вывод" not in system
    assert "Иначе" not in system
    assert json.loads(user.removeprefix("TASK_VIEW:\n")) == view
