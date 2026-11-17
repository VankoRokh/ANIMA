"""ANIMA H5.5 R4.1 / F-03 — preserve finalized Event -> Memory results.

Based on the independent H5.5 evidence archive:
h55_work/independent_probes.py::projection_delete and independent.json.
All fixtures are disposable. No real instance, audit snapshot, or production
Raw is changed. The policy is fail-closed, not replay/reprocessing:
- a done Event protects every Memory carrying its source ID;
- skipped and unprocessed standalone data keep their previous semantics;
- damaged legacy done-without-source is reported, never re-created silently.
"""

from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.memory_store import MemoryStore
from anima.release_v01 import open_release
from labs.v02_h5_compatibility import analyze_snapshot


T0 = "2020-01-01T00:00:00+00:00"


def _event(number, anchor="alpha"):
    return Event(
        "conversation.user",
        {"text": f"h55r4{anchor}: synthetic Raw event {number} retained"},
        source="user", session_id="session_00000001",
        event_id="ev_" + str(UUID(int=(4 << 76) | (2 << 62) | number)),
        timestamp=T0,
    )


def _project(core, number, anchor="alpha"):
    item = _event(number, anchor)
    core.event_log.write(item)
    result = core.event_processing.process(item)
    assert result["action"] == "create"
    return item, result["memory_id"]


def _unsafe_drop_memory_on_disposable_db(core, memory_id):
    """Simulate old/rogue direct SQL; never call on real instance data."""
    with core.memory_store.transaction(immediate=True) as conn:
        conn.execute("DELETE FROM memories WHERE public_id = ?", (memory_id,))


def test_h55_r4_f03_auditor_release_projection_delete_is_refused(tmp_path):
    with open_release(tmp_path) as release:
        (event_id,) = release.handle({
            "op": "report", "text": "h55deleted marker"
        })["event_ids"]
        core = release.core
        candidates = [
            row["id"] for row in core.memory_store.list_memories()
            if event_id in core.memory_store.source_events(row["id"])
        ]
        assert len(candidates) == 1
        memory_id = candidates[0]
        assert core.event_processing.get(event_id)["status"] == "done"
        before_memory = core.memory_store.get_memory(memory_id)
        before_sources = core.memory_store.source_events(memory_id)
        before_raw = core.event_log.log_file.read_bytes()
        before_db = core.memory_store.database_file.read_bytes()
        before_ledger = core.event_processing.get(event_id)

        with pytest.raises(
            ValueError, match="finalized Event processing projection"
        ):
            core.memory_store.delete_memory(memory_id)

        assert core.memory_store.get_memory(memory_id) == before_memory
        assert core.memory_store.source_events(memory_id) == before_sources
        assert core.event_log.log_file.read_bytes() == before_raw
        assert core.memory_store.database_file.read_bytes() == before_db
        assert core.event_processing.get(event_id) == before_ledger

    # Auditor's restart path: source is present and no replay/rebuild occurs.
    with open_release(tmp_path) as release:
        core = release.core
        original = next(
            record for record in core.event_log.load_events()
            if record["id"] == event_id
        )
        replay = core.event_processing.process(
            core.event_processing._event_from_record(original)
        )
        assert replay["action"] == "already_done"
        assert replay["memory_id"] == memory_id
        assert core.event_processing.get(event_id)["attempts"] == 1
        assert core.event_processing.recover()["retried"] == 0
        context = release.handle({
            "op": "context", "query": "h55deleted",
        })
        assert any(
            item["record"]["id"] == memory_id
            for item in context["result"]["memories"]
        )
        raw_search = release.handle({
            "op": "search_events", "query": "h55deleted",
        })
        assert event_id in {
            row["id"] for row in raw_search["result"]["results"]
        }

    report = analyze_snapshot(
        tmp_path / "memory.db", tmp_path / "events.jsonl",
    )
    assert "done_without_source" not in report["compatibility_findings"]
    assert report["status"] != "BLOCKED"


def test_h55_r4_done_from_other_processor_version_still_protects_source(
    tmp_path,
):
    store = MemoryStore(tmp_path / "memory.db")
    source_id = "ev_" + str(UUID(int=(4 << 76) | (2 << 62) | 11))
    memory_id = store.create_memory(
        memory_type="episodic", domain="user", status="open",
        content="h55r4 legacy projection", created_at=T0,
        source_event_id=source_id,
    )["id"]
    with store.transaction(immediate=True) as conn:
        conn.execute(
            "INSERT INTO event_processing("
            "event_id, processor, processor_version, status, attempts,"
            "started_at, finished_at, last_error) "
            "VALUES (?, 'memory_processor', '0.9', 'done', 1, ?, ?, NULL)",
            (source_id, T0, T0),
        )
    with pytest.raises(
        ValueError, match="finalized Event processing projection"
    ):
        store.delete_memory(memory_id)
    assert store.source_events(memory_id) == [source_id]


