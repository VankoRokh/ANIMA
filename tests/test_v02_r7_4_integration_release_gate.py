"""R7.4: cross-component negative acceptance cases for R7.0–R7.3.

These tests exercise interacting *public* APIs with canonical Raw Events.
Deliberately damaged legacy fixtures are confined to pytest tmp_path.
No migration, auto-repair, branch mutation or release side effects.
"""

import hashlib
import json
import sqlite3
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.memory.retrieval import RetrievalEngine
from labs.v02_h5_legacy_diagnostic import audit_snapshot


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"
T7 = "2020-01-01T00:07:00+00:00"
T8 = "2020-01-01T00:08:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def raw_event(core, n, *, text=None, entity_id=None):
    references = (
        [] if entity_id is None
        else [{"kind": "entity", "id": entity_id}]
    )
    event = Event(
        "conversation.user",
        {"text": text or f"r74proof:{n} independent measurement"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", n),
        timestamp=T0,
        references=references,
    )
    core.event_log.write(event)
    return event


def memory(core, n, *, text=None, entity_id=None, status="closed"):
    event = raw_event(core, n, text=text, entity_id=entity_id)
    item = core.memory_store.create_memory(
        memory_type="episodic",
        domain="user",
        status=status,
        content=event.payload["text"],
        created_at=T0,
        source_event_id=event.event_id,
        public_id=uid("mem_", n),
    )
    return item["id"], event


def fixture(root):
    core = build_core(root)
    a, _ = memory(core, 7401)
    b, _ = memory(core, 7402)
    c, _ = memory(core, 7403)
    d, _ = memory(core, 7404)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    claim = layer.create_candidate(
        domain="user",
        statement="R7.4 measured baseline is supported",
        source_memory_id=a,
        created_at=T2,
        public_id=uid("kn_", 7401),
    )["knowledge"]["id"]
    return core, layer, claim, a, b, c, d


def edge(core, source, claim, kind, *, start, end=None):
    return core.link_store.create_relation(
        source_kind="memory", source_id=source,
        relation_type=kind,
        target_kind="knowledge", target_id=claim,
        created_at=start, valid_until=end,
    )


def all_relations(core, claim):
    return core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    )


def snapshot(core, layer, claim):
    return {
        "knowledge": layer.get(claim),
        "history": layer.history(claim),
        "relations": all_relations(core, claim),
        "raw": core.event_log.log_file.read_bytes(),
    }


def test_r74_future_proof_finite_challenge_and_new_proof_are_consistent(tmp_path):
    core, layer, claim, a, b, c, d = fixture(tmp_path)
    future = edge(core, c, claim, "supports", start=FUTURE)
    finite = edge(core, b, claim, "contradicts", start=T4, end=T8)
    layer.confirm(claim, confirmed_at=T3)
    relation_ids = {item["id"] for item in all_relations(core, claim)}
    layer.challenge(claim, b, challenged_at=T5)
    assert {item["id"] for item in all_relations(core, claim)} == relation_ids
    assert layer.history(claim)[-1]["changes"]["contradiction_relation"] == finite["id"]

    before = snapshot(core, layer, claim)
    with pytest.raises(ValueError, match="effective|new supporting evidence"):
        layer.confirm(claim, source_memory_id=c, confirmed_at=T6)
    assert snapshot(core, layer, claim) == before

    result = layer.confirm(claim, source_memory_id=d, confirmed_at=T6)
    assert result["knowledge"]["status"] == "confirmed"
    assert future["created_at"] == FUTURE
    assert finite["valid_until"] == T8
    assert len(all_relations(core, claim)) == len(before["relations"]) + 1
    new_proof = next(
        item for item in all_relations(core, claim)
        if item["source_memory_id"] == d and item["type"] == "supports"
    )
    assert layer.history(claim)[-1]["changes"]["support_relation"] == new_proof["id"]
    assert core.event_log.log_file.read_bytes() == before["raw"]


@pytest.mark.parametrize("explicit", [False, True], ids=["implicit", "explicit"])
def test_r74_finite_challenge_reject_preserves_evidence_window(tmp_path, explicit):
    core, layer, claim, a, b, c, d = fixture(tmp_path)
    finite = edge(core, b, claim, "contradicts", start=T4, end=T8)
    edge(core, b, claim, "supports", start=T8)
    layer.confirm(claim, confirmed_at=T3)
    layer.challenge(claim, b, challenged_at=T5)
    before = all_relations(core, claim)
    rejected = layer.reject(
        claim, rejected_at=T6,
        **({"contradiction_memory_id": b} if explicit else {}),
    )
    assert rejected["knowledge"]["status"] == "rejected"
    assert all_relations(core, claim) == before
    assert finite["valid_until"] == T8
    if explicit:
        assert layer.history(claim)[-1]["changes"]["contradiction_relation"] == finite["id"]


