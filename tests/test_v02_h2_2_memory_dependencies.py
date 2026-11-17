"""v0.2 H2.2: refuse deletion that would orphan durable evidence.

No test touches external state. All files are created under pytest tmp_path.
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
    return store, LinkStore(store)


def memory(store, number, *, status="closed"):
    return store.create_memory(
        memory_type="episodic", domain="project",
        content=f"Historical data {number}",
        status=status, importance=1, created_at=T0,
        source_event_id=uid("ev_", number),
        public_id=uid("mem_", number),
    )


def knowledge(links, number):
    return links.create_knowledge(
        domain="project", statement=f"Durable claim {number}",
        status="provisional", created_at=T1,
        public_id=uid("kn_", number),
    )


def linked(links, source, fact, *, kind="supports", until=None):
    return links.create_relation(
        source_kind="memory", source_id=source["id"],
        relation_type=kind, target_kind="knowledge",
        target_id=fact["id"], created_at=T1,
        valid_until=until,
    )


def test_h2_2_deleting_supported_memory_is_rejected_without_any_side_effects(tmp_path):
    store, links = stack(tmp_path)
    source = memory(store, 301)
    fact = knowledge(links, 401)
    relation = linked(links, source, fact)
    before_memory = store.get_memory(source["id"])
    before_sources = store.source_events(source["id"])
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(source["id"])
    assert store.get_memory(source["id"]) == before_memory
    assert store.source_events(source["id"]) == before_sources
    assert links.get_relation(relation["id"]) == relation
    assert links.get_knowledge(fact["id"]) == fact


def test_h2_2_expired_relation_is_still_durable_history(tmp_path):
    store, links = stack(tmp_path)
    source = memory(store, 302)
    fact = knowledge(links, 402)
    linked(links, source, fact, until=T2)
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(source["id"])
    assert store.get_memory(source["id"]) is not None


def test_h2_2_memory_referenced_only_as_provenance_cannot_be_deleted(tmp_path):
    store, links = stack(tmp_path)
    provenance = memory(store, 303)
    entity = links.create_entity(
        entity_type="concept", canonical_name="Provenance anchor",
        public_id=uid("ent_", 403),
    )
    concept = links.create_entity(
        entity_type="concept", canonical_name="Other entity",
        public_id=uid("ent_", 404),
    )
    relationship = links.create_relation(
        source_kind="entity", source_id=entity["id"],
        relation_type="related_to", target_kind="entity",
        target_id=concept["id"],
        source_memory_id=provenance["id"], created_at=T1,
    )
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(provenance["id"])
    assert links.get_relation(relationship["id"]) is not None


def test_h2_2_memory_as_relation_target_is_protected(tmp_path):
    store, links = stack(tmp_path)
    src = memory(store, 304)
    dst = memory(store, 305)
    link = links.create_relation(
        source_kind="memory", source_id=src["id"],
        relation_type="related_to", target_kind="memory",
        target_id=dst["id"], created_at=T1,
    )
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(dst["id"])
    assert links.get_relation(link["id"]) == link


def test_h2_2_knowledge_lifecycle_history_protects_memory_source(tmp_path):
    store, links = stack(tmp_path)
    src = memory(store, 306)
    layer = KnowledgeLayer(memory_store=store)
    fact = layer.create_candidate(
        domain="project", statement="Evidence provenance",
        source_memory_id=src["id"], created_at=T1,
        public_id=uid("kn_", 406),
    )
    assert fact["knowledge"]["status"] == "provisional"
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(src["id"])
    assert layer.history(uid("kn_", 406))[0]["source_id"] == src["id"]


def test_h2_2_legacy_knowledge_sources_cannot_cascade_silently(tmp_path):
    store, links = stack(tmp_path)
    src = memory(store, 307)
    fact = knowledge(links, 407)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO knowledge_sources(knowledge_id, memory_id, relation) "
            "VALUES (?, ?, 'supports')",
            (fact["id"], src["id"]),
        )
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(src["id"])
    with store.transaction() as conn:
        assert conn.execute(
            "SELECT 1 FROM knowledge_sources WHERE knowledge_id=? AND memory_id=?",
            (fact["id"], src["id"]),
        ).fetchone() is not None


def test_h2_2_legacy_memory_entity_link_is_not_cascaded(tmp_path):
    store, links = stack(tmp_path)
    src = memory(store, 311)
    entity = links.create_entity(
        entity_type="concept", canonical_name="Legacy fixture",
        public_id=uid("ent_", 411),
    )
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO memory_entities(memory_id, entity_id) VALUES (?, ?)",
            (src["id"], entity["id"]),
        )
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(src["id"])
    with store.transaction() as conn:
        assert conn.execute(
            "SELECT 1 FROM memory_entities WHERE memory_id=?",
            (src["id"],),
        ).fetchone() is not None


def test_h2_2_merge_target_cannot_be_deleted_while_referenced(tmp_path):
    store, _links = stack(tmp_path)
    source = memory(store, 312)
    target = memory(store, 313)
    store.update_memory(
        source["id"], status="merged", merged_into=target["id"],
        updated_at=T1,
    )
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(target["id"])
    assert store.get_memory(source["id"])["merged_into"] == target["id"]


def test_h2_2_pure_unlinked_memory_remains_deletable(tmp_path):
    store, _links = stack(tmp_path)
    src = memory(store, 308)
    assert store.delete_memory(src["id"]) is True
    assert store.get_memory(src["id"]) is None
    assert store.delete_memory(src["id"]) is False


def test_h2_2_memory_lifecycle_history_must_not_be_orphaned(tmp_path):
    store, _links = stack(tmp_path)
    src = memory(store, 309, status="open")
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO history(object_kind, object_id, operation, timestamp, "
            "source_kind, source_id, changes_json) "
            "VALUES ('memory', ?, 'close', ?, 'manual', NULL, '{}')",
            (src["id"], T1),
        )
    with pytest.raises(ValueError, match="Cannot delete Memory with"):
        store.delete_memory(src["id"])
    assert store.get_memory(src["id"]) is not None
