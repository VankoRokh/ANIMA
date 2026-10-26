import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver


T1 = "2026-10-26T12:00:00+00:00"
T2 = "2026-10-26T12:10:00+00:00"
T3 = "2026-10-26T12:20:00+00:00"
T4 = "2026-10-26T12:30:00+00:00"
T5 = "2026-10-26T12:40:00+00:00"
T6 = "2026-10-26T12:50:00+00:00"
T7 = "2026-10-26T13:00:00+00:00"
T8 = "2026-10-26T13:10:00+00:00"

EVENT_1 = "ev_11111111-1111-4111-8111-111111111111"
EVENT_2 = "ev_22222222-2222-4222-8222-222222222222"
EVENT_3 = "ev_33333333-3333-4333-8333-333333333333"
EVENT_4 = "ev_44444444-4444-4444-8444-444444444444"

MEMORY_1 = "mem_11111111-aaaa-4111-8111-111111111111"
MEMORY_2 = "mem_22222222-bbbb-4222-8222-222222222222"
MEMORY_3 = "mem_33333333-cccc-4333-8333-333333333333"
MEMORY_4 = "mem_44444444-dddd-4444-8444-444444444444"

KNOWLEDGE_1 = "kn_55555555-eeee-4555-8555-555555555555"
KNOWLEDGE_2 = "kn_66666666-ffff-4666-8666-666666666666"


def build_stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    event_log = EventLog(tmp_path / "events.jsonl")
    lifecycle = MemoryLifecycle(memory_store=store)
    knowledge = KnowledgeLayer(memory_store=store)
    links = LinkStore(store)
    provenance = ProvenanceResolver(store, links, event_log)
    return store, event_log, lifecycle, knowledge, provenance


def create_memory(
    store,
    event_log,
    lifecycle,
    *,
    memory_id,
    event_id,
    text,
    created_at,
    closed_at=None,
):
    event = Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000001",
        event_id=event_id,
        timestamp=created_at,
    )
    event_log.write(event)
    memory = store.create_memory(
        memory_type="episodic",
        domain="project",
        content=text,
        status="open",
        importance=1,
        created_at=created_at,
        public_id=memory_id,
        source_event_id=event_id,
    )
    if closed_at is not None:
        memory = lifecycle.close(memory_id, closed_at=closed_at)
    return memory


def test_knowledge_candidate_requires_closed_memory_and_keeps_provenance(tmp_path):
    store, event_log, lifecycle, layer, provenance = build_stack(tmp_path)
    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_1,
        event_id=EVENT_1,
        text="Decision: SQLite is the Stage 1 storage baseline.",
        created_at=T1,
    )

    with pytest.raises(ValueError, match="must be CLOSED memory"):
        layer.create_candidate(
            domain="project",
            statement="SQLite is the Stage 1 storage baseline.",
            source_memory_id=MEMORY_1,
            created_at=T2,
            public_id=KNOWLEDGE_1,
        )

    lifecycle.close(MEMORY_1, closed_at=T2)
    result = layer.create_candidate(
        domain="project",
        statement="SQLite is the Stage 1 storage baseline.",
        source_memory_id=MEMORY_1,
        created_at=T3,
        public_id=KNOWLEDGE_1,
    )

    assert result["knowledge"]["status"] == "provisional"
    assert result["supporting_sources"] == [MEMORY_1]
    assert result["contradicting_sources"] == []
    assert result["open_challenges"] is False

    resolved = provenance.knowledge(KNOWLEDGE_1)
    assert [
        event["id"]
        for source in resolved["sources"]
        for event in source["events"]
    ] == [EVENT_1]

    history = layer.history(KNOWLEDGE_1)
    assert history[0]["operation"] == "create"
    assert history[0]["changes"]["status"] == [None, "provisional"]


def test_investigation_does_not_challenge_but_closed_contradiction_does(tmp_path):
    store, event_log, lifecycle, layer, _ = build_stack(tmp_path)
    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_1,
        event_id=EVENT_1,
        text="Decision: SQLite is the baseline.",
        created_at=T1,
        closed_at=T2,
    )
    layer.create_candidate(
        domain="project",
        statement="SQLite is the baseline.",
        source_memory_id=MEMORY_1,
        created_at=T3,
        public_id=KNOWLEDGE_1,
    )
    confirmed = layer.confirm(KNOWLEDGE_1, confirmed_at=T4)
    assert confirmed["knowledge"]["status"] == "confirmed"

    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_2,
        event_id=EVENT_2,
        text="Investigate SQLite write contention.",
        created_at=T3,
    )
    layer.investigate(KNOWLEDGE_1, MEMORY_2, created_at=T5)
    after_investigation = layer.describe(KNOWLEDGE_1)
    assert after_investigation["knowledge"]["status"] == "confirmed"
    assert after_investigation["investigating_sources"] == [MEMORY_2]

    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_3,
        event_id=EVENT_3,
        text="Result: the current SQLite mode fails the concurrency requirement.",
        created_at=T3,
        closed_at=T5,
    )
    challenged = layer.challenge(
        KNOWLEDGE_1,
        MEMORY_3,
        challenged_at=T6,
    )
    assert challenged["knowledge"]["status"] == "challenged"
    assert challenged["contradicting_sources"] == [MEMORY_3]
    assert challenged["open_challenges"] is True

    with pytest.raises(ValueError, match="new supporting evidence"):
        layer.confirm(
            KNOWLEDGE_1,
            source_memory_id=MEMORY_1,
            confirmed_at=T7,
        )

    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_4,
        event_id=EVENT_4,
        text="Result: WAL mode satisfies the tested concurrency requirement.",
        created_at=T4,
        closed_at=T6,
    )
    reconfirmed = layer.confirm(
        KNOWLEDGE_1,
        source_memory_id=MEMORY_4,
        confirmed_at=T7,
    )
    assert reconfirmed["knowledge"]["status"] == "confirmed"
    assert reconfirmed["supporting_sources"] == [MEMORY_1, MEMORY_4]
    assert reconfirmed["contradicting_sources"] == [MEMORY_3]
    assert reconfirmed["open_challenges"] is False