def test_r74_real_supersession_survives_reopen_and_retrieval(tmp_path):
    core, layer, claim, a, b, c, d = fixture(tmp_path)
    layer.confirm(claim, confirmed_at=T3)
    layer.challenge(claim, b, challenged_at=T5)
    result = layer.supersede(
        claim, source_memory_id=d,
        statement="R7.4 revised measurement supersedes baseline",
        superseded_at=T6, public_id=uid("kn_", 7410),
    )
    replacement = result["new"]["knowledge"]["id"]
    assert result["old"]["knowledge"]["status"] == "superseded"

    reopened = build_core(tmp_path)
    another = KnowledgeLayer(memory_store=reopened.memory_store)
    assert another.describe(claim)["superseded_by"] == [replacement]
    assert another.describe(replacement)["supersedes"] == [claim]
    retrieval = RetrievalEngine(
        memory_store=reopened.memory_store, link_store=reopened.link_store,
    ).retrieve(
        object_ids=[claim], kinds=("knowledge",),
        relation_hops=1, top_k=10,
    )
    got = {item["id"]: item for item in retrieval["results"]}
    assert replacement in got
    assert any(
        "relation:supersedes" in reason
        for reason in got[replacement]["reasons"]
    )
    assert audit_snapshot(
        reopened.memory_store.database_file, reopened.event_log.log_file,
    )["findings"].get("unauthorized_lifecycle_supersedes") is None


