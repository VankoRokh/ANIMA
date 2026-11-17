"""H5.5 R1 regression: confirmed Evidence survives subsequent Memory mutations.

Based on the independent auditor's evidence_merge / evidence_update cases
in ANIMA_v0.2_H5.5_evidence.zip (frozen audit SHA 28e8438f...).
The tests run only against pytest tmp_path and do not read user instance data.

R1 policy: block an API mutation when ANY supports/contradicts relation
links that Memory to currently confirmed Knowledge. This intentionally
covers historical and future-dated dependencies until a formal Knowledge
revision/invalidation protocol exists; it is fail-closed rather than a new
temporal policy. Direct SQL modifications are out of API scope.
"""

from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.retrieval import RetrievalEngine
from labs.v02_h5_legacy_diagnostic import audit_snapshot


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"


def _uid(number):
    return "ev_" + str(UUID(int=(4 << 76) | (2 << 62) | number))


def _project(core, number, anchor):
    event = Event(
        "conversation.user",
        {"text": f"h55r1{anchor}: synthetic event {number}"},
        source="user",
        session_id="session_00000001",
        timestamp=T0,
        event_id=_uid(number),
    )
    core.event_log.write(event)
    result = core.event_processing.process(event)
    assert result["action"] == "create"
    return event, result["memory_id"]


def _confirmed(core, memory_id):
    lifecycle = MemoryLifecycle(memory_store=core.memory_store)
    knowledge = KnowledgeLayer(memory_store=core.memory_store)
    lifecycle.close(memory_id, closed_at=T1)
    claim_id = knowledge.create_candidate(
        domain="user",
        statement="h55r1knowledge temperature is stable",
        source_memory_id=memory_id,
        created_at=T2,
    )["knowledge"]["id"]
    confirmed = knowledge.confirm(claim_id, confirmed_at=T3)
    assert confirmed["knowledge"]["status"] == "confirmed"
    return lifecycle, knowledge, claim_id


def _assert_confirmed_usable(core, memory_id, claim_id):
    knowledge = KnowledgeLayer(memory_store=core.memory_store)
    assert knowledge.get(claim_id)["status"] == "confirmed"
    assert core.memory_store.get_memory(memory_id)["status"] == "closed"
    retrieved = RetrievalEngine(
        memory_store=core.memory_store,
        link_store=core.link_store,
    ).retrieve("h55r1knowledge", kinds=("knowledge",))
    assert claim_id in {item["id"] for item in retrieved["results"]}
    diagnostic = audit_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert diagnostic["status"] == "healthy", diagnostic["findings"]


def test_h55_r1_auditor_confirm_merge_rejected_atomically(tmp_path):
    core = build_core(tmp_path)
    source_event, source_id = _project(core, 101, "alpha")
    _target_event, target_id = _project(core, 102, "beta")
    assert source_id != target_id

    lifecycle, knowledge, claim_id = _confirmed(core, source_id)
    before_source = core.memory_store.get_memory(source_id)
    before_target = core.memory_store.get_memory(target_id)
    before_claim = knowledge.get(claim_id)
    before_history = knowledge.history(claim_id)
    before_raw = core.event_log.log_file.read_bytes()
    before_db = core.memory_store.database_file.read_bytes()
    before_source_events = core.memory_store.source_events(source_id)

    with pytest.raises(ValueError, match="confirmed Knowledge evidence"):
        lifecycle.merge(source_id, target_id, merged_at=T4)

    assert core.memory_store.get_memory(source_id) == before_source
    assert core.memory_store.get_memory(target_id) == before_target
    assert core.memory_store.source_events(source_id) == before_source_events
    assert knowledge.get(claim_id) == before_claim
    assert knowledge.history(claim_id) == before_history
    assert core.event_log.log_file.read_bytes() == before_raw
    assert core.memory_store.database_file.read_bytes() == before_db
    assert core.event_processing.get(source_event.event_id)["status"] == "done"
    _assert_confirmed_usable(core, source_id, claim_id)


@pytest.mark.parametrize(
    "changes",
    [
        {"content": "h55r1alpha: modified source truth"},
        {"status": "open"},
        {"importance": 3},
        {"closed_at": None},
    ],
    ids=["content", "reopen", "importance", "closed_at"],
)
def test_h55_r1_auditor_confirm_update_rejected_atomically(
    tmp_path, changes,
):
    core = build_core(tmp_path)
    _event, source_id = _project(core, 201, "alpha")
    _lifecycle, knowledge, claim_id = _confirmed(core, source_id)
    before_source = core.memory_store.get_memory(source_id)
    before_claim = knowledge.get(claim_id)
    before_history = knowledge.history(claim_id)
    before_db = core.memory_store.database_file.read_bytes()
    before_raw = core.event_log.log_file.read_bytes()

    with pytest.raises(ValueError, match="confirmed Knowledge evidence"):
        core.memory_store.update_memory(source_id, updated_at=T4, **changes)

    assert core.memory_store.get_memory(source_id) == before_source
    assert knowledge.get(claim_id) == before_claim
    assert knowledge.history(claim_id) == before_history
    assert core.memory_store.database_file.read_bytes() == before_db
    assert core.event_log.log_file.read_bytes() == before_raw
    _assert_confirmed_usable(core, source_id, claim_id)


def test_h55_r1_unrelated_memory_can_still_update_and_merge(tmp_path):
    core = build_core(tmp_path)
    _event_a, evidence_source = _project(core, 301, "confirmed")
    _event_b, unrelated_source = _project(core, 302, "unrelated")
    _event_c, merge_target = _project(core, 303, "target")
    lifecycle, knowledge, claim_id = _confirmed(core, evidence_source)

    updated = core.memory_store.update_memory(
        unrelated_source, importance=2, updated_at=T4,
    )
    assert updated["importance"] == 2
    result = lifecycle.merge(unrelated_source, merge_target, merged_at=T4)
    assert result["source"]["status"] == "merged"
    assert result["target"]["status"] == "open"
    assert knowledge.get(claim_id)["status"] == "confirmed"
    _assert_confirmed_usable(core, evidence_source, claim_id)


def test_h55_r1_unconfirmed_candidate_is_not_arbitrarily_frozen(tmp_path):
    core = build_core(tmp_path)
    _event, source_id = _project(core, 401, "alpha")
    lifecycle = MemoryLifecycle(memory_store=core.memory_store)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    lifecycle.close(source_id, closed_at=T1)
    candidate = layer.create_candidate(
        domain="user", statement="h55r1provisional statement",
        source_memory_id=source_id, created_at=T2,
    )["knowledge"]["id"]
    assert layer.get(candidate)["status"] == "provisional"
    updated = core.memory_store.update_memory(
        source_id, status="open", updated_at=T4,
    )
    assert updated["status"] == "open"
    assert layer.get(candidate)["status"] == "provisional"


def test_h55_r1_provisional_support_does_not_block_legacy_merge(tmp_path):
    core = build_core(tmp_path)
    _a, source_id = _project(core, 501, "alpha")
    _b, target_id = _project(core, 502, "beta")
    lifecycle = MemoryLifecycle(memory_store=core.memory_store)
    layer = KnowledgeLayer(memory_store=core.memory_store)
    lifecycle.close(source_id, closed_at=T1)
    candidate = layer.create_candidate(
        domain="user", statement="h55r1provisional merge case",
        source_memory_id=source_id, created_at=T2,
    )["knowledge"]["id"]
    result = lifecycle.merge(source_id, target_id, merged_at=T4)
    assert result["source"]["status"] == "merged"
    assert layer.get(candidate)["status"] == "provisional"
