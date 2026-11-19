"""R8.3 integrated H57-01/02/03 acceptance over real Raw, Memory, Knowledge.

No production changes. Every SQL corruption is on a new pytest tmp_path,
and all canonical Raw records belong to the disposable synthetic Core.
"""
import json
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.provenance import ProvenanceResolver


T0 = "2020-01-01T00:00:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"
T8 = "2020-01-01T00:08:00+00:00"
T9 = "2020-01-01T00:09:00+00:00"


def uid(prefix, n):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | n))


def raw_event(core, number, *, at=T0):
    event = Event(
        "conversation.user",
        {"text": f"r83 proof source {number} is independent and durable"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", number),
        timestamp=at,
    )
    core.event_log.write(event)
    return event


def closed_source(core, number, *, at=T0):
    event = raw_event(core, number, at=at)
    memory_id = core.memory_store.create_memory(
        memory_type="episodic",
        domain="user",
        content=event.payload["text"],
        status="closed",
        created_at=at,
        source_event_id=event.event_id,
        public_id=uid("mem_", number),
    )["id"]
    return memory_id, event


def fresh_after_challenge(core, number=8304):
    """New physical Event and CLOSED Memory produced after Knowledge challenge."""
    event = raw_event(core, number, at=T4)
    memory_id = core.memory_store.create_memory(
        memory_type="episodic",
        domain="user",
        content=event.payload["text"],
        status="open",
        created_at=T4,
        source_event_id=event.event_id,
        public_id=uid("mem_", number),
    )["id"]
    MemoryLifecycle(memory_store=core.memory_store).close(
        memory_id, closed_at=T4,
    )
    return memory_id, event


def challenged(root, *, future=False):
    core = build_core(root)
    a, _ = closed_source(core, 8301)
    b, _ = closed_source(core, 8302)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    k = layer.create_candidate(
        domain="user",
        statement="R8.3 base knowledge requires testable proof",
        source_memory_id=a,
        created_at=T2,
        public_id=uid("kn_", 8301),
    )["knowledge"]["id"]
    future_relation = None
    if future:
        c, _ = closed_source(core, 8303)
        future_relation = core.link_store.create_relation(
            source_kind="memory", source_id=c,
            relation_type="supports",
            target_kind="knowledge", target_id=k,
            created_at=T8, valid_until=T9,
        )
    layer.confirm(k, confirmed_at=T3)
    layer.challenge(k, b, challenged_at=T4)
    assert layer.get(k)["status"] == "challenged"
    return core, layer, k, a, b, future_relation


def snapshot(core):
    tables = ("knowledge", "relations", "history", "memory_sources")
    with core.memory_store.transaction() as connection:
        value = {
            name: [
                tuple(row)
                for row in connection.execute(
                    f"SELECT * FROM {name} ORDER BY rowid"
                )
            ]
            for name in tables
        }
    value["raw"] = core.event_log.log_file.read_bytes()
    return value


def support(core, k, memory_id):
    return [
        relation for relation in core.link_store.relations_for(
            "knowledge", k, direction="incoming",
            relation_types={"supports"},
        )
        if relation["source_memory_id"] == memory_id
    ]


def valid_candidates(core, layer, knowledge_id, memory_id):
    return [
        {
            "kind": "knowledge",
            "id": knowledge_id,
            "record": layer.get(knowledge_id),
            "score": 15,
            "reasons": ["structured_filter:+20"],
        },
        {
            "kind": "memory",
            "id": memory_id,
            "record": core.memory_store.get_memory(memory_id),
            "score": 10,
            "reasons": ["structured_filter:+20"],
        },
    ]


class Adapter:
    def __init__(self, results):
        self.results = results

    def retrieve(self, query, *, top_k, relation_hops, **kwargs):
        return {
            "results": self.results,
            "stats": {
                "candidates": len(self.results),
                "returned": len(self.results),
                "fts_truncated": False,
                "filters_truncated": False,
            },
        }


class ForbiddenProvenance:
    """An invalid adapter response must be denied before provenance calls."""

    def knowledge(self, knowledge_id):
        raise AssertionError("Provenance accessed before adapter validation")

    def memory(self, memory_id):
        raise AssertionError("Provenance accessed before adapter validation")


def builder(core, candidates, *, forbidden=False):
    provenance = (
        ForbiddenProvenance()
        if forbidden else ProvenanceResolver(
            core.memory_store, core.link_store, core.event_log,
        )
    )
    return ContextBuilder(
        retrieval=Adapter(candidates),
        provenance=provenance,
    )


@pytest.mark.parametrize(
    "confirmed_at",
    [T4, "2020-01-01T04:04:00+04:00"],
    ids=["equal_string", "offset_equivalent"],
)
def test_r83_fresh_same_instant_proof_preserves_history_and_raw(
    tmp_path, confirmed_at,
):
    core, layer, k, a, b, _ = challenged(tmp_path)
    new, physical_event = fresh_after_challenge(core)
    before = snapshot(core)
    result = layer.confirm(k, source_memory_id=new, confirmed_at=confirmed_at)
    assert result["knowledge"]["status"] == "confirmed"
    proofs = support(core, k, new)
    assert len(proofs) == 1
    assert proofs[0]["created_at"] == confirmed_at
    assert layer.history(k)[-1]["changes"]["support_relation"] == proofs[0]["id"]
    assert core.memory_store.source_events(new) == [physical_event.event_id]
    assert snapshot(core)["raw"] == before["raw"]


@pytest.mark.parametrize(
    "damaged_start,damaged_end",
    [
        ("2020-01-01T00:08:00", T9),
        (T8, "2020-01-01T00:07:00+00:00"),
    ],
    ids=["offset_naive", "inverted"],
)
def test_r83_invalid_future_evidence_blocks_fresh_reconfirm_then_repairs(
    tmp_path, damaged_start, damaged_end,
):
    core, layer, k, a, b, future = challenged(tmp_path, future=True)
    new, _ = fresh_after_challenge(core)
    with core.memory_store.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE relations SET created_at=?, valid_until=? WHERE public_id=?",
            (damaged_start, damaged_end, future["id"]),
        )
    before = snapshot(core)
    with pytest.raises(ValueError, match="Knowledge evidence"):
        layer.confirm(k, source_memory_id=new, confirmed_at=T4)
    assert snapshot(core) == before
    assert layer.get(k)["status"] == "challenged"
    assert support(core, k, new) == []

    # Explicit operator repair on the disposable fixture, NOT a new
    # product auto-repair path. Retry must now succeed on the same instant.
    with core.memory_store.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE relations SET created_at=?, valid_until=? WHERE public_id=?",
            (T8, T9, future["id"]),
        )
    fixed = layer.confirm(k, source_memory_id=new, confirmed_at=T4)
    assert fixed["knowledge"]["status"] == "confirmed"
    assert layer.history(k)[-1]["changes"]["support_relation"] == support(
        core, k, new,
    )[0]["id"]
    assert len(support(core, k, new)) == 1


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
def test_r83_real_provenance_and_valid_adapter_context_are_consistent(
    tmp_path, consumer,
):
    core, layer, k, a, b, _ = challenged(tmp_path)
    new, physical = fresh_after_challenge(core)
    layer.confirm(k, source_memory_id=new, confirmed_at=T4)
    response = builder(
        core, valid_candidates(core, layer, k, new),
    ).build(
        "r83", consumer=consumer, max_items=10, max_chars=2000,
    )

    assert [item["record"]["id"] for item in response["knowledge"]] == [k]
    assert [item["record"]["id"] for item in response["memories"]] == [new]
    assert response["retrieval_coverage"]["complete"] is True
    assert response["truncated"] is False
    assert response["selection_stats"]["retrieval_returned"] == 2
    assert response["selection_stats"]["omitted_budget"] == 0
    if consumer == "FAST":
        assert response["events"] == []
        assert response["selection_stats"]["items_used"] == 2
    else:
        # All distinct support/challenge events are retained in DEEP.
        event_ids = {entry["record"]["id"] for entry in response["events"]}
        assert event_ids == {
            uid("ev_", 8301), uid("ev_", 8302), physical.event_id,
        }
        assert response["selection_stats"]["items_used"] == 5


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
@pytest.mark.parametrize("defect", ["unsupported_kind", "wrong_record_id", "nan_score"])
def test_r83_invalid_adapter_rejected_before_context_or_provenance(
    tmp_path, consumer, defect,
):
    core, layer, k, a, b, _ = challenged(tmp_path)
    new, _ = fresh_after_challenge(core)
    layer.confirm(k, source_memory_id=new, confirmed_at=T4)
    records = valid_candidates(core, layer, k, new)
    corrupted = dict(records[1])
    if defect == "unsupported_kind":
        corrupted.update({
            "kind": "entity",
            "id": "ent-invalid",
            "record": {"id": "ent-invalid", "content": "cannot consume"},
        })
    elif defect == "wrong_record_id":
        corrupted["record"] = {
            **corrupted["record"], "id": uid("mem_", 8399),
        }
    else:
        corrupted["score"] = float("nan")
    before = snapshot(core)
    with pytest.raises(ValueError, match="Context Retrieval candidate"):
        builder(core, [records[0], corrupted], forbidden=True).build(
            "r83", consumer=consumer,
        )
    assert snapshot(core) == before


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
def test_r83_valid_adapter_budget_omission_is_not_false_full_context(
    tmp_path, consumer,
):
    core, layer, k, a, b, _ = challenged(tmp_path)
    new, _ = fresh_after_challenge(core)
    layer.confirm(k, source_memory_id=new, confirmed_at=T4)
    results = builder(core, valid_candidates(core, layer, k, new)).build(
        "r83", consumer=consumer, max_items=1, max_chars=2000,
    )
    assert results["retrieval_coverage"]["complete"] is True
    assert results["selection_stats"]["retrieval_returned"] == 2
    assert results["selection_stats"]["items_used"] == 1
    assert results["selection_stats"]["omitted_budget"] >= 1
    assert results["truncated"] is True


