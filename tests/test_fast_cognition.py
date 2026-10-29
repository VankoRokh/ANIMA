import pytest

from anima.cognition.fast import FastCognition, FastRequest, FastResult
from anima.core.event_bus import Event


class StubContextBuilder:
    def __init__(self):
        self.calls = []

    def build(self, query, *, consumer):
        self.calls.append((query, consumer))
        return {
            "query": query,
            "consumer": consumer,
            "budget": {"max_items": 6, "max_chars": 1200},
            "knowledge": [],
            "memories": [],
            "events": [],
            "truncated": False,
            "selection_stats": {
                "items_used": 0,
                "chars_used": 0,
            },
        }


class RecordingFastBackend:
    def __init__(self, response="Принято."):
        self.response = response
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return FastResult(response_text=self.response)


class InvalidFastBackend:
    def complete(self, request):
        return "not-a-fast-result"


def user_event(text="Привет"):
    return Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000001",
    )


def test_fast_cognition_builds_fast_context_and_returns_observable_turn():
    context_builder = StubContextBuilder()
    backend = RecordingFastBackend("Ответ FAST")
    cognition = FastCognition(
        context_builder=context_builder,
        backend=backend,
    )
    event = user_event("Что ты помнишь?")

    turn = cognition.process(event)

    assert context_builder.calls == [("Что ты помнишь?", "FAST")]
    assert len(backend.requests) == 1
    assert isinstance(turn.request, FastRequest)
    assert turn.request.input_event_id == event.event_id
    assert turn.request.input_text == "Что ты помнишь?"
    assert turn.request.context_bundle["consumer"] == "FAST"
    assert turn.result == FastResult(response_text="Ответ FAST")


def test_fast_cognition_rejects_non_user_events_and_empty_text():
    cognition = FastCognition(
        context_builder=StubContextBuilder(),
        backend=RecordingFastBackend(),
    )

    wake = Event(
        "system.wake",
        source="runtime",
        session_id="session_00000001",
    )
    with pytest.raises(ValueError, match="conversation.user"):
        cognition.process(wake)

    with pytest.raises(ValueError, match="empty user text"):
        cognition.process(user_event("   "))


def test_fast_request_requires_fast_context_bundle():
    event = user_event()

    with pytest.raises(ValueError, match="consumer='FAST'"):
        FastRequest(
            input_event_id=event.event_id,
            input_text="Привет",
            context_bundle={"consumer": "DEEP"},
        )


def test_fast_backend_must_return_fast_result():
    cognition = FastCognition(
        context_builder=StubContextBuilder(),
        backend=InvalidFastBackend(),
    )

    with pytest.raises(TypeError, match="FastResult"):
        cognition.process(user_event())


def test_fast_cognition_does_not_require_runtime_state_sleep_or_agent():
    cognition = FastCognition(
        context_builder=StubContextBuilder(),
        backend=RecordingFastBackend(),
    )

    turn = cognition.process(user_event("Тест минимального контура"))

    assert turn.result.response_text == "Принято."
