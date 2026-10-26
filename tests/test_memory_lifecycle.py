import pytest

from anima.core.event_bus import Event
from anima.memory.composer import RuleBasedComposer
from anima.memory.event_log import EventLog
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver


TIME_1 = "2026-10-26T12:00:00+00:00"
TIME_2 = "2026-10-26T12:10:00+00:00"
TIME_3 = "2026-10-26T12:20:00+00:00"
EVENT_1 = "ev_11111111-1111-4111-8111-111111111111"
EVENT_2 = "ev_22222222-2222-4222-8222-222222222222"
MEMORY_1 = "mem_33333333-3333-4333-8333-333333333333"
MEMORY_2 = "mem_44444444-4444-4444-8444-444444444444"
MEMORY_3 = "mem_55555555-5555-4555-8555-555555555555"
ENTITY_SQLITE = "ent_77777777-7777-4777-8777-777777777777"


def create_event(log, event_id, text, timestamp):
    event = Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000001",
        event_id=event_id,
        timestamp=timestamp,
    )
    log.write(event)
    return event


def create_memory(
    store,
    public_id,
    event_id,
    content,
    timestamp,
    *,
    status="open",
    memory_type="episodic",
    domain="project",
):
    return store.create_memory(
        memory_type=memory_type,
        domain=domain,
        content=content,
        status=status,
        importance=1,
        created_at=timestamp,
        public_id=public_id,
        source_event_id=event_id,
    )


