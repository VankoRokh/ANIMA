"""H5.5 R4.2 / F-05 — merge must preserve temporal Entity attribution.

Primary independent evidence:
ANIMA_v0.2_H5.5_evidence.zip,
h55_work/independent_probes.py::temporal_merge (2099 future about).

Only disposable pytest tmp_path is mutated. A transferred source relation
is restricted to [max(source.created_at, merged_at), source.valid_until).
No old/expired fact may be resurrected, and source_memory_id is preserved.
"""

from datetime import datetime
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.retrieval import RetrievalEngine
from labs.v02_h5_legacy_diagnostic import audit_snapshot


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"
FUTURE_END = "2100-01-01T00:00:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def instant(value):
    return datetime.fromisoformat(value)


def stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    lifecycle = MemoryLifecycle(memory_store=store)
    return store, links, lifecycle


def memory(store, number):
    return store.create_memory(
        memory_type="episodic", domain="project",
        content=f"h55r42 stable item {number}", status="open",
        created_at=T0, public_id=uid("mem_", number),
        source_event_id=uid("ev_", number),
    )["id"]


def entity(links, number):
    return links.create_entity(
        entity_type="object", canonical_name=f"Temporal Subject {number}",
        public_id=uid("ent_", number),
    )["id"]


def about(links, source, target, *, started=T1, ended=None,
          provenance=None):
    return links.create_relation(
        source_kind="memory", source_id=source,
        relation_type="about", target_kind="entity", target_id=target,
        created_at=started, valid_until=ended,
        source_memory_id=provenance,
    )


def target_links(links, target, *, at=None):
    return links.relations_for(
        "memory", target, direction="outgoing",
        relation_types={"about"}, active_at=at,
    )


def project(core, number, marker):
    item = Event(
        "conversation.user",
        {"text": f"h55r42{marker}: electrical circuit normal {number}"},
        source="user", session_id="session_00000001",
        event_id=uid("ev_", number), timestamp=T0,
    )
    core.event_log.write(item)
    result = core.event_processing.process(item)
    assert result["action"] == "create"
    return item, result["memory_id"]


def test_h55_r42_auditor_future_attribution_not_backdated(tmp_path):
    core = build_core(tmp_path)
    original, source = project(core, 211, "alpha")
    _second, target = project(core, 212, "beta")
    assert source != target
    subject = entity(core.link_store, 213)
    legacy = about(
        core.link_store, source, subject, started=FUTURE,
    )
    retrieval = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store,
    )
    before = retrieval.retrieve(
        entity_ids=[subject], kinds=("memory",), relation_hops=0,
    )
    assert before["results"] == []

    merged = MemoryLifecycle(
        memory_store=core.memory_store,
    ).merge(source, target, merged_at=T4)
    assert merged["entity_links_added"] == [subject]
    result = retrieval.retrieve(
        entity_ids=[subject], kinds=("memory",), relation_hops=0,
    )
    assert result["results"] == []  # Must remain absent in 2026.

    transferred = target_links(core.link_store, target)
    assert len(transferred) == 1
    assert instant(transferred[0]["created_at"]) == instant(FUTURE)
    assert transferred[0]["valid_until"] is None
    assert transferred[0]["source_memory_id"] == source
    assert target_links(core.link_store, target, at=T4) == []
    assert target_links(core.link_store, target, at=FUTURE) == transferred
    assert core.link_store.get_relation(legacy["id"]) == legacy
    assert core.event_processing.get(original.event_id)["status"] == "done"
    assert audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
        at=T5,
    )["status"] == "healthy"


def test_h55_r42_active_past_start_is_clipped_to_merge_instant(tmp_path):
    store, links, lifecycle = stack(tmp_path)
    source, target = memory(store, 1), memory(store, 2)
    subject = entity(links, 1)
    original = about(links, source, subject, started=T1)
    merged = lifecycle.merge(source, target, merged_at=T4)
    assert merged["entity_links_added"] == [subject]
    transferred = target_links(links, target)
    assert len(transferred) == 1
    assert instant(transferred[0]["created_at"]) == instant(T4)
    assert transferred[0]["source_memory_id"] == original[
        "source_memory_id"
    ]
    assert target_links(links, target, at=T3) == []
    assert target_links(links, target, at=T4) == transferred


def test_h55_r42_finite_source_end_preserved_and_end_excluded(tmp_path):
    store, links, lifecycle = stack(tmp_path)
    source, target = memory(store, 3), memory(store, 4)
    subject = entity(links, 2)
    about(links, source, subject, started=T2, ended=T6)
    lifecycle.merge(source, target, merged_at=T4)
    transferred = target_links(links, target)
    assert len(transferred) == 1
    assert instant(transferred[0]["created_at"]) == instant(T4)
    assert transferred[0]["valid_until"] == T6
    assert target_links(links, target, at=T3) == []
    assert target_links(links, target, at=T5) == transferred
    assert target_links(links, target, at=T6) == []


