import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver


CREATED_AT = "2026-10-26T12:00:00+00:00"
EVENT_1 = "ev_11111111-1111-4111-8111-111111111111"
EVENT_2 = "ev_22222222-2222-4222-8222-222222222222"
EVENT_MISSING = "ev_99999999-9999-4999-8999-999999999999"
MEMORY_1 = "mem_33333333-3333-4333-8333-333333333333"
MEMORY_2 = "mem_44444444-4444-4444-8444-444444444444"
KNOWLEDGE_1 = "kn_55555555-5555-4555-8555-555555555555"
ENTITY_1 = "ent_66666666-6666-4666-8666-666666666666"
ENTITY_2 = "ent_77777777-7777-4777-8777-777777777777"
RELATION_1 = "rel_88888888-8888-4888-8888-888888888888"


def create_event(log, event_id, text):
    event = Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000001",
        event_id=event_id,
        timestamp=CREATED_AT,
    )
    log.write(event)
    return event


def create_memory(store, public_id, event_id, content):
    return store.create_memory(
        memory_type="episodic",
        domain="project",
        content=content,
        status="closed",
        importance=1,
        created_at=CREATED_AT,
        public_id=public_id,
        source_event_id=event_id,
    )


def test_entity_alias_resolution_is_conservative(tmp_path):
    memory_store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(memory_store)

    entity = links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        aliases=["SQLite3", " sqlite "],
        public_id=ENTITY_1,
    )

    assert entity["canonical_name"] == "SQLite"
    assert entity["aliases"] == ["SQLite3"]
    assert links.resolve_entity("SQLite")["id"] == ENTITY_1
    assert links.resolve_entity("SQLITE3")["id"] == ENTITY_1
    assert links.resolve_entity("  sqlite  ")["id"] == ENTITY_1
    assert links.resolve_entity("PostgreSQL") is None

    links.create_entity(
        entity_type="concept",
        canonical_name="Database",
        aliases=["db"],
        public_id=ENTITY_2,
    )
    links.add_entity_alias(ENTITY_1, "db")

    with pytest.raises(ValueError, match="Ambiguous entity name"):
        links.resolve_entity("db")


def test_relations_validate_direction_and_provenance(tmp_path):
    memory_store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(memory_store)

    create_memory(
        memory_store,
        MEMORY_1,
        EVENT_1,
        "SQLite was selected as the baseline.",
    )
    links.create_knowledge(
        domain="project",
        statement="SQLite is the Stage 1 baseline.",
        status="confirmed",
        created_at=CREATED_AT,
        public_id=KNOWLEDGE_1,
    )
    links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        public_id=ENTITY_1,
    )

    about = links.create_relation(
        source_kind="memory",
        source_id=MEMORY_1,
        relation_type="about",
        target_kind="entity",
        target_id=ENTITY_1,
        created_at=CREATED_AT,
        public_id=RELATION_1,
    )

    assert about["source_memory_id"] == MEMORY_1

    support = links.create_relation(
        source_kind="memory",
        source_id=MEMORY_1,
        relation_type="supports",
        target_kind="knowledge",
        target_id=KNOWLEDGE_1,
        created_at=CREATED_AT,
    )

    incoming = links.relations_for(
        "knowledge",
        KNOWLEDGE_1,
        direction="incoming",
    )
    assert [item["id"] for item in incoming] == [support["id"]]

    with pytest.raises(ValueError, match="does not allow"):
        links.create_relation(
            source_kind="knowledge",
            source_id=KNOWLEDGE_1,
            relation_type="continues",
            target_kind="entity",
            target_id=ENTITY_1,
            source_memory_id=MEMORY_1,
        )

    with pytest.raises(ValueError, match="Unknown entity"):
        links.create_relation(
            source_kind="memory",
            source_id=MEMORY_1,
            relation_type="about",
            target_kind="entity",
            target_id="ent_99999999-9999-4999-8999-999999999999",
        )

    with pytest.raises(ValueError, match="Equivalent relation"):
        links.create_relation(
            source_kind="memory",
            source_id=MEMORY_1,
            relation_type="about",
            target_kind="entity",
            target_id=ENTITY_1,
            created_at=CREATED_AT,
        )


