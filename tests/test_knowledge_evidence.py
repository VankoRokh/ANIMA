import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.memory_store import MemoryStore


T1 = "2026-10-26T14:00:00+00:00"
T2 = "2026-10-26T14:10:00+00:00"
T3 = "2026-10-26T14:20:00+00:00"
T4 = "2026-10-26T14:30:00+00:00"
T5 = "2026-10-26T14:40:00+00:00"
T6 = "2026-10-26T14:50:00+00:00"

EVENT_1 = "ev_aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
EVENT_2 = "ev_bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
MEMORY_1 = "mem_aaaaaaaa-aaaa-4111-8111-aaaaaaaaaaaa"
MEMORY_2 = "mem_bbbbbbbb-bbbb-4222-8222-bbbbbbbbbbbb"
KNOWLEDGE_1 = "kn_cccccccc-cccc-4333-8333-cccccccccccc"
KNOWLEDGE_2 = "kn_dddddddd-dddd-4444-8444-dddddddddddd"


def add_memory(store, log, lifecycle, memory_id, event_id, text, created_at, closed_at):
    event = Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000001",
        event_id=event_id,
        timestamp=created_at,
    )
    log.write(event)
    store.create_memory(
        memory_type="episodic",
        domain="project",
        content=text,
        status="open",
        importance=1,
        created_at=created_at,
        public_id=memory_id,
        source_event_id=event_id,
    )
    lifecycle.close(memory_id, closed_at=closed_at)


def build_confirmed(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    lifecycle = MemoryLifecycle(memory_store=store)
    layer = KnowledgeLayer(memory_store=store)
    add_memory(
        store,
        log,
        lifecycle,
        MEMORY_1,
        EVENT_1,
        "Decision: baseline is valid.",
        T1,
        T2,
    )
    layer.create_candidate(
        domain="project",
        statement="Baseline is valid.",
        source_memory_id=MEMORY_1,
        created_at=T3,
        public_id=KNOWLEDGE_1,
    )
    layer.confirm(KNOWLEDGE_1, confirmed_at=T4)
    return store, log, lifecycle, layer


def test_same_memory_cannot_support_and_contradict_one_knowledge(tmp_path):
    _, _, _, layer = build_confirmed(tmp_path)

    with pytest.raises(ValueError, match="both support and contradict"):
        layer.challenge(KNOWLEDGE_1, MEMORY_1, challenged_at=T5)

    assert layer.get(KNOWLEDGE_1)["status"] == "confirmed"


def test_confirmed_cannot_skip_challenged_state(tmp_path):
    store, log, lifecycle, layer = build_confirmed(tmp_path)
    add_memory(
        store,
        log,
        lifecycle,
        MEMORY_2,
        EVENT_2,
        "Decision: replacement baseline.",
        T2,
        T5,
    )

    with pytest.raises(ValueError, match="Only challenged knowledge"):
        layer.reject(KNOWLEDGE_1, rejected_at=T6)

    with pytest.raises(ValueError, match="Only challenged knowledge"):
        layer.supersede(
            KNOWLEDGE_1,
            statement="Replacement baseline is valid.",
            source_memory_id=MEMORY_2,
            superseded_at=T6,
            public_id=KNOWLEDGE_2,
        )

    assert layer.get(KNOWLEDGE_1)["status"] == "confirmed"


def test_terminal_knowledge_cannot_open_new_investigation(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    lifecycle = MemoryLifecycle(memory_store=store)
    layer = KnowledgeLayer(memory_store=store)

    add_memory(
        store,
        log,
        lifecycle,
        MEMORY_1,
        EVENT_1,
        "Decision: assumption is valid.",
        T1,
        T2,
    )
    add_memory(
        store,
        log,
        lifecycle,
        MEMORY_2,
        EVENT_2,
        "Result: assumption is false.",
        T1,
        T2,
    )
    layer.create_candidate(
        domain="project",
        statement="Assumption is valid.",
        source_memory_id=MEMORY_1,
        created_at=T3,
        public_id=KNOWLEDGE_1,
    )
    layer.confirm(KNOWLEDGE_1, confirmed_at=T4)
    layer.challenge(KNOWLEDGE_1, MEMORY_2, challenged_at=T5)
    layer.reject(KNOWLEDGE_1, rejected_at=T6)

    with pytest.raises(ValueError, match="Terminal knowledge"):
        layer.investigate(
            KNOWLEDGE_1,
            MEMORY_2,
            created_at="2026-10-26T15:00:00+00:00",
        )
