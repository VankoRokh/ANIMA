"""R6.3 — NEW-04 finite Evidence reuse and NEW-05 adapter coverage.

All SQLite fixtures use pytest tmp_path. Legacy SQL injection is not needed
for the valid disjoint half-open Evidence windows in these cases.
"""

from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def finite_evidence(tmp_path):
    core = build_core(tmp_path)
    event = Event(
        "conversation.user",
        {"text": "r63finite: source measurement for finite Evidence"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", 1301),
        timestamp=T0,
    )
    core.event_log.write(event)
    created = core.event_processing.process(event)
    assert created["action"] == "create"
    memory_id = created["memory_id"]
    MemoryLifecycle(memory_store=core.memory_store).close(
        memory_id, closed_at=T1,
    )
    knowledge_id = core.link_store.create_knowledge(
        domain="user",
        statement="Finite source supports this baseline.",
        created_at=T2,
        public_id=uid("kn_", 1301),
    )["id"]
    links = core.link_store
    support = links.create_relation(
        source_kind="memory", source_id=memory_id,
        relation_type="supports", target_kind="knowledge",
        target_id=knowledge_id, created_at=T2, valid_until=T5,
    )
    contradiction = links.create_relation(
        source_kind="memory", source_id=memory_id,
        relation_type="contradicts", target_kind="knowledge",
        target_id=knowledge_id, created_at=T5,
    )
    return core, KnowledgeLayer(memory_store=core.memory_store), memory_id, knowledge_id, support, contradiction


@pytest.mark.parametrize("explicit", [False, True], ids=["implicit", "explicit"])
def test_r63_finite_support_reused_without_creating_overlap(tmp_path, explicit):
    core, layer, source, claim, support, contradiction = finite_evidence(tmp_path)
    before_relations = core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    )
    before_raw = core.event_log.log_file.read_bytes()
    kwargs = {"source_memory_id": source} if explicit else {}
    result = layer.confirm(claim, confirmed_at=T3, **kwargs)
    assert result["knowledge"]["status"] == "confirmed"
    # KnowledgeLayer.describe() deliberately projects Relations at the
    # current wall-clock time, not at historical confirmed_at. Inspect
    # effective evidence at the transition instant via LinkStore.
    active_at_confirmation = core.link_store.relations_for(
        "knowledge", claim, direction="incoming", active_at=T3,
    )
    assert [row["source_memory_id"] for row in active_at_confirmation
            if row["type"] == "supports"] == [source]
    assert not any(
        row["type"] == "contradicts" for row in active_at_confirmation
    )
    assert core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    ) == before_relations
    assert support["valid_until"] == T5
    assert contradiction["created_at"] == T5
    assert core.event_log.log_file.read_bytes() == before_raw
    operations = layer.history(claim)
    assert [row["operation"] for row in operations] == ["confirm"]
    if explicit:
        assert operations[0]["changes"]["support_relation"] == support["id"]


def test_r63_finite_support_end_is_exclusive_for_explicit_confirm(tmp_path):
    core, layer, source, claim, support, contradiction = finite_evidence(tmp_path)
    with pytest.raises(ValueError, match="both support and contradict"):
        layer.confirm(claim, source_memory_id=source, confirmed_at=T5)
    assert layer.get(claim)["status"] == "provisional"
    assert layer.history(claim) == []
    relations = core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    )
    assert {row["id"] for row in relations} == {support["id"], contradiction["id"]}


def test_r63_finite_support_offsets_compared_as_instants(tmp_path):
    core, layer, source, claim, support, _ = finite_evidence(tmp_path)
    confirmed = layer.confirm(
        claim,
        source_memory_id=source,
        confirmed_at="2020-01-01T03:04:00+03:00",
    )
    assert confirmed["knowledge"]["status"] == "confirmed"
    assert layer.history(claim)[0]["changes"]["support_relation"] == support["id"]
    assert len(core.link_store.relations_for(
        "knowledge", claim, direction="incoming",
    )) == 2


class StubRetrieval:
    def __init__(self, results=None, stats=None, *, include_stats=True):
        self.results = [] if results is None else results
        self.stats = stats
        self.include_stats = include_stats

    def retrieve(self, query, *, top_k, relation_hops, **options):
        response = {"results": self.results}
        if self.include_stats:
            response["stats"] = self.stats
        return response


