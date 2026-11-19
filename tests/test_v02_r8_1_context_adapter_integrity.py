"""R8.1 / H57-02: invalid Retrieval adapters cannot claim complete Context.

No SQL, Raw mutation or real user data. Stub adapters return only synthetic
in-memory response dictionaries; both FAST and DEEP consumers are covered.
"""
from copy import deepcopy

import pytest

from anima.memory.context_builder import ContextBuilder


MEMORY_ID = "mem_r81_valid"
KNOWLEDGE_ID = "kn_r81_valid"


class StubRetrieval:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def retrieve(self, query, *, top_k, relation_hops, **options):
        self.calls.append((query, top_k, relation_hops, options))
        return self.response


class EmptyProvenance:
    def knowledge(self, knowledge_id):
        return {"sources": []}

    def memory(self, memory_id):
        return {"events": []}


def candidate(kind="memory", *, exact=False):
    ident = MEMORY_ID if kind == "memory" else KNOWLEDGE_ID
    record = {
        "id": ident,
        "content": "A synthetic measured episode",
    } if kind == "memory" else {
        "id": ident,
        "statement": "A synthetic verified claim",
    }
    return {
        "kind": kind,
        "id": ident,
        "record": record,
        "score": 1,
        "reasons": ["exact_id:+100"] if exact else [],
    }


def response(results, *, stats=None):
    if stats is None:
        stats = {
            "candidates": len(results),
            "returned": len(results),
            "fts_truncated": False,
            "filters_truncated": False,
        }
    return {"results": results, "stats": stats}


def build(results, *, consumer="FAST", stats=None):
    adapter = StubRetrieval(response(results, stats=stats))
    builder = ContextBuilder(
        retrieval=adapter,
        provenance=EmptyProvenance(),
    )
    return builder.build(
        "r81 synthetic query", consumer=consumer,
    )


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
@pytest.mark.parametrize("exact", [False, True], ids=["ordinary", "exact"])
def test_r81_h5702_entity_candidate_is_rejected_not_silently_lost(
    consumer, exact,
):
    unknown = candidate("entity", exact=exact)
    unknown["id"] = "ent_r81"
    unknown["record"] = {"id": "ent_r81", "content": "would disappear"}
    with pytest.raises(ValueError, match="candidate 0 kind"):
        build([unknown], consumer=consumer)


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
@pytest.mark.parametrize("unknown_index", [0, 1])
def test_r81_mixed_valid_and_unknown_candidate_rejects_entire_response(
    consumer, unknown_index,
):
    valid = candidate("memory")
    unsupported = candidate("entity")
    items = [valid, unsupported] if unknown_index else [unsupported, valid]
    with pytest.raises(ValueError, match="kind must be knowledge or memory"):
        build(items, consumer=consumer)


@pytest.mark.parametrize(
    "kind",
    [None, "entity", "event", "Memory", "", 0, [], {}],
    ids=["missing", "entity", "event", "wrong_case", "empty", "int", "list", "dict"],
)
def test_r81_unknown_candidate_kinds_fail_closed(kind):
    item = candidate()
    item["kind"] = kind
    with pytest.raises(ValueError, match="kind must be knowledge or memory"):
        build([item])


@pytest.mark.parametrize(
    "item",
    [None, [], "not-an-item", 1, False],
    ids=["none", "list", "string", "number", "bool"],
)
def test_r81_candidate_itself_must_be_dict(item):
    with pytest.raises(ValueError, match="candidate 0 must be a dict"):
        build([item])


@pytest.mark.parametrize(
    "bad_id",
    [None, "", " ", 23, [], {}],
    ids=["missing", "empty", "whitespace", "number", "list", "dict"],
)
def test_r81_candidate_id_must_be_nonempty_string(bad_id):
    item = candidate()
    item["id"] = bad_id
    with pytest.raises(ValueError, match="candidate 0 id"):
        build([item])


