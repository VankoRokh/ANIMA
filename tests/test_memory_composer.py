import pytest

from anima.core.event_bus import Event
from anima.memory.composer import RuleBasedComposer
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor


EVENT_1 = "ev_aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
EVENT_2 = "ev_bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
TIMESTAMP_1 = "2026-10-26T12:00:00+00:00"
TIMESTAMP_2 = "2026-10-26T12:05:00+00:00"


def test_composer_normalizes_and_deduplicates_create():
    composer = RuleBasedComposer()

    result = composer.compose_create(
        "  Decision: use SQLite.   Decision: use SQLite.  "
    )

    assert result["content"] == "Decision: use SQLite."
    assert result["kept_units"] == 1
    assert result["dropped_units"] == 0
    assert result["truncated"] is False
    assert result["categories"] == ["decision"]


def test_composer_update_revises_without_repeating_existing_fact():
    composer = RuleBasedComposer()

    result = composer.compose_update(
        "Decision: use SQLite. Constraint: Python 3.12.",
        "Decision: use SQLite. Open question: enable WAL?",
    )

    assert result["content"].count("Decision: use SQLite.") == 1
    assert "Constraint: Python 3.12." in result["content"]
    assert "Open question: enable WAL?" in result["content"]
    assert result["truncated"] is False


def test_composer_budget_prioritizes_semantic_signal():
    composer = RuleBasedComposer(max_chars=96)

    result = composer.compose_update(
        "General chat about storage layout. Another incidental detail about naming.",
        "Decision: use SQLite. Constraint: must stay local. Open question: enable WAL?",
    )

    assert len(result["content"]) <= 96
    assert "Decision: use SQLite." in result["content"]
    assert "Constraint: must stay local." in result["content"]
    assert "Open question: enable WAL?" in result["content"]
    assert "General chat" not in result["content"]
    assert result["truncated"] is True
    assert result["dropped_units"] >= 1


def test_composer_is_deterministic():
    composer = RuleBasedComposer(max_chars=128)
    existing = "Decision: use SQLite. Old detail about setup."
    incoming = "Because it is local. Open question: enable WAL?"

    first = composer.compose_update(existing, incoming)
    second = composer.compose_update(existing, incoming)

    assert first == second


def test_composer_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="max_chars"):
        RuleBasedComposer(max_chars=32)

    composer = RuleBasedComposer()

    with pytest.raises(ValueError, match="non-empty string"):
        composer.compose_create("   ")

    with pytest.raises(ValueError, match="non-empty string"):
        composer.compose_update("existing", "")


def test_memory_processor_accepts_replaceable_composer(tmp_path):
    class RecordingComposer:
        def __init__(self):
            self.calls = []

        def compose_create(self, text):
            self.calls.append(("create", text))
            return {"content": "CREATE: " + text}

        def compose_update(self, existing_content, new_text):
            self.calls.append(("update", existing_content, new_text))
            return {"content": "UPDATE: " + new_text}

    event_log = EventLog(tmp_path / "events.jsonl")
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    composer = RecordingComposer()
    processor = MemoryProcessor(
        memory_store=store,
        event_log=event_log,
        link_store=links,
        composer=composer,
    )

    first = Event(
        "conversation.user",
        {"text": "SQLite storage baseline"},
        source="user",
        session_id="session_00000001",
        event_id=EVENT_1,
        timestamp=TIMESTAMP_1,
    )
    second = Event(
        "conversation.user",
        {"text": "SQLite storage baseline works locally"},
        source="user",
        session_id="session_00000001",
        event_id=EVENT_2,
        timestamp=TIMESTAMP_2,
    )

    event_log.write(first)
    first_result = processor.process_event(first)
    event_log.write(second)
    second_result = processor.process_event(second)

    assert first_result["action"] == "create"
    assert second_result["action"] == "update"
    assert composer.calls[0] == ("create", "SQLite storage baseline")
    assert composer.calls[1][0] == "update"
    assert store.get_memory(first_result["memory_id"])["content"] == (
        "UPDATE: SQLite storage baseline works locally"
    )
