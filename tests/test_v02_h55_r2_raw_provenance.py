"""H5.5 R2: Raw existence at Knowledge publication in a composed Core.

Uses only disposable tmp_path. Independent audit's missing_raw_confirmation
is the primary failure case. A persistent schema_meta binding ensures even
a separately reopened MemoryStore respects the Core's Raw provenance policy.

Contract: require ALL declared sources for each effective Memory to exist
as well-formed, LF-terminated Raw Events. This does NOT attest Memory text,
event-to-claim semantics, cross-file physical durability or unbound standalone
legacy store instances. Existing test-only standalone stores are not migrated.
"""

import sqlite3
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.memory_store import (
    MemoryStore,
    RAW_PROVENANCE_META_KEY,
    RAW_PROVENANCE_META_VALUE,
)
from anima.memory.provenance import ProvenanceResolver


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"


def uid(n):
    return "ev_" + str(UUID(int=(4 << 76) | (2 << 62) | n))


def event(n, marker="valid"):
    return Event(
        "conversation.user",
        {"text": f"h55r2{marker} event {n}"},
        source="user", session_id="session_00000001",
        timestamp=T0, event_id=uid(n),
    )


def project(core, n):
    item = event(n)
    core.event_log.write(item)
    result = core.event_processing.process(item)
    assert result["action"] == "create"
    return item, result["memory_id"]


def ghost(core, n):
    return core.memory_store.create_memory(
        memory_type="episodic", domain="user", status="closed",
        content=f"h55r2ghost declared unobserved event {n}",
        created_at=T0, source_event_id=uid(n),
    )["id"]


def close(core, memory_id):
    return MemoryLifecycle(
        memory_store=core.memory_store
    ).close(memory_id, closed_at=T1)


def candidate(core, memory_id, marker="knowledge"):
    layer = KnowledgeLayer(memory_store=core.memory_store)
    claim = layer.create_candidate(
        domain="user", statement=f"h55r2{marker} is confirmed",
        source_memory_id=memory_id,
        created_at=T2,
    )["knowledge"]["id"]
    return layer, claim


def test_h55_r2_auditor_missing_raw_cannot_confirm_or_publish(tmp_path):
    core = build_core(tmp_path)
    missing_id = ghost(core, 21)
    layer, claim = candidate(core, missing_id)
    before_db = core.memory_store.database_file.read_bytes()
    before_raw_exists = core.event_log.log_file.exists()
    before_history = layer.history(claim)

    with pytest.raises(ValueError, match="Raw provenance missing source Event"):
        layer.confirm(claim, confirmed_at=T3)

    assert layer.get(claim)["status"] == "provisional"
    assert layer.history(claim) == before_history
    assert core.memory_store.database_file.read_bytes() == before_db
    assert core.event_log.log_file.exists() == before_raw_exists
    assert core.event_processing.recover()["finalized"] == 0


def test_h55_r2_regular_projected_raw_can_confirm_and_resolve(tmp_path):
    core = build_core(tmp_path)
    original, memory_id = project(core, 31)
    close(core, memory_id)
    layer, claim = candidate(core, memory_id, "valid")
    result = layer.confirm(claim, confirmed_at=T3)
    assert result["knowledge"]["status"] == "confirmed"
    provenance = ProvenanceResolver(
        core.memory_store, core.link_store, core.event_log,
    ).knowledge(claim)
    assert original.event_id in {
        row["id"]
        for source in provenance["sources"]
        for row in source["events"]
    }


def test_h55_r2_cannot_confirm_memory_with_no_source_links(tmp_path):
    core = build_core(tmp_path)
    memory = core.memory_store.create_memory(
        memory_type="episodic", domain="user", status="closed",
        content="h55r2 missing source links", created_at=T0,
    )["id"]
    layer, claim = candidate(core, memory, "without_sources")
    with pytest.raises(ValueError, match="requires source Events"):
        layer.confirm(claim, confirmed_at=T3)
    assert layer.get(claim)["status"] == "provisional"


def test_h55_r2_all_declared_sources_must_exist(tmp_path):
    core = build_core(tmp_path)
    _original, memory_id = project(core, 41)
    close(core, memory_id)
    with core.memory_store.transaction() as connection:
        # Deliberate corrupted external projection in a disposable fixture.
        connection.execute(
            "INSERT INTO memory_sources(memory_id, event_id) VALUES (?, ?)",
            (memory_id, uid(42)),
        )
    layer, claim = candidate(core, memory_id, "partial")
    with pytest.raises(ValueError, match="Raw provenance missing source Event"):
        layer.confirm(claim, confirmed_at=T3)
    assert layer.get(claim)["status"] == "provisional"


