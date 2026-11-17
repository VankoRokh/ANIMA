"""v0.2 H1.2: finalized SQLite processing cannot outlive its Raw Event.

Tests use tmp_path exclusively. The missing events below are deliberately
removed from disposable test fixtures, never from user/production files.
H1.2 intentionally refuses startup; it does not auto-reconstruct evidence.
"""

import json
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.release_v01 import open_release


STAMP = "2026-11-17T12:00:00+00:00"


def event(number, *, selected=True):
    event_id = f"ev_{UUID(int=(4 << 76) | (2 << 62) | number)}"
    if selected:
        return Event(
            "conversation.user", {"text": f"h12 unique memory event {number}"},
            source="user", session_id="session_00000001",
            event_id=event_id, timestamp=STAMP,
        )
    return Event(
        "system.wake", source="runtime", session_id="session_00000001",
        event_id=event_id, timestamp=STAMP,
    )


def stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    log = EventLog(tmp_path / "events.jsonl")
    processor = MemoryProcessor(
        memory_store=store, event_log=log, link_store=LinkStore(store),
    )
    coordinator = EventProcessingCoordinator(
        memory_store=store, memory_processor=processor, event_log=log,
    )
    return store, log, coordinator


def remove_event(log, event_id):
    lines = log.log_file.read_bytes().splitlines(keepends=True)
    remaining = [
        raw for raw in lines if json.loads(raw)["id"] != event_id
    ]
    if len(remaining) != len(lines) - 1:
        raise RuntimeError("Fixture requires exactly one source record")
    log.log_file.write_bytes(b"".join(remaining))


def test_h1_2_finalized_done_missing_raw_refuses_before_any_changes(tmp_path):
    store, log, coordinator = stack(tmp_path)
    original = event(101)
    log.write(original)
    first = coordinator.process(original)
    assert first["action"] == "create"
    before_ledger = coordinator.list_records()
    before_memories = store.list_memories()
    remove_event(log, original.event_id)
    remaining_raw = log.log_file.read_bytes()

    with pytest.raises(ValueError, match="Missing finalized raw event") as caught:
        coordinator.recover()
    assert original.event_id in str(caught.value)
    assert coordinator.list_records() == before_ledger
    assert store.list_memories() == before_memories
    assert log.log_file.read_bytes() == remaining_raw


def test_h1_2_skipped_finalized_event_is_checked_too(tmp_path):
    store, log, coordinator = stack(tmp_path)
    original = event(201, selected=False)
    log.write(original)
    assert coordinator.process(original)["action"] == "skip"
    remove_event(log, original.event_id)

    with pytest.raises(ValueError, match="Missing finalized raw event"):
        coordinator.recover()
    assert coordinator.get(original.event_id)["status"] == "skipped"
    assert store.count() == 0


def test_h1_2_missing_finalized_blocks_adoption_of_unrelated_raw(tmp_path):
    store, log, coordinator = stack(tmp_path)
    finalized = event(301)
    waiting = event(302)
    log.write(finalized)
    assert coordinator.process(finalized)["action"] == "create"
    log.write(waiting)  # Raw exists, no processing record yet.
    remove_event(log, finalized.event_id)
    ledger_before = coordinator.list_records()

    with pytest.raises(ValueError, match="Missing finalized raw event"):
        coordinator.recover()
    assert coordinator.list_records() == ledger_before
    assert coordinator.get(waiting.event_id) is None
    assert store.count() == 1


def test_h1_2_intact_raw_recovers_and_remains_idempotent(tmp_path):
    store, log, coordinator = stack(tmp_path)
    original = event(401)
    log.write(original)
    first = coordinator.process(original)
    assert first["action"] == "create"

    recovered = coordinator.recover()
    assert recovered["retried"] == 0
    assert recovered["adopted"] == 0
    assert recovered["finalized"] == 1
    assert coordinator.process(original)["action"] == "already_done"
    assert store.count() == 1


def test_h1_2_missing_many_reports_a_bounded_deterministic_sample(tmp_path):
    _, log, coordinator = stack(tmp_path)
    ids = []
    for number in range(501, 505):
        original = event(number, selected=False)
        ids.append(original.event_id)
        log.write(original)
        assert coordinator.process(original)["action"] == "skip"
    log.log_file.write_bytes(b"")

    with pytest.raises(ValueError, match="Missing finalized raw event") as caught:
        coordinator.recover()
    detail = str(caught.value)
    assert ids[0] in detail
    assert ids[1] in detail
    assert ids[2] in detail
    assert ids[3] not in detail
    assert "(+1 more)" in detail
    assert all(coordinator.get(eid)["status"] == "skipped" for eid in ids)


def test_h1_2_release_reopen_refuses_before_new_wake_event(tmp_path):
    with open_release(tmp_path) as release:
        written = release.handle({
            "op": "report", "text": "h12release unique committed observation"
        })
        original_id = written["event_ids"][0]
    log = EventLog(tmp_path / "events.jsonl")
    remove_event(log, original_id)
    before_restart = log.log_file.read_bytes()

    with pytest.raises(ValueError, match="Missing finalized raw event"):
        with open_release(tmp_path):
            pass
    assert log.log_file.read_bytes() == before_restart


def test_h1_2_release_reopen_with_complete_sources_still_operates(tmp_path):
    with open_release(tmp_path) as release:
        written = release.handle({
            "op": "report", "text": "h12healthy unique committed observation"
        })
        original_id = written["event_ids"][0]
    with open_release(tmp_path) as release:
        response = release.handle({
            "op": "search_events", "query": "h12healthy"
        })
        assert original_id in {
            r["id"] for r in response["result"]["results"]
        }
        assert response["result"]["coverage"]["status"] == "complete"
