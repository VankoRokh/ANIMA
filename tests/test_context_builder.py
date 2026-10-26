import pytest

from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


T1 = "2026-10-26T12:00:00+00:00"
T2 = "2026-10-26T12:10:00+00:00"
T3 = "2026-10-26T12:20:00+00:00"

EV_SQLITE = "ev_11111111-1111-4111-8111-111111111111"
EV_PROBE = "ev_22222222-2222-4222-8222-222222222222"
EV_SHORT = "ev_33333333-3333-4333-8333-333333333333"

M_SQLITE = "mem_44444444-4444-4444-8444-444444444444"
M_PROBE = "mem_55555555-5555-4555-8555-555555555555"
M_SHORT = "mem_66666666-6666-4666-8666-666666666666"
K_CURRENT = "kn_77777777-7777-4777-8777-777777777777"


def add_event(log, event_id, text, timestamp):
    event = Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000001",
        event_id=event_id,
        timestamp=timestamp,
    )
    log.write(event)


def build_stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    log = EventLog(tmp_path / "events.jsonl")

    add_event(
        log,
        EV_SQLITE,
        "Decision: SQLite WAL mode is required for concurrent writes.",
        T1,
    )
    add_event(
        log,
        EV_PROBE,
        "benchmarkprobe reproduced SQLite write contention.",
        T2,
    )
    add_event(log, EV_SHORT, "SQLite", T3)

    store.create_memory(
        memory_type="episodic",
        domain="project",
        content="SQLite WAL mode is required for concurrent writes.",
        status="closed",
        importance=2,
        created_at=T1,
        public_id=M_SQLITE,
        source_event_id=EV_SQLITE,
    )
    store.create_memory(
        memory_type="episodic",
        domain="project",
        content="benchmarkprobe reproduced SQLite write contention.",
        status="closed",
        importance=1,
        created_at=T2,
        public_id=M_PROBE,
        source_event_id=EV_PROBE,
    )
    store.create_memory(
        memory_type="episodic",
        domain="project",
        content="SQLite",
        status="closed",
        importance=0,
        created_at=T3,
        public_id=M_SHORT,
        source_event_id=EV_SHORT,
    )

    links.create_knowledge(
        domain="project",
        statement="SQLite WAL mode is required for concurrent writes.",
        status="confirmed",
        created_at=T3,
        public_id=K_CURRENT,
    )
    links.create_relation(
        source_kind="memory",
        source_id=M_SQLITE,
        relation_type="supports",
        target_kind="knowledge",
        target_id=K_CURRENT,
        created_at=T3,
    )
    links.create_relation(
        source_kind="memory",
        source_id=M_PROBE,
        relation_type="supports",
        target_kind="knowledge",
        target_id=K_CURRENT,
        created_at=T3,
    )

    retrieval = RetrievalEngine(memory_store=store, link_store=links)
    provenance = ProvenanceResolver(store, links, log)
    builder = ContextBuilder(
        retrieval=retrieval,
        provenance=provenance,
    )
    return store, links, log, builder


def ids(entries):
    return [entry["record"]["id"] for entry in entries]


def test_fast_and_deep_policies_are_deterministic_and_distinct(tmp_path):
    _, _, _, builder = build_stack(tmp_path)

    fast_first = builder.build("benchmarkprobe", consumer="fast")
    fast_second = builder.build("benchmarkprobe", consumer="FAST")
    deep = builder.build("benchmarkprobe", consumer="DEEP")

    assert fast_first == fast_second
    assert fast_first["consumer"] == "FAST"
    assert ids(fast_first["knowledge"]) == []
    assert ids(fast_first["memories"]) == [M_PROBE]
    assert fast_first["events"] == []

    assert deep["consumer"] == "DEEP"
    assert ids(deep["knowledge"]) == [K_CURRENT]
    assert M_PROBE in ids(deep["memories"])
    assert ids(deep["events"]) == [EV_SQLITE, EV_PROBE]
    assert deep["selection_stats"]["selected_events"] == 2


def test_knowledge_is_selected_before_memory_when_item_budget_is_tight(tmp_path):
    _, _, _, builder = build_stack(tmp_path)

    bundle = builder.build(
        "SQLite concurrent writes",
        consumer="FAST",
        max_items=1,
        max_chars=500,
    )

    assert ids(bundle["knowledge"]) == [K_CURRENT]
    assert bundle["memories"] == []
    assert bundle["events"] == []
    assert bundle["truncated"] is True
    assert bundle["selection_stats"]["items_used"] == 1
    assert bundle["selection_stats"]["omitted_budget"] >= 1


def test_exact_id_precedes_knowledge_first_policy(tmp_path):
    _, _, _, builder = build_stack(tmp_path)

    bundle = builder.build(
        M_PROBE,
        consumer="DEEP",
        max_items=1,
        max_chars=500,
    )

    assert bundle["knowledge"] == []
    assert ids(bundle["memories"]) == [M_PROBE]
    assert "exact_id:+100" in bundle["memories"][0]["selection_reason"]
    assert bundle["truncated"] is True


def test_char_budget_skips_whole_records_instead_of_cutting_content(tmp_path):
    _, _, _, builder = build_stack(tmp_path)

    bundle = builder.build(
        "SQLite",
        consumer="FAST",
        max_items=5,
        max_chars=6,
    )

    assert bundle["knowledge"] == []
    assert ids(bundle["memories"]) == [M_SHORT]
    assert bundle["memories"][0]["record"]["content"] == "SQLite"
    assert bundle["selection_stats"]["chars_used"] == 6
    assert bundle["truncated"] is True


def test_deep_context_deduplicates_provenance_events_and_keeps_reasons(tmp_path):
    _, _, _, builder = build_stack(tmp_path)

    bundle = builder.build(
        "benchmarkprobe",
        consumer="DEEP",
        max_items=10,
        max_chars=2000,
    )

    event_by_id = {
        entry["record"]["id"]: entry for entry in bundle["events"]
    }
    assert set(event_by_id) == {EV_SQLITE, EV_PROBE}
    probe_reasons = event_by_id[EV_PROBE]["selection_reason"]
    assert f"provenance:knowledge:{K_CURRENT}" in probe_reasons
    assert f"provenance:memory:{M_PROBE}" in probe_reasons


def test_context_builder_passes_structured_retrieval_filters(tmp_path):
    _, _, _, builder = build_stack(tmp_path)

    bundle = builder.build(
        None,
        consumer="FAST",
        retrieval_options={
            "kinds": {"memory"},
            "domain": "project",
            "memory_statuses": {"closed"},
        },
        max_items=2,
        max_chars=1000,
    )

    assert bundle["knowledge"] == []
    assert len(bundle["memories"]) == 2
    assert all(
        entry["record"]["domain"] == "project"
        and entry["record"]["status"] == "closed"
        for entry in bundle["memories"]
    )
    assert bundle["selection_stats"]["items_used"] == 2


def test_context_builder_rejects_invalid_policy_and_budget(tmp_path):
    _, _, _, builder = build_stack(tmp_path)

    with pytest.raises(ValueError, match="FAST or DEEP"):
        builder.build("SQLite", consumer="ARCHIVE")

    with pytest.raises(ValueError, match="max_items"):
        builder.build("SQLite", max_items=0)

    with pytest.raises(ValueError, match="max_chars"):
        builder.build("SQLite", max_chars=0)

    with pytest.raises(ValueError, match="retrieval_options"):
        builder.build("SQLite", retrieval_options=[])

    with pytest.raises(ValueError, match="owns retrieval policy"):
        builder.build(
            "SQLite",
            retrieval_options={"relation_hops": 1},
        )
