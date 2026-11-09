"""EXP-009: narrow Event -> Memory -> retrieval/provenance baseline.

This intentionally does not exercise the full Core runtime or prove semantic reasoning.
The fixture is synthetic, deterministic and isolated from real instance data.
"""

from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


STAMP = "2026-11-09T12:00:00+00:00"
COUNT = 96


def _id(prefix, index):
    # Fixed valid UUIDv4 values make corpus identities repeatable.
    value = UUID(int=(4 << 76) | (2 << 62) | (index + 1))
    return f"{prefix}{value}"


def _build_corpus(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    store = MemoryStore(tmp_path / "memory.db")

    for index in range(COUNT):
        marker = f"samplez{index:04d}"
        event = Event(
            "lab.sensor",
            {"marker": marker, "reading": index % 27, "unit": "C"},
            source=f"synthetic.sensor_{index % 4}",
            timestamp=STAMP,
            event_id=_id("ev_", index),
        )
        event_log.write(event)
        store.create_memory(
            memory_type="episodic",
            domain="project",
            content=f"thermalsample {marker} recorded reading {index % 27} C",
            status="closed",
            importance=1,
            created_at=STAMP,
            public_id=_id("mem_", index),
            source_event_id=event.event_id,
        )

    return tmp_path / "events.jsonl", tmp_path / "memory.db"


def test_bounded_retrieval_preserves_source_after_reopening(tmp_path):
    events_path, memory_path = _build_corpus(tmp_path)
    reopened = MemoryStore(memory_path)
    links = LinkStore(reopened)
    retrieval = RetrievalEngine(memory_store=reopened, link_store=links)

    target = 42
    marker = f"samplez{target:04d}"
    found = retrieval.retrieve(
        marker, kinds={"memory"}, relation_hops=0, top_k=4
    )
    assert reopened.count() == COUNT
    assert [row["id"] for row in found["results"]] == [_id("mem_", target)]

    provenance = ProvenanceResolver(
        reopened, links, EventLog(events_path)
    ).memory(_id("mem_", target))
    assert provenance["memory"]["id"] == _id("mem_", target)
    assert [event["id"] for event in provenance["events"]] == [
        _id("ev_", target)
    ]
    assert provenance["events"][0]["payload"] == {
        "marker": marker, "reading": target % 27, "unit": "C"
    }

    # A bounded projection must not suddenly return all 96 memories.
    limited = retrieval.retrieve(
        "thermalsample", kinds={"memory"}, relation_hops=0, top_k=5
    )
    assert len(limited["results"]) == 5
    assert limited == retrieval.retrieve(
        "thermalsample", kinds={"memory"}, relation_hops=0, top_k=5
    )
    assert retrieval.retrieve(
        "samplez9999", kinds={"memory"}, relation_hops=0
    )["results"] == []


def test_duplicate_raw_event_is_not_appended_twice(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    event = Event(
        "lab.sensor", {"marker": "samplez0000", "reading": 1},
        source="synthetic.sensor_0", timestamp=STAMP,
        event_id=_id("ev_", 0),
    )
    event_log.write(event)

    with pytest.raises(ValueError, match="Duplicate event id"):
        event_log.write(event)

    assert [item["id"] for item in event_log.load_events()] == [
        event.event_id
    ]
