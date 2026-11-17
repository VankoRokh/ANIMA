"""H5.5 R4.3 / F-06 — future contradictory evidence at confirm time.

Independent audit: h55_work/independent_probes.py::temporal_future_contradiction
in ANIMA_v0.2_H5.5_evidence.zip. That probe used LinkStore to insert
a future contradiction; R3 already forbids the public write. To preserve
the exact historical state, R4.3 injects legacy Relations by SQL only in
disposable pytest tmp_path and tests both confirm call shapes.

The temporal policy evaluates old evidence at the transition instant,
but never creates a new open-ended relation overlapping opposite
evidence (including future intervals). No legacy auto-repair.
"""

from uuid import UUID, uuid4

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


def uid(prefix, n):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | n))


def project_closed(core, n):
    e = Event(
        "conversation.user",
        {"text": f"h55r43unique-{n}: distinct sensor observation {n}"},
        source="user", session_id="session_00000001",
        event_id=uid("ev_", n), timestamp=T0,
    )
    core.event_log.write(e)
    created = core.event_processing.process(e)
    assert created["action"] == "create"
    MemoryLifecycle(memory_store=core.memory_store).close(
        created["memory_id"], closed_at=T1,
    )
    return created["memory_id"]


def scenario(root):
    core = build_core(root)
    mem_id = project_closed(core, 101)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    knowledge_id = layer.create_candidate(
        domain="user", statement="h55r43 measured baseline",
        source_memory_id=mem_id, created_at=T2,
    )["knowledge"]["id"]
    return core, layer, mem_id, knowledge_id


def inject_opposite(core, memory_id, knowledge_id, *,
                    relation_type="contradicts", start=FUTURE, end=None):
    """Simulate ONLY the legacy state that R3 now blocks in LinkStore."""
    relation_id = f"rel_{uuid4()}"
    with core.memory_store.transaction(immediate=True) as conn:
        conn.execute(
            """
            INSERT INTO relations(
                public_id, source_kind, source_id, relation_type,
                target_kind, target_id, created_at, valid_until,
                source_memory_id
            ) VALUES (?, 'memory', ?, ?, 'knowledge', ?, ?, ?, ?)
            """,
            (relation_id, memory_id, relation_type, knowledge_id,
             start, end, memory_id),
        )
    return relation_id


@pytest.mark.parametrize("explicit", [False, True], ids=["implicit", "explicit"])
def test_h55_r43_auditor_future_contradiction_does_not_backdate(
    tmp_path, explicit,
):
    core, layer, source_id, claim_id = scenario(tmp_path)
    future_rel = inject_opposite(core, source_id, claim_id)
    before_raw = core.event_log.log_file.read_bytes()
    kwargs = {"source_memory_id": source_id} if explicit else {}
    confirmed = layer.confirm(claim_id, confirmed_at=T3, **kwargs)
    assert confirmed["knowledge"]["status"] == "confirmed"
    assert confirmed["supporting_sources"] == [source_id]
    assert confirmed["contradicting_sources"] == []
    assert core.event_log.log_file.read_bytes() == before_raw
    with core.memory_store.transaction() as conn:
        relation_count = conn.execute(
            "SELECT COUNT(*) AS c FROM relations "
            "WHERE source_kind='memory' AND source_id=? "
            "AND target_kind='knowledge' AND target_id=?",
            (source_id, claim_id),
        ).fetchone()["c"]
    assert relation_count == 2  # Old supports + injected future contradicts.
    assert layer.get(claim_id)["status"] == "confirmed"
    assert future_rel


@pytest.mark.parametrize("explicit", [False, True], ids=["implicit", "explicit"])
def test_h55_r43_active_contradiction_blocks_both_confirm_forms(
    tmp_path, explicit,
):
    core, layer, source_id, claim_id = scenario(tmp_path)
    inject_opposite(core, source_id, claim_id, start=T2)
    before_history = layer.history(claim_id)
    before_db = core.memory_store.database_file.read_bytes()
    kwargs = {"source_memory_id": source_id} if explicit else {}
    with pytest.raises(ValueError, match="both support and contradict"):
        layer.confirm(claim_id, confirmed_at=T3, **kwargs)
    assert layer.get(claim_id)["status"] == "provisional"
    assert layer.history(claim_id) == before_history
    assert core.memory_store.database_file.read_bytes() == before_db


@pytest.mark.parametrize("explicit", [False, True], ids=["implicit", "explicit"])
def test_h55_r43_expired_contradiction_allows_both_confirm_forms(
    tmp_path, explicit,
):
    core, layer, source_id, claim_id = scenario(tmp_path)
    inject_opposite(core, source_id, claim_id, start=T2, end=T3)
    kwargs = {"source_memory_id": source_id} if explicit else {}
    confirmed = layer.confirm(claim_id, confirmed_at=T4, **kwargs)
    assert confirmed["knowledge"]["status"] == "confirmed"
    assert confirmed["contradicting_sources"] == []


