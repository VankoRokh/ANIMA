import sqlite3
from uuid import uuid4

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.memory_store import MemoryStore
from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.store import SleepStore


def _source_fixture(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    memory_store = MemoryStore(tmp_path / "memory.db")
    knowledge_layer = KnowledgeLayer(memory_store=memory_store)

    event = Event(
        "conversation.user",
        {"text": "Stage 3 source contract"},
        source="test",
        session_id="sleep-contract",
    )
    event_log.write(event)

    memory = memory_store.create_memory(
        memory_type="episodic",
        domain="project",
        content="Stage 3 source contract memory",
        status="closed",
        source_event_id=event.event_id,
    )
    knowledge = knowledge_layer.create_candidate(
        domain="project",
        statement="Sleep uses references instead of copied source payloads.",
        source_memory_id=memory["id"],
    )
    knowledge_layer.confirm(knowledge["knowledge"]["id"])

    asset_id = f"asset_{uuid4()}"
    assets = {asset_id}

    registry = SourceRegistry()
    registry.register(
        "event",
        lambda source_id: any(
            record["id"] == source_id
            for record in event_log.load_events()
        ),
    )
    registry.register(
        "memory",
        lambda source_id: memory_store.get_memory(source_id) is not None,
    )
    registry.register(
        "knowledge",
        lambda source_id: knowledge_layer.get(source_id) is not None,
    )
    registry.register("asset", lambda source_id: source_id in assets)

    return {
        "event": event.event_id,
        "memory": memory["id"],
        "knowledge": knowledge["knowledge"]["id"],
        "asset": asset_id,
        "registry": registry,
    }


def test_source_ref_validates_supported_kinds_and_id_prefixes():
    refs = [
        SourceRef("event", f"ev_{uuid4()}"),
        SourceRef("memory", f"mem_{uuid4()}"),
        SourceRef("knowledge", f"kn_{uuid4()}"),
        SourceRef("asset", f"asset_{uuid4()}"),
    ]

    assert [ref.kind for ref in refs] == [
        "event",
        "memory",
        "knowledge",
        "asset",
    ]
    assert SourceRef.from_dict(refs[0].to_dict()) == refs[0]

    with pytest.raises(ValueError, match="Unsupported source kind"):
        SourceRef("video", f"asset_{uuid4()}")

    with pytest.raises(ValueError, match="event source_id"):
        SourceRef("event", f"mem_{uuid4()}")

    with pytest.raises(ValueError, match="fields must be exactly"):
        SourceRef.from_dict(
            {
                "kind": "event",
                "id": f"ev_{uuid4()}",
                "payload": "must not be embedded",
            }
        )


def test_event_memory_knowledge_and_asset_use_one_source_contract(tmp_path):
    fixture = _source_fixture(tmp_path)
    registry = fixture["registry"]
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()

    refs = [
        SourceRef(kind, fixture[kind])
        for kind in ("event", "memory", "knowledge", "asset")
    ]

    assert all(registry.contains(ref) for ref in refs)
    assert [registry.require(ref) for ref in refs] == refs

    items = []
    for priority, ref in enumerate(refs):
        item = WorkItem.create(
            job_id=job["id"],
            source_ref=ref,
            processor="contract-test",
            processor_version="1",
            priority=priority,
        )
        items.append(store.create_work_item(item, source_registry=registry))

    assert items == store.list_work_items(job_id=job["id"])
    assert [item.source_ref for item in items] == refs


def test_source_registry_reports_dangling_and_unregistered_sources(tmp_path):
    fixture = _source_fixture(tmp_path)
    registry = fixture["registry"]

    dangling = SourceRef("event", f"ev_{uuid4()}")
    with pytest.raises(ValueError, match="Dangling source"):
        registry.require(dangling)

    incomplete = SourceRegistry()
    asset = SourceRef("asset", fixture["asset"])
    with pytest.raises(ValueError, match="No source resolver registered"):
        incomplete.require(asset)


def test_source_registry_requires_boolean_exists_result():
    registry = SourceRegistry().register("asset", lambda source_id: {"id": source_id})
    source = SourceRef("asset", f"asset_{uuid4()}")

    with pytest.raises(ValueError, match="must return bool"):
        registry.contains(source)


def test_work_item_contract_contains_metadata_without_payload():
    source = SourceRef("asset", f"asset_{uuid4()}")
    work_item = WorkItem.create(
        job_id=f"sj_{uuid4()}",
        source_ref=source,
        processor="deterministic-text",
        processor_version="1",
        priority=7,
        cost_hint="expensive",
        checkpoint_ref="checkpoint:42",
    )

    record = work_item.to_dict()

    assert record["id"].startswith("wi_")
    assert record["work_kind"] == "CONSOLIDATE"
    assert record["source"] == source.to_dict()
    assert record["processor"] == "deterministic-text"
    assert record["processor_version"] == "1"
    assert record["priority"] == 7
    assert record["cost_hint"] == "expensive"
    assert record["status"] == "queued"
    assert record["attempts"] == 0
    assert record["checkpoint_ref"] == "checkpoint:42"
    assert "payload" not in record
    assert set(record["source"]) == {"kind", "id"}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("work_kind", "REFLECT", "Unsupported work kind"),
        ("processor", "", "processor must be a non-empty string"),
        ("processor_version", "", "processor_version must be a non-empty string"),
        ("priority", -1, "priority must be a non-negative integer"),
        ("priority", True, "priority must be a non-negative integer"),
        ("cost_hint", "huge", "Unknown WorkItem cost_hint"),
        ("status", "interrupted", "Unknown WorkItem status"),
        ("attempts", -1, "attempts must be a non-negative integer"),
        ("checkpoint_ref", "", "checkpoint_ref must be a non-empty string"),
    ],
)
def test_work_item_rejects_invalid_contract_fields(field, value, message):
    kwargs = {
        "job_id": f"sj_{uuid4()}",
        "source_ref": SourceRef("event", f"ev_{uuid4()}"),
        "processor": "processor",
        "processor_version": "1",
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        WorkItem.create(**kwargs)


def test_sleep_store_persists_work_items_without_source_payload(tmp_path):
    database = tmp_path / "sleep.db"
    store = SleepStore(database)
    job = store.create_job()

    asset_id = f"asset_{uuid4()}"
    marker = "PAYLOAD_MUST_STAY_OUTSIDE_SLEEP_DB_"
    external_asset = marker + ("x" * 1_000_000)
    assets = {asset_id: external_asset}
    registry = SourceRegistry().register(
        "asset",
        lambda source_id: source_id in assets,
    )

    item = WorkItem.create(
        job_id=job["id"],
        source_ref=SourceRef("asset", asset_id),
        processor="synthetic-asset",
        processor_version="1",
        priority=3,
        cost_hint="expensive",
    )
    stored = store.create_work_item(item, source_registry=registry)

    assert stored == item
    assert store.get_work_item(item.public_id) == item
    assert store.list_work_items(job_id=job["id"]) == [item]

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(work_items)").fetchall()
        }
    assert "payload" not in columns
    assert "content" not in columns
    assert marker.encode("utf-8") not in database.read_bytes()


