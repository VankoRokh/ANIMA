"""ANIMA v0.2 H3.2: eligible records precede bounded Retrieval seeds.

This closes R1-S1 N8. All database data is created in pytest tmp_path.
The returned truncation flags describe the bounded candidate seed window,
not a claim that all FTS matches were materialized into the result list.
"""

from uuid import UUID

from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.retrieval import FTS_SEED_LIMIT, RetrievalEngine


STAMP = "2026-11-17T12:00:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    return store, links, RetrievalEngine(memory_store=store, link_store=links)


def memory(store, number, *, status="open", domain="project", content=None):
    return store.create_memory(
        memory_type="episodic", domain=domain, status=status,
        content=content or "filtermarker common text", importance=1,
        created_at=STAMP, source_event_id=uid("ev_", number),
        public_id=uid("mem_", number),
    )


def knowledge(links, number, *, status="provisional", domain="project"):
    return links.create_knowledge(
        domain=domain, status=status,
        statement="retrievalmarker common text", created_at=STAMP,
        public_id=uid("kn_", number),
    )


def ids(response):
    return [row["id"] for row in response["results"]]


def test_h3_2_merged_fts_seeds_cannot_hide_open_memory(tmp_path):
    store, _links, retrieval = stack(tmp_path)
    for i in range(FTS_SEED_LIMIT):
        memory(
            store, 100 + i, status="merged",
            content="filtermarker legacy entry",
        )
    live = memory(
        store, 200, status="open",
        content="filtermarker current entry",
    )

    response = retrieval.retrieve(
        "filtermarker", kinds=("memory",), top_k=10, relation_hops=0,
    )
    assert ids(response) == [live["id"]]
    assert response["stats"]["fts"] == 1
    assert response["stats"]["fts_truncated"] is False


def test_h3_2_explicit_merged_fts_retrieval_remains_possible(tmp_path):
    store, _links, retrieval = stack(tmp_path)
    archived = memory(store, 201, status="merged")
    memory(store, 202, status="open")
    response = retrieval.retrieve(
        "filtermarker", kinds=("memory",), top_k=10,
        memory_statuses={"merged"}, relation_hops=0,
    )
    assert ids(response) == [archived["id"]]


def test_h3_2_knowledge_terminal_decoys_do_not_hide_provisional(tmp_path):
    _store, links, retrieval = stack(tmp_path)
    for i in range(FTS_SEED_LIMIT):
        knowledge(links, 300 + i, status="rejected")
    candidate = knowledge(links, 400, status="provisional")
    response = retrieval.retrieve(
        "retrievalmarker", kinds=("knowledge",), relation_hops=0,
    )
    assert ids(response) == [candidate["id"]]
    assert response["stats"]["fts_truncated"] is False


def test_h3_2_structured_filter_excludes_terminal_before_limit(tmp_path):
    store, _links, retrieval = stack(tmp_path)
    live = memory(store, 500, status="open")
    # Latest 25 are terminal, so the previous query pre-LIMIT would hide live.
    for i in range(FTS_SEED_LIMIT):
        memory(store, 501 + i, status="merged")
    response = retrieval.retrieve(
        kinds=("memory",), domain="project", relation_hops=0, top_k=25,
    )
    assert ids(response) == [live["id"]]
    assert response["stats"]["filters"] == 1
    assert response["stats"]["filters_truncated"] is False


def test_h3_2_domain_filter_applies_inside_fts_before_limit(tmp_path):
    store, _links, retrieval = stack(tmp_path)
    for i in range(FTS_SEED_LIMIT):
        memory(store, 600 + i, domain="user")
    project = memory(store, 700, domain="project")
    response = retrieval.retrieve(
        "filtermarker", kinds=("memory",), domain="project",
        relation_hops=0, top_k=10,
    )
    assert ids(response) == [project["id"]]
    assert response["stats"]["fts_truncated"] is False


def test_h3_2_fts_truncation_is_truthful_after_eligibility(tmp_path):
    store, _links, retrieval = stack(tmp_path)
    for i in range(FTS_SEED_LIMIT + 5):
        memory(store, 800 + i)
    result = retrieval.retrieve(
        "filtermarker", kinds=("memory",), relation_hops=0,
        top_k=100,
    )
    assert len(result["results"]) == FTS_SEED_LIMIT
    assert result["stats"]["fts_truncated"] is True
    assert result["stats"]["candidates"] == FTS_SEED_LIMIT
    assert result["stats"]["returned"] == FTS_SEED_LIMIT


def test_h3_2_structured_truncation_is_truthful(tmp_path):
    store, _links, retrieval = stack(tmp_path)
    for i in range(FTS_SEED_LIMIT + 5):
        memory(store, 900 + i)
    result = retrieval.retrieve(
        kinds=("memory",), domain="project",
        relation_hops=0, top_k=100,
    )
    assert len(result["results"]) == FTS_SEED_LIMIT
    assert result["stats"]["filters_truncated"] is True
    assert result["stats"]["candidates"] == FTS_SEED_LIMIT


def test_h3_2_exact_seed_does_not_get_lost_to_fts_cap(tmp_path):
    store, _links, retrieval = stack(tmp_path)
    for i in range(FTS_SEED_LIMIT + 3):
        memory(store, 1000 + i)
    target = memory(store, 1200, content="filtermarker priority evidence")
    response = retrieval.retrieve(
        "filtermarker", object_ids=[target["id"]], kinds=("memory",),
        relation_hops=0, top_k=5,
    )
    assert ids(response)[0] == target["id"]
    assert response["stats"]["fts_truncated"] is True
