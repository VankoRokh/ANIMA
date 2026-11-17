"""H5.5 R5 — fail-closed Raw authority for standalone Knowledge writes.

R2 initially protected only build_core-bound MemoryStore. The public
standalone MemoryStore + KnowledgeLayer path could still confirm, reject or
supersede Knowledge with missing/unregistered Raw. R5 removes that bypass:
an unbound DB can be read and used to build provisional candidates, but it
cannot finalize Knowledge unless explicitly bound to the canonical EventLog.

No test-only bypass. All source and damaged-state fixtures are disposable
pytest tmp_path databases. Real Raw Events are required for positive cases.
"""

from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import (
    MemoryStore,
    RAW_PROVENANCE_META_KEY,
    RAW_PROVENANCE_META_VALUE,
)


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"


def uid(prefix, n):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | n))


def unbound(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    layer = KnowledgeLayer(memory_store=store)
    mem = store.create_memory(
        memory_type="episodic", domain="project",
        status="closed", content="R5 missing-raw source for candidate",
        created_at=T0, public_id=uid("mem_", 10),
        source_event_id=uid("ev_", 10),
    )["id"]
    claim = layer.create_candidate(
        domain="project", statement="R5 candidate claim",
        source_memory_id=mem, created_at=T1,
        public_id=uid("kn_", 10),
    )["knowledge"]["id"]
    return store, layer, mem, claim


def _real_event(n):
    return Event(
        "conversation.user",
        {"text": f"h55r5group{n:04d}: isolated source observation {n}"},
        source="user", session_id="session_00000001",
        timestamp=T0, event_id=uid("ev_", n),
    )


def _core_challenged(tmp_path):
    core = build_core(tmp_path)
    memories = []
    for n in (101, 102, 103):
        event = _real_event(n)
        core.event_log.write(event)
        result = core.event_processing.process(event)
        assert result["action"] == "create"
        MemoryLifecycle(memory_store=core.memory_store).close(
            result["memory_id"], closed_at=T1,
        )
        memories.append(result["memory_id"])
    layer = KnowledgeLayer(memory_store=core.memory_store)
    fact = layer.create_candidate(
        domain="user", statement="h55r5 original truth",
        source_memory_id=memories[0], created_at=T2,
    )["knowledge"]["id"]
    layer.confirm(fact, confirmed_at=T3)
    layer.challenge(fact, memories[1], challenged_at=T4)
    assert layer.get(fact)["status"] == "challenged"
    return core, layer, fact, memories


def test_h55_r5_unbound_implicit_confirm_refused_without_side_effects(
    tmp_path,
):
    store, layer, memory_id, claim = unbound(tmp_path)
    assert layer.get(claim)["status"] == "provisional"
    before = store.database_file.read_bytes()
    history = layer.history(claim)

    with pytest.raises(ValueError, match="Raw provenance is unbound"):
        layer.confirm(claim, confirmed_at=T2)

    assert store.database_file.read_bytes() == before
    assert layer.get(claim)["status"] == "provisional"
    assert layer.history(claim) == history
    assert store.source_events(memory_id) == [uid("ev_", 10)]
    assert not (tmp_path / "events.jsonl").exists()
    with store.transaction() as conn:
        assert conn.execute(
            "SELECT value FROM schema_meta WHERE key=?",
            (RAW_PROVENANCE_META_KEY,),
        ).fetchone() is None


def test_h55_r5_unbound_explicit_confirm_rolls_back_new_relation(
    tmp_path,
):
    store, layer, _memory, claim = unbound(tmp_path)
    second = store.create_memory(
        memory_type="episodic", domain="project", status="closed",
        content="second unverified source", created_at=T0,
        public_id=uid("mem_", 11), source_event_id=uid("ev_", 11),
    )["id"]
    before_hist = layer.history(claim)
    with pytest.raises(ValueError, match="Raw provenance is unbound"):
        layer.confirm(claim, source_memory_id=second, confirmed_at=T2)
    assert layer.get(claim)["status"] == "provisional"
    assert layer.history(claim) == before_hist
    with store.transaction() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM relations WHERE source_id=? "
            "AND target_id=? AND relation_type='supports'",
            (second, claim),
        ).fetchone()[0] == 0


