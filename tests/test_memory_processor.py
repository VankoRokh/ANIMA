import pytest

from anima.core.event_bus import Event
from anima.diagnostics.trace import DiagnosticTrace
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor


ENTITY_SQLITE = "ent_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

EVENT_IDS = [
    f"ev_{number:08d}-1111-4111-8111-{number:012d}"
    for number in range(1, 20)
]


def build_processor(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    memory_store = MemoryStore(tmp_path / "memory.db")
    link_store = LinkStore(memory_store)
    trace = DiagnosticTrace()
    processor = MemoryProcessor(
        memory_store=memory_store,
        event_log=event_log,
        link_store=link_store,
        trace=trace,
    )
    return processor, event_log, memory_store, link_store, trace


def write_event(
    event_log,
    event_id,
    event_type,
    timestamp,
    *,
    session_id,
    text=None,
    references=None,
):
    payload = None
    if event_type == "conversation.user":
        payload = {"text": text}

    event = Event(
        event_type,
        payload,
        source="user" if event_type == "conversation.user" else "runtime",
        session_id=session_id,
        references=references,
        event_id=event_id,
        timestamp=timestamp,
    )
    event_log.write(event)
    return event


def test_canonical_corpus_groups_events_explainably(tmp_path):
    processor, event_log, store, links, trace = build_processor(tmp_path)
    links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        aliases=["SQLite3"],
        public_id=ENTITY_SQLITE,
    )

    wake = write_event(
        event_log,
        EVENT_IDS[0],
        "system.wake",
        "2026-10-26T12:00:00+00:00",
        session_id="session_00000001",
    )
    sqlite_first = write_event(
        event_log,
        EVENT_IDS[1],
        "conversation.user",
        "2026-10-26T12:01:00+00:00",
        session_id="session_00000001",
        text="SQLite storage baseline",
        references=[{"kind": "entity", "id": ENTITY_SQLITE}],
    )
    sqlite_followup = write_event(
        event_log,
        EVENT_IDS[2],
        "conversation.user",
        "2026-10-26T12:05:00+00:00",
        session_id="session_00000001",
        text="SQLite storage baseline uses local database",
        references=[{"kind": "entity", "id": ENTITY_SQLITE}],
    )
    cm5_first = write_event(
        event_log,
        EVENT_IDS[3],
        "conversation.user",
        "2026-10-26T12:10:00+00:00",
        session_id="session_00000001",
        text="CM5 hardware planning",
    )
    cm5_followup = write_event(
        event_log,
        EVENT_IDS[4],
        "conversation.user",
        "2026-10-26T12:15:00+00:00",
        session_id="session_00000001",
        text="CM5 hardware power planning",
    )
    sleep = write_event(
        event_log,
        EVENT_IDS[5],
        "system.sleep",
        "2026-10-26T12:20:00+00:00",
        session_id="session_00000001",
    )
    sqlite_later = write_event(
        event_log,
        EVENT_IDS[6],
        "conversation.user",
        "2026-10-27T12:00:00+00:00",
        session_id="session_00000002",
        text="SQLite storage benchmark",
    )
    blank = write_event(
        event_log,
        EVENT_IDS[7],
        "conversation.user",
        "2026-10-27T12:01:00+00:00",
        session_id="session_00000002",
        text="   ",
    )

    wake_result = processor.process_event(wake)
    first_result = processor.process_event(sqlite_first)
    followup_result = processor.process_event(sqlite_followup)
    cm5_first_result = processor.process_event(cm5_first)
    cm5_followup_result = processor.process_event(cm5_followup)
    sleep_result = processor.process_event(sleep)
    later_result = processor.process_event(sqlite_later)
    blank_result = processor.process_event(blank)

    assert wake_result["action"] == "skip"
    assert sleep_result["action"] == "skip"
    assert blank_result["action"] == "skip"

    assert first_result["action"] == "create"
    assert followup_result["action"] == "update"
    assert followup_result["memory_id"] == first_result["memory_id"]
    assert followup_result["score"] >= 7
    assert any(
        reason.startswith("fts_overlap:")
        for reason in followup_result["reasons"]
    )

    assert cm5_first_result["action"] == "create"
    assert cm5_first_result["memory_id"] != first_result["memory_id"]
    assert cm5_followup_result["action"] == "update"
    assert cm5_followup_result["memory_id"] == cm5_first_result["memory_id"]

    assert later_result["action"] == "create_related"
    assert later_result["candidate_id"] == first_result["memory_id"]
    assert later_result["memory_id"] != first_result["memory_id"]
    assert "large_time_gap:block_update" in later_result["reasons"]

    assert store.count() == 3
    assert store.source_events(first_result["memory_id"]) == [
        EVENT_IDS[1],
        EVENT_IDS[2],
    ]
    assert store.source_events(cm5_first_result["memory_id"]) == [
        EVENT_IDS[3],
        EVENT_IDS[4],
    ]
    assert store.source_events(later_result["memory_id"]) == [EVENT_IDS[6]]

    relation = links.get_relation(later_result["relation_id"])
    assert relation["type"] == "related_to"
    assert relation["source_id"] == later_result["memory_id"]
    assert relation["target_id"] == first_result["memory_id"]

    sqlite_about = links.relations_for(
        "memory",
        first_result["memory_id"],
        direction="outgoing",
        relation_types={"about"},
    )
    assert len(sqlite_about) == 1
    assert sqlite_about[0]["target_id"] == ENTITY_SQLITE

    trace_text = "\n".join(trace.lines())
    assert "action=create" in trace_text
    assert "action=update" in trace_text
    assert "action=create_related" in trace_text
    assert "score=" in trace_text
    assert "reasons=" in trace_text


