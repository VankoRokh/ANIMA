"""R6.1: public Knowledge/Evidence writes and the offline gate agree.

All deliberate corruption is confined to temporary pytest databases.
No real instance data, migration or automatic repair is involved.
"""

from uuid import UUID, uuid4

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from labs.v02_h5_legacy_diagnostic import audit_snapshot
from labs.v02_h5_compatibility import analyze_snapshot


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def verified_memory(core, number):
    event = Event(
        "conversation.user",
        {"text": f"r6-1 verified independent observation {number}"},
        source="user",
        session_id="session_00000001",
        timestamp=T0,
        event_id=uid("ev_", number),
    )
    core.event_log.write(event)
    projection = core.event_processing.process(event)
    assert projection["action"] == "create"
    memory_id = projection["memory_id"]
    MemoryLifecycle(memory_store=core.memory_store).close(
        memory_id, closed_at=T1,
    )
    return memory_id


def published(core):
    memory_id = verified_memory(core, 501)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    claim = layer.create_candidate(
        domain="user", statement="R6.1 published and evidenced",
        source_memory_id=memory_id, created_at=T2,
        public_id=uid("kn_", 501),
    )["knowledge"]["id"]
    layer.confirm(claim, confirmed_at=T3)
    assert audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )["status"] == "healthy"
    return layer, memory_id, claim


def ghost_memory(store, number, *, source_event=True):
    params = dict(
        memory_type="episodic", domain="user", status="closed",
        content=f"R6.1 unverified evidence {number}", created_at=T0,
        public_id=uid("mem_", number),
    )
    if source_event:
        params["source_event_id"] = uid("ev_", number)
    return store.create_memory(**params)["id"]


def add_evidence(links, memory_id, knowledge_id, kind="supports", at=T4):
    return links.create_relation(
        source_kind="memory", source_id=memory_id,
        relation_type=kind,
        target_kind="knowledge", target_id=knowledge_id,
        created_at=at,
    )


@pytest.mark.parametrize("status", ["challenged", "rejected", "superseded"])
def test_r6_1_status_only_writer_fails_without_sql_mutation(tmp_path, status):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    with pytest.raises(ValueError, match="lifecycle transition"):
        links.create_knowledge(
            domain="user", statement="Unsupported terminal state",
            status=status, created_at=T0,
        )
    with store.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0


def test_r6_1_provisional_creation_remains_available(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    claim = LinkStore(store).create_knowledge(
        domain="user", statement="Still exploratory",
        status="provisional", created_at=T0,
    )
    assert claim["status"] == "provisional"
    assert KnowledgeLayer(memory_store=store).history(claim["id"]) == []


@pytest.mark.parametrize("has_declared_source", [False, True])
def test_r6_1_published_claim_refuses_late_unbacked_evidence(
    tmp_path, has_declared_source,
):
    core = build_core(tmp_path)
    layer, source, claim = published(core)
    ghost = ghost_memory(
        core.memory_store, 601 + int(has_declared_source),
        source_event=has_declared_source,
    )
    before_history = layer.history(claim)
    before_relations = core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    )
    for kind in ("supports", "contradicts"):
        with pytest.raises(ValueError, match="Published Knowledge evidence"):
            add_evidence(core.link_store, ghost, claim, kind)
    assert core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    ) == before_relations
    assert layer.history(claim) == before_history
    assert layer.get(claim)["status"] == "confirmed"
    assert source in layer.describe(claim)["supporting_sources"]


def test_r6_1_challenged_claim_also_refuses_direct_evidence(tmp_path):
    core = build_core(tmp_path)
    layer, source, claim = published(core)
    contrary = verified_memory(core, 502)
    layer.challenge(claim, contrary, challenged_at=T4)
    before = layer.history(claim)
    with pytest.raises(ValueError, match="Published Knowledge evidence"):
        add_evidence(core.link_store, source, claim, "supports", at=T5)
    assert layer.get(claim)["status"] == "challenged"
    assert layer.history(claim) == before


def test_r6_1_preconfirmation_unbacked_contradiction_is_not_published(
    tmp_path,
):
    core = build_core(tmp_path)
    good = verified_memory(core, 510)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    claim = layer.create_candidate(
        domain="user", statement="R6.1 staged evidence",
        source_memory_id=good, created_at=T2,
    )["knowledge"]["id"]
    ghost = ghost_memory(core.memory_store, 611)
    add_evidence(core.link_store, ghost, claim, "contradicts", at=T2)
    history_before = layer.history(claim)
    with pytest.raises(ValueError, match="missing source Event"):
        layer.confirm(claim, confirmed_at=T3)
    assert layer.get(claim)["status"] == "provisional"
    assert layer.history(claim) == history_before


def test_r6_1_preconfirmation_unbacked_future_support_is_not_published(
    tmp_path,
):
    core = build_core(tmp_path)
    good = verified_memory(core, 520)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    claim = layer.create_candidate(
        domain="user", statement="R6.1 future staged evidence",
        source_memory_id=good, created_at=T2,
    )["knowledge"]["id"]
    ghost = ghost_memory(core.memory_store, 621, source_event=False)
    add_evidence(core.link_store, ghost, claim, "supports", at=T5)
    with pytest.raises(ValueError, match="requires source Events"):
        layer.confirm(claim, confirmed_at=T3)
    assert layer.get(claim)["status"] == "provisional"


@pytest.mark.parametrize("status", ["challenged", "rejected", "superseded"])
def test_r6_1_offline_diagnostic_detects_legacy_status_only_insert(
    tmp_path, status,
):
    core = build_core(tmp_path)
    verified_memory(core, 531)
    claim = core.link_store.create_knowledge(
        domain="user", statement="Legacy unsafe status",
        status="provisional", created_at=T2,
        public_id=uid("kn_", 531),
    )["id"]
    with core.memory_store.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE knowledge SET status = ? WHERE public_id = ?",
            (status, claim),
        )
    result = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert result["status"] == "degraded"
    assert claim in result["findings"][
        "knowledge_status_without_lifecycle_history"
    ]["ids"]
    compatibility = analyze_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert compatibility["status"] == "BLOCKED"


def test_r6_1_offline_detects_late_evidence_without_any_source_rows(tmp_path):
    core = build_core(tmp_path)
    layer, _source, claim = published(core)
    ghost = ghost_memory(core.memory_store, 699, source_event=False)
    relation_id = "rel_" + str(uuid4())
    # Deliberate SQL damage in a disposable fixture: public API now rejects.
    with core.memory_store.transaction(immediate=True) as conn:
        conn.execute(
            """
            INSERT INTO relations(
                public_id, source_kind, source_id, relation_type,
                target_kind, target_id, created_at, valid_until,
                source_memory_id
            ) VALUES (?, 'memory', ?, 'supports', 'knowledge', ?, ?, NULL, ?)
            """,
            (relation_id, ghost, claim, T4, ghost),
        )
    result = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert result["status"] == "degraded"
    assert relation_id in result["findings"][
        "published_evidence_without_raw_sources"
    ]["ids"]
    assert analyze_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )["status"] == "BLOCKED"
    assert layer.get(claim)["status"] == "confirmed"  # No silent repair.