def test_close_transitions_open_to_closed_and_records_history(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    lifecycle = MemoryLifecycle(memory_store=store)
    create_memory(
        store,
        MEMORY_1,
        EVENT_1,
        "SQLite episode",
        TIME_1,
    )

    closed = lifecycle.close(
        MEMORY_1,
        closed_at=TIME_2,
        source_kind="event",
        source_id=EVENT_2,
    )

    assert closed["status"] == "closed"
    assert closed["closed_at"] == TIME_2
    assert closed["updated_at"] == TIME_2
    assert closed["merged_into"] is None

    history = lifecycle.history(MEMORY_1)
    assert history == [
        {
            "operation": "close",
            "timestamp": TIME_2,
            "source_kind": "event",
            "source_id": EVENT_2,
            "changes": {
                "closed_at": [None, TIME_2],
                "status": ["open", "closed"],
            },
        }
    ]

    with pytest.raises(ValueError, match="Only OPEN memory"):
        lifecycle.close(MEMORY_1, closed_at=TIME_3)


def test_merge_preserves_source_record_and_raw_event_provenance(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    lifecycle = MemoryLifecycle(
        memory_store=store,
        composer=RuleBasedComposer(max_chars=256),
    )
    provenance = ProvenanceResolver(store, links, event_log)

    create_event(event_log, EVENT_1, "Decision: use SQLite.", TIME_1)
    create_event(
        event_log,
        EVENT_2,
        "Constraint: keep storage local.",
        TIME_2,
    )
    target = create_memory(
        store,
        MEMORY_1,
        EVENT_1,
        "Decision: use SQLite.",
        TIME_1,
    )
    source = create_memory(
        store,
        MEMORY_2,
        EVENT_2,
        "Constraint: keep storage local.",
        TIME_2,
    )
    links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        public_id=ENTITY_SQLITE,
    )
    links.create_relation(
        source_kind="memory",
        source_id=MEMORY_2,
        relation_type="about",
        target_kind="entity",
        target_id=ENTITY_SQLITE,
        created_at=TIME_2,
    )

    result = lifecycle.merge(
        MEMORY_2,
        MEMORY_1,
        merged_at=TIME_3,
    )

    merged_source = result["source"]
    merged_target = result["target"]

    assert target["content"] == "Decision: use SQLite."
    assert source["content"] == "Constraint: keep storage local."
    assert merged_source["content"] == source["content"]
    assert merged_source["status"] == "merged"
    assert merged_source["merged_into"] == MEMORY_1
    assert merged_source["closed_at"] == TIME_3

    assert merged_target["status"] == "open"
    assert "Decision: use SQLite." in merged_target["content"]
    assert "Constraint: keep storage local." in merged_target["content"]
    assert set(store.source_events(MEMORY_1)) == {EVENT_1, EVENT_2}
    assert store.source_events(MEMORY_2) == [EVENT_2]
    assert result["source_events_added"] == [EVENT_2]
    assert result["entity_links_added"] == [ENTITY_SQLITE]

    target_about = links.relations_for(
        "memory",
        MEMORY_1,
        direction="outgoing",
        relation_types={"about"},
    )
    source_about = links.relations_for(
        "memory",
        MEMORY_2,
        direction="outgoing",
        relation_types={"about"},
    )
    assert [relation["target_id"] for relation in target_about] == [ENTITY_SQLITE]
    assert [relation["target_id"] for relation in source_about] == [ENTITY_SQLITE]

    target_provenance = provenance.memory(MEMORY_1)
    assert {
        event["id"] for event in target_provenance["events"]
    } == {EVENT_1, EVENT_2}
    source_provenance = provenance.memory(MEMORY_2)
    assert [event["id"] for event in source_provenance["events"]] == [EVENT_2]

    target_history = lifecycle.history(MEMORY_1)
    assert target_history[-1]["operation"] == "merge_target"
    assert target_history[-1]["source_id"] == MEMORY_2
    assert target_history[-1]["changes"]["content_before"] == target["content"]
    assert target_history[-1]["changes"]["content_after"] == merged_target["content"]
    assert target_history[-1]["changes"]["source_events_added"] == [EVENT_2]
    assert target_history[-1]["changes"]["entity_links_added"] == [ENTITY_SQLITE]

    source_history = lifecycle.history(MEMORY_2)
    assert source_history[-1]["operation"] == "merged"
    assert source_history[-1]["source_id"] == MEMORY_1
    assert source_history[-1]["changes"]["status"] == ["open", "merged"]
    assert source_history[-1]["changes"]["merged_into"] == [None, MEMORY_1]


def test_merge_keeps_existing_closed_at_on_closed_source(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    lifecycle = MemoryLifecycle(memory_store=store)

    create_memory(
        store,
        MEMORY_1,
        EVENT_1,
        "Target episode",
        TIME_1,
    )
    create_memory(
        store,
        MEMORY_2,
        EVENT_2,
        "Source episode",
        TIME_1,
    )
    lifecycle.close(MEMORY_2, closed_at=TIME_2)

    result = lifecycle.merge(MEMORY_2, MEMORY_1, merged_at=TIME_3)

    assert result["source"]["status"] == "merged"
    assert result["source"]["closed_at"] == TIME_2
    assert lifecycle.history(MEMORY_2)[-1]["changes"]["closed_at"] == [
        TIME_2,
        TIME_2,
    ]


def test_merge_rejects_invalid_transitions_without_mutation(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    lifecycle = MemoryLifecycle(memory_store=store)

    create_memory(
        store,
        MEMORY_1,
        EVENT_1,
        "Target",
        TIME_1,
    )
    create_memory(
        store,
        MEMORY_2,
        EVENT_2,
        "Source",
        TIME_1,
    )

    with pytest.raises(ValueError, match="itself"):
        lifecycle.merge(MEMORY_1, MEMORY_1, merged_at=TIME_2)

    lifecycle.close(MEMORY_1, closed_at=TIME_2)
    before_source = store.get_memory(MEMORY_2)

    with pytest.raises(ValueError, match="target must be OPEN"):
        lifecycle.merge(MEMORY_2, MEMORY_1, merged_at=TIME_3)

    assert store.get_memory(MEMORY_2) == before_source
    assert store.source_events(MEMORY_2) == [EVENT_2]


def test_merge_rejects_different_type_or_domain(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    lifecycle = MemoryLifecycle(memory_store=store)

    create_memory(
        store,
        MEMORY_1,
        EVENT_1,
        "Target",
        TIME_1,
    )
    create_memory(
        store,
        MEMORY_2,
        EVENT_2,
        "Different type",
        TIME_1,
        memory_type="procedural",
    )

    with pytest.raises(ValueError, match="different types"):
        lifecycle.merge(MEMORY_2, MEMORY_1, merged_at=TIME_2)

    create_memory(
        store,
        MEMORY_3,
        "ev_66666666-6666-4666-8666-666666666666",
        "Different domain",
        TIME_1,
        domain="system",
    )

    with pytest.raises(ValueError, match="different domains"):
        lifecycle.merge(MEMORY_3, MEMORY_1, merged_at=TIME_2)


def test_lifecycle_rejects_timestamps_before_last_memory_change(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    lifecycle = MemoryLifecycle(memory_store=store)

    create_memory(
        store,
        MEMORY_1,
        EVENT_1,
        "Target",
        TIME_2,
    )
    create_memory(
        store,
        MEMORY_2,
        EVENT_2,
        "Source",
        TIME_2,
    )

    with pytest.raises(ValueError, match="closed_at cannot be earlier"):
        lifecycle.close(MEMORY_1, closed_at=TIME_1)

    with pytest.raises(ValueError, match="merged_at cannot be earlier"):
        lifecycle.merge(MEMORY_2, MEMORY_1, merged_at=TIME_1)

    assert store.get_memory(MEMORY_1)["status"] == "open"
    assert store.get_memory(MEMORY_2)["status"] == "open"