def test_r83_reopen_recovers_ledger_without_replaying_confirmed_proof(tmp_path):
    core, layer, k, a, b, _ = challenged(tmp_path)

    # Coordinator owns the third event projection and its done ledger.
    event = raw_event(core, 8304, at=T4)
    projected = core.event_processing.process(event)
    assert projected["action"] == "create"
    memory_id = projected["memory_id"]
    MemoryLifecycle(memory_store=core.memory_store).close(
        memory_id, closed_at=T4,
    )
    layer.confirm(k, source_memory_id=memory_id, confirmed_at=T4)
    before_history = layer.history(k)
    before_raw = core.event_log.log_file.read_bytes()
    before_sources = core.memory_store.source_events(memory_id)

    reopened = build_core(tmp_path)
    resumed = reopened.event_processing.recover()
    assert resumed["retried"] == 0
    replay = reopened.event_processing.process(event)
    assert replay["action"] == "already_done"
    assert replay["memory_id"] == memory_id
    assert reopened.event_processing.get(event.event_id)["attempts"] == 1
    assert KnowledgeLayer(memory_store=reopened.memory_store).history(
        k,
    ) == before_history
    assert reopened.memory_store.source_events(memory_id) == before_sources
    assert reopened.event_log.log_file.read_bytes() == before_raw