def test_h55_r43_future_interval_start_is_exclusive_before_inclusive_at(
    tmp_path,
):
    _core, layer, source_id, claim_id = scenario(tmp_path / "before")
    inject_opposite(_core, source_id, claim_id, start=T4)
    assert layer.confirm(
        claim_id, source_memory_id=source_id, confirmed_at=T3,
    )["knowledge"]["status"] == "confirmed"

    other, layer2, source2, claim2 = scenario(tmp_path / "at")
    inject_opposite(other, source2, claim2, start=T4)
    with pytest.raises(ValueError, match="both support and contradict"):
        layer2.confirm(claim2, source_memory_id=source2, confirmed_at=T4)
    assert layer2.get(claim2)["status"] == "provisional"


def test_h55_r43_offset_aware_opposite_is_compared_as_instant(tmp_path):
    core, layer, source_id, claim_id = scenario(tmp_path / "before")
    inject_opposite(
        core, source_id, claim_id,
        start="2020-01-01T03:05:00+03:00",  # T5 in UTC
    )
    assert layer.confirm(
        claim_id, source_memory_id=source_id, confirmed_at=T4,
    )["knowledge"]["status"] == "confirmed"

    other, layer2, source2, claim2 = scenario(tmp_path / "at")
    inject_opposite(
        other, source2, claim2,
        start="2020-01-01T03:05:00+03:00",
    )
    with pytest.raises(ValueError, match="both support and contradict"):
        layer2.confirm(claim2, confirmed_at=T5)
    assert layer2.get(claim2)["status"] == "provisional"


def test_h55_r43_r3_public_writer_cannot_create_future_opposition(tmp_path):
    core, layer, source_id, claim_id = scenario(tmp_path)
    with pytest.raises(ValueError, match="both support and contradict"):
        core.link_store.create_relation(
            source_kind="memory", source_id=source_id,
            relation_type="contradicts", target_kind="knowledge",
            target_id=claim_id, created_at=FUTURE,
        )
    assert layer.confirm(
        claim_id, source_memory_id=source_id, confirmed_at=T3,
    )["knowledge"]["status"] == "confirmed"


def test_h55_r43_new_private_support_must_not_overlap_future_opposite(
    tmp_path,
):
    core, layer, _first, claim_id = scenario(tmp_path)
    new_memory = project_closed(core, 202)
    inject_opposite(core, new_memory, claim_id, start=FUTURE)
    before_history = layer.history(claim_id)
    with pytest.raises(ValueError, match="overlapping intervals"):
        layer.confirm(
            claim_id, source_memory_id=new_memory, confirmed_at=T3,
        )
    assert layer.get(claim_id)["status"] == "provisional"
    assert layer.history(claim_id) == before_history
    with core.memory_store.transaction() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM relations WHERE "
            "source_kind='memory' AND source_id=? "
            "AND target_kind='knowledge' AND target_id=? "
            "AND relation_type='supports'",
            (new_memory, claim_id),
        ).fetchone()["n"] == 0


def test_h55_r43_new_support_allowed_after_opposite_expired(tmp_path):
    core, layer, initial, claim_id = scenario(tmp_path)
    second = project_closed(core, 203)
    inject_opposite(
        core, second, claim_id, start=T2, end=T3,
    )
    result = layer.confirm(
        claim_id, source_memory_id=second, confirmed_at=T4,
    )
    assert result["knowledge"]["status"] == "confirmed"
    assert set(result["supporting_sources"]) == {initial, second}
    assert result["contradicting_sources"] == []


def test_h55_r43_future_opposite_while_challenging_does_not_create_overlap(
    tmp_path,
):
    core, layer, _source, claim_id = scenario(tmp_path)
    layer.confirm(claim_id, confirmed_at=T3)
    second = project_closed(core, 204)
    inject_opposite(
        core, second, claim_id, relation_type="supports", start=FUTURE,
    )
    with pytest.raises(ValueError, match="overlapping intervals"):
        layer.challenge(
            claim_id, second, challenged_at=T4,
        )
    assert layer.get(claim_id)["status"] == "confirmed"


def test_h55_r43_reject_with_existing_contradiction_ignores_future_support(
    tmp_path,
):
    core, layer, _source, claim_id = scenario(tmp_path)
    layer.confirm(claim_id, confirmed_at=T3)
    second = project_closed(core, 205)
    layer.challenge(claim_id, second, challenged_at=T4)
    inject_opposite(
        core, second, claim_id, relation_type="supports", start=FUTURE,
    )
    result = layer.reject(
        claim_id, contradiction_memory_id=second, rejected_at=T5,
    )
    assert result["knowledge"]["status"] == "rejected"
    assert layer.get(claim_id)["status"] == "rejected"