def test_h55_r2_torn_raw_tail_fails_closed_without_repair(tmp_path):
    core = build_core(tmp_path)
    _original, memory_id = project(core, 51)
    close(core, memory_id)
    layer, claim = candidate(core, memory_id, "torn")
    with core.event_log.log_file.open("ab") as output:
        output.write(b'{"id":"ev_torn"')
    original_raw = core.event_log.log_file.read_bytes()
    before_db = core.memory_store.database_file.read_bytes()
    with pytest.raises(ValueError, match="unterminated"):
        layer.confirm(claim, confirmed_at=T3)
    assert layer.get(claim)["status"] == "provisional"
    assert core.memory_store.database_file.read_bytes() == before_db
    assert core.event_log.log_file.read_bytes() == original_raw


def test_h55_r2_persistent_binding_survives_independent_store_reopen(tmp_path):
    core = build_core(tmp_path)
    memory_id = ghost(core, 61)
    # A module that reopens the same database without passing EventLog must
    # NOT downgrade an already registered composed instance to legacy mode.
    reopened = MemoryStore(core.memory_store.database_file)
    layer = KnowledgeLayer(memory_store=reopened)
    claim = layer.create_candidate(
        domain="user", statement="h55r2 reopened", created_at=T2,
        source_memory_id=memory_id,
    )["knowledge"]["id"]
    with pytest.raises(ValueError, match="Raw provenance missing source Event"):
        layer.confirm(claim, confirmed_at=T3)
    assert layer.get(claim)["status"] == "provisional"

    with sqlite3.connect(core.memory_store.database_file) as connection:
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key=?",
            (RAW_PROVENANCE_META_KEY,),
        ).fetchone()
    assert row == (RAW_PROVENANCE_META_VALUE,)


def test_h55_r2_rejects_binding_to_unrelated_eventlog(tmp_path):
    core = build_core(tmp_path / "core")
    outside = EventLog(tmp_path / "different" / "events.jsonl")
    with pytest.raises(ValueError, match="canonical sibling"):
        MemoryStore(core.memory_store.database_file, event_log=outside)
    # The rejected operation cannot remove the existing protection.
    with sqlite3.connect(core.memory_store.database_file) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key=?",
            (RAW_PROVENANCE_META_KEY,),
        ).fetchone() == (RAW_PROVENANCE_META_VALUE,)


def test_h55_r2_legacy_knowledge_source_without_policy_is_not_retroactively_modified(
    tmp_path,
):
    store = MemoryStore(tmp_path / "standalone" / "memory.db")
    with store.transaction() as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key=?",
            (RAW_PROVENANCE_META_KEY,),
        ).fetchone() is None
    # This is the historical storage-only mode used by older isolated
    # fixtures; it is NOT a verified Core source and cannot be certified as
    # secure for RC by R2. No automatic metadata migration occurs here.


def test_h55_r2_supersede_cannot_publish_ghost_raw_as_confirmed(tmp_path):
    core = build_core(tmp_path)
    _event1, support_id = project(core, 81)
    _event2, contradicting_id = project(core, 82)
    close(core, support_id)
    close(core, contradicting_id)
    layer, claim = candidate(core, support_id, "original")
    layer.confirm(claim, confirmed_at=T3)
    layer.challenge(
        claim, contradicting_id, challenged_at=T4,
    )
    missing = ghost(core, 83)
    before_history = layer.history(claim)
    with pytest.raises(ValueError, match="Raw provenance missing source Event"):
        layer.supersede(
            claim, statement="h55r2 alternate source",
            source_memory_id=missing, superseded_at=T5,
        )
    assert layer.get(claim)["status"] == "challenged"
    assert layer.history(claim) == before_history


def test_h55_r2_reject_cannot_use_ghost_source(tmp_path):
    core = build_core(tmp_path)
    _event1, support_id = project(core, 91)
    _event2, contradiction_id = project(core, 92)
    close(core, support_id)
    close(core, contradiction_id)
    layer, claim = candidate(core, support_id, "original")
    layer.confirm(claim, confirmed_at=T3)
    layer.challenge(
        claim, contradiction_id, challenged_at=T4,
    )
    missing = ghost(core, 93)
    before_history = layer.history(claim)
    with pytest.raises(ValueError, match="Raw provenance missing source Event"):
        layer.reject(
            claim, contradiction_memory_id=missing, rejected_at=T5,
        )
    assert layer.get(claim)["status"] == "challenged"
    assert layer.history(claim) == before_history
