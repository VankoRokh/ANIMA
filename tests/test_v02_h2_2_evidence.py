"""v0.2 H2.2: evidence is a valid CLOSED Memory at decision time.

All fixtures are disposable. Deliberate raw SQL damage simulates historical
orphan evidence only inside pytest's tmp_path, never on user instance data.
"""

from uuid import UUID, uuid4

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore


T0 = "2026-11-17T12:00:00+00:00"
T1 = "2026-11-17T12:01:00+00:00"
T2 = "2026-11-17T12:02:00+00:00"
T3 = "2026-11-17T12:03:00+00:00"
T4 = "2026-11-17T12:04:00+00:00"
T5 = "2026-11-17T12:05:00+00:00"


def uid(prefix, i):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | i))


def stack(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    store = MemoryStore(tmp_path / "memory.db", event_log=log)
    links = LinkStore(store)
    layer = KnowledgeLayer(memory_store=store)
    return store, links, layer


def memory(store, number, *, status="closed"):
    # Real synthetic Raw is required even for unit-level evidence tests.
    # Damaged/legacy scenarios below still inject only the damage they
    # actually intend to test, under pytest tmp_path.
    EventLog(store.database_file.parent / "events.jsonl").write(Event(
        "conversation.user",
        {"text": f"Evidence record {number}"},
        source="user",
        session_id="session_00000001",
        timestamp=T0,
        event_id=uid("ev_", number),
    ))
    return store.create_memory(
        memory_type="episodic", domain="project",
        content=f"Evidence record {number}",
        status=status, importance=1, created_at=T0,
        public_id=uid("mem_", number), source_event_id=uid("ev_", number),
    )


def knowledge(links, number):
    return links.create_knowledge(
        domain="project", statement=f"Claim {number}",
        status="provisional", created_at=T1,
        public_id=uid("kn_", number),
    )


def relation(links, source, target, *, kind="supports", until=None, at=T1):
    return links.create_relation(
        source_kind="memory", source_id=source["id"],
        relation_type=kind, target_kind="knowledge", target_id=target["id"],
        created_at=at, valid_until=until,
    )


def legacy_opposite_sql(store, source, fact, *, until=None):
    """Inject an old contradictory relation past the R3 public writer.

    KnowledgeLayer must still reject historical damaged evidence; the
    ordinary LinkStore.create_relation now refuses overlapping polarities.
    This modifies ONLY a disposable pytest Memory database.
    """
    relation_id = f"rel_{uuid4()}"
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO relations(
                public_id, source_kind, source_id, relation_type,
                target_kind, target_id, created_at, valid_until,
                source_memory_id
            ) VALUES (?, 'memory', ?, 'contradicts', 'knowledge', ?, ?, ?, ?)
            """,
            (relation_id, source["id"], fact["id"], T1, until, source["id"]),
        )
    return relation_id


def test_h2_2_closed_memory_support_confirms_and_is_auditable(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 101)
    fact = knowledge(links, 201)
    relation(links, source, fact)
    result = layer.confirm(fact["id"], confirmed_at=T2)
    assert result["knowledge"]["status"] == "confirmed"
    assert result["supporting_sources"] == [source["id"]]
    assert [row["operation"] for row in layer.history(fact["id"])] == [
        "confirm"
    ]


def test_h2_2_open_memory_relation_is_not_usable_support(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 102, status="open")
    fact = knowledge(links, 202)
    relation(links, source, fact)
    with pytest.raises(ValueError, match="existing CLOSED Memory"):
        layer.confirm(fact["id"], confirmed_at=T2)
    assert layer.get(fact["id"])["status"] == "provisional"
    assert layer.history(fact["id"]) == []


def test_h2_2_merged_memory_relation_is_not_usable_support(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 103, status="merged")
    fact = knowledge(links, 203)
    relation(links, source, fact)
    with pytest.raises(ValueError, match="existing CLOSED Memory"):
        layer.confirm(fact["id"], confirmed_at=T2)
    assert layer.get(fact["id"])["status"] == "provisional"


def test_h2_2_orphan_support_is_not_usable_evidence(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 104)
    fact = knowledge(links, 204)
    relation(links, source, fact)
    # Deliberately bypass the public safe delete API to emulate a legacy
    # orphaned relation from a historical dataset.
    with store.transaction() as conn:
        conn.execute(
            "DELETE FROM memories WHERE public_id = ?", (source["id"],)
        )
    assert store.get_memory(source["id"]) is None
    with pytest.raises(ValueError, match="existing CLOSED Memory"):
        layer.confirm(fact["id"], confirmed_at=T2)
    assert layer.get(fact["id"])["status"] == "provisional"


def test_h2_2_expired_support_does_not_confirm_knowledge(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 105)
    fact = knowledge(links, 205)
    relation(links, source, fact, until=T2)
    with pytest.raises(ValueError, match="without support"):
        layer.confirm(fact["id"], confirmed_at=T3)
    assert layer.get(fact["id"])["status"] == "provisional"


def test_h2_2_finite_future_valid_until_counts_as_current_support(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 106)
    fact = knowledge(links, 206)
    relation(links, source, fact, until=T4)
    assert layer.confirm(
        fact["id"], confirmed_at=T3,
    )["knowledge"]["status"] == "confirmed"


def test_h2_2_future_dated_support_cannot_backdate_confirmation(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 107)
    fact = knowledge(links, 207)
    relation(links, source, fact, at=T4)
    with pytest.raises(ValueError, match="without support"):
        layer.confirm(fact["id"], confirmed_at=T3)


def test_h2_2_active_self_contradictory_evidence_is_rejected(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 108)
    fact = knowledge(links, 208)
    relation(links, source, fact, kind="supports")
    legacy_opposite_sql(store, source, fact)
    with pytest.raises(ValueError, match="both support and contradict"):
        layer.confirm(fact["id"], confirmed_at=T3)
    assert layer.get(fact["id"])["status"] == "provisional"


def test_h2_2_expired_contradiction_from_same_memory_is_not_current(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 109)
    fact = knowledge(links, 209)
    relation(links, source, fact, kind="supports")
    legacy_opposite_sql(store, source, fact, until=T2)
    assert layer.confirm(
        fact["id"], confirmed_at=T3,
    )["knowledge"]["status"] == "confirmed"


def test_h2_2_valid_challenged_reconfirmation_with_distinct_evidence(tmp_path):
    store, links, layer = stack(tmp_path)
    first = memory(store, 110)
    contrary = memory(store, 111)
    revised = memory(store, 112)
    result = layer.create_candidate(
        domain="project", statement="Initial evidence",
        source_memory_id=first["id"], created_at=T1,
        public_id=uid("kn_", 210),
    )
    knowledge_id = result["knowledge"]["id"]
    layer.confirm(knowledge_id, confirmed_at=T2)
    layer.challenge(knowledge_id, contrary["id"], challenged_at=T3)
    final = layer.confirm(
        knowledge_id,
        source_memory_id=revised["id"],
        confirmed_at=T4,
    )
    assert final["knowledge"]["status"] == "confirmed"
    assert final["supporting_sources"] == [first["id"], revised["id"]]
    assert final["contradicting_sources"] == [contrary["id"]]


def test_h2_2_orphan_contradiction_cannot_reject_knowledge(tmp_path):
    store, links, layer = stack(tmp_path)
    source = memory(store, 113)
    fact = knowledge(links, 213)
    # Direct legacy transitional state: H2.1 only guards confirmed status.
    with store.transaction() as conn:
        conn.execute(
            "UPDATE knowledge SET status = 'challenged' WHERE public_id = ?",
            (fact["id"],),
        )
    relation(links, source, fact, kind="contradicts")
    with store.transaction() as conn:
        conn.execute(
            "DELETE FROM memories WHERE public_id = ?", (source["id"],)
        )
    with pytest.raises(ValueError, match="existing CLOSED Memory"):
        layer.reject(fact["id"], rejected_at=T3)
    assert layer.get(fact["id"])["status"] == "challenged"


def test_h2_2_mismatched_provenance_id_cannot_confirm(tmp_path):
    store, links, layer = stack(tmp_path)
    first = memory(store, 114)
    second = memory(store, 115)
    fact = knowledge(links, 214)
    links.create_relation(
        source_kind="memory", source_id=first["id"],
        relation_type="supports", target_kind="knowledge",
        target_id=fact["id"], source_memory_id=second["id"],
        created_at=T1,
    )
    with pytest.raises(ValueError, match="Invalid active Knowledge evidence"):
        layer.confirm(fact["id"], confirmed_at=T3)
