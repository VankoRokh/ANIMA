import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.retrieval import RetrievalEngine


T1 = "2026-10-26T12:00:00+00:00"
T2 = "2026-10-26T12:10:00+00:00"
T3 = "2026-10-26T12:20:00+00:00"

M_SQLITE = "mem_11111111-1111-4111-8111-111111111111"
M_PROBE = "mem_22222222-2222-4222-8222-222222222222"
M_OPEN = "mem_33333333-3333-4333-8333-333333333333"
M_MERGED = "mem_44444444-4444-4444-8444-444444444444"

K_CURRENT = "kn_55555555-5555-4555-8555-555555555555"
K_OLD = "kn_66666666-6666-4666-8666-666666666666"
K_PROVISIONAL = "kn_77777777-7777-4777-8777-777777777777"
K_REJECTED = "kn_88888888-8888-4888-8888-888888888888"

E_SQLITE = "ent_99999999-9999-4999-8999-999999999999"

EV_1 = "ev_11111111-aaaa-4111-8111-111111111111"
EV_2 = "ev_22222222-bbbb-4222-8222-222222222222"
EV_3 = "ev_33333333-cccc-4333-8333-333333333333"
EV_4 = "ev_44444444-dddd-4444-8444-444444444444"


def build_corpus(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    store = MemoryStore(tmp_path / "memory.db", event_log=log)
    links = LinkStore(store)
    # All four Memory sources are synthetic but physically verifiable.
    for event_id, timestamp, text in (
        (EV_1, T1, "SQLite concurrent writes require WAL mode."),
        (EV_2, T2, "benchmarkprobe reproduced write contention."),
        (EV_3, T3, "Current open discussion about CM5 cooling."),
        (EV_4, T1, "Old merged SQLite note."),
    ):
        log.write(Event(
            "conversation.user", {"text": text}, source="user",
            session_id="session_00000001",
            event_id=event_id, timestamp=timestamp,
        ))

    store.create_memory(
        memory_type="episodic",
        domain="project",
        content="SQLite concurrent writes require WAL mode.",
        status="closed",
        importance=2,
        created_at=T1,
        public_id=M_SQLITE,
        source_event_id=EV_1,
    )
    store.create_memory(
        memory_type="episodic",
        domain="project",
        content="benchmarkprobe reproduced write contention.",
        status="closed",
        importance=1,
        created_at=T2,
        public_id=M_PROBE,
        source_event_id=EV_2,
    )
    store.create_memory(
        memory_type="episodic",
        domain="user",
        content="Current open discussion about CM5 cooling.",
        status="open",
        importance=1,
        created_at=T3,
        public_id=M_OPEN,
        source_event_id=EV_3,
    )
    store.create_memory(
        memory_type="episodic",
        domain="project",
        content="Old merged SQLite note.",
        status="merged",
        importance=1,
        created_at=T1,
        public_id=M_MERGED,
        source_event_id=EV_4,
    )

    # Publish the same corpus through the real Knowledge lifecycle.
    # The old superseded/rejected rows are no longer minted directly by
    # the storage writer. Keep source/target IDs and statuses unchanged.
    layer = KnowledgeLayer(memory_store=store)
    layer.create_candidate(
        domain="project",
        statement="Default SQLite mode is sufficient for concurrent writes.",
        source_memory_id=M_SQLITE,
        created_at=T1,
        public_id=K_OLD,
    )
    layer.confirm(K_OLD, confirmed_at=T1)
    layer.challenge(K_OLD, M_PROBE, challenged_at=T2)
    layer.supersede(
        K_OLD,
        statement="SQLite WAL mode is required for concurrent writes.",
        source_memory_id=M_PROBE,
        superseded_at=T3,
        public_id=K_CURRENT,
    )
    links.create_knowledge(
        domain="project",
        statement="SQLite may remain the local Stage 1 baseline.",
        status="provisional",
        created_at=T2,
        public_id=K_PROVISIONAL,
    )
    layer.create_candidate(
        domain="project",
        statement="SQLite cannot be used locally.",
        source_memory_id=M_SQLITE,
        created_at=T2,
        public_id=K_REJECTED,
    )
    layer.confirm(K_REJECTED, confirmed_at=T2)
    layer.challenge(K_REJECTED, M_PROBE, challenged_at=T2)
    layer.reject(K_REJECTED, rejected_at=T2)

    links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        aliases=["SQLite3"],
        public_id=E_SQLITE,
    )

    links.create_relation(
        source_kind="memory",
        source_id=M_SQLITE,
        relation_type="about",
        target_kind="entity",
        target_id=E_SQLITE,
        created_at=T1,
    )
    links.create_relation(
        source_kind="knowledge",
        source_id=K_CURRENT,
        relation_type="about",
        target_kind="entity",
        target_id=E_SQLITE,
        source_memory_id=M_SQLITE,
        created_at=T3,
    )
    return store, links, RetrievalEngine(
        memory_store=store,
        link_store=links,
    )


