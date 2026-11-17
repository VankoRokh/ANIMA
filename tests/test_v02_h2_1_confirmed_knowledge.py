"""ANIMA v0.2 H2.1: confirmed Knowledge requires an evidence-aware lifecycle.

All tests use disposable SQLite fixtures created under tmp_path.
N3 is a storage/API authority bypass, separate from N4 orphan evidence and
the open/contradictory support validation still scheduled for H2.2.
"""

from uuid import UUID

import pytest

from anima.memory.knowledge import KnowledgeLayer
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore


T0 = "2026-11-17T12:00:00+00:00"
T1 = "2026-11-17T12:01:00+00:00"
T2 = "2026-11-17T12:02:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    layer = KnowledgeLayer(memory_store=store)
    return store, links, layer


def closed_memory(store, number):
    return store.create_memory(
        memory_type="episodic",
        domain="project",
        content=f"Evidence for hypothesis {number}",
        status="closed",
        importance=1,
        created_at=T0,
        public_id=uid("mem_", number),
        source_event_id=uid("ev_", number),
    )


def test_h2_1_direct_confirmed_is_rejected_without_any_writes(tmp_path):
    store, links, _layer = stack(tmp_path)
    knowledge_id = uid("kn_", 101)
    with pytest.raises(ValueError, match="Confirmed Knowledge requires evidence"):
        links.create_knowledge(
            domain="project", statement="A fact without witnesses",
            status="confirmed", created_at=T1, public_id=knowledge_id,
        )

    assert links.get_knowledge(knowledge_id) is None
    with store.transaction() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE public_id = ?",
            (knowledge_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM history WHERE object_kind='knowledge' "
            "AND object_id=?",
            (knowledge_id,),
        ).fetchone()[0] == 0


def test_h2_1_direct_provisional_remains_legal(tmp_path):
    store, links, _layer = stack(tmp_path)
    result = links.create_knowledge(
        domain="project", statement="Provisional design note",
        status="provisional", created_at=T0, public_id=uid("kn_", 201),
    )
    assert result["status"] == "provisional"
    assert links.get_knowledge(result["id"])["status"] == "provisional"


def test_h2_1_confirmed_requires_closed_evidence_and_records_history(tmp_path):
    store, _links, layer = stack(tmp_path)
    evidence = closed_memory(store, 301)
    candidate = layer.create_candidate(
        domain="project", statement="Verified foundation milestone",
        source_memory_id=evidence["id"], created_at=T1,
        public_id=uid("kn_", 302),
    )
    assert candidate["knowledge"]["status"] == "provisional"
    confirmed = layer.confirm(uid("kn_", 302), confirmed_at=T2)
    assert confirmed["knowledge"]["status"] == "confirmed"
    assert confirmed["supporting_sources"] == [evidence["id"]]
    history = layer.history(uid("kn_", 302))
    assert [row["operation"] for row in history] == ["create", "confirm"]


def test_h2_1_provisional_without_evidence_cannot_confirm(tmp_path):
    _store, links, layer = stack(tmp_path)
    knowledge_id = uid("kn_", 401)
    links.create_knowledge(
        domain="project", statement="Unbacked provisional note",
        status="provisional", created_at=T0, public_id=knowledge_id,
    )
    with pytest.raises(ValueError, match="cannot be confirmed without support"):
        layer.confirm(knowledge_id, confirmed_at=T1)
    assert links.get_knowledge(knowledge_id)["status"] == "provisional"
    assert layer.history(knowledge_id) == []


def test_h2_1_raw_writer_does_not_accept_unknown_status(tmp_path):
    _store, links, _layer = stack(tmp_path)
    with pytest.raises(ValueError, match="Unknown knowledge status"):
        links.create_knowledge(
            domain="project", statement="Invalid lifecycle state",
            status="certified", created_at=T0,
        )


def test_h2_1_lifecycle_rejects_open_memory_as_candidate_support(tmp_path):
    store, _links, layer = stack(tmp_path)
    memory = store.create_memory(
        memory_type="episodic", domain="project", content="Still open",
        status="open", importance=1, created_at=T0,
        public_id=uid("mem_", 601), source_event_id=uid("ev_", 601),
    )
    with pytest.raises(ValueError, match="CLOSED memory"):
        layer.create_candidate(
            domain="project", statement="Not yet supported",
            source_memory_id=memory["id"],
            created_at=T1, public_id=uid("kn_", 602),
        )
