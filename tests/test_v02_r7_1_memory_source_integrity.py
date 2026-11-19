"""R7.1 / H56-06: candidate source graph must stay fresh until SQLite write.

The source graph is a scorer input independent of the memories row.
MemoryLifecycle.merge can transfer another Event's source IDs while keeping
target content and timestamps identical. These tests use real typed Event
claims, real Raw and the public merge API on disposable tmp_path databases.
"""

from threading import Event as ThreadEvent, Thread
from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.processor import MemoryProcessor


T0 = "2020-01-01T00:00:00+00:00"
TEXT = "h56same: shared baseline sensor reading"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def stack(tmp_path):
    core = build_core(tmp_path)
    alice = core.link_store.create_entity(
        entity_type="person", canonical_name="R7 Alice",
    )["id"]
    boris = core.link_store.create_entity(
        entity_type="person", canonical_name="R7 Boris",
    )["id"]

    def event(number, entity_id):
        return Event(
            "conversation.user", {"text": TEXT},
            source="user", session_id="session_00000001",
            timestamp=T0, event_id=uid("ev_", number),
            references=[{"kind": "entity", "id": entity_id}],
        )

    first = event(7101, alice)
    incoming = event(7102, alice)
    other = event(7103, boris)
    for item in (first, incoming, other):
        core.event_log.write(item)

    def memory(number, item):
        return core.memory_store.create_memory(
            memory_type="episodic", domain="user",
            content=TEXT, status="open", created_at=T0,
            source_event_id=item.event_id,
            public_id=uid("mem_", number),
        )["id"]

    target = memory(7101, first)
    source = memory(7103, other)
    return core, target, source, incoming, first, other


def processor(core, *, selected=None, resume=None, frozen=None):
    if selected is None and frozen is None:
        return core.memory_processor

    class ControlledSelection(MemoryProcessor):
        def _best_candidate(self, event, text, entity_ids):
            candidate = (
                frozen if frozen is not None
                else super()._best_candidate(event, text, entity_ids)
            )
            assert candidate is not None
            if selected is not None:
                selected.set()
                assert resume.wait(12), "R7.1 selection barrier timed out"
            return candidate

    return ControlledSelection(
        memory_store=core.memory_store,
        event_log=core.event_log,
        link_store=core.link_store,
    )


def scored_candidate(core, incoming, target):
    chosen = core.memory_processor._best_candidate(
        incoming, TEXT, [],
    )
    assert chosen is not None
    assert chosen["memory"]["id"] == target
    return chosen


def merge_without_row_change(core, source, target):
    selected_row = core.memory_store.get_memory(target)
    original_sources = core.memory_store.source_events(target)
    merged = MemoryLifecycle(memory_store=core.memory_store).merge(
        source, target, merged_at=T0,
    )
    assert merged
    assert core.memory_store.get_memory(target) == selected_row
    assert len(core.memory_store.source_events(target)) > len(original_sources)
    return original_sources


def assert_stale_rejected(error):
    assert isinstance(error, ValueError)
    assert "Stale MemoryProcessor candidate" in str(error)
    assert "source graph changed" in str(error)


def test_r71_h5606_paused_direct_processor_rejects_source_only_merge(tmp_path):
    core, target, source, incoming, first, other = stack(tmp_path)
    selected, resume = ThreadEvent(), ThreadEvent()
    worker = processor(core, selected=selected, resume=resume)
    outcome = {}

    def run():
        try:
            outcome["result"] = worker.process_event(incoming)
        except Exception as exc:
            outcome["error"] = exc

    thread = Thread(target=run, daemon=True)
    thread.start()
    if not selected.wait(12):
        resume.set()
        thread.join(6)
        pytest.fail("Processor did not select candidate")

    try:
        original_sources = merge_without_row_change(core, source, target)
        assert original_sources == [first.event_id]
        # A fresh decision rejects the mixed Alice + Boris source group.
        assert core.memory_processor._best_candidate(incoming, TEXT, []) is None
        before = {
            "target": core.memory_store.get_memory(target),
            "sources": core.memory_store.source_events(target),
            "raw": core.event_log.log_file.read_bytes(),
            "ledger": core.event_processing.get(incoming.event_id),
            "memories": core.memory_store.count(),
        }
    finally:
        resume.set()

    thread.join(12)
    assert not thread.is_alive()
    assert "result" not in outcome
    assert_stale_rejected(outcome.get("error"))
    assert core.memory_store.get_memory(target) == before["target"]
    assert core.memory_store.source_events(target) == before["sources"]
    assert incoming.event_id not in before["sources"]
    assert core.event_processing.get(incoming.event_id) == before["ledger"]
    assert core.memory_store.count() == before["memories"]
    assert core.event_log.log_file.read_bytes() == before["raw"]


def test_r71_supplied_writer_connection_checks_captured_source_ids(tmp_path):
    core, target, source, incoming, first, other = stack(tmp_path)
    chosen = scored_candidate(core, incoming, target)
    merge_without_row_change(core, source, target)
    before_memory = core.memory_store.get_memory(target)
    before_sources = core.memory_store.source_events(target)
    before_raw = core.event_log.log_file.read_bytes()

    forced_stale = processor(core, frozen=chosen)
    with pytest.raises(ValueError, match="source graph changed"):
        with core.memory_store.transaction(immediate=True) as conn:
            forced_stale.process_event(
                incoming, connection=conn, trace_result=False,
            )

    assert core.memory_store.get_memory(target) == before_memory
    assert core.memory_store.source_events(target) == before_sources
    assert core.event_log.log_file.read_bytes() == before_raw
    assert core.event_processing.get(incoming.event_id) is None


def test_r71_control_no_source_change_preserves_normal_update(tmp_path):
    core, target, source, incoming, first, other = stack(tmp_path)
    chosen = scored_candidate(core, incoming, target)
    assert chosen["source_event_ids"] == (first.event_id,)
    assert core.memory_store.source_events(target) == [first.event_id]

    result = core.memory_processor.process_event(incoming)
    assert result["action"] == "update"
    assert result["memory_id"] == target
    assert core.memory_store.source_events(target) == sorted([
        first.event_id, incoming.event_id,
    ])


def test_r71_after_merge_fresh_selection_does_not_update_mixed_owner(tmp_path):
    core, target, source, incoming, first, other = stack(tmp_path)
    merge_without_row_change(core, source, target)
    original = core.memory_store.get_memory(target)
    assert core.memory_processor._best_candidate(incoming, TEXT, []) is None

    result = core.memory_processor.process_event(incoming)
    assert result["action"] == "create"
    assert result["memory_id"] != target
    assert core.memory_store.get_memory(target) == original
    assert incoming.event_id not in core.memory_store.source_events(target)
    assert core.memory_store.source_events(result["memory_id"]) == [
        incoming.event_id,
    ]


def test_r71_source_snapshot_matches_actual_scoring_inputs(tmp_path):
    core, target, source, incoming, first, other = stack(tmp_path)
    before = scored_candidate(core, incoming, target)
    assert before["source_event_ids"] == (first.event_id,)
    merge_without_row_change(core, source, target)
    after_ids = tuple(core.memory_store.source_events(target))
    assert after_ids != before["source_event_ids"]
    assert after_ids == tuple(sorted([first.event_id, other.event_id]))
    assert core.memory_processor._best_candidate(incoming, TEXT, []) is None
