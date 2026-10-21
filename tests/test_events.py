import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("wake", None),
        ("sleep", None),
        ("user_input", {"text": "hello"}),
        ("user_input", {"text": "   "}),
    ],
)
def test_valid_events_are_accepted(
    event_type,
    payload,
):
    event = Event(event_type, payload)

    assert event.event_type == event_type


@pytest.mark.parametrize(
    ("event_type", "payload", "message"),
    [
        (
            123,
            None,
            "Event type must be a string",
        ),
        (
            "unknown",
            None,
            "Unknown event type",
        ),
        (
            "wake",
            {"unexpected": True},
            "must have null payload",
        ),
        (
            "sleep",
            {},
            "must have null payload",
        ),
        (
            "user_input",
            "hello",
            "payload must be an object",
        ),
        (
            "user_input",
            {},
            "must contain 'text'",
        ),
        (
            "user_input",
            {"text": 123},
            "'text' must be a string",
        ),
    ],
)
def test_invalid_events_are_rejected(
    event_type,
    payload,
    message,
):
    with pytest.raises(
        ValueError,
        match=message,
    ):
        Event(event_type, payload)


def test_event_log_preserves_event_order(tmp_path):
    log_file = tmp_path / "events.jsonl"
    event_log = EventLog(log_file)

    event_log.write(Event("wake"))
    event_log.write(
        Event(
            "user_input",
            {"text": "hello"},
        )
    )

    loaded = event_log.load_events()

    assert len(loaded) == 2
    assert loaded[0]["type"] == "wake"
    assert loaded[1]["type"] == "user_input"


def test_event_log_reports_malformed_line(tmp_path):
    log_file = tmp_path / "events.jsonl"

    log_file.write_text(
        '{"type":"wake","payload":null,'
        '"timestamp":"2026-10-13T12:00:00"}\n'
        '{"type":\n',
        encoding="utf-8",
    )

    event_log = EventLog(log_file)

    with pytest.raises(
        ValueError,
        match="line 2: malformed JSON",
    ):
        event_log.load_events()


def test_event_log_reports_invalid_event_with_line_number(
    tmp_path,
):
    log_file = tmp_path / "events.jsonl"

    log_file.write_text(
        '{"type":"wake",'
        '"payload":{"bad":true},'
        '"timestamp":"2026-10-13T12:00:00"}\n',
        encoding="utf-8",
    )

    event_log = EventLog(log_file)

    with pytest.raises(ValueError) as error:
        event_log.load_events()

    message = str(error.value)

    assert "line 1" in message
    assert "must have null payload" in message
