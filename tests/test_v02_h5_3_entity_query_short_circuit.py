"""H5.3c: prove removing zero-value Entity SQL reads is behavior-preserving.

These tests use disposable Raw/SQLite stores and do not relax the H4
authority contract: Event.references does not create verified about links.
"""

from uuid import UUID

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor


STAMP = "2026-11-17T12:00:00+00:00"


def _id(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def _stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    links = LinkStore(store)
    processor = MemoryProcessor(
        memory_store=store, event_log=log, link_store=links,
    )
    return processor, log, store, links


def _event(n, group, references=None):
    return Event(
        "conversation.user",
        {
            "text": (
                f"h53group{group:02d}: sensor calibration "
                f"status verified reading{n:06d} synthetic rig"
            )
        },
        source="user", session_id="session_00000001",
        event_id=_id("ev_", n), timestamp=STAMP,
        references=references or [],
    )


def test_h53c_no_entity_sql_for_eight_unverified_streams(tmp_path, monkeypatch):
    processor, log, store, _links = _stack(tmp_path)

    def query_must_not_be_called(_memory_id):
        raise AssertionError("Unverified Event caused an Entity SQL query")

    monkeypatch.setattr(
        processor, "_memory_entities", query_must_not_be_called,
    )
    actions = []
    for n in range(1, 17):
        event = _event(n, (n - 1) % 8)
        log.write(event)
        actions.append(processor.process_event(event)["action"])

    assert actions[:8] == ["create"] * 8
    assert actions[8:] == ["update"] * 8
    assert store.count() == 8
    assert sum(
        len(store.source_events(row["id"]))
        for row in store.list_memories()
    ) == 16


def test_h53c_registered_active_unverified_id_does_not_trigger_sql(
    tmp_path, monkeypatch,
):
    processor, log, store, links = _stack(tmp_path)
    declared_entity = links.create_entity(
        entity_type="object", canonical_name="Vega",
        public_id=_id("ent_", 101),
    )["id"]

    def query_must_not_be_called(_memory_id):
        raise AssertionError("Self-declared ID was treated as authorized")

    monkeypatch.setattr(
        processor, "_memory_entities", query_must_not_be_called,
    )
    results = []
    for n in (101, 102):
        event = _event(
            n, 0, references=[{"kind": "entity", "id": declared_entity}],
        )
        log.write(event)
        results.append(processor.process_event(event))

    assert results[0]["action"] == "create"
    assert results[1]["action"] == "update"
    assert results[0]["memory_id"] == results[1]["memory_id"]
    assert store.count() == 1
    assert links.relations_for(
        "memory", results[0]["memory_id"], direction="outgoing",
        relation_types={"about"},
    ) == []
    assert all(
        row["references"] == [{"kind": "entity", "id": declared_entity}]
        for row in log.load_events()
    )


def test_h53c_explicit_nonempty_authorized_ids_keep_original_overlap_score(
    tmp_path, monkeypatch,
):
    processor, log, store, _links = _stack(tmp_path)
    original = _event(201, 0)
    log.write(original)
    result = processor.process_event(original)
    candidate = store.get_memory(result["memory_id"])
    followup = _event(202, 0)
    event_index = {row["id"]: row for row in log.load_events()}
    calls = []
    entity_id = _id("ent_", 202)

    def supply_authorized_entities(memory_id):
        calls.append(memory_id)
        return {entity_id}

    monkeypatch.setattr(
        processor, "_memory_entities", supply_authorized_entities,
    )
    without = processor._score_candidate(
        candidate, followup, followup.payload["text"],
        [], event_index,
    )
    assert calls == []
    with_overlap = processor._score_candidate(
        candidate, followup, followup.payload["text"],
        [entity_id], event_index,
    )
    assert calls == [candidate["id"]]
    assert without["entity_overlap"] == 0
    assert with_overlap["entity_overlap"] == 1
    assert with_overlap["score"] == without["score"] + 1
    assert "entity_overlap:+1" in with_overlap["reasons"]
