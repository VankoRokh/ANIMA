"""R8.0 / H57-01: same-instant fresh proof is not its own prior support.

All fixtures are isolated temporary Core instances with canonical Raw Event
records. No SQL damage, repository modification, or real user instance data.
"""
import json
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle


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


def source(core, number, *, at=T0, status="closed"):
    event = Event(
        "conversation.user",
        {"text": f"r80-h5701-{number}: genuine Raw observation"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", number),
        timestamp=at,
    )
    core.event_log.write(event)
    record = core.memory_store.create_memory(
        memory_type="episodic", domain="user", status=status,
        content=event.payload["text"], created_at=at,
        public_id=uid("mem_", number),
        source_event_id=event.event_id,
    )
    return record["id"], event


def initial(root, *, staged_start=None, staged_end=None):
    core = build_core(root)
    a, _ = source(core, 8001)
    b, _ = source(core, 8002)
    c, _ = source(core, 8003)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    k = layer.create_candidate(
        domain="user", statement="R8.0 initial knowledge",
        source_memory_id=a, created_at=T2,
        public_id=uid("kn_", 8001),
    )["knowledge"]["id"]
    staged = None
    if staged_start is not None:
        staged = core.link_store.create_relation(
            source_kind="memory", source_id=c,
            relation_type="supports",
            target_kind="knowledge", target_id=k,
            created_at=staged_start, valid_until=staged_end,
        )
    layer.confirm(k, confirmed_at=T3)
    return core, layer, k, a, b, c, staged


def challenged(root, *, staged_start=None, staged_end=None):
    core, layer, k, a, b, c, staged = initial(
        root, staged_start=staged_start, staged_end=staged_end,
    )
    layer.challenge(k, b, challenged_at=T4)
    assert layer.get(k)["status"] == "challenged"
    return core, layer, k, a, b, c, staged


def state(core, layer, k):
    return {
        "knowledge": layer.get(k),
        "history": layer.history(k),
        "relations": core.link_store.relations_for(
            "knowledge", k, direction="incoming",
        ),
        "raw": core.event_log.log_file.read_bytes(),
    }


def support(core, k, memory_id):
    return [
        relation for relation in core.link_store.relations_for(
            "knowledge", k, direction="incoming",
            relation_types={"supports"},
        )
        if relation["source_memory_id"] == memory_id
    ]


@pytest.mark.parametrize(
    "confirmed_at",
    [T4, "2020-01-01T04:04:00+04:00"],
    ids=["identical_string", "identical_instant_different_offset"],
)
def test_r80_new_raw_proof_confirmed_at_challenge_instant(tmp_path, confirmed_at):
    core, layer, k, a, b, c, _ = challenged(tmp_path)
    before = state(core, layer, k)
    result = layer.confirm(
        k, source_memory_id=c, confirmed_at=confirmed_at,
    )
    assert result["knowledge"]["status"] == "confirmed"
    proof = support(core, k, c)
    assert len(proof) == 1
    assert proof[0]["created_at"] == confirmed_at
    assert proof[0]["valid_until"] is None
    assert len(state(core, layer, k)["relations"]) == len(before["relations"]) + 1
    assert layer.history(k)[-1]["source_id"] == c
    assert layer.history(k)[-1]["changes"]["support_relation"] == proof[0]["id"]
    assert core.event_log.log_file.read_bytes() == before["raw"]


def test_r80_default_clock_calls_accept_raw_observed_after_challenge(
    tmp_path, monkeypatch,
):
    core, layer, k, a, b, _c, _ = initial(tmp_path)
    # Calls omit both challenged_at and confirmed_at. Force both clock
    # reads into the same second without sleep/real-time flakiness.
    monkeypatch.setattr(KnowledgeLayer, "_now", staticmethod(lambda: T4))
    assert layer.challenge(k, b)["knowledge"]["status"] == "challenged"

    # Only now append the physical Raw Event and create/close its Memory.
    fresh, event = source(core, 8004, at=T4, status="open")
    MemoryLifecycle(memory_store=core.memory_store).close(
        fresh, closed_at=T4,
    )
    assert core.memory_store.source_events(fresh) == [event.event_id]
    assert layer.confirm(
        k, source_memory_id=fresh,
    )["knowledge"]["status"] == "confirmed"
    proof = support(core, k, fresh)
    assert len(proof) == 1
    assert proof[0]["created_at"] == T4
    assert layer.history(k)[-1]["changes"]["support_relation"] == proof[0]["id"]


@pytest.mark.parametrize("at", [T4, T5], ids=["equal", "later"])
def test_r80_old_support_still_rejected_and_rolled_back(tmp_path, at):
    core, layer, k, a, b, c, _ = challenged(tmp_path)
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="new supporting evidence"):
        layer.confirm(k, source_memory_id=a, confirmed_at=at)
    assert state(core, layer, k) == before
    assert layer.get(k)["status"] == "challenged"


