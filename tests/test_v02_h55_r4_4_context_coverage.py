"""ANIMA H5.5 R4.4 / F-07 — Context must not conceal Retrieval seed limits.

RetrievalEngine can return exactly 25 of >25 eligible FTS or structured
matches. Its stats truthfully flag a truncated seed window, even when
candidates == returned and Context has enough room for all 25 results.
ContextBuilder must carry that information without claiming completeness.

All fixtures live under pytest tmp_path, with real Raw Events, Memory FTS,
RetrievalEngine and ProvenanceResolver; no user instance data is accessed.
"""

from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import FTS_SEED_LIMIT, RetrievalEngine


STAMP = "2026-11-17T12:00:00+00:00"
TOKEN = "h55r44seedmarker"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


class TraceRecorder:
    def __init__(self):
        self.messages = []

    def record(self, message):
        self.messages.append(message)


def stack(tmp_path, count, *, trace=None):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    links = LinkStore(store)
    for i in range(count):
        event_id = uid("ev_", 1000 + i)
        item = Event(
            "conversation.user",
            {"text": f"{TOKEN}: independent source event {i}"},
            source="user",
            session_id="session_00000001",
            event_id=event_id,
            timestamp=STAMP,
        )
        log.write(item)
        store.create_memory(
            memory_type="episodic",
            domain="project",
            status="open",
            importance=1,
            content=f"{TOKEN} independent memory record {i}",
            created_at=STAMP,
            source_event_id=event_id,
            public_id=uid("mem_", 1000 + i),
        )
    retrieval = RetrievalEngine(memory_store=store, link_store=links)
    provenance = ProvenanceResolver(store, links, log)
    return ContextBuilder(
        retrieval=retrieval,
        provenance=provenance,
        trace=trace,
    )


def roomy(builder, *, query=TOKEN, retrieval_options=None, consumer="FAST"):
    return builder.build(
        query,
        consumer=consumer,
        max_items=100,
        max_chars=100_000,
        retrieval_options=retrieval_options or {"kinds": ("memory",)},
    )


def test_h55_r44_auditor_fts_seed_limit_cannot_report_complete_context(
    tmp_path,
):
    builder = stack(tmp_path, FTS_SEED_LIMIT + 5)
    bundle = roomy(builder)
    assert len(bundle["memories"]) == FTS_SEED_LIMIT
    assert bundle["selection_stats"]["retrieval_candidates"] == FTS_SEED_LIMIT
    assert bundle["selection_stats"]["retrieval_returned"] == FTS_SEED_LIMIT
    assert bundle["selection_stats"]["omitted_budget"] == 0
    assert bundle["retrieval_coverage"] == {
        "fts_truncated": True,
        "filters_truncated": False,
        "top_k_truncated": False,
        "complete": False,
    }
    # Before F-07 the same bundle incorrectly returned truncated=False.
    assert bundle["truncated"] is True


def test_h55_r44_structured_filter_seed_limit_is_visible(tmp_path):
    builder = stack(tmp_path, FTS_SEED_LIMIT + 5)
    bundle = roomy(
        builder, query=None,
        retrieval_options={
            "kinds": ("memory",),
            "domain": "project",
        },
    )
    assert len(bundle["memories"]) == FTS_SEED_LIMIT
    assert bundle["retrieval_coverage"] == {
        "fts_truncated": False,
        "filters_truncated": True,
        "top_k_truncated": False,
        "complete": False,
    }
    assert bundle["selection_stats"]["omitted_budget"] == 0
    assert bundle["truncated"] is True


def test_h55_r44_both_seed_limits_are_reported_independently(tmp_path):
    builder = stack(tmp_path, FTS_SEED_LIMIT + 5)
    bundle = roomy(
        builder,
        retrieval_options={
            "kinds": ("memory",),
            "domain": "project",
        },
    )
    assert bundle["retrieval_coverage"]["fts_truncated"] is True
    assert bundle["retrieval_coverage"]["filters_truncated"] is True
    assert bundle["retrieval_coverage"]["top_k_truncated"] is False
    assert bundle["retrieval_coverage"]["complete"] is False
    assert bundle["truncated"] is True
    assert bundle["selection_stats"]["omitted_budget"] == 0


def test_h55_r44_top_k_truncation_stays_distinct_from_seed_limits(tmp_path):
    builder = stack(tmp_path, 18)
    bundle = builder.build(
        TOKEN,
        consumer="FAST",
        max_items=1,
        max_chars=10000,
        retrieval_options={"kinds": ("memory",)},
    )
    assert bundle["retrieval_coverage"] == {
        "fts_truncated": False,
        "filters_truncated": False,
        "top_k_truncated": True,
        "complete": False,
    }
    assert len(bundle["memories"]) == 1
    assert bundle["selection_stats"]["retrieval_candidates"] == 18
    assert bundle["selection_stats"]["retrieval_returned"] == 12
    assert bundle["selection_stats"]["omitted_budget"] == 11
    assert bundle["truncated"] is True


def test_h55_r44_context_budget_only_does_not_falsely_truncate_retrieval(
    tmp_path,
):
    builder = stack(tmp_path, 2)
    bundle = builder.build(
        TOKEN,
        consumer="FAST",
        max_items=1,
        max_chars=10000,
        retrieval_options={"kinds": ("memory",)},
    )
    assert bundle["retrieval_coverage"] == {
        "fts_truncated": False,
        "filters_truncated": False,
        "top_k_truncated": False,
        "complete": True,
    }
    assert len(bundle["memories"]) == 1
    assert bundle["selection_stats"]["omitted_budget"] == 1
    assert bundle["truncated"] is True


def test_h55_r44_complete_retrieval_and_roomy_context_remain_not_truncated(
    tmp_path,
):
    builder = stack(tmp_path, 2)
    bundle = roomy(builder)
    assert len(bundle["memories"]) == 2
    assert bundle["selection_stats"]["omitted_budget"] == 0
    assert bundle["retrieval_coverage"]["complete"] is True
    assert bundle["truncated"] is False


def test_h55_r44_deep_context_preserves_incomplete_retrieval_with_events(
    tmp_path,
):
    builder = stack(tmp_path, FTS_SEED_LIMIT + 5)
    bundle = roomy(builder, consumer="DEEP")
    assert len(bundle["memories"]) == FTS_SEED_LIMIT
    assert len(bundle["events"]) == FTS_SEED_LIMIT
    assert bundle["selection_stats"]["omitted_budget"] == 0
    assert bundle["retrieval_coverage"]["fts_truncated"] is True
    assert bundle["retrieval_coverage"]["complete"] is False
    assert bundle["truncated"] is True
    event_ids = {row["record"]["id"] for row in bundle["events"]}
    assert len(event_ids) == FTS_SEED_LIMIT
    assert event_ids <= {
        uid("ev_", 1000 + i) for i in range(FTS_SEED_LIMIT + 5)
    }


def test_h55_r44_trace_reports_retrieval_coverage_not_just_total_truncation(
    tmp_path,
):
    trace = TraceRecorder()
    builder = stack(tmp_path, FTS_SEED_LIMIT + 5, trace=trace)
    bundle = roomy(builder)
    assert bundle["truncated"] is True
    assert len(trace.messages) == 1
    message = trace.messages[0]
    assert "retrieval_complete=false" in message
    assert "retrieval_fts_truncated=true" in message
    assert "retrieval_filters_truncated=false" in message
    assert "retrieval_top_k_truncated=false" in message
    assert "truncated=true" in message