def test_provenance_resolves_knowledge_entity_and_relation_to_events(tmp_path):
    database = tmp_path / "memory.db"
    event_file = tmp_path / "events.jsonl"
    memory_store = MemoryStore(database)
    links = LinkStore(memory_store)
    event_log = EventLog(event_file)
    provenance = ProvenanceResolver(
        memory_store,
        links,
        event_log,
    )

    create_event(event_log, EVENT_1, "Choose SQLite for Stage 1.")
    create_event(event_log, EVENT_2, "A later test found a limitation.")

    create_memory(
        memory_store,
        MEMORY_1,
        EVENT_1,
        "SQLite was selected as the Stage 1 baseline.",
    )
    create_memory(
        memory_store,
        MEMORY_2,
        EVENT_2,
        "A later test found a SQLite limitation.",
    )

    links.create_knowledge(
        domain="project",
        statement="SQLite is the Stage 1 baseline.",
        status="challenged",
        created_at=CREATED_AT,
        public_id=KNOWLEDGE_1,
    )
    links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        aliases=["SQLite3"],
        public_id=ENTITY_1,
    )

    support = links.create_relation(
        source_kind="memory",
        source_id=MEMORY_1,
        relation_type="supports",
        target_kind="knowledge",
        target_id=KNOWLEDGE_1,
        created_at=CREATED_AT,
    )
    contradiction = links.create_relation(
        source_kind="memory",
        source_id=MEMORY_2,
        relation_type="contradicts",
        target_kind="knowledge",
        target_id=KNOWLEDGE_1,
        created_at=CREATED_AT,
    )
    about_memory = links.create_relation(
        source_kind="memory",
        source_id=MEMORY_1,
        relation_type="about",
        target_kind="entity",
        target_id=ENTITY_1,
        created_at=CREATED_AT,
        public_id=RELATION_1,
    )
    links.create_relation(
        source_kind="knowledge",
        source_id=KNOWLEDGE_1,
        relation_type="about",
        target_kind="entity",
        target_id=ENTITY_1,
        source_memory_id=MEMORY_2,
        created_at=CREATED_AT,
    )

    memory_result = provenance.memory(MEMORY_1)
    assert [event["id"] for event in memory_result["events"]] == [EVENT_1]

    knowledge_result = provenance.knowledge(KNOWLEDGE_1)
    assert {
        item["relation"]["type"]
        for item in knowledge_result["sources"]
    } == {"supports", "contradicts"}
    assert {
        event["id"]
        for item in knowledge_result["sources"]
        for event in item["events"]
    } == {EVENT_1, EVENT_2}
    assert {
        item["relation"]["id"]
        for item in knowledge_result["sources"]
    } == {support["id"], contradiction["id"]}

    relation_result = provenance.relation(about_memory["id"])
    assert relation_result["source_memory"]["id"] == MEMORY_1
    assert [event["id"] for event in relation_result["events"]] == [EVENT_1]

    entity_result = provenance.entity(ENTITY_1)
    assert {
        item["source_memory"]["id"]
        for item in entity_result["sources"]
    } == {MEMORY_1, MEMORY_2}
    assert {
        event["id"]
        for item in entity_result["sources"]
        for event in item["events"]
    } == {EVENT_1, EVENT_2}


def test_provenance_reports_missing_raw_event(tmp_path):
    memory_store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(memory_store)
    event_log = EventLog(tmp_path / "events.jsonl")
    provenance = ProvenanceResolver(
        memory_store,
        links,
        event_log,
    )

    create_memory(
        memory_store,
        MEMORY_1,
        EVENT_MISSING,
        "Memory with unavailable raw source.",
    )

    with pytest.raises(ValueError, match="Missing source event"):
        provenance.memory(MEMORY_1)