def test_sleep_store_rejects_dangling_source_before_insert(tmp_path):
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    registry = SourceRegistry().register("event", lambda source_id: False)
    item = WorkItem.create(
        job_id=job["id"],
        source_ref=SourceRef("event", f"ev_{uuid4()}"),
        processor="test",
        processor_version="1",
    )

    with pytest.raises(ValueError, match="Dangling source"):
        store.create_work_item(item, source_registry=registry)

    assert store.list_work_items(job_id=job["id"]) == []


def test_sleep_store_rejects_unknown_job_for_valid_source(tmp_path):
    store = SleepStore(tmp_path / "sleep.db")
    source_id = f"asset_{uuid4()}"
    registry = SourceRegistry().register(
        "asset",
        lambda candidate: candidate == source_id,
    )
    item = WorkItem.create(
        job_id=f"sj_{uuid4()}",
        source_ref=SourceRef("asset", source_id),
        processor="test",
        processor_version="1",
    )

    with pytest.raises(ValueError, match="Unknown SleepJob"):
        store.create_work_item(item, source_registry=registry)


def test_sleep_store_migrates_v1_database_without_losing_job(tmp_path):
    database = tmp_path / "sleep.db"
    job_id = f"sj_{uuid4()}"
    timestamp = "2026-10-27T12:00:00+00:00"

    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE sleep_jobs (
                row_id INTEGER PRIMARY KEY,
                public_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '1')"
        )
        connection.execute(
            """
            INSERT INTO sleep_jobs(public_id, status, created_at, updated_at)
            VALUES (?, 'checkpointed', ?, ?)
            """,
            (job_id, timestamp, timestamp),
        )

    store = SleepStore(database)

    assert store.schema_version() == 2
    assert store.get_job(job_id)["status"] == "checkpointed"
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "work_items" in tables
