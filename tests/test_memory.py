import sqlite3

import pytest

from anima.memory.episodic import EpisodicMemory
from anima.memory.memory_store import MemoryStore


CREATED_AT = "2026-10-26T12:00:00+00:00"
EVENT_ID = "ev_11111111-1111-4111-8111-111111111111"
MEMORY_ID = "mem_22222222-2222-4222-8222-222222222222"


def create_test_memory(store, **overrides):
    values = {
        "memory_type": "episodic",
        "domain": "user",
        "content": "SQLite memory baseline",
        "status": "open",
        "importance": 1,
        "created_at": CREATED_AT,
        "public_id": MEMORY_ID,
        "source_event_id": EVENT_ID,
    }
    values.update(overrides)
    return store.create_memory(**values)


def test_memory_store_initializes_stage1_schema(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    snapshot = store.export_debug()

    assert snapshot["schema_version"] == 1
    assert snapshot["memory_count"] == 0

    expected_tables = {
        "memories",
        "memory_sources",
        "knowledge",
        "knowledge_sources",
        "entities",
        "entity_aliases",
        "memory_entities",
        "knowledge_entities",
        "relations",
        "history",
        "event_processing",
        "memory_fts",
        "knowledge_fts",
    }

    assert expected_tables <= set(snapshot["tables"])


def test_memory_store_crud_and_reader_view(tmp_path):
    database = tmp_path / "memory.db"
    store = MemoryStore(database)
    memory = EpisodicMemory(store)

    created = create_test_memory(store)

    assert created["id"] == MEMORY_ID
    assert created["content"] == "SQLite memory baseline"
    assert memory.count() == 1
    assert memory.load_memories() == [created]
    assert memory.last() == [created]
    assert store.source_events(MEMORY_ID) == [EVENT_ID]

    updated = store.update_memory(
        MEMORY_ID,
        content="SQLite memory baseline updated",
        importance=2,
        updated_at="2026-10-26T12:05:00+00:00",
    )

    assert updated["content"] == "SQLite memory baseline updated"
    assert updated["importance"] == 2

    assert store.delete_memory(MEMORY_ID) is True
    assert store.get_memory(MEMORY_ID) is None
    assert memory.count() == 0


def test_memory_store_reopens_existing_database(tmp_path):
    database = tmp_path / "memory.db"
    first = MemoryStore(database)
    create_test_memory(first)

    reopened = MemoryStore(database)

    assert reopened.schema_version() == 1
    assert reopened.count() == 1
    assert reopened.get_memory(MEMORY_ID)["content"] == "SQLite memory baseline"
    assert reopened.source_events(MEMORY_ID) == [EVENT_ID]


def test_memory_store_rolls_back_transaction(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    with pytest.raises(RuntimeError, match="rollback test"):
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO memories(
                    public_id, type, domain, status, content, importance,
                    created_at, updated_at, closed_at, merged_into
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    MEMORY_ID,
                    "episodic",
                    "user",
                    "open",
                    "must roll back",
                    1,
                    CREATED_AT,
                    CREATED_AT,
                ),
            )
            raise RuntimeError("rollback test")

    assert store.count() == 0
    assert store.search_memories("rollback") == []


def test_memory_store_enforces_constraints(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    create_test_memory(store)

    with pytest.raises(ValueError, match="Cannot create memory"):
        create_test_memory(store)

    with pytest.raises(ValueError, match="importance"):
        store.create_memory(
            memory_type="episodic",
            domain="user",
            content="invalid importance",
            importance=9,
            created_at=CREATED_AT,
        )

    with pytest.raises(ValueError, match="UTC offset"):
        store.create_memory(
            memory_type="episodic",
            domain="user",
            content="invalid time",
            created_at="2026-10-26T12:00:00",
        )

    with pytest.raises(ValueError, match="Invalid memory record fields"):
        store.write({"type": "episodic"})


def test_memory_fts_tracks_create_update_delete(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    create_test_memory(store)

    found = store.search_memories("SQLite")
    assert [item["id"] for item in found] == [MEMORY_ID]

    store.update_memory(
        MEMORY_ID,
        content="PostgreSQL comparison",
        updated_at="2026-10-26T12:05:00+00:00",
    )

    assert store.search_memories("SQLite") == []
    assert [
        item["id"]
        for item in store.search_memories("PostgreSQL")
    ] == [MEMORY_ID]

    store.delete_memory(MEMORY_ID)
    assert store.search_memories("PostgreSQL") == []


def test_memory_database_reports_invalid_file(tmp_path):
    database = tmp_path / "memory.db"
    database.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="Cannot initialize memory database",
    ):
        MemoryStore(database)


def test_sqlite_foreign_keys_are_enabled(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO memory_sources(memory_id, event_id) VALUES (?, ?)",
                (MEMORY_ID, EVENT_ID),
            )