def ids(response):
    return [item["id"] for item in response["results"]]


def test_exact_id_can_retrieve_terminal_history(tmp_path):
    _, _, retrieval = build_corpus(tmp_path)

    response = retrieval.retrieve(K_OLD, top_k=3)

    # Real lifecycle adds legitimate Memory evidence neighbors to the
    # superseded claim. Exact-ID priority and the supersedes hop must
    # remain first; an additional 1-hop Memory result is permitted.
    assert ids(response)[:2] == [K_OLD, K_CURRENT]
    assert response["results"][0]["record"]["status"] == "superseded"
    assert "exact_id:+100" in response["results"][0]["reasons"]
    assert any(
        reason.startswith("relation:supersedes")
        for reason in response["results"][1]["reasons"]
    )


def test_fts_prefers_current_confirmed_knowledge(tmp_path):
    _, _, retrieval = build_corpus(tmp_path)

    response = retrieval.retrieve(
        "SQLite concurrent writes",
        top_k=4,
    )

    assert ids(response)[0] == K_CURRENT
    assert M_SQLITE in ids(response)[:3]
    assert K_OLD not in ids(response)
    assert K_REJECTED not in ids(response)
    assert M_MERGED not in ids(response)
    assert any(
        reason.startswith("fts_rank:")
        for reason in response["results"][0]["reasons"]
    )


def test_entity_filter_resolves_alias_and_returns_about_objects(tmp_path):
    _, _, retrieval = build_corpus(tmp_path)

    response = retrieval.retrieve(
        entity_names=["sqlite3"],
        relation_hops=0,
        top_k=5,
    )

    assert ids(response) == [K_CURRENT, M_SQLITE]
    assert all(
        any(reason.startswith(f"entity:{E_SQLITE}") for reason in item["reasons"])
        for item in response["results"]
    )


def test_structured_filters_are_deterministic_and_bounded(tmp_path):
    _, _, retrieval = build_corpus(tmp_path)

    first = retrieval.retrieve(
        kinds={"memory"},
        domain="project",
        memory_types={"episodic"},
        memory_statuses={"closed"},
        relation_hops=0,
        top_k=1,
    )
    second = retrieval.retrieve(
        kinds={"memory"},
        domain="project",
        memory_types={"episodic"},
        memory_statuses={"closed"},
        relation_hops=0,
        top_k=1,
    )

    assert first == second
    assert len(first["results"]) == 1
    assert first["results"][0]["record"]["status"] == "closed"
    assert first["results"][0]["record"]["domain"] == "project"
    assert "structured_filter:+20" in first["results"][0]["reasons"]


def test_one_hop_relation_expands_direct_fts_seed(tmp_path):
    _, _, retrieval = build_corpus(tmp_path)

    without_relations = retrieval.retrieve(
        "benchmarkprobe",
        relation_hops=0,
        top_k=5,
    )
    with_relations = retrieval.retrieve(
        "benchmarkprobe",
        relation_hops=1,
        top_k=5,
    )

    assert ids(without_relations) == [M_PROBE]
    assert ids(with_relations)[0] == M_PROBE
    assert K_CURRENT in ids(with_relations)
    knowledge = next(
        item for item in with_relations["results"] if item["id"] == K_CURRENT
    )
    assert "relation:supports:1hop:+8" in knowledge["reasons"]


def test_explicit_status_filter_can_request_terminal_record(tmp_path):
    _, _, retrieval = build_corpus(tmp_path)

    response = retrieval.retrieve(
        kinds={"knowledge"},
        domain="project",
        knowledge_statuses={"rejected"},
        relation_hops=0,
    )

    assert ids(response) == [K_REJECTED]
    assert response["results"][0]["record"]["status"] == "rejected"


def test_invalid_retrieval_requests_are_rejected(tmp_path):
    _, _, retrieval = build_corpus(tmp_path)

    with pytest.raises(ValueError, match="requires query"):
        retrieval.retrieve()

    with pytest.raises(ValueError, match="relation_hops"):
        retrieval.retrieve("SQLite", relation_hops=2)

    with pytest.raises(ValueError, match="top_k"):
        retrieval.retrieve("SQLite", top_k=0)

    with pytest.raises(ValueError, match="Unknown entity name"):
        retrieval.retrieve(entity_names=["PostgreSQL"])

    with pytest.raises(ValueError, match="Invalid retrieval object ID"):
        retrieval.retrieve("mem_not-a-uuid")
