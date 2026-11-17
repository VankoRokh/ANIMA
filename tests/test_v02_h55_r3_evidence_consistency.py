"""H5.5 R3 / F-04: overlapping support vs contradiction is never silent.

Primary source: independent auditor ANIMA_v0.2_H5.5_evidence.zip,
h55_work/independent_probes.py::contradictory_current_evidence.

The public writer must reject conflicting intervals atomically. Legacy
inconsistent rows are injected ONLY through SQL in disposable tmp_path and
must be reported by the read-only H5.0/H5.4b diagnostics. Time windows are
half-open [created_at, valid_until), with instant-aware UTC offsets.
"""

from uuid import UUID, uuid4

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from labs.v02_h5_compatibility import analyze_snapshot
from labs.v02_h5_legacy_diagnostic import audit_snapshot


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def legacy_fixture(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    source = store.create_memory(
        memory_type="episodic", domain="project", status="closed",
        content="h55r3 synthetic source", created_at=T0,
        public_id=uid("mem_", 1), source_event_id=uid("ev_", 1),
    )["id"]
    knowledge = links.create_knowledge(
        domain="project", statement="h55r3 synthetic claim",
        created_at=T0, public_id=uid("kn_", 1),
    )["id"]
    return store, links, source, knowledge


def add(links, source, knowledge, kind, *, at=T1, until=None):
    return links.create_relation(
        source_kind="memory", source_id=source,
        relation_type=kind, target_kind="knowledge", target_id=knowledge,
        created_at=at, valid_until=until,
    )


def compose_confirmed(root):
    core = build_core(root)
    source_event = Event(
        "conversation.user",
        {"text": "h55r3alpha: source statement for Knowledge"},
        source="user", session_id="session_00000001",
        timestamp=T0, event_id=uid("ev_", 500),
    )
    core.event_log.write(source_event)
    result = core.event_processing.process(source_event)
    assert result["action"] == "create"
    memory_id = result["memory_id"]
    MemoryLifecycle(memory_store=core.memory_store).close(
        memory_id, closed_at=T1,
    )
    layer = KnowledgeLayer(memory_store=core.memory_store)
    knowledge_id = layer.create_candidate(
        domain="user", statement="h55r3alpha confirmed claim",
        source_memory_id=memory_id, created_at=T2,
    )["knowledge"]["id"]
    assert layer.confirm(
        knowledge_id, confirmed_at=T3,
    )["knowledge"]["status"] == "confirmed"
    return core, memory_id, knowledge_id


def inject_legacy_opposition(store, memory_id, knowledge_id,
                            *, at=T4, until=None):
    """Bypass public safety ONLY in tmp_path to simulate historical damage."""
    rel_id = f"rel_{uuid4()}"
    with store.transaction(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO relations(
                public_id, source_kind, source_id, relation_type,
                target_kind, target_id, created_at, valid_until,
                source_memory_id
            ) VALUES (?, 'memory', ?, 'contradicts', 'knowledge', ?, ?, ?, ?)
            """,
            (rel_id, memory_id, knowledge_id, at, until, memory_id),
        )
    return rel_id


def test_h55_r3_auditor_public_writer_rejects_confirmed_contradiction(
    tmp_path,
):
    core, source, claim = compose_confirmed(tmp_path)
    before_db = core.memory_store.database_file.read_bytes()
    before_raw = core.event_log.log_file.read_bytes()
    before_relations = core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    )
    with pytest.raises(ValueError, match="both support and contradict"):
        add(core.link_store, source, claim, "contradicts", at=T4)
    assert core.memory_store.database_file.read_bytes() == before_db
    assert core.event_log.log_file.read_bytes() == before_raw
    assert core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    ) == before_relations
    assert KnowledgeLayer(memory_store=core.memory_store).get(claim)[
        "status"
    ] == "confirmed"
    assert audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )["status"] == "healthy"


def test_h55_r3_public_writer_rejects_opposition_before_confirmation(
    tmp_path,
):
    store, links, source, claim = legacy_fixture(tmp_path)
    add(links, source, claim, "supports")
    with pytest.raises(ValueError, match="both support and contradict"):
        add(links, source, claim, "contradicts", at=T2)
    assert len(links.relations_for(
        "knowledge", claim, direction="incoming",
    )) == 1


def test_h55_r3_reverse_order_is_equally_protected(tmp_path):
    _store, links, source, claim = legacy_fixture(tmp_path)
    add(links, source, claim, "contradicts")
    with pytest.raises(ValueError, match="both support and contradict"):
        add(links, source, claim, "supports", at=T2)


def test_h55_r3_same_source_different_knowledge_is_not_a_conflict(
    tmp_path,
):
    _store, links, source, claim = legacy_fixture(tmp_path)
    other = links.create_knowledge(
        domain="project", statement="different h55r3 claim",
        created_at=T0, public_id=uid("kn_", 2),
    )["id"]
    add(links, source, claim, "supports")
    opposite = add(links, source, other, "contradicts")
    assert opposite["target_id"] == other


def test_h55_r3_different_memory_sources_can_disagree(tmp_path):
    store, links, source, claim = legacy_fixture(tmp_path)
    second = store.create_memory(
        memory_type="episodic", domain="project", status="closed",
        content="another independent source", created_at=T0,
        public_id=uid("mem_", 2), source_event_id=uid("ev_", 2),
    )["id"]
    add(links, source, claim, "supports")
    opponent = add(links, second, claim, "contradicts")
    assert opponent["source_id"] == second


def test_h55_r3_disjoint_intervals_allow_historical_change_in_evidence(
    tmp_path,
):
    _store, links, source, claim = legacy_fixture(tmp_path)
    first = add(links, source, claim, "supports", at=T1, until=T3)
    second = add(links, source, claim, "contradicts", at=T3)
    assert first["valid_until"] == second["created_at"]
    assert [row["id"] for row in links.relations_for(
        "knowledge", claim, direction="incoming", active_at=T2,
    )] == [first["id"]]
    assert [row["id"] for row in links.relations_for(
        "knowledge", claim, direction="incoming", active_at=T3,
    )] == [second["id"]]


def test_h55_r3_timezone_offsets_are_compared_as_instants(tmp_path):
    _store, links, source, claim = legacy_fixture(tmp_path)
    add(links, source, claim, "supports", at=T1)
    # Same instant as 2020-01-01T00:02Z: lexical ordering is misleading.
    with pytest.raises(ValueError, match="both support and contradict"):
        add(
            links, source, claim, "contradicts",
            at="2020-01-01T03:02:00+03:00",
        )


def test_h55_r3_future_overlap_rejected_even_when_not_yet_active(
    tmp_path,
):
    _store, links, source, claim = legacy_fixture(tmp_path)
    add(links, source, claim, "supports", at=T4)
    with pytest.raises(ValueError, match="both support and contradict"):
        add(links, source, claim, "contradicts", at=T5)


def test_h55_r3_invalid_empty_evidence_interval_refused(tmp_path):
    _store, links, source, claim = legacy_fixture(tmp_path)
    with pytest.raises(ValueError, match="Invalid Knowledge evidence"):
        add(links, source, claim, "supports", at=T3, until=T3)


def test_h55_r3_legacy_sql_conflict_now_degrades_both_diagnostics(
    tmp_path,
):
    core, source, claim = compose_confirmed(tmp_path)
    before_base = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert before_base["status"] == "healthy"
    legacy_id = inject_legacy_opposition(
        core.memory_store, source, claim, at=T4,
    )
    before_db = core.memory_store.database_file.read_bytes()
    before_raw = core.event_log.log_file.read_bytes()

    detected = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    compatibility = analyze_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert detected["status"] == "degraded"
    assert detected["findings"][
        "conflicting_active_knowledge_evidence"
    ]["count"] == 1
    assert legacy_id in detected["findings"][
        "conflicting_active_knowledge_evidence"
    ]["ids"]
    assert compatibility["status"] == "BLOCKED"
    assert compatibility["base_findings"][
        "conflicting_active_knowledge_evidence"
    ]["count"] == 1
    assert core.memory_store.database_file.read_bytes() == before_db
    assert core.event_log.log_file.read_bytes() == before_raw
    assert KnowledgeLayer(memory_store=core.memory_store).get(claim)[
        "status"
    ] == "confirmed"  # No silent repair.


def test_h55_r3_legacy_expired_conflict_does_not_report_active_conflict(
    tmp_path,
):
    core, source, claim = compose_confirmed(tmp_path)
    # A corrupted old DB can contain this historical self-contradiction.
    inject_legacy_opposition(
        core.memory_store, source, claim, at=T3, until=T4,
    )
    active = audit_snapshot(
        core.memory_store.database_file,
        core.event_log.log_file, at=T3,
    )
    expired = audit_snapshot(
        core.memory_store.database_file,
        core.event_log.log_file, at=T5,
    )
    assert active["findings"][
        "conflicting_active_knowledge_evidence"
    ]["count"] == 1
    assert "conflicting_active_knowledge_evidence" not in expired["findings"]


def test_h55_r3_legacy_future_conflict_only_appears_when_active(
    tmp_path,
):
    core, source, claim = compose_confirmed(tmp_path)
    inject_legacy_opposition(core.memory_store, source, claim, at=T6)
    before = audit_snapshot(
        core.memory_store.database_file,
        core.event_log.log_file, at=T5,
    )
    after = audit_snapshot(
        core.memory_store.database_file,
        core.event_log.log_file, at=T6,
    )
    assert "conflicting_active_knowledge_evidence" not in before["findings"]
    assert after["findings"][
        "conflicting_active_knowledge_evidence"
    ]["count"] == 1
