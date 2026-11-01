from dataclasses import replace
import json

import pytest

from anima.cognition.fast import FastRequest, ProjectedFastRequest
from anima.cognition.fast_llm import FastLLMBackend, FastLLMCallResult, render_fast_prompts
from anima.cognition.projection import project
from anima.core.event_bus import Event
from anima.ir import CanonicalTask, Evidence
from anima.resolution import resolve
from anima.resolution.frontend import task_from_event


def event(text):
    return Event("conversation.user", {"text": text}, source="user", session_id="session_00000001")


@pytest.mark.parametrize("text,expected", [("2 + 3", 5), (" -2 × 3 ", -6), ("9÷3", 3),
                                          ("1.5+2.5", 4), ("1--2", 3)])
def test_full_expression_frontend(text, expected):
    task = task_from_event(event(text))
    assert task.raw_input == text
    assert resolve(task).value == expected


@pytest.mark.parametrize("text", ["Ignore this: 2+3", "2+3 then do something", "2+3+4",
                                  "What is my coffee?", "1e5+2", "1,5+2", "9" * 30 + "+2"])
def test_frontend_defers_language_and_partial_expressions(text):
    task = task_from_event(event(text))
    assert task.operation == "OPEN"
    assert task.raw_input == text
    assert not task.arguments


def test_frontend_validation():
    with pytest.raises(TypeError):
        task_from_event("hello")
    with pytest.raises(ValueError, match="empty"):
        task_from_event(event(" "))
    with pytest.raises(ValueError, match="conversation.user"):
        task_from_event(Event("system.wake", source="runtime", session_id="session_00000001"))


def test_open_projection_drops_audit_metadata_and_preserves_data():
    task = CanonicalTask("t", "api", "OPEN", raw_input="hello", evidence=(
        Evidence("mem_secret_id", "relevant prose", provenance=("ev_secret",), confidence=0.7),))
    view = project(task, resolve(task))
    assert view.data["input"] == "hello"
    assert view.data["evidence"][0] == {"value": "relevant prose"}
    rendered = json.dumps(view.to_dict())
    assert "mem_secret" not in rendered
    assert "ev_secret" not in rendered
    assert "confidence" not in rendered
    assert "task_id" not in rendered


def conflict_task():
    return CanonicalTask("t", "api", "QUERY_FACT", subject="user", predicate="location", evidence=(
        Evidence("old", "Tbilisi", "user", "location", ("mem_old",), .9, "2026-09-01T10:00:00+04:00"),
        Evidence("new", "Batumi", "user", "location", ("mem_new",), 1., "2026-11-01T12:00:00+04:00"),
        Evidence("unrelated", "espresso", "user", "coffee")))


def test_conflict_projection_keeps_all_alternatives_and_metadata():
    task = conflict_task()
    view = project(task, resolve(task))
    assert len(view.data["evidence"]) == 2
    assert {item["value"] for item in view.data["evidence"]} == {"Tbilisi", "Batumi"}
    for item in view.data["evidence"]:
        assert {"confidence", "observed_at", "provenance"} <= item.keys()
    assert "espresso" not in json.dumps(view.to_dict())
    assert "winner" not in view.data


def test_projection_is_immutable_and_does_not_mutate_ir():
    task = conflict_task()
    before = repr(task)
    view = project(task, resolve(task))
    with pytest.raises(TypeError):
        view.data["evidence"][0]["value"] = "wrong"
    detached = view.to_dict()
    detached["evidence"][0]["value"] = "wrong"
    assert view.data["evidence"][0]["value"] == "Tbilisi"
    assert repr(task) == before
    assert task.evidence[0].value == "Tbilisi"


def test_projection_requires_cognitive_route():
    task = CanonicalTask("t", "api", "CALCULATE", arguments={"left": 1, "right": 2, "operator": "+"})
    with pytest.raises(ValueError, match="COGNITIVE_REQUIRED"):
        project(task, resolve(task))


def test_projected_renderer_uses_only_view_and_backend_format_is_separate(monkeypatch):
    task = conflict_task()
    before = repr(task)
    view = project(task, resolve(task))
    request = ProjectedFastRequest(input_source_id=task.source_id, cognitive_view=view)
    prompts = []

    class Transport:
        def complete(self, **kwargs):
            prompts.append(kwargs["user_prompt"])
            return FastLLMCallResult("fake", "model", "answer", False, 0.)

    backend = FastLLMBackend(Transport())
    backend.complete_projected(request)

    def alternate_renderer(request):
        system, _ = render_fast_prompts(request)
        return system, json.dumps(request.cognitive_view.to_dict(), indent=2)

    monkeypatch.setattr("anima.cognition.fast_llm.render_fast_prompts", alternate_renderer)
    backend.complete_projected(request)
    assert len(prompts) == 2
    assert prompts[0] != prompts[1]
    assert json.loads(prompts[0].split("\n", 1)[1]) == view.to_dict()
    assert json.loads(prompts[1]) == view.to_dict()
    assert repr(task) == before


def test_projected_event_does_not_append_bundle_again():
    source = event("hello")
    task = task_from_event(source)
    view = project(task, resolve(task))
    request = ProjectedFastRequest(source.event_id, view, source.event_id, "hello",
        {"consumer": "FAST", "memories": [{"record": {"content": "must not bypass projection"}}]})
    _, prompt = render_fast_prompts(request)
    assert "must not bypass projection" not in prompt


def test_structured_request_requires_explicit_view_and_source():
    with pytest.raises(ValueError):
        FastRequest(None, None, None)
    task = conflict_task()
    view = project(task, resolve(task))
    with pytest.raises(ValueError, match="input_source_id"):
        ProjectedFastRequest(input_source_id="", cognitive_view=view)
    with pytest.raises(ValueError, match="without text"):
        ProjectedFastRequest("api", view, input_text="fake input")