def test_h55_r4_reopened_store_cannot_bypass_persistent_done_ledger(tmp_path):
    core = build_core(tmp_path)
    original, memory_id = _project(core, 21)
    independent = MemoryStore(core.memory_store.database_file)
    with pytest.raises(ValueError, match="finalized Event processing"):
        independent.delete_memory(memory_id)
    assert independent.source_events(memory_id) == [original.event_id]
    assert core.event_processing.get(original.event_id)["status"] == "done"


def test_h55_r4_multiple_done_events_on_one_memory_protect_it(tmp_path):
    core = build_core(tmp_path)
    first, memory_id = _project(core, 31)
    second = _event(32)
    core.event_log.write(second)
    another = core.event_processing.process(second)
    assert another["action"] == "update"
    assert another["memory_id"] == memory_id
    assert core.memory_store.source_events(memory_id) == sorted([
        first.event_id, second.event_id,
    ])
    with pytest.raises(ValueError, match="finalized Event processing"):
        core.memory_store.delete_memory(memory_id)
    assert core.event_processing.finalized_count() == 2


def test_h55_r4_unfinalized_standalone_memory_still_deletable(tmp_path):
    # Preserve the H2.2 contract for a standalone provisional fixture:
    # no event_processing done exists, so no immutable projection was made.
    store = MemoryStore(tmp_path / "memory.db")
    memory_id = store.create_memory(
        memory_type="episodic", domain="project", status="open",
        content="h55r4 disposable standalone unprocessed sample",
        created_at=T0, source_event_id=_event(41).event_id,
    )["id"]
    assert store.delete_memory(memory_id) is True
    assert store.get_memory(memory_id) is None
    assert store.delete_memory(memory_id) is False


def test_h55_r4_legacy_sql_damage_replay_fails_closed(tmp_path):
    core = build_core(tmp_path)
    item, memory_id = _project(core, 51)
    before_raw = core.event_log.log_file.read_bytes()
    before_ledger = core.event_processing.get(item.event_id)
    _unsafe_drop_memory_on_disposable_db(core, memory_id)
    assert core.memory_store.source_events(memory_id) == []

    with pytest.raises(ValueError, match="Finalized Event processing missing"):
        core.event_processing.process(item)
    assert core.event_processing.get(item.event_id) == before_ledger
    assert core.event_log.log_file.read_bytes() == before_raw
    assert core.memory_store.count() == 0


def test_h55_r4_legacy_sql_damage_recovery_refuses_before_adoption(tmp_path):
    core = build_core(tmp_path)
    first, memory_id = _project(core, 61)
    _unsafe_drop_memory_on_disposable_db(core, memory_id)
    new_raw = _event(62, "new")
    core.event_log.write(new_raw)
    raw_before = core.event_log.log_file.read_bytes()

    for _ in range(2):
        with pytest.raises(
            ValueError, match="Finalized Event processing missing Memory"
        ):
            core.event_processing.recover()

    # The preflight refused BEFORE creating a new processing ledger row.
    assert core.event_processing.get(new_raw.event_id) is None
    assert core.event_processing.get(first.event_id)["status"] == "done"
    assert core.event_processing.get(first.event_id)["attempts"] == 1
    assert core.memory_store.count() == 0
    assert core.event_log.log_file.read_bytes() == raw_before

    report = analyze_snapshot(
        core.memory_store.database_file, core.event_log.log_file,
    )
    assert report["status"] == "BLOCKED"
    assert first.event_id in report["compatibility_findings"][
        "done_without_source"
    ]["ids"]


def test_h55_r4_skipped_event_without_memory_remains_valid(tmp_path):
    core = build_core(tmp_path)
    item = Event(
        "system.wake", source="runtime", session_id="session_00000001",
        timestamp=T0, event_id=_event(71).event_id,
    )
    core.event_log.write(item)
    result = core.event_processing.process(item)
    assert result["action"] == "skip"
    assert core.event_processing.get(item.event_id)["status"] == "skipped"
    recovered = core.event_processing.recover()
    assert recovered["finalized"] == 1
    assert recovered["retried"] == 0
    assert core.memory_store.count() == 0