@pytest.mark.parametrize(
    "bad_record",
    [
        None, [], "string", {},
        {"id": "mem_wrong", "content": "another owner"},
        {"id": MEMORY_ID},
        {"id": MEMORY_ID, "content": None},
        {"id": MEMORY_ID, "content": 123},
    ],
    ids=[
        "none", "list", "string", "empty", "mismatch",
        "no_content", "null_content", "numeric_content",
    ],
)
def test_r81_memory_candidate_requires_matching_record_and_text(bad_record):
    item = candidate()
    item["record"] = bad_record
    with pytest.raises(ValueError, match="candidate 0 record"):
        build([item])


@pytest.mark.parametrize(
    "bad_record",
    [
        {"id": KNOWLEDGE_ID},
        {"id": KNOWLEDGE_ID, "statement": None},
        {"id": KNOWLEDGE_ID, "statement": []},
        {"id": "kn_other", "statement": "mismatched"},
    ],
    ids=["no_statement", "null_statement", "list_statement", "mismatched_id"],
)
def test_r81_knowledge_candidate_requires_matching_record_and_statement(
    bad_record,
):
    item = candidate("knowledge")
    item["record"] = bad_record
    with pytest.raises(ValueError, match="candidate 0 record"):
        build([item])


@pytest.mark.parametrize(
    "reasons",
    [None, "exact_id:+100", {}, [None], [1], [""], ["valid", True]],
    ids=["missing", "string", "dict", "none_item", "int_item", "empty_item", "mixed"],
)
def test_r81_reasons_must_be_string_list(reasons):
    item = candidate()
    item["reasons"] = reasons
    with pytest.raises(ValueError, match="candidate 0 reasons"):
        build([item])


@pytest.mark.parametrize(
    "score",
    [None, True, False, "1", [], float("nan"), float("inf"), -float("inf")],
    ids=["missing", "true", "false", "string", "list", "nan", "inf", "minus_inf"],
)
def test_r81_score_must_be_finite_numeric(score):
    item = candidate()
    item["score"] = score
    with pytest.raises(ValueError, match="candidate 0 score"):
        build([item])


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
@pytest.mark.parametrize("kind", ["memory", "knowledge"])
def test_r81_valid_adapters_keep_selection_coverage_and_budget(consumer, kind):
    item = candidate(kind)
    original = deepcopy(item)
    result = build([item], consumer=consumer)
    bucket = "memories" if kind == "memory" else "knowledge"
    other = "knowledge" if kind == "memory" else "memories"
    assert result[bucket][0]["record"]["id"] == item["id"]
    assert result[other] == []
    assert result["selection_stats"]["retrieval_returned"] == 1
    assert result["selection_stats"]["items_used"] == 1
    assert result["selection_stats"]["omitted_budget"] == 0
    assert result["retrieval_coverage"]["complete"] is True
    assert result["truncated"] is False
    assert item == original


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
def test_r81_valid_empty_response_is_still_complete(consumer):
    result = build([], consumer=consumer)
    assert result["retrieval_coverage"]["complete"] is True
    assert result["truncated"] is False
    assert result["selection_stats"]["retrieval_returned"] == 0
    assert result["selection_stats"]["items_used"] == 0


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
def test_r81_missing_stats_remains_incomplete_for_valid_items(consumer):
    item = candidate("memory")
    adapter = StubRetrieval({"results": [item]})
    builder = ContextBuilder(
        retrieval=adapter,
        provenance=EmptyProvenance(),
    )
    result = builder.build("r81 query", consumer=consumer)
    assert result["selection_stats"]["items_used"] == 1
    assert result["retrieval_coverage"]["complete"] is False
    assert result["truncated"] is True
    assert result["retrieval_coverage"]["top_k_truncated"] is None


@pytest.mark.parametrize("consumer", ["FAST", "DEEP"])
def test_r81_budget_omission_is_not_reclassified_as_bad_payload(consumer):
    two = [candidate("knowledge"), candidate("memory")]
    adapter = StubRetrieval(response(two))
    builder = ContextBuilder(
        retrieval=adapter,
        provenance=EmptyProvenance(),
    )
    result = builder.build(
        "r81 query", consumer=consumer, max_items=1,
    )
    assert result["selection_stats"]["retrieval_returned"] == 2
    assert result["selection_stats"]["items_used"] == 1
    assert result["selection_stats"]["omitted_budget"] == 1
    assert result["retrieval_coverage"]["complete"] is True
    assert result["truncated"] is True
