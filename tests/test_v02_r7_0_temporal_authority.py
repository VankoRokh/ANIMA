"""R7.0: independent H56-01/H56-02 invariants and temporal contracts.

No real instance data, no direct SQL corruption and no Date.now monkeypatch.
Every source Event is appended to a temporary canonical Raw EventLog.
"""

from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer


T0 = "2020-01-01T00:00:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T6 = "2020-01-01T00:06:00+00:00"
T8 = "2020-01-01T00:08:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def source(core, number):
    event = Event(
        "conversation.user",
        {"text": f"r70-temporal-{number}: durable independent observation"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", number),
        timestamp=T0,
    )
    core.event_log.write(event)
    memory = core.memory_store.create_memory(
        memory_type="episodic", domain="user", status="closed",
        content=event.payload["text"], created_at=T0,
        public_id=uid("mem_", number),
        source_event_id=event.event_id,
    )
    return memory["id"]


def case(root):
    core = build_core(root)
    a, b, c = (source(core, n) for n in (1701, 1702, 1703))
    layer = KnowledgeLayer(memory_store=core.memory_store)
    k = layer.create_candidate(
        domain="user", statement="R7.0 baseline has supporting Evidence",
        source_memory_id=a, created_at=T2, public_id=uid("kn_", 1701),
    )["knowledge"]["id"]
    return core, layer, k, a, b, c


def edge(core, memory_id, knowledge_id, relation_type, start, end=None):
    return core.link_store.create_relation(
        source_kind="memory",
        source_id=memory_id,
        relation_type=relation_type,
        target_kind="knowledge",
        target_id=knowledge_id,
        created_at=start,
        valid_until=end,
    )


def relations(core, knowledge_id):
    return core.link_store.relations_for(
        "knowledge", knowledge_id, direction="incoming",
    )


def state(core, layer, knowledge_id):
    return {
        "knowledge": layer.get(knowledge_id),
        "history": layer.history(knowledge_id),
        "relations": relations(core, knowledge_id),
        "raw": core.event_log.log_file.read_bytes(),
    }


def prepared_challenged(root, *, future_relation=False):
    core, layer, k, a, b, c = case(root)
    future = edge(core, c, k, "supports", FUTURE) if future_relation else None
    layer.confirm(k, confirmed_at=T3)
    layer.challenge(k, b, challenged_at=T4)
    assert layer.get(k)["status"] == "challenged"
    return core, layer, k, a, b, c, future


def test_r70_h5601_future_support_cannot_reconfirm_challenged(tmp_path):
    core, layer, k, a, b, c, future = prepared_challenged(
        tmp_path, future_relation=True,
    )
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="effective|new supporting evidence"):
        layer.confirm(k, source_memory_id=c, confirmed_at=T5)
    assert state(core, layer, k) == before
    assert future["created_at"] == FUTURE
    assert layer.get(k)["status"] == "challenged"


def test_r70_explicit_provisional_confirm_cannot_claim_future_support(tmp_path):
    core, layer, k, a, _b, c = case(tmp_path)
    future = edge(core, c, k, "supports", FUTURE)
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="effective|not active"):
        layer.confirm(k, source_memory_id=c, confirmed_at=T3)
    assert state(core, layer, k) == before
    assert future["id"] in {row["id"] for row in relations(core, k)}


def test_r70_old_support_cannot_reconfirm_challenged(tmp_path):
    core, layer, k, a, _b, _c, _ = prepared_challenged(tmp_path)
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="new supporting evidence"):
        layer.confirm(k, source_memory_id=a, confirmed_at=T5)
    assert state(core, layer, k) == before


def test_r70_h5601_default_clock_does_not_accept_2099_support(tmp_path):
    core, layer, k, _a, _b, c, _future = prepared_challenged(
        tmp_path, future_relation=True,
    )
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="effective|new supporting evidence"):
        layer.confirm(k, source_memory_id=c)
    assert state(core, layer, k) == before


def test_r70_expired_contradiction_does_not_reopen_silently(tmp_path):
    core, layer, k, _a, b, _c = case(tmp_path)
    finite = edge(core, b, k, "contradicts", T4, T5)
    layer.confirm(k, confirmed_at=T3)
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="not effective"):
        layer.challenge(k, b, challenged_at=T6)
    assert state(core, layer, k) == before
    assert finite["valid_until"] == T5


def test_r70_new_closed_raw_source_reconfirms_and_is_in_history(tmp_path):
    core, layer, k, a, _b, c, _ = prepared_challenged(tmp_path)
    before_count = len(relations(core, k))
    result = layer.confirm(k, source_memory_id=c, confirmed_at=T5)
    assert result["knowledge"]["status"] == "confirmed"
    assert len(relations(core, k)) == before_count + 1
    evidence = next(
        row for row in relations(core, k)
        if row["source_id"] == c and row["type"] == "supports"
    )
    assert evidence["created_at"] == T5
    assert evidence["valid_until"] is None
    history = layer.history(k)
    assert history[-1]["changes"]["support_relation"] == evidence["id"]