def test_r74_forged_legacy_supersession_does_not_override_real_history(tmp_path):
    core, layer, claim, a, b, c, d = fixture(tmp_path)
    layer.confirm(claim, confirmed_at=T3)
    layer.challenge(claim, b, challenged_at=T5)
    replacement = layer.supersede(
        claim, source_memory_id=d,
        statement="R7.4 authorized new assertion",
        superseded_at=T6, public_id=uid("kn_", 7410),
    )["new"]["knowledge"]["id"]
    provisional = core.link_store.create_knowledge(
        domain="user",
        statement="R7.4 untrusted candidate",
        public_id=uid("kn_", 7411),
        created_at=T2,
    )["id"]

    forged_id = uid("rel_", 7499)
    with core.memory_store.transaction(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO relations(
                public_id, source_kind, source_id, relation_type,
                target_kind, target_id, created_at, valid_until,
                source_memory_id
            ) VALUES (?, 'knowledge', ?, 'supersedes',
                      'knowledge', ?, ?, NULL, ?)
            """,
            (forged_id, provisional, claim, T7, c),
        )

    assert {row["id"] for row in all_relations(core, claim)
            if row["type"] == "supersedes"} == {forged_id, result_id(
                core, replacement, claim,
            )}
    assert layer.describe(claim)["superseded_by"] == [replacement]
    assert layer.describe(provisional)["supersedes"] == []
    response = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store,
    ).retrieve(
        object_ids=[claim], kinds=("knowledge",),
        relation_hops=1, top_k=10,
    )
    neighbors = {item["id"] for item in response["results"]}
    assert replacement in neighbors
    assert provisional not in neighbors
    report = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert report["status"] == "degraded"
    assert forged_id in report["findings"]["unauthorized_lifecycle_supersedes"]["ids"]


def result_id(core, new, old):
    return next(
        item["id"] for item in core.link_store.relations_for(
            "knowledge", new, direction="outgoing",
            relation_types={"supersedes"},
        )
        if item["target_id"] == old
    )


def test_r74_corrupted_dormant_evidence_blocks_reconfirmation_atomically(tmp_path):
    core, layer, claim, a, b, c, d = fixture(tmp_path)
    future = edge(core, c, claim, "supports", start=T8, end=FUTURE)
    layer.confirm(claim, confirmed_at=T3)
    layer.challenge(claim, b, challenged_at=T5)

    with core.memory_store.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE relations SET valid_until=? WHERE public_id=?",
            (T7, future["id"]),
        )
    before = snapshot(core, layer, claim)
    with pytest.raises(ValueError, match="Invalid Knowledge evidence relation interval"):
        layer.confirm(claim, source_memory_id=d, confirmed_at=T6)
    assert snapshot(core, layer, claim) == before
    assert layer.get(claim)["status"] == "challenged"
    report = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
        at=T6,
    )
    assert future["id"] in report["findings"]["invalid_relation_interval"]["ids"]


def test_r74_missing_raw_prevents_new_proof_and_rolls_back(tmp_path):
    core, layer, claim, a, b, c, d = fixture(tmp_path)
    layer.confirm(claim, confirmed_at=T3)
    layer.challenge(claim, b, challenged_at=T5)

    # Deliberate corruption of a disposable synthetic JSONL copy only.
    raw = core.event_log.log_file.read_bytes().splitlines(keepends=True)
    without_d = [
        line for line in raw
        if json.loads(line)["id"] != uid("ev_", 7404)
    ]
    assert len(without_d) + 1 == len(raw)
    core.event_log.log_file.write_bytes(b"".join(without_d))
    before = snapshot(core, layer, claim)

    with pytest.raises(ValueError, match="missing source Event"):
        layer.confirm(claim, source_memory_id=d, confirmed_at=T6)
    assert snapshot(core, layer, claim) == before
    assert layer.get(claim)["status"] == "challenged"
    assert not any(
        rel["type"] == "supports" and rel["source_memory_id"] == d
        for rel in all_relations(core, claim)
    )


def test_r74_supported_storage_reopens_but_future_schema_copy_is_unchanged(tmp_path):
    core, layer, claim, a, b, c, d = fixture(tmp_path)
    layer.confirm(claim, confirmed_at=T3)
    baseline_history = layer.history(claim)

    reopened = MemoryStore(core.memory_store.database_file)
    assert KnowledgeLayer(memory_store=reopened).history(claim) == baseline_history
    future_path = tmp_path / "future" / "memory.db"
    future_path.parent.mkdir(parents=True)
    with sqlite3.connect(core.memory_store.database_file) as source:
        with sqlite3.connect(future_path) as destination:
            source.backup(destination)
    with sqlite3.connect(future_path) as connection:
        connection.execute(
            "UPDATE schema_meta SET value='999' WHERE key='schema_version'"
        )
    sha_before = hashlib.sha256(future_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Unsupported memory database schema"):
        MemoryStore(future_path)
    assert hashlib.sha256(future_path.read_bytes()).hexdigest() == sha_before
    assert KnowledgeLayer(memory_store=reopened).history(claim) == baseline_history


def test_r74_committed_recovery_and_knowledge_proof_remain_idempotent(tmp_path):
    core = build_core(tmp_path)
    event = raw_event(core, 7431)
    outcome = core.event_processing.process(event)
    assert outcome["action"] == "create"
    memory_id = outcome["memory_id"]
    MemoryLifecycle(memory_store=core.memory_store).close(
        memory_id, closed_at=T1,
    )
    layer = KnowledgeLayer(memory_store=core.memory_store)
    claim = layer.create_candidate(
        domain="user", statement="R7.4 recovered projection is supported",
        source_memory_id=memory_id, created_at=T2,
        public_id=uid("kn_", 7431),
    )["knowledge"]["id"]
    layer.confirm(claim, confirmed_at=T3)
    old_history = layer.history(claim)
    old_raw = core.event_log.log_file.read_bytes()

    reopened = build_core(tmp_path)
    assert reopened.event_processing.recover()["retried"] == 0
    replay = reopened.event_processing.process(event)
    assert replay["action"] == "already_done"
    assert replay["memory_id"] == memory_id
    assert reopened.event_processing.get(event.event_id)["attempts"] == 1
    assert reopened.memory_store.source_events(memory_id) == [event.event_id]
    assert KnowledgeLayer(memory_store=reopened.memory_store).history(claim) == old_history
    assert reopened.event_log.log_file.read_bytes() == old_raw


def test_r74_stale_source_graph_blocks_update_before_knowledge_publication(tmp_path):
    core = build_core(tmp_path)
    alice = core.link_store.create_entity(
        entity_type="person", canonical_name="R74 Alice",
    )["id"]
    boris = core.link_store.create_entity(
        entity_type="person", canonical_name="R74 Boris",
    )["id"]
    shared = "r74same: stable episode reading"
    a, first = memory(
        core, 7441, text=shared, entity_id=alice, status="open",
    )
    b, other = memory(
        core, 7442, text=shared, entity_id=boris, status="open",
    )
    incoming = raw_event(core, 7443, text=shared, entity_id=alice)
    snapshot_choice = core.memory_processor._best_candidate(
        incoming, shared, [],
    )
    assert snapshot_choice is not None
    assert snapshot_choice["memory"]["id"] == a
    before_row = core.memory_store.get_memory(a)
    MemoryLifecycle(memory_store=core.memory_store).merge(b, a, merged_at=T0)
    assert core.memory_store.get_memory(a) == before_row

    class PausedDecision(MemoryProcessor):
        def _best_candidate(self, event, text, entity_ids):
            return snapshot_choice

    stale_processor = PausedDecision(
        memory_store=core.memory_store,
        event_log=core.event_log,
        link_store=core.link_store,
    )
    sources_after_merge = core.memory_store.source_events(a)
    with pytest.raises(ValueError, match="Stale MemoryProcessor candidate"):
        stale_processor.process_event(incoming)
    assert core.memory_store.source_events(a) == sources_after_merge
    assert incoming.event_id not in sources_after_merge

    MemoryLifecycle(memory_store=core.memory_store).close(a, closed_at=T1)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    claim = layer.create_candidate(
        domain="user",
        statement="Merged source memory is immutable after publication",
        source_memory_id=a, created_at=T2,
    )["knowledge"]["id"]
    assert layer.confirm(claim, confirmed_at=T3)["knowledge"]["status"] == "confirmed"
    assert set(core.memory_store.source_events(a)) == {
        first.event_id, other.event_id,
    }
    with pytest.raises(ValueError, match="confirmed Knowledge evidence"):
        core.memory_store.update_memory(
            a, content="forbidden after confirmed", updated_at=T4,
        )
