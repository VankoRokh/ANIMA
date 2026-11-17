"""H4 integration regressions adapted from R1-S1 / M-T2C C1,C3,C4,C5.

Gold object labels are *test-only* and are not available to ANIMA.
This is a known-failure regression corpus, not a semantic generalization test.
"""

from itertools import combinations
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor


PREFIX = "2026-11-17T12:"
SESSION = "session_00000001"


def uid(prefix, n):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | n))


def stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    links = LinkStore(store)
    vega = links.create_entity(
        entity_type="object", canonical_name="Vega",
        public_id=uid("ent_", 101),
    )["id"]
    orion = links.create_entity(
        entity_type="object", canonical_name="Orion",
        public_id=uid("ent_", 102),
    )["id"]
    processor = MemoryProcessor(
        memory_store=store, event_log=log, link_store=links,
    )
    return store, log, links, processor, {"vega": vega, "orion": orion}


SCENARIOS = {
    "C1_missing_claims": [
        ("Контроллер Vega сообщил о перегреве.", "vega", ["vega"]),
        ("Контроллер Orion сообщил о перегреве.", "orion", []),
        ("Контроллер Orion включил охлаждение.", "orion", ["orion"]),
        ("Контроллер Vega включил охлаждение.", "vega", ["vega"]),
        ("Контроллер Orion теперь стабилен.", "orion", []),
        ("Контроллер Vega теперь стабилен.", "vega", ["vega"]),
    ],
    "C3_disjoint_singletons": [
        ("Контроллер Vega показал температуру 82 градуса.", "vega", ["vega"]),
        ("Контроллер Orion показал температуру 82 градуса.", "orion", ["orion"]),
        ("Температура Vega поднялась до 91 градуса.", "vega", ["vega"]),
        ("Температура Orion поднялась до 91 градуса.", "orion", ["orion"]),
        ("Охлаждение Vega включилось автоматически.", "vega", ["vega"]),
        ("Охлаждение Orion включилось автоматически.", "orion", ["orion"]),
    ],
    "C5_multi_entity_bridge": [
        ("Контроллер Vega показал высокую температуру 91 градус.",
         "vega", ["vega"]),
        ("Контроллер Vega и Orion показали высокую температуру 91 градус.",
         "joint", ["vega", "orion"]),
        ("Контроллер Orion показал высокую температуру 91 градус.",
         "orion", ["orion"]),
        ("Контроллер Vega снова показал высокую температуру 91 градус.",
         "vega", ["vega"]),
        ("Контроллер Orion снова показал высокую температуру 91 градус.",
         "orion", ["orion"]),
    ],
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_h4_selected_mt2c_different_objects_never_share_memory(
    tmp_path, scenario,
):
    store, log, links, processor, entity_ids = stack(tmp_path)
    rows = SCENARIOS[scenario]
    observations = []
    for i, (text, truth, claims) in enumerate(rows, start=1):
        event = Event(
            "conversation.user", {"text": text},
            source="user", session_id=SESSION,
            timestamp=PREFIX + f"{i:02d}:00+00:00",
            event_id=uid("ev_", 300 + i),
            references=[
                {"kind": "entity", "id": entity_ids[claim]}
                for claim in claims
            ],
        )
        log.write(event)
        result = processor.process_event(event)
        observations.append((truth, result["memory_id"], event.event_id))
        assert links.relations_for(
            "memory", result["memory_id"], direction="outgoing",
            relation_types={"about"},
        ) == []

    distinct_singletons_merged = [
        (left, right)
        for left, right in combinations(observations, 2)
        if left[0] in {"vega", "orion"}
        and right[0] in {"vega", "orion"}
        and left[0] != right[0]
        and left[1] == right[1]
    ]
    assert distinct_singletons_merged == []
    assert len(log.load_events()) == len(rows)
    assert len({
        event_id for _truth, _memory_id, event_id in observations
    }) == len(rows)
    assert sum(
        len(store.source_events(row["id"]))
        for row in store.list_memories()
    ) == len(rows)


def test_h4_c4_false_but_registered_claim_does_not_publish_about(tmp_path):
    store, log, links, processor, entity_ids = stack(tmp_path)
    event = Event(
        "conversation.user",
        {"text": "Контроллер Orion сообщил об опасном перегреве."},
        source="user", session_id=SESSION,
        timestamp=PREFIX + "01:00+00:00",
        event_id=uid("ev_", 440),
        references=[{"kind": "entity", "id": entity_ids["vega"]}],
    )
    log.write(event)
    result = processor.process_event(event)
    assert result["action"] == "create"
    assert links.relations_for(
        "memory", result["memory_id"], direction="outgoing",
        relation_types={"about"},
    ) == []
    assert log.load_events()[0]["references"][0]["id"] == entity_ids["vega"]
    assert store.source_events(result["memory_id"]) == [event.event_id]