def test_entity_overlap_can_associate_without_shared_words(tmp_path):
    processor, event_log, store, links, _ = build_processor(tmp_path)
    links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        public_id=ENTITY_SQLITE,
    )

    first = write_event(
        event_log,
        EVENT_IDS[8],
        "conversation.user",
        "2026-10-26T13:00:00+00:00",
        session_id="session_00000001",
        text="Storage baseline",
        references=[{"kind": "entity", "id": ENTITY_SQLITE}],
    )
    second = write_event(
        event_log,
        EVENT_IDS[9],
        "conversation.user",
        "2026-10-26T13:05:00+00:00",
        session_id="session_00000001",
        text="Database choice",
        references=[{"kind": "entity", "id": ENTITY_SQLITE}],
    )

    first_result = processor.process_event(first)
    second_result = processor.process_event(second)

    assert first_result["action"] == "create"
    assert second_result["action"] == "update"
    assert second_result["memory_id"] == first_result["memory_id"]
    assert "entity_overlap:+1" in second_result["reasons"]
    assert store.count() == 1


def test_closed_memory_is_not_update_candidate(tmp_path):
    processor, event_log, store, _, _ = build_processor(tmp_path)
    source = write_event(
        event_log,
        EVENT_IDS[10],
        "conversation.user",
        "2026-10-26T14:00:00+00:00",
        session_id="session_00000001",
        text="Archive note",
    )
    closed = store.create_memory(
        memory_type="episodic",
        domain="user",
        content="Archive note",
        status="closed",
        importance=1,
        created_at=source.timestamp,
        source_event_id=source.event_id,
    )
    current = write_event(
        event_log,
        EVENT_IDS[11],
        "conversation.user",
        "2026-10-26T14:05:00+00:00",
        session_id="session_00000001",
        text="Archive note",
    )

    result = processor.process_event(current)

    assert result["action"] == "create"
    assert result["memory_id"] != closed["id"]
    assert store.count() == 2


def test_unknown_entity_reference_is_not_silently_accepted(tmp_path):
    processor, event_log, _, _, _ = build_processor(tmp_path)
    event = write_event(
        event_log,
        EVENT_IDS[12],
        "conversation.user",
        "2026-10-26T15:00:00+00:00",
        session_id="session_00000001",
        text="Unknown entity",
        references=[
            {
                "kind": "entity",
                "id": "ent_bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            }
        ],
    )

    with pytest.raises(ValueError, match="Unknown entity reference"):
        processor.process_event(event)