def test_r83_missing_physical_raw_blocks_proof_and_deep_context_until_repaired(
    tmp_path,
):
    core, layer, k, a, b, _ = challenged(tmp_path)
    new, event = fresh_after_challenge(core)
    original_raw = core.event_log.log_file.read_bytes()
    surviving = [
        line for line in original_raw.splitlines(keepends=True)
        if json.loads(line)["id"] != event.event_id
    ]
    assert len(surviving) == len(original_raw.splitlines()) - 1

    # Simulate loss of the actual Raw witness only in this temporary JSONL.
    core.event_log.log_file.write_bytes(b"".join(surviving))
    before = snapshot(core)
    with pytest.raises(ValueError, match="missing source Event"):
        layer.confirm(k, source_memory_id=new, confirmed_at=T4)
    assert snapshot(core) == before
    assert layer.get(k)["status"] == "challenged"
    assert support(core, k, new) == []

    # The adapter payload is structurally correct, yet DEEP's provenance
    # resolver must not silently invent the physically missing source.
    with pytest.raises(ValueError, match="Missing source event"):
        builder(
            core, valid_candidates(core, layer, k, new),
        ).build("r83", consumer="DEEP", max_items=10, max_chars=2000)
    assert snapshot(core) == before

    # Explicit restore of synthetic original Raw; no product auto-repair.
    core.event_log.log_file.write_bytes(original_raw)
    layer.confirm(k, source_memory_id=new, confirmed_at=T4)
    accepted = builder(
        core, valid_candidates(core, layer, k, new),
    ).build("r83", consumer="DEEP", max_items=10, max_chars=2000)
    assert event.event_id in {
        record["record"]["id"] for record in accepted["events"]
    }
    assert accepted["retrieval_coverage"]["complete"] is True


def test_r83_old_proof_stays_old_after_rechallenging_reconfirmed_knowledge(
    tmp_path,
):
    core, layer, k, a, b, _ = challenged(tmp_path)
    new, _ = fresh_after_challenge(core)
    layer.confirm(k, source_memory_id=new, confirmed_at=T4)
    layer.challenge(k, b, challenged_at=T5)
    before = snapshot(core)
    with pytest.raises(ValueError, match="new supporting evidence"):
        layer.confirm(k, source_memory_id=new, confirmed_at=T6)
    assert snapshot(core) == before
    assert layer.get(k)["status"] == "challenged"