@pytest.mark.parametrize(
    "staged_start",
    [T4, "2020-01-01T04:04:00+04:00"],
    ids=["same_offset", "equivalent_offset"],
)
def test_r80_preexisting_staged_support_at_challenge_instant_is_old(
    tmp_path, staged_start,
):
    core, layer, k, a, b, c, staged = challenged(
        tmp_path, staged_start=staged_start,
    )
    assert staged is not None
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="new supporting evidence"):
        layer.confirm(k, source_memory_id=c, confirmed_at=T4)
    assert state(core, layer, k) == before
    assert support(core, k, c)[0]["id"] == staged["id"]


def test_r80_preexisting_support_later_than_challenge_stays_valid(tmp_path):
    core, layer, k, a, b, c, staged = challenged(
        tmp_path, staged_start=T5, staged_end=T8,
    )
    before = state(core, layer, k)
    result = layer.confirm(k, source_memory_id=c, confirmed_at=T5)
    assert result["knowledge"]["status"] == "confirmed"
    assert support(core, k, c) == [staged]
    assert len(state(core, layer, k)["relations"]) == len(before["relations"])
    assert layer.history(k)[-1]["changes"]["support_relation"] == staged["id"]


@pytest.mark.parametrize(
    "staged_start,staged_end,at",
    [
        (FUTURE, None, T4),
        (FUTURE, None, T5),
        (T2, T4, T4),
    ],
    ids=["future_equal", "future_later", "expired_equal"],
)
def test_r80_future_or_expired_support_cannot_be_reasserted(
    tmp_path, staged_start, staged_end, at,
):
    core, layer, k, a, b, c, staged = challenged(
        tmp_path, staged_start=staged_start, staged_end=staged_end,
    )
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="not effective|new supporting evidence"):
        layer.confirm(k, source_memory_id=c, confirmed_at=at)
    assert state(core, layer, k) == before
    assert support(core, k, c)[0]["id"] == staged["id"]


def test_r80_missing_physical_raw_rolls_back_equal_instant_new_support(tmp_path):
    core, layer, k, a, b, c, _ = challenged(tmp_path)
    # Corrupt *only* disposable Raw so memory_sources points to a missing
    # physical Event. Novelty may pass, but Raw provenance must fail.
    raw = core.event_log.log_file.read_bytes().splitlines(keepends=True)
    remaining = [
        line for line in raw
        if json.loads(line)["id"] != uid("ev_", 8003)
    ]
    assert len(remaining) + 1 == len(raw)
    core.event_log.log_file.write_bytes(b"".join(remaining))
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="missing source Event"):
        layer.confirm(k, source_memory_id=c, confirmed_at=T4)
    assert state(core, layer, k) == before
    assert support(core, k, c) == []


def test_r80_challenged_confirm_without_new_source_still_refused(tmp_path):
    core, layer, k, a, b, c, _ = challenged(tmp_path)
    before = state(core, layer, k)
    with pytest.raises(ValueError, match="new supporting evidence"):
        layer.confirm(k, confirmed_at=T4)
    assert state(core, layer, k) == before