def test_challenged_knowledge_can_be_superseded_without_overwrite(tmp_path):
    store, event_log, lifecycle, layer, provenance = build_stack(tmp_path)
    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_1,
        event_id=EVENT_1,
        text="Decision: default SQLite mode is sufficient.",
        created_at=T1,
        closed_at=T2,
    )
    layer.create_candidate(
        domain="project",
        statement="Default SQLite mode is sufficient.",
        source_memory_id=MEMORY_1,
        created_at=T3,
        public_id=KNOWLEDGE_1,
    )
    layer.confirm(KNOWLEDGE_1, confirmed_at=T4)

    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_2,
        event_id=EVENT_2,
        text="Result: default mode fails concurrent writes.",
        created_at=T3,
        closed_at=T5,
    )
    layer.challenge(KNOWLEDGE_1, MEMORY_2, challenged_at=T6)

    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_3,
        event_id=EVENT_3,
        text="Decision: use SQLite WAL mode for concurrent writes.",
        created_at=T4,
        closed_at=T6,
    )
    result = layer.supersede(
        KNOWLEDGE_1,
        statement="SQLite WAL mode is required for concurrent writes.",
        source_memory_id=MEMORY_3,
        superseded_at=T7,
        public_id=KNOWLEDGE_2,
    )

    assert result["old"]["knowledge"]["status"] == "superseded"
    assert result["old"]["superseded_by"] == [KNOWLEDGE_2]
    assert result["new"]["knowledge"]["status"] == "confirmed"
    assert result["new"]["supersedes"] == [KNOWLEDGE_1]
    assert result["new"]["supporting_sources"] == [MEMORY_3]
    assert layer.get(KNOWLEDGE_1)["statement"] == "Default SQLite mode is sufficient."

    new_provenance = provenance.knowledge(KNOWLEDGE_2)
    assert [
        event["id"]
        for source in new_provenance["sources"]
        for event in source["events"]
    ] == [EVENT_3]

    old_history = layer.history(KNOWLEDGE_1)
    new_history = layer.history(KNOWLEDGE_2)
    assert old_history[-1]["operation"] == "supersede"
    assert new_history[-1]["operation"] == "create_superseding"

    with pytest.raises(ValueError, match="provisional or challenged"):
        layer.confirm(KNOWLEDGE_1, confirmed_at=T8)


def test_challenged_knowledge_can_be_rejected(tmp_path):
    store, event_log, lifecycle, layer, _ = build_stack(tmp_path)
    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_1,
        event_id=EVENT_1,
        text="Decision: assumption A is true.",
        created_at=T1,
        closed_at=T2,
    )
    layer.create_candidate(
        domain="project",
        statement="Assumption A is true.",
        source_memory_id=MEMORY_1,
        created_at=T3,
        public_id=KNOWLEDGE_1,
    )
    layer.confirm(KNOWLEDGE_1, confirmed_at=T4)

    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_2,
        event_id=EVENT_2,
        text="Result: assumption A is false.",
        created_at=T3,
        closed_at=T5,
    )
    layer.challenge(KNOWLEDGE_1, MEMORY_2, challenged_at=T6)
    rejected = layer.reject(KNOWLEDGE_1, rejected_at=T7)

    assert rejected["knowledge"]["status"] == "rejected"
    assert rejected["contradicting_sources"] == [MEMORY_2]

    with pytest.raises(ValueError, match="Only confirmed knowledge"):
        layer.challenge(KNOWLEDGE_1, MEMORY_2, challenged_at=T8)


def test_invalid_transitions_and_backdated_operations_are_rejected(tmp_path):
    store, event_log, lifecycle, layer, _ = build_stack(tmp_path)
    create_memory(
        store,
        event_log,
        lifecycle,
        memory_id=MEMORY_1,
        event_id=EVENT_1,
        text="Decision: baseline.",
        created_at=T1,
        closed_at=T3,
    )

    with pytest.raises(ValueError, match="cannot be earlier"):
        layer.create_candidate(
            domain="project",
            statement="Baseline is accepted.",
            source_memory_id=MEMORY_1,
            created_at=T2,
            public_id=KNOWLEDGE_1,
        )

    layer.create_candidate(
        domain="project",
        statement="Baseline is accepted.",
        source_memory_id=MEMORY_1,
        created_at=T4,
        public_id=KNOWLEDGE_1,
    )

    with pytest.raises(ValueError, match="Only confirmed knowledge"):
        layer.challenge(KNOWLEDGE_1, MEMORY_1, challenged_at=T5)

    with pytest.raises(ValueError, match="Only challenged knowledge"):
        layer.reject(KNOWLEDGE_1, rejected_at=T5)

    with pytest.raises(ValueError, match="Only challenged knowledge"):
        layer.supersede(
            KNOWLEDGE_1,
            statement="Replacement.",
            source_memory_id=MEMORY_1,
            superseded_at=T5,
            public_id=KNOWLEDGE_2,
        )
