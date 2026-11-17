"""ANIMA v0.2 H4 — conservative Entity claim handling in MemoryProcessor.

A supplied ID is a *raw claim*, not a verified about relationship. These
negative tests deliberately emphasize false-merge safety over episode recall.
They use disposable tmp_path stores and do not touch user data.
"""

from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor


T0 = "2026-11-17T12:00:00+00:00"
T1 = "2026-11-17T12:01:00+00:00"
T2 = "2026-11-17T12:02:00+00:00"
T3 = "2026-11-17T12:03:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def make_event(number, text, references=(), timestamp=T0):
    return Event(
        "conversation.user", {"text": text},
        source="user", session_id="session_00000001",
        event_id=uid("ev_", number), timestamp=timestamp,
        references=[
            {"kind": "entity", "id": entity_id}
            for entity_id in references
        ],
    )


def stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    links = LinkStore(store)
    processor = MemoryProcessor(
        memory_store=store, event_log=log, link_store=links,
    )
    return store, log, links, processor


def create_entity(links, number, name, *, status="active"):
    return links.create_entity(
        entity_type="object", canonical_name=name,
        status=status, public_id=uid("ent_", number),
    )["id"]


def process(log, processor, event):
    log.write(event)
    return processor.process_event(event)


def about(links, memory_id):
    return links.relations_for(
        "memory", memory_id, direction="outgoing",
        relation_types={"about"},
    )


def test_h4_distinct_declared_entity_sets_never_merge_on_identical_boilerplate(
    tmp_path,
):
    store, log, links, processor = stack(tmp_path)
    vega = create_entity(links, 101, "Vega")
    orion = create_entity(links, 102, "Orion")
    first = make_event(
        201, "Контроллер Vega сообщил о перегреве датчика температуры.",
        [vega], T0,
    )
    second = make_event(
        202, "Контроллер Orion сообщил о перегреве датчика температуры.",
        [orion], T1,
    )
    a = process(log, processor, first)
    b = process(log, processor, second)
    assert a["action"] == b["action"] == "create"
    assert a["memory_id"] != b["memory_id"]
    assert store.count() == 2
    assert about(links, a["memory_id"]) == []
    assert about(links, b["memory_id"]) == []
    assert store.source_events(a["memory_id"]) == [first.event_id]
    assert store.source_events(b["memory_id"]) == [second.event_id]


def test_h4_multi_entity_bridge_cannot_transitively_join_singleton_episodes(
    tmp_path,
):
    store, log, links, processor = stack(tmp_path)
    vega = create_entity(links, 103, "Vega")
    orion = create_entity(links, 104, "Orion")
    common = "Контроллер сообщил о перегреве датчика температуры."
    first = process(
        log, processor, make_event(203, common + " Vega.", [vega], T0)
    )
    second = process(
        log, processor, make_event(204, common + " Orion.", [orion], T1)
    )
    both = process(
        log, processor, make_event(
            205, common + " Vega Orion.", [vega, orion], T2,
        ),
    )
    assert len({
        first["memory_id"], second["memory_id"], both["memory_id"]
    }) == 3
    assert store.count() == 3


def test_h4_followup_uses_pure_claim_group_not_multi_entity_bridge(tmp_path):
    store, log, links, processor = stack(tmp_path)
    vega = create_entity(links, 105, "Vega")
    orion = create_entity(links, 106, "Orion")
    first = process(log, processor, make_event(
        206, "Vega reported sensor overload warning", [vega], T0,
    ))
    second = process(log, processor, make_event(
        207, "Orion reported sensor overload warning", [orion], T1,
    ))
    both = process(log, processor, make_event(
        208, "Vega Orion reported sensor overload warning", [vega, orion], T2,
    ))
    followup = process(log, processor, make_event(
        209, "Vega reported sensor overload warning again", [vega], T3,
    ))
    assert followup["memory_id"] == first["memory_id"]
    assert followup["action"] == "update"
    assert followup["memory_id"] not in {
        second["memory_id"], both["memory_id"]
    }
    assert store.count() == 3


def test_h4_registered_active_wrong_id_is_not_a_confirmed_about(tmp_path):
    store, log, links, processor = stack(tmp_path)
    orion = create_entity(links, 107, "Orion")
    forged = make_event(
        210, "Контроллер Vega исправен.", [orion], T0,
    )
    result = process(log, processor, forged)
    assert result["action"] == "create"
    assert about(links, result["memory_id"]) == []
    raw = next(row for row in log.load_events() if row["id"] == forged.event_id)
    assert raw["references"] == [{"kind": "entity", "id": orion}]
    assert store.source_events(result["memory_id"]) == [forged.event_id]


def test_h4_inactive_claim_is_rejected_without_creating_derived_memory(tmp_path):
    store, log, links, processor = stack(tmp_path)
    inactive = create_entity(links, 108, "Orion", status="inactive")
    event = make_event(
        211, "Контроллер Vega исправен.", [inactive], T0,
    )
    log.write(event)
    with pytest.raises(ValueError, match="Inactive entity reference"):
        processor.process_event(event)
    assert store.count() == 0
    assert log.load_events()[0]["references"][0]["id"] == inactive


def test_h4_unknown_claim_still_rejected_without_side_effects(tmp_path):
    store, log, _links, processor = stack(tmp_path)
    event = make_event(
        212, "Unknown sensor reference", [uid("ent_", 999)], T0,
    )
    log.write(event)
    with pytest.raises(ValueError, match="Unknown entity reference"):
        processor.process_event(event)
    assert store.count() == 0
    assert log.load_events()[0]["id"] == event.event_id


def test_h4_same_claim_is_not_sufficient_for_association(tmp_path):
    store, log, links, processor = stack(tmp_path)
    shared = create_entity(links, 109, "SQLite")
    first = process(
        log, processor, make_event(213, "Storage baseline", [shared], T0),
    )
    second = process(
        log, processor, make_event(214, "Database choice", [shared], T1),
    )
    assert first["action"] == second["action"] == "create"
    assert first["memory_id"] != second["memory_id"]
    assert store.count() == 2


def test_h4_compatible_raw_claim_with_lexical_evidence_still_updates(tmp_path):
    store, log, links, processor = stack(tmp_path)
    common = create_entity(links, 110, "SQLite")
    first = process(log, processor, make_event(
        215, "SQLite storage configuration changed", [common], T0,
    ))
    followup = process(log, processor, make_event(
        216, "SQLite storage configuration changed again", [common], T1,
    ))
    assert followup["action"] == "update"
    assert followup["memory_id"] == first["memory_id"]
    assert store.count() == 1
    assert about(links, first["memory_id"]) == []
    assert store.source_events(first["memory_id"]) == [
        uid("ev_", 215), uid("ev_", 216),
    ]


def test_h4_untyped_plain_events_keep_legacy_lexical_association(tmp_path):
    store, log, _links, processor = stack(tmp_path)
    first = process(log, processor, make_event(
        217, "Linux Python tools are installed", [], T0,
    ))
    followup = process(log, processor, make_event(
        218, "Linux Python tools are installed properly", [], T1,
    ))
    assert followup["action"] == "update"
    assert followup["memory_id"] == first["memory_id"]
    assert store.count() == 1
