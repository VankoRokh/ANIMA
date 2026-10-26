import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from tests.harness import AnimaTestHarness


T1 = "2026-10-26T12:00:00+00:00"
EVENT_1 = "ev_11111111-1111-4111-8111-111111111111"
EVENT_2 = "ev_22222222-2222-4222-8222-222222222222"
EVENT_3 = "ev_33333333-3333-4333-8333-333333333333"
EVENT_4 = "ev_44444444-4444-4444-8444-444444444444"
EVENT_MISSING = "ev_99999999-9999-4999-8999-999999999999"
MEMORY_1 = "mem_55555555-5555-4555-8555-555555555555"
ENTITY_1 = "ent_66666666-6666-4666-8666-666666666666"


def build_stack(tmp_path, *, fault_hook=None):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    links = LinkStore(store)
    processor = MemoryProcessor(
        memory_store=store,
        event_log=log,
        link_store=links,
    )
    coordinator = EventProcessingCoordinator(
        memory_store=store,
        memory_processor=processor,
        event_log=log,
        fault_hook=fault_hook,
    )
    return store, log, links, processor, coordinator


def user_event(event_id, text, *, references=None):
    return Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000001",
        references=references,
        event_id=event_id,
        timestamp=T1,
    )


def test_replaying_finalized_event_does_not_duplicate_memory(tmp_path):
    store, log, _, _, coordinator = build_stack(tmp_path)
    event = user_event(EVENT_1, "Idempotent SQLite memory event.")
    log.write(event)

    first = coordinator.process(event)
    replay = coordinator.process(event)

    assert first["action"] == "create"
    assert replay["action"] == "already_done"
    assert replay["memory_id"] == first["memory_id"]
    assert store.count() == 1

    record = coordinator.get(EVENT_1)
    assert record["status"] == "done"
    assert record["attempts"] == 1
    assert record["last_error"] is None


def test_skipped_event_is_final_and_idempotent(tmp_path):
    store, log, _, _, coordinator = build_stack(tmp_path)
    event = Event(
        "system.wake",
        source="runtime",
        session_id="session_00000001",
        event_id=EVENT_2,
        timestamp=T1,
    )
    log.write(event)

    first = coordinator.process(event)
    replay = coordinator.process(event)

    assert first["action"] == "skip"
    assert replay["action"] == "skip"
    assert store.count() == 0
    assert coordinator.get(EVENT_2)["status"] == "skipped"
    assert coordinator.get(EVENT_2)["attempts"] == 1


def test_fault_after_memory_effects_rolls_back_then_retries_once(tmp_path):
    def fail_after_effects(event, result, connection):
        raise RuntimeError("simulated crash before commit")

    store, log, links, _, coordinator = build_stack(
        tmp_path,
        fault_hook=fail_after_effects,
    )
    links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        public_id=ENTITY_1,
    )
    event = user_event(
        EVENT_1,
        "SQLite recovery transaction.",
        references=[{"kind": "entity", "id": ENTITY_1}],
    )
    log.write(event)

    with pytest.raises(RuntimeError, match="simulated crash"):
        coordinator.process(event)

    assert store.count() == 0
    with store.transaction() as connection:
        relation_count = connection.execute(
            "SELECT COUNT(*) AS count FROM relations"
        ).fetchone()["count"]
    assert relation_count == 0

    failed = coordinator.get(EVENT_1)
    assert failed["status"] == "failed"
    assert failed["attempts"] == 1
    assert "simulated crash" in failed["last_error"]

    coordinator.fault_hook = None
    result = coordinator.process(event)

    assert result["action"] == "create"
    assert store.count() == 1
    assert coordinator.get(EVENT_1)["status"] == "done"
    assert coordinator.get(EVENT_1)["attempts"] == 2

    about = links.relations_for(
        "memory",
        result["memory_id"],
        direction="outgoing",
        relation_types={"about"},
    )
    assert [relation["target_id"] for relation in about] == [ENTITY_1]


def test_recovery_retries_stale_processing_record(tmp_path):
    store, log, _, _, coordinator = build_stack(tmp_path)
    event = user_event(EVENT_3, "Recover stale processing event.")
    log.write(event)

    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO event_processing(
                event_id, processor, processor_version, status,
                attempts, started_at, finished_at, last_error
            ) VALUES (?, 'memory_processor', '1.0', 'processing', 1, ?, NULL, NULL)
            """,
            (EVENT_3, T1),
        )

    recovery = coordinator.recover()

    assert recovery["retried"] == 1
    assert store.count() == 1
    record = coordinator.get(EVENT_3)
    assert record["status"] == "done"
    assert record["attempts"] == 2


def test_recovery_adopts_legacy_event_without_reprocessing(tmp_path):
    store, log, _, _, coordinator = build_stack(tmp_path)
    event = user_event(EVENT_4, "Legacy already materialized event.")
    log.write(event)
    store.create_memory(
        memory_type="episodic",
        domain="user",
        content="Legacy already materialized event.",
        created_at=T1,
        public_id=MEMORY_1,
        source_event_id=EVENT_4,
    )

    recovery = coordinator.recover()

    assert recovery["adopted"] == 1
    assert recovery["retried"] == 0
    assert store.count() == 1
    record = coordinator.get(EVENT_4)
    assert record["status"] == "done"
    assert record["attempts"] == 0


def test_recovery_reports_processing_record_without_raw_event(tmp_path):
    store, _, _, _, coordinator = build_stack(tmp_path)
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO event_processing(
                event_id, processor, processor_version, status,
                attempts, started_at, finished_at, last_error
            ) VALUES (?, 'memory_processor', '1.0', 'pending', 0, NULL, NULL, NULL)
            """,
            (EVENT_MISSING,),
        )

    with pytest.raises(ValueError, match="Missing raw event"):
        coordinator.recover()

    record = coordinator.get(EVENT_MISSING)
    assert record["status"] == "failed"
    assert record["attempts"] == 1
    assert "Missing raw event" in record["last_error"]


def test_runtime_reconciles_state_after_commit_before_state_save(tmp_path):
    first = AnimaTestHarness(tmp_path)
    event = user_event(EVENT_1, "Committed before state counter update.")
    first.event_log.write(event)
    first.event_processing.process(event)

    assert first.state.get()["events_processed"] == 0
    assert first.memory_store.count() == 1

    restarted = AnimaTestHarness(tmp_path)
    restarted.runtime.wake()

    assert restarted.memory_store.count() == 1
    assert restarted.state.get()["events_processed"] == 2
    assert restarted.event_processing.finalized_count() == 2
