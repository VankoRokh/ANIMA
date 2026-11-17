"""ANIMA v0.2 H3.1: time-aware Relation projections (R1-S1 N5).

All fixtures are disposable. Historical Relations remain inspectable; current
Retrieval and Knowledge.describe exclude expired/not-yet-active links.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anima.memory.knowledge import KnowledgeLayer
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.retrieval import RetrievalEngine


PAST = "2020-01-01T00:00:00+00:00"
ENDS = "2021-01-01T00:00:00+00:00"
AFTER = "2022-01-01T00:00:00+00:00"


def uid(prefix, n):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | n))


def stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    return store, links, RetrievalEngine(memory_store=store, link_store=links)


def memory(store, n, *, created_at=PAST, status="closed"):
    return store.create_memory(
        memory_type="episodic", domain="project",
        content=f"Temporal record {n}", status=status,
        importance=1, created_at=created_at,
        source_event_id=uid("ev_", n), public_id=uid("mem_", n),
    )


def knowledge(links, n, *, created_at=PAST):
    return links.create_knowledge(
        domain="project", statement=f"Temporal claim {n}",
        status="provisional", created_at=created_at,
        public_id=uid("kn_", n),
    )


def entity(links, n):
    return links.create_entity(
        entity_type="concept", canonical_name=f"Controller {n}",
        public_id=uid("ent_", n),
    )


def add(links, source, target, *, relation_type="about", until=None,
        created_at=PAST, target_kind="entity"):
    return links.create_relation(
        source_kind="memory", source_id=source["id"],
        relation_type=relation_type, target_kind=target_kind,
        target_id=target["id"], created_at=created_at,
        valid_until=until,
    )


def test_h3_1_half_open_window_with_explicit_timestamp(tmp_path):
    store, links, _ = stack(tmp_path)
    source = memory(store, 1)
    target = entity(links, 2)
    relation = add(links, source, target, until=ENDS)
    history = links.relations_for(
        "entity", target["id"], direction="incoming",
    )
    assert [row["id"] for row in history] == [relation["id"]]

    def active(at):
        return links.relations_for(
            "entity", target["id"], direction="incoming", active_at=at,
        )

    assert active("2019-12-31T23:59:59+00:00") == []
    assert [row["id"] for row in active(PAST)] == [relation["id"]]
    assert [row["id"] for row in active("2020-12-31T23:59:59+00:00")] == [
        relation["id"]
    ]
    assert active(ENDS) == []
    assert active(AFTER) == []
    assert links.get_relation(relation["id"]) is not None


def test_h3_1_offset_aware_comparison_does_not_use_lexical_iso(tmp_path):
    store, links, _ = stack(tmp_path)
    source = memory(store, 3)
    target = entity(links, 4)
    rel = add(links, source, target, until="2021-01-01T03:00:00+03:00")
    # Equal instant: end is excluded, regardless of differing UTC offset.
    assert links.relations_for(
        "entity", target["id"], direction="incoming",
        active_at="2021-01-01T00:00:00+00:00",
    ) == []
    assert [r["id"] for r in links.relations_for(
        "entity", target["id"], direction="incoming",
        active_at="2020-12-31T23:59:59+00:00",
    )] == [rel["id"]]


def test_h3_1_retrieval_entity_matches_current_not_expired_about(tmp_path):
    store, links, retrieval = stack(tmp_path)
    previous = memory(store, 5)
    active = memory(store, 6)
    target = entity(links, 7)
    add(links, previous, target, until=ENDS)
    add(links, active, target, until=None)

    results = retrieval.retrieve(
        entity_ids=[target["id"]], kinds=("memory",),
        relation_hops=0, top_k=10,
    )
    assert [row["id"] for row in results["results"]] == [active["id"]]
    assert results["stats"]["entities"] == 1


def test_h3_1_one_hop_retrieval_does_not_expand_expired_relation(tmp_path):
    store, links, retrieval = stack(tmp_path)
    origin = memory(store, 8)
    expired = memory(store, 9)
    current = memory(store, 10)
    links.create_relation(
        source_kind="memory", source_id=origin["id"],
        relation_type="related_to", target_kind="memory", target_id=expired["id"],
        created_at=PAST, valid_until=ENDS,
    )
    links.create_relation(
        source_kind="memory", source_id=origin["id"],
        relation_type="related_to", target_kind="memory", target_id=current["id"],
        created_at=PAST,
    )

    results = retrieval.retrieve(
        object_ids=[origin["id"]], kinds=("memory",),
        relation_hops=1, top_k=10,
    )
    assert {row["id"] for row in results["results"]} == {
        origin["id"], current["id"],
    }


def test_h3_1_describe_shows_finite_future_expiry_and_hides_past(tmp_path):
    store, links, _ = stack(tmp_path)
    layer = KnowledgeLayer(memory_store=store)
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).isoformat()
    last_month = (now - timedelta(days=30)).isoformat()
    tomorrow = (now + timedelta(days=1)).isoformat()

    fact = knowledge(links, 11, created_at=last_month)
    past_source = memory(store, 12, created_at=last_month)
    current_source = memory(store, 13, created_at=last_month)
    add(
        links, past_source, fact,
        relation_type="supports", target_kind="knowledge",
        created_at=last_month, until=yesterday,
    )
    add(
        links, current_source, fact,
        relation_type="supports", target_kind="knowledge",
        created_at=last_month, until=tomorrow,
    )

    described = layer.describe(fact["id"])
    assert described["supporting_sources"] == [current_source["id"]]
    assert len(links.relations_for(
        "knowledge", fact["id"], direction="incoming",
        relation_types={"supports"},
    )) == 2


def test_h3_1_knowledge_describe_omits_future_relation(tmp_path):
    store, links, _ = stack(tmp_path)
    layer = KnowledgeLayer(memory_store=store)
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=2)).isoformat()
    future = (now + timedelta(days=2)).isoformat()

    fact = knowledge(links, 14, created_at=past)
    source = memory(store, 15, created_at=past)
    add(
        links, source, fact, relation_type="supports",
        target_kind="knowledge", created_at=future,
    )
    assert layer.describe(fact["id"])["supporting_sources"] == []
    assert len(links.relations_for(
        "knowledge", fact["id"], direction="incoming",
        relation_types={"supports"},
    )) == 1


def test_h3_1_history_query_preserves_expired_relations(tmp_path):
    store, links, _ = stack(tmp_path)
    src = memory(store, 16)
    dst = entity(links, 17)
    rel = add(links, src, dst, until=ENDS)
    assert links.get_relation(rel["id"])["valid_until"] == ENDS
    assert links.relations_for("memory", src["id"], direction="outgoing")
    assert links.relations_for(
        "memory", src["id"], direction="outgoing",
        active_at=AFTER,
    ) == []


def test_h3_1_invalid_active_at_is_rejected(tmp_path):
    store, links, _ = stack(tmp_path)
    src = memory(store, 18)
    with pytest.raises(ValueError, match="UTC offset"):
        links.relations_for(
            "memory", src["id"], active_at="2026-11-17T12:00:00",
        )