def test_h55_r42_expired_source_relation_not_resurrected(tmp_path):
    store, links, lifecycle = stack(tmp_path)
    source, target = memory(store, 5), memory(store, 6)
    subject = entity(links, 3)
    original = about(links, source, subject, started=T1, ended=T3)
    result = lifecycle.merge(source, target, merged_at=T4)
    assert result["entity_links_added"] == []
    assert target_links(links, target) == []
    assert coreless_source_link(links, source, original["id"]) is True


def coreless_source_link(links, source, relation_id):
    return relation_id in {
        item["id"] for item in target_links(links, source)
    }


def test_h55_r42_future_finite_relation_keeps_both_bounds(tmp_path):
    store, links, lifecycle = stack(tmp_path)
    source, target = memory(store, 7), memory(store, 8)
    subject = entity(links, 4)
    about(
        links, source, subject,
        started=FUTURE, ended=FUTURE_END,
    )
    lifecycle.merge(source, target, merged_at=T4)
    transferred = target_links(links, target)
    assert len(transferred) == 1
    assert instant(transferred[0]["created_at"]) == instant(FUTURE)
    assert transferred[0]["valid_until"] == FUTURE_END
    assert target_links(links, target, at=T4) == []
    assert target_links(links, target, at=FUTURE) == transferred
    assert target_links(links, target, at=FUTURE_END) == []


def test_h55_r42_existing_target_coverage_prevents_duplicate(tmp_path):
    store, links, lifecycle = stack(tmp_path)
    source, target = memory(store, 9), memory(store, 10)
    subject = entity(links, 5)
    current = about(links, target, subject, started=T2)
    about(links, source, subject, started=T1)
    result = lifecycle.merge(source, target, merged_at=T4)
    assert result["entity_links_added"] == []
    assert target_links(links, target) == [current]


def test_h55_r42_future_target_link_does_not_hide_current_transfer(
    tmp_path,
):
    store, links, lifecycle = stack(tmp_path)
    source, target = memory(store, 11), memory(store, 12)
    subject = entity(links, 6)
    future = about(links, target, subject, started=T6)
    about(links, source, subject, started=T1)
    merged = lifecycle.merge(source, target, merged_at=T4)
    assert merged["entity_links_added"] == [subject]
    mid = target_links(links, target, at=T5)
    assert len(mid) == 1 and mid[0]["id"] != future["id"]
    assert instant(mid[0]["created_at"]) == instant(T4)


def test_h55_r42_source_provenance_is_not_replaced_by_target(tmp_path):
    store, links, lifecycle = stack(tmp_path)
    original_provenance = memory(store, 13)
    source, target = memory(store, 14), memory(store, 15)
    subject = entity(links, 7)
    about(
        links, source, subject, started=T2,
        provenance=original_provenance,
    )
    lifecycle.merge(source, target, merged_at=T4)
    copied = target_links(links, target)
    assert len(copied) == 1
    assert copied[0]["source_memory_id"] == original_provenance


def test_h55_r42_timezone_offsets_preserve_the_later_instant(tmp_path):
    store, links, lifecycle = stack(tmp_path)
    source, target = memory(store, 16), memory(store, 17)
    subject = entity(links, 8)
    at_utc_t5 = "2020-01-01T03:05:00+03:00"
    about(links, source, subject, started=at_utc_t5)
    lifecycle.merge(source, target, merged_at=T4)
    copied = target_links(links, target)
    assert len(copied) == 1
    assert instant(copied[0]["created_at"]) == instant(T5)
    assert target_links(links, target, at=T4) == []
    assert target_links(links, target, at=T5) == copied


def test_h55_r42_invalid_legacy_source_interval_fails_atomically(tmp_path):
    store, links, lifecycle = stack(tmp_path)
    source, target = memory(store, 18), memory(store, 19)
    subject = entity(links, 9)
    # Old direct SQL may contain an inverted interval. Writer would not
    # repair this unsupported state during merge.
    from uuid import uuid4
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO relations("
            "public_id,source_kind,source_id,relation_type,target_kind,"
            "target_id,created_at,valid_until,source_memory_id) "
            "VALUES (?, 'memory', ?, 'about', 'entity', ?, ?, ?, ?)",
            (f"rel_{uuid4()}", source, subject, T6, T2, source),
        )
    before_source = store.get_memory(source)
    before_target = store.get_memory(target)
    before_sources = store.source_events(target)
    with pytest.raises(ValueError, match="invalid source about relation"):
        lifecycle.merge(source, target, merged_at=T4)
    assert store.get_memory(source) == before_source
    assert store.get_memory(target) == before_target
    assert store.source_events(target) == before_sources
