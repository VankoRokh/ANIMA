"""H5.0 read-only legacy diagnostics: healthy, historical, orphaned, corrupt.

Runs exclusively on temporary SQLite/JSONL fixture files. These tests do
not "repair" the fixture and do not mutate its bytes during audit_snapshot().
"""

import sqlite3
from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from labs.v02_h5_legacy_diagnostic import audit_snapshot


T0 = "2026-11-17T12:00:00+00:00"
T1 = "2026-11-17T12:01:00+00:00"
T2 = "2026-11-17T12:02:00+00:00"
T3 = "2026-11-17T12:03:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def seed(tmp_path):
    root = tmp_path
    store = MemoryStore(root / "memory.db")
    log = EventLog(root / "events.jsonl")
    links = LinkStore(store)
    layer = KnowledgeLayer(memory_store=store)

    event = Event(
        "conversation.user",
        {"text": "offline evidence for Knowledge"},
        source="user", session_id="session_00000001",
        event_id=uid("ev_", 1), timestamp=T0,
    )
    log.write(event)
    source = store.create_memory(
        memory_type="episodic", domain="project",
        content="offline evidence for Knowledge",
        status="closed", importance=1, created_at=T0,
        public_id=uid("mem_", 1), source_event_id=event.event_id,
    )
    knowledge = layer.create_candidate(
        domain="project", statement="Verified source",
        source_memory_id=source["id"],
        created_at=T1, public_id=uid("kn_", 1),
    )
    assert knowledge["knowledge"]["status"] == "provisional"
    layer.confirm(knowledge["knowledge"]["id"], confirmed_at=T2)
    return store, log, links, layer, source["id"], knowledge["knowledge"]["id"]


def diagnostics(store, log):
    return audit_snapshot(
        store.database_file, log.log_file, at=T3,
    )


def test_h5_legacy_healthy_fixture_has_no_findings_and_no_mutations(tmp_path):
    store, log, _links, _layer, _mem, _kn = seed(tmp_path)
    source_bytes = log.log_file.read_bytes()
    db_bytes = store.database_file.read_bytes()
    report = diagnostics(store, log)
    assert report["status"] == "healthy"
    assert report["counts"]["raw_events"] == 1
    assert report["counts"]["knowledge"] == 1
    assert report["counts"]["memories"] == 1
    assert report["counts"]["relations"] == 1
    assert report["findings"] == {}
    assert log.log_file.read_bytes() == source_bytes
    assert store.database_file.read_bytes() == db_bytes


def test_h5_legacy_confirmed_without_evidence_is_detected(tmp_path):
    store, log, _links, _layer, _mem, _kn = seed(tmp_path)
    rogue = uid("kn_", 2)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO knowledge("
            "public_id, domain, statement, status, created_at, updated_at"
            ") VALUES (?, 'project', 'legacy unsupported', 'confirmed', ?, ?)",
            (rogue, T1, T2),
        )
    report = diagnostics(store, log)
    assert report["status"] == "degraded"
    assert rogue in report["findings"][
        "confirmed_without_live_closed_support"
    ]["ids"]
    assert rogue in report["findings"][
        "confirmed_without_confirmation_history"
    ]["ids"]


def test_h5_legacy_orphaned_relation_is_detected_without_repair(tmp_path):
    store, log, links, _layer, memory_id, kn_id = seed(tmp_path)
    relation = links.relations_for(
        "knowledge", kn_id, direction="incoming",
        relation_types={"supports"},
    )[0]
    with store.transaction() as conn:
        # Simulate a legacy low-level DELETE that bypassed H2.2.
        conn.execute(
            "DELETE FROM memories WHERE public_id=?", (memory_id,),
        )
    before = store.database_file.read_bytes()
    report = diagnostics(store, log)
    assert report["status"] == "degraded"
    for code in (
        "orphan_relation_source",
        "orphan_relation_provenance",
        "invalid_active_knowledge_evidence",
    ):
        assert relation["id"] in report["findings"][code]["ids"]
    assert kn_id in report["findings"][
        "confirmed_without_live_closed_support"
    ]["ids"]
    assert store.database_file.read_bytes() == before
    assert links.get_relation(relation["id"]) is not None


def test_h5_legacy_missing_raw_for_memory_and_finalized_ledger(tmp_path):
    store, log, _links, _layer, _mem, _kn = seed(tmp_path)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO event_processing("
            "event_id, processor, processor_version, status, attempts, "
            "started_at, finished_at, last_error"
            ") VALUES (?, 'memory_processor', '1.0', 'done', 1, ?, ?, NULL)",
            (uid("ev_", 1), T1, T2),
        )
    # Simulate source truncation on a disposable test copy.
    log.log_file.write_bytes(b"")
    before = store.database_file.read_bytes()
    report = diagnostics(store, log)
    assert report["status"] == "degraded"
    assert uid("ev_", 1) in report["findings"][
        "memory_source_missing_raw"
    ]["ids"]
    assert uid("ev_", 1) in report["findings"][
        "finalized_event_missing_raw"
    ]["ids"]
    assert store.database_file.read_bytes() == before


def test_h5_legacy_torn_tail_reports_failure_not_false_missing_raw(tmp_path):
    store, log, _links, _layer, _mem, _kn = seed(tmp_path)
    source = log.log_file.read_bytes()
    assert source.endswith(b"\n")
    log.log_file.write_bytes(source[:-1])
    report = diagnostics(store, log)
    assert report["status"] == "degraded"
    assert report["findings"]["invalid_raw_eventlog"]["count"] == 1
    # Invalid Raw is not used as complete evidence of what is absent.
    assert "memory_source_missing_raw" not in report["findings"]


def test_h5_legacy_db_only_cannot_claim_complete_source_health(tmp_path):
    store, _log, _links, _layer, _mem, _kn = seed(tmp_path)
    report = audit_snapshot(store.database_file, at=T3)
    assert report["status"] == "unverified"
    assert report["counts"]["raw_events"] is None
    assert report["findings"] == {}


def test_h5_legacy_missing_schema_is_detected_without_bootstrap(tmp_path):
    database = tmp_path / "incomplete.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE memories (public_id TEXT PRIMARY KEY)")
    before = database.read_bytes()
    report = audit_snapshot(database, at=T3)
    assert report["status"] == "degraded"
    assert report["findings"]["missing_table"]["count"] >= 1
    assert database.read_bytes() == before
