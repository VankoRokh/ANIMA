"""R7.2 / H56-03: no generic forged Knowledge supersedes authority.

All write/corruption probes are on isolated pytest tmp_path databases.
Raw and published Knowledge are real; only explicitly named legacy
corruption tests bypass public APIs with temporary SQL.
"""

from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer
from labs.v02_h5_legacy_diagnostic import audit_snapshot
from labs.v02_h5_compatibility import analyze_snapshot


T0 = "2020-01-01T00:00:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"


def uid(prefix, n):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | n))


def closed_source(core, n):
    raw = Event(
        "conversation.user",
        {"text": f"r72authority:{n} synthetic source of claims"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", n),
        timestamp=T0,
    )
    core.event_log.write(raw)
    return core.memory_store.create_memory(
        memory_type="episodic",
        domain="user",
        status="closed",
        content=raw.payload["text"],
        created_at=T0,
        source_event_id=raw.event_id,
        public_id=uid("mem_", n),
    )["id"]


def base(root):
    core = build_core(root)
    a, b, c = (closed_source(core, n) for n in (7201, 7202, 7203))
    layer = KnowledgeLayer(memory_store=core.memory_store)
    old = layer.create_candidate(
        domain="user",
        statement="Baseline requires retention",
        source_memory_id=a,
        created_at=T2,
        public_id=uid("kn_", 7201),
    )["knowledge"]["id"]
    layer.confirm(old, confirmed_at=T3)
    newer = core.link_store.create_knowledge(
        domain="user",
        statement="Exploratory replacement is not authoritative",
        created_at=T2,
        public_id=uid("kn_", 7202),
    )["id"]
    return core, layer, old, newer, a, b, c


def supersedes_links(core, old):
    return [
        row for row in core.link_store.relations_for(
            "knowledge", old, direction="incoming",
            relation_types={"supersedes"},
        )
    ]


def forge_legacy_supersedes(core, new, old, memory):
    """Only on a disposable database: represent historical direct SQL."""
    relation_id = uid("rel_", 7299)
    with core.memory_store.transaction(immediate=True) as conn:
        conn.execute(
            """
            INSERT INTO relations(
                public_id, source_kind, source_id, relation_type,
                target_kind, target_id, created_at, valid_until,
                source_memory_id
            ) VALUES (?, 'knowledge', ?, 'supersedes',
                      'knowledge', ?, ?, NULL, ?)
            """,
            (relation_id, new, old, T4, memory),
        )
    return relation_id


def test_r72_h5603_generic_writer_refuses_forged_supersedes_atomically(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    before = (
        layer.get(old),
        layer.get(newer),
        layer.history(old),
        layer.history(newer),
        supersedes_links(core, old),
        core.event_log.log_file.read_bytes(),
    )
    with pytest.raises(ValueError, match="KnowledgeLayer.supersede"):
        core.link_store.create_relation(
            source_kind="knowledge", source_id=newer,
            relation_type="supersedes",
            target_kind="knowledge", target_id=old,
            source_memory_id=c, created_at=T4,
        )
    after = (
        layer.get(old),
        layer.get(newer),
        layer.history(old),
        layer.history(newer),
        supersedes_links(core, old),
        core.event_log.log_file.read_bytes(),
    )
    assert after == before
    assert layer.describe(old)["superseded_by"] == []
    assert layer.describe(newer)["supersedes"] == []


def test_r72_generic_nonlifecycle_relation_still_available(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    relation = core.link_store.create_relation(
        source_kind="knowledge", source_id=newer,
        relation_type="related_to",
        target_kind="knowledge", target_id=old,
        source_memory_id=c, created_at=T4,
    )
    assert relation["type"] == "related_to"
    assert relation["source_id"] == newer
    assert relation["target_id"] == old
    assert layer.describe(old)["superseded_by"] == []


def test_r72_h5603_generic_writer_refuses_even_with_real_raw_source(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    assert core.memory_store.source_events(c) == [uid("ev_", 7203)]
    before = core.memory_store.count()
    with pytest.raises(ValueError, match="KnowledgeLayer.supersede"):
        core.link_store.create_relation(
            source_kind="knowledge", source_id=newer,
            relation_type="supersedes",
            target_kind="knowledge", target_id=old,
            source_memory_id=c,
            created_at=T4,
        )
    assert core.memory_store.count() == before


def test_r72_legacy_forgery_is_visible_for_forensics_but_not_lifecycle(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    forged = forge_legacy_supersedes(core, newer, old, c)
    assert {row["id"] for row in supersedes_links(core, old)} == {forged}

    assert layer.get(old)["status"] == "confirmed"
    assert layer.get(newer)["status"] == "provisional"
    assert layer.describe(old)["superseded_by"] == []
    assert layer.describe(newer)["supersedes"] == []

    report = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert report["status"] == "degraded"
    assert forged in report["findings"]["unauthorized_lifecycle_supersedes"]["ids"]
    compat = analyze_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert compat["status"] == "BLOCKED"


def test_r72_legacy_forgery_cannot_expand_retrieval_as_supersedes(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    forged = forge_legacy_supersedes(core, newer, old, c)
    from anima.memory.retrieval import RetrievalEngine

    engine = RetrievalEngine(
        memory_store=core.memory_store,
        link_store=core.link_store,
    )
    result = engine.retrieve(
        object_ids=[old], kinds=("knowledge",),
        relation_hops=1, top_k=10,
    )
    assert old in {item["id"] for item in result["results"]}
    assert newer not in {item["id"] for item in result["results"]}
    assert not any(
        f"relation:supersedes" in reason
        for item in result["results"] for reason in item["reasons"]
    )
    assert {row["id"] for row in supersedes_links(core, old)} == {forged}


def test_r72_real_lifecycle_supersede_still_authorizes_both_views(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    layer.challenge(old, b, challenged_at=T4)
    result = layer.supersede(
        old, statement="New measured evidence requires retention",
        source_memory_id=c, superseded_at=T5,
        public_id=uid("kn_", 7204),
    )
    new_id = result["new"]["knowledge"]["id"]
    relation = result["supersedes_relation"]

    assert layer.get(old)["status"] == "superseded"
    assert layer.get(new_id)["status"] == "confirmed"
    assert layer.describe(old)["superseded_by"] == [new_id]
    assert layer.describe(new_id)["supersedes"] == [old]
    assert relation["type"] == "supersedes"
    assert relation["source_memory_id"] == c
    assert layer.history(old)[-1]["changes"]["supersedes_relation"] == relation["id"]

    diag = audit_snapshot(core.memory_store.database_file, core.event_log.log_file)
    assert "unauthorized_lifecycle_supersedes" not in diag["findings"]


def test_r72_real_supersede_remains_retrievable_as_authorized_neighbor(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    layer.challenge(old, b, challenged_at=T4)
    result = layer.supersede(
        old, statement="Measured revision from source C",
        source_memory_id=c, superseded_at=T5,
        public_id=uid("kn_", 7204),
    )
    new_id = result["new"]["knowledge"]["id"]
    from anima.memory.retrieval import RetrievalEngine

    engine = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store,
    )
    response = engine.retrieve(
        object_ids=[old], kinds=("knowledge",),
        relation_hops=1, top_k=10,
    )
    matches = {
        item["id"]: item for item in response["results"]
    }
    assert old in matches
    assert new_id in matches
    assert any(
        "relation:supersedes" in reason
        for reason in matches[new_id]["reasons"]
    )


@pytest.mark.parametrize("damage", ["old_history", "new_history"])
def test_r72_legacy_missing_half_of_lifecycle_history_is_not_authority(
    tmp_path, damage,
):
    core, layer, old, newer, a, b, c = base(tmp_path)
    layer.challenge(old, b, challenged_at=T4)
    result = layer.supersede(
        old, statement="Revised with canonical Evidence",
        source_memory_id=c, superseded_at=T5,
        public_id=uid("kn_", 7204),
    )
    new_id = result["new"]["knowledge"]["id"]
    edge_id = result["supersedes_relation"]["id"]
    assert layer.describe(old)["superseded_by"] == [new_id]

    # Simulate noncooperative legacy history loss on a disposable DB.
    with core.memory_store.transaction(immediate=True) as conn:
        if damage == "old_history":
            conn.execute(
                """
                DELETE FROM history WHERE object_kind='knowledge'
                  AND object_id=? AND operation='supersede'
                """,
                (old,),
            )
        else:
            conn.execute(
                """
                DELETE FROM history WHERE object_kind='knowledge'
                  AND object_id=? AND operation='create_superseding'
                """,
                (new_id,),
            )

    assert layer.describe(old)["superseded_by"] == []
    assert layer.describe(new_id)["supersedes"] == []
    report = audit_snapshot(core.memory_store.database_file, core.event_log.log_file)
    assert edge_id in report["findings"]["unauthorized_lifecycle_supersedes"]["ids"]


def test_r72_legacy_finite_supersedes_is_not_authority(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    layer.challenge(old, b, challenged_at=T4)
    result = layer.supersede(
        old, statement="Measured supersession with evidence C",
        source_memory_id=c, superseded_at=T5,
        public_id=uid("kn_", 7204),
    )
    edge_id = result["supersedes_relation"]["id"]
    assert layer.describe(old)["superseded_by"] == [uid("kn_", 7204)]
    with core.memory_store.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE relations SET valid_until=? WHERE public_id=?",
            ("2099-01-01T00:00:00+00:00", edge_id),
        )
    # A finite expiry is not the lifecycle Relation created by supersede.
    # The forensic graph still preserves its current historical row.
    assert layer.describe(old)["superseded_by"] == []
    report = audit_snapshot(core.memory_store.database_file, core.event_log.log_file)
    assert edge_id in report["findings"]["unauthorized_lifecycle_supersedes"]["ids"]


def test_r72_public_link_inspection_preserves_historical_raw_edges(tmp_path):
    core, layer, old, newer, a, b, c = base(tmp_path)
    edge_id = forge_legacy_supersedes(core, newer, old, c)
    row = core.link_store.get_relation(edge_id)
    assert row["type"] == "supersedes"
    assert row["source_id"] == newer
    assert row["target_id"] == old
    assert row["source_memory_id"] == c
    assert layer.describe(old)["superseded_by"] == []
