import json
from datetime import datetime
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("system.wake", None),
        ("system.sleep", None),
        ("conversation.user", {"text": "hello"}),
        ("conversation.user", {"text": "   "}),
        (
            "observation.visual",
            {"objects": ["cup"]},
        ),
    ],
)
def test_valid_events_are_accepted(
    event_type,
    payload,
):
    event = Event(
        event_type,
        payload,
        source="pytest",
        session_id="session_00000001",
    )

    assert event.event_type == event_type
    assert event.source == "pytest"
    assert event.session_id == "session_00000001"
    assert event.event_id.startswith("ev_")
    assert UUID(event.event_id[3:]).version == 4

    parsed_time = datetime.fromisoformat(event.timestamp)
    assert parsed_time.utcoffset() is not None


@pytest.mark.parametrize(
    ("event_type", "payload", "extra", "message"),
    [
        (
            123,
            None,
            {},
            "Event type must be a string",
        ),
        (
            "unknown",
            None,
            {},
            "hierarchical lowercase name",
        ),
        (
            "system.wake",
            {"unexpected": True},
            {},
            "must have null payload",
        ),
        (
            "system.sleep",
            {},
            {},
            "must have null payload",
        ),
        (
            "conversation.user",
            "hello",
            {},
            "payload must be an object",
        ),
        (
            "conversation.user",
            {},
            {},
            "must contain 'text'",
        ),
        (
            "conversation.user",
            {"text": 123},
            {},
            "'text' must be a string",
        ),
        (
            "observation.visual",
            {"bad": {1, 2}},
            {},
            "must be JSON-serializable",
        ),
        (
            "system.wake",
            None,
            {"source": "   "},
            "'source' must be a non-empty string",
        ),
        (
            "system.wake",
            None,
            {"session_id": ""},
            "'session_id' must be a non-empty string or null",
        ),
        (
            "system.wake",
            None,
            {"references": [{"kind": "asset"}]},
            "must contain only 'kind' and 'id'",
        ),
        (
            "system.wake",
            None,
            {"timestamp": "2026-10-26T12:00:00"},
            "must include a UTC offset",
        ),
    ],
)
def test_invalid_events_are_rejected(
    event_type,
    payload,
    extra,
    message,
):
    arguments = {
        "source": "pytest",
        "session_id": "session_00000001",
        "references": [],
    }
    arguments.update(extra)

    with pytest.raises(
        ValueError,
        match=message,
    ):
        Event(
            event_type,
            payload,
            **arguments,
        )


def test_event_references_are_preserved():
    references = [
        {
            "kind": "asset",
            "id": "asset_camera_0001",
        }
    ]

    event = Event(
        "observation.visual",
        {"summary": "test frame"},
        source="camera.front",
        session_id="session_00000001",
        references=references,
    )

    assert event.to_dict()["references"] == references


def test_event_log_preserves_event_order_and_schema(tmp_path):
    log_file = tmp_path / "events.jsonl"
    event_log = EventLog(log_file)

    event_log.write(
        Event(
            "system.wake",
            source="runtime",
            session_id="session_00000001",
        )
    )
    event_log.write(
        Event(
            "conversation.user",
            {"text": "hello"},
            source="user",
            session_id="session_00000001",
        )
    )

    loaded = event_log.load_events()

    assert len(loaded) == 2
    assert loaded[0]["type"] == "system.wake"
    assert loaded[1]["type"] == "conversation.user"
    assert loaded[0]["source"] == "runtime"
    assert loaded[1]["source"] == "user"
    assert loaded[0]["session_id"] == "session_00000001"
    assert loaded[1]["references"] == []
    assert loaded[0]["id"] != loaded[1]["id"]


def test_event_log_reports_malformed_line(tmp_path):
    log_file = tmp_path / "events.jsonl"
    valid = Event(
        "system.wake",
        source="runtime",
        session_id="session_00000001",
    ).to_dict()

    log_file.write_text(
        json.dumps(valid) + "\n" + '{"id":\n',
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
    invalid = Event(
        "system.wake",
        source="runtime",
        session_id="session_00000001",
    ).to_dict()
    invalid["payload"] = {"bad": True}

    log_file.write_text(
        json.dumps(invalid) + "\n",
        encoding="utf-8",
    )

    event_log = EventLog(log_file)

    with pytest.raises(ValueError) as error:
        event_log.load_events()

    message = str(error.value)

    assert "line 1" in message
    assert "must have null payload" in message


def test_event_log_rejects_duplicate_id_on_write(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    event = Event(
        "system.wake",
        source="runtime",
        session_id="session_00000001",
    )

    event_log.write(event)

    with pytest.raises(
        ValueError,
        match="Duplicate event id",
    ):
        event_log.write(event)


def test_event_log_reports_duplicate_id_in_file(tmp_path):
    log_file = tmp_path / "events.jsonl"
    record = Event(
        "system.wake",
        source="runtime",
        session_id="session_00000001",
    ).to_dict()
    line = json.dumps(record)

    log_file.write_text(
        line + "\n" + line + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="line 2: duplicate event id",
    ):
        EventLog(log_file).load_events()


def test_event_log_reopens_existing_history(tmp_path):
    log_file = tmp_path / "events.jsonl"
    first_log = EventLog(log_file)

    first = Event(
        "system.wake",
        source="runtime",
        session_id="session_00000001",
    )
    first_log.write(first)

    reopened = EventLog(log_file)
    loaded = reopened.load_events()

    assert [record["id"] for record in loaded] == [
        first.event_id
    ]

    second = Event(
        "system.sleep",
        source="runtime",
        session_id="session_00000001",
    )
    reopened.write(second)

    assert [
        record["id"]
        for record in reopened.load_events()
    ] == [
        first.event_id,
        second.event_id,
    ]
