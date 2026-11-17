"""v0.2 H1.1: EventLog and Recovery agree on complete JSONL records.

Only temporary pytest data is damaged; none of these tests modifies user data.
H1.1 deliberately refuses damaged tails rather than truncating them.
"""

import json
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.event_retrieval import EventRetrieval
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor


STAMP = "2026-11-17T12:00:00+00:00"


def make_event(number):
    event_id = f"ev_{UUID(int=(4 << 76) | (2 << 62) | number)}"
    return Event(
        "conversation.user", {"text": f"h1tailmarker{number} test"},
        event_id=event_id, timestamp=STAMP, source="user",
        session_id="session_00000001",
    )


def test_h1_1_complete_log_is_appendable_reopenable_and_indexable(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    first, second = make_event(1), make_event(2)
    assert log.load_events() == []
    log.write(first)
    log.write(second)

    lines = log.log_file.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2
    assert all(line.endswith(b"\n") for line in lines)
    assert [json.loads(line)["id"] for line in lines] == [
        first.event_id, second.event_id,
    ]
    reopened = EventLog(log.log_file)
    assert [record["id"] for record in reopened.load_events()] == [
        first.event_id, second.event_id,
    ]
    store = MemoryStore(tmp_path / "memory.db")
    index = EventRetrieval(reopened, tmp_path / "event_index.db",
                           memory_store=store)
    assert index.sync()["status"] == "complete"
    assert index.get(second.event_id)["payload"]["text"] == (
        "h1tailmarker2 test"
    )


def test_h1_1_valid_json_without_lf_is_not_a_committed_event(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    first = make_event(11)
    log.write(first)
    raw = log.log_file.read_bytes()
    assert raw.endswith(b"\n")
    torn = raw[:-1]
    log.log_file.write_bytes(torn)

    reopened = EventLog(log.log_file)
    with pytest.raises(ValueError, match="unterminated JSONL record"):
        reopened.load_events()
    with pytest.raises(ValueError, match="unterminated JSONL record"):
        reopened.write(make_event(12))
    assert log.log_file.read_bytes() == torn


def test_h1_1_cached_ids_cannot_append_to_torn_tail(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    first, second = make_event(21), make_event(22)
    log.write(first)
    torn = log.log_file.read_bytes()[:-1]
    log.log_file.write_bytes(torn)

    # The same object has cached _known_ids, so load_events is not revisited
    # by _load_known_ids. Physical tail checking is required on every append.
    with pytest.raises(ValueError, match="unterminated trailing JSONL record"):
        log.write(second)
    assert log.log_file.read_bytes() == torn

    # Explicit fixture restoration is possible; EventLog never does it.
    log.log_file.write_bytes(torn + b"\n")
    log.write(second)
    assert [r["id"] for r in log.load_events()] == [
        first.event_id, second.event_id,
    ]


def test_h1_1_partial_json_tail_is_not_auto_truncated(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.write(make_event(31))
    with log.log_file.open("ab") as stream:
        stream.write(b'{"type":"conversation.user",')
    broken = log.log_file.read_bytes()
    with pytest.raises(ValueError, match="unterminated JSONL record"):
        log.load_events()
    with pytest.raises(ValueError, match="unterminated"):
        log.write(make_event(32))
    assert log.log_file.read_bytes() == broken


def test_h1_1_recovery_refuses_unterminated_tail_without_projection(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    links = LinkStore(store)
    processor = MemoryProcessor(
        memory_store=store, event_log=log, link_store=links,
    )
    coordinator = EventProcessingCoordinator(
        memory_store=store, memory_processor=processor, event_log=log,
    )
    log.write(make_event(41))
    torn = log.log_file.read_bytes()[:-1]
    log.log_file.write_bytes(torn)

    with pytest.raises(ValueError, match="unterminated JSONL record"):
        coordinator.recover()
    assert log.log_file.read_bytes() == torn
    assert coordinator.list_records() == []
    assert store.count() == 0


def test_h1_1_index_and_eventlog_disagree_no_longer_on_valid_json_tail(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.write(make_event(51))
    log.log_file.write_bytes(log.log_file.read_bytes()[:-1])
    index = EventRetrieval(log, tmp_path / "event_index.db")
    status = index.sync()
    assert status["status"] == "partial"
    assert status["indexed_events"] == 0
    with pytest.raises(ValueError, match="unterminated JSONL record"):
        log.load_events()


def test_h1_1_crlf_terminated_record_remains_compatible(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    event = make_event(61)
    log.write(event)
    raw = log.log_file.read_bytes()
    log.log_file.write_bytes(raw[:-1] + b"\r\n")
    assert log.load_events()[0]["id"] == event.event_id
    log.write(make_event(62))
    assert len(EventLog(log.log_file).load_events()) == 2