def test_h55_r5_new_store_reopening_unbound_db_cannot_confirm(tmp_path):
    store, _layer, _, claim = unbound(tmp_path)
    reopened = MemoryStore(store.database_file)
    layer = KnowledgeLayer(memory_store=reopened)
    with pytest.raises(ValueError, match="Raw provenance is unbound"):
        layer.confirm(claim, confirmed_at=T2)
    assert layer.get(claim)["status"] == "provisional"


def test_h55_r5_bind_without_raw_is_not_enough_but_real_event_allows_confirm(
    tmp_path,
):
    store, layer, _, claim = unbound(tmp_path)
    log = EventLog(tmp_path / "events.jsonl")
    store.bind_event_log(log)
    with pytest.raises(ValueError, match="missing source Event"):
        layer.confirm(claim, confirmed_at=T2)
    assert layer.get(claim)["status"] == "provisional"

    log.write(_real_event(10))
    confirmed = layer.confirm(claim, confirmed_at=T2)
    assert confirmed["knowledge"]["status"] == "confirmed"
    assert len(layer.history(claim)) == 2

    with store.transaction() as conn:
        assert conn.execute(
            "SELECT value FROM schema_meta WHERE key=?",
            (RAW_PROVENANCE_META_KEY,),
        ).fetchone()["value"] == RAW_PROVENANCE_META_VALUE


@pytest.mark.parametrize("operation", ["reject", "supersede"])
def test_h55_r5_unbound_legacy_terminal_transition_is_refused(
    tmp_path, operation,
):
    core, _layer, claim, sources = _core_challenged(tmp_path)
    # Simulate an historical unbound database by removing the policy
    # ONLY on a throwaway, fully backed-up test fixture.
    with core.memory_store.transaction(immediate=True) as connection:
        connection.execute(
            "DELETE FROM schema_meta WHERE key=?",
            (RAW_PROVENANCE_META_KEY,),
        )
    independent = MemoryStore(core.memory_store.database_file)
    layer = KnowledgeLayer(memory_store=independent)
    before = independent.database_file.read_bytes()
    before_history = layer.history(claim)
    if operation == "reject":
        def terminal():
            return layer.reject(claim, rejected_at=T5)
    else:
        def terminal():
            return layer.supersede(
                claim, statement="h55r5 updated claim",
                source_memory_id=sources[2], superseded_at=T5,
            )
    with pytest.raises(ValueError, match="Raw provenance is unbound"):
        terminal()
    assert independent.database_file.read_bytes() == before
    assert layer.get(claim)["status"] == "challenged"
    assert layer.history(claim) == before_history
    assert core.event_processing.finalized_count() == 3


def test_h55_r5_read_only_and_provisional_legacy_usage_remains_supported(
    tmp_path,
):
    store, layer, mem, claim = unbound(tmp_path)
    assert layer.get(claim)["status"] == "provisional"
    assert layer.describe(claim)["supporting_sources"] == [mem]
    additional = LinkStore(store).create_knowledge(
        domain="project", statement="Unverified provisional is allowed",
        status="provisional", created_at=T1,
    )
    assert additional["status"] == "provisional"
    assert layer.history(claim)[0]["operation"] == "create"
    with store.transaction() as conn:
        assert conn.execute(
            "SELECT value FROM schema_meta WHERE key=?",
            (RAW_PROVENANCE_META_KEY,),
        ).fetchone() is None


def test_h55_r5_composed_core_still_publishes_with_real_raw(tmp_path):
    core, layer, claim, sources = _core_challenged(tmp_path)
    new_fact = layer.create_candidate(
        domain="user", statement="h55r5 separate properly verified",
        source_memory_id=sources[2], created_at=T2,
    )["knowledge"]["id"]
    assert layer.confirm(new_fact, confirmed_at=T3)[
        "knowledge"
    ]["status"] == "confirmed"
    assert core.event_processing.finalized_count() == 3