def bundle(stats, results=None, *, include_stats=True):
    builder = ContextBuilder(
        retrieval=StubRetrieval(
            results=results, stats=stats, include_stats=include_stats,
        ),
        provenance=None,
    )
    return builder.build("r63context", consumer="FAST", max_items=10)


def valid_stats(*, candidates=0, returned=0):
    return {
        "fts_truncated": False,
        "filters_truncated": False,
        "candidates": candidates,
        "returned": returned,
    }


def one_candidate():
    return [{
        "kind": "memory",
        "id": uid("mem_", 1360),
        "score": 1,
        "reasons": [],
        "record": {
            "id": uid("mem_", 1360),
            "content": "R6.3 observed candidate",
        },
    }]


def test_r63_valid_adapter_can_prove_complete():
    result = bundle(valid_stats())
    assert result["retrieval_coverage"] == {
        "fts_truncated": False,
        "filters_truncated": False,
        "top_k_truncated": False,
        "complete": True,
    }
    assert result["truncated"] is False


@pytest.mark.parametrize("override", [
    {"fts_truncated": None},
    {"fts_truncated": 0},
    {"fts_truncated": "false"},
    {"filters_truncated": None},
    {"filters_truncated": 1},
])
def test_r63_unreliable_flags_must_not_claim_complete(override):
    result = bundle({**valid_stats(), **override})
    coverage = result["retrieval_coverage"]
    assert coverage["complete"] is False
    assert result["truncated"] is True
    if "fts_truncated" in override:
        assert coverage["fts_truncated"] is None
        assert coverage["filters_truncated"] is False
    else:
        assert coverage["filters_truncated"] is None
        assert coverage["fts_truncated"] is False
    assert coverage["top_k_truncated"] is False


def test_r63_missing_flags_or_stats_are_unknown_not_complete():
    partial = bundle({"candidates": 0, "returned": 0})
    assert partial["retrieval_coverage"] == {
        "fts_truncated": None,
        "filters_truncated": None,
        "top_k_truncated": False,
        "complete": False,
    }
    assert partial["truncated"] is True
    absent = bundle(None, include_stats=False)
    assert absent["retrieval_coverage"] == {
        "fts_truncated": None,
        "filters_truncated": None,
        "top_k_truncated": None,
        "complete": False,
    }
    assert absent["selection_stats"]["retrieval_candidates"] is None
    assert absent["selection_stats"]["retrieval_returned"] == 0


@pytest.mark.parametrize("counts", [
    {"candidates": None, "returned": 1},
    {"candidates": 0, "returned": 1},
    {"candidates": 1, "returned": 0},
    {"candidates": 1, "returned": True},
    {"candidates": True, "returned": 1},
    {"candidates": -1, "returned": 1},
    {"candidates": "1", "returned": 1},
])
def test_r63_inconsistent_adapter_counts_are_unknown(counts):
    result = bundle({**valid_stats(), **counts}, results=one_candidate())
    coverage = result["retrieval_coverage"]
    assert coverage["fts_truncated"] is False
    assert coverage["filters_truncated"] is False
    assert coverage["top_k_truncated"] is None
    assert coverage["complete"] is False
    assert result["truncated"] is True
    assert result["selection_stats"]["retrieval_candidates"] is None
    assert result["selection_stats"]["retrieval_returned"] == 1


def test_r63_verified_top_k_truncation_stays_distinct_from_unknown():
    result = bundle(
        valid_stats(candidates=2, returned=1),
        results=one_candidate(),
    )
    assert result["retrieval_coverage"] == {
        "fts_truncated": False,
        "filters_truncated": False,
        "top_k_truncated": True,
        "complete": False,
    }
    assert result["selection_stats"]["retrieval_candidates"] == 2
    assert result["selection_stats"]["retrieval_returned"] == 1


def test_r63_adapter_must_supply_result_list():
    builder = ContextBuilder(
        retrieval=StubRetrieval(results="not-a-list", stats=valid_stats()),
        provenance=None,
    )
    with pytest.raises(ValueError, match="results must be a list"):
        builder.build("r63context")