def test_r70_newly_effective_staged_support_may_reconfirm(tmp_path):
    core, layer, k, a, b, c = case(tmp_path)
    staged = edge(core, c, k, "supports", T5, T8)
    layer.confirm(k, confirmed_at=T3)
    layer.challenge(k, b, challenged_at=T4)
    before = relations(core, k)
    result = layer.confirm(k, source_memory_id=c, confirmed_at=T6)
    assert result["knowledge"]["status"] == "confirmed"
    assert relations(core, k) == before
    assert layer.history(k)[-1]["changes"]["support_relation"] == staged["id"]


@pytest.mark.parametrize("future_opposite", [False, True], ids=["finite", "finite_future_support"])
def test_r70_h5602_challenge_reuses_finite_contradiction(tmp_path, future_opposite):
    core, layer, k, a, b, _c = case(tmp_path)
    finite = edge(core, b, k, "contradicts", T4, T8)
    future = (
        edge(core, b, k, "supports", T8)
        if future_opposite else None
    )
    layer.confirm(k, confirmed_at=T3)
    before = relations(core, k)
    result = layer.challenge(k, b, challenged_at=T5)
    assert result["knowledge"]["status"] == "challenged"
    assert relations(core, k) == before
    assert layer.history(k)[-1]["changes"]["contradiction_relation"] == finite["id"]
    assert finite["valid_until"] == T8
    if future is not None:
        assert future["created_at"] == T8


@pytest.mark.parametrize("explicit", [False, True], ids=["implicit", "explicit"])
def test_r70_h5602_reject_reuses_finite_contradiction(tmp_path, explicit):
    core, layer, k, a, b, c = case(tmp_path)
    finite = edge(core, b, k, "contradicts", T4, T8)
    layer.confirm(k, confirmed_at=T3)
    layer.challenge(k, c, challenged_at=T4)
    before = relations(core, k)
    result = layer.reject(
        k,
        contradiction_memory_id=b if explicit else None,
        rejected_at=T5,
    )
    assert result["knowledge"]["status"] == "rejected"
    assert relations(core, k) == before
    assert finite["valid_until"] == T8
    if explicit:
        assert layer.history(k)[-1]["changes"]["contradiction_relation"] == finite["id"]


def test_r70_finite_contradiction_end_excludes_challenge(tmp_path):
    core, layer, k, a, b, c = case(tmp_path)
    finite = edge(core, b, k, "contradicts", T4, T8)
    future = edge(core, b, k, "supports", T8)
    layer.confirm(k, confirmed_at=T3)
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="both support and contradict"):
        layer.challenge(k, b, challenged_at=T8)
    assert state(core, layer, k) == before
    assert finite["valid_until"] == future["created_at"]


def test_r70_finite_contradiction_offset_aware_reuse(tmp_path):
    core, layer, k, a, b, _c = case(tmp_path)
    finite = edge(
        core, b, k, "contradicts",
        "2020-01-01T03:04:00+03:00",
        "2020-01-01T03:08:00+03:00",
    )
    layer.confirm(k, confirmed_at=T3)
    before = relations(core, k)
    layer.challenge(
        k, b, challenged_at="2020-01-01T03:05:00+03:00",
    )
    assert relations(core, k) == before
    assert layer.history(k)[-1]["changes"]["contradiction_relation"] == finite["id"]


def test_r70_initial_confirm_retains_finite_support_without_extension(tmp_path):
    core = build_core(tmp_path)
    a = source(core, 1730)
    k = core.link_store.create_knowledge(
        domain="user", statement="R7.0 finite support",
        created_at=T2, public_id=uid("kn_", 1730),
    )["id"]
    finite = edge(core, a, k, "supports", T2, T8)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    before = relations(core, k)
    layer.confirm(k, source_memory_id=a, confirmed_at=T5)
    assert relations(core, k) == before
    assert layer.history(k)[-1]["changes"]["support_relation"] == finite["id"]


def test_r70_old_expired_source_cannot_be_reasserted_to_clear_challenge(tmp_path):
    core = build_core(tmp_path)
    a, b = source(core, 1731), source(core, 1732)
    k = core.link_store.create_knowledge(
        domain="user", statement="R7.0 source version is immutable",
        created_at=T2, public_id=uid("kn_", 1731),
    )["id"]
    edge(core, a, k, "supports", T2, T5)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    layer.confirm(k, confirmed_at=T3)
    layer.challenge(k, b, challenged_at=T4)
    before = state(core, layer, k)
    # The same source A was already used to support K. Starting another
    # identical support at T6 is not new independent evidence.
    with pytest.raises(ValueError, match="new supporting evidence"):
        layer.confirm(k, source_memory_id=a, confirmed_at=T6)
    assert state(core, layer, k) == before
