"""R6.2 / NEW-03 — MemoryProcessor cannot mutate confirmed Evidence.

All fixtures are isolated under pytest tmp_path. No user instance or raw
GitHub audit branch is changed. The race is scheduled with thread Events,
not sleeps, monkeypatched SQL or a test-only production bypass.
"""

from threading import Event as ThreadEvent, Thread
from uuid import UUID

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.composer import RuleBasedComposer
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor


T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def fixture(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    store = MemoryStore(tmp_path / "memory.db", event_log=event_log)
    links = LinkStore(store)
    first = Event(
        "conversation.user",
        {"text": "r6pressure: pressure stable"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", 811),
        timestamp=T0,
    )
    second = Event(
        "conversation.user",
        {"text": "r6pressure: pressure changed"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", 812),
        timestamp=T4,
    )
    event_log.write(first)
    event_log.write(second)
    memory = store.create_memory(
        memory_type="episodic",
        domain="user",
        status="open",
        content="r6pressure: pressure stable",
        created_at=T0,
        public_id=uid("mem_", 811),
        source_event_id=first.event_id,
    )["id"]
    return store, event_log, links, memory, second


def new_processor(store, log, links, *, selected=None, proceed=None):
    if selected is None:
        return MemoryProcessor(
            memory_store=store, event_log=log, link_store=links,
        )

    class PausingProcessor(MemoryProcessor):
        def _best_candidate(self, event, text, entity_ids):
            candidate = super()._best_candidate(event, text, entity_ids)
            assert candidate is not None
            assert candidate["memory"]["status"] == "open"
            selected.set()
            if not proceed.wait(10):
                raise AssertionError("R6.2 test scheduling timed out")
            return candidate

    return PausingProcessor(
        memory_store=store, event_log=log, link_store=links,
    )


def run_paused(processor, event, selected, proceed):
    outcome = {}

    def target():
        try:
            outcome["result"] = processor.process_event(event)
        except Exception as error:
            outcome["error"] = error

    thread = Thread(target=target, daemon=True)
    thread.start()
    if not selected.wait(10):
        proceed.set()
        thread.join(5)
        pytest.fail("MemoryProcessor did not select an OPEN candidate")
    return thread, outcome


def assert_rejected(thread, outcome, proceed):
    proceed.set()
    thread.join(10)
    assert not thread.is_alive(), "MemoryProcessor remained blocked"
    assert "result" not in outcome
    assert isinstance(outcome.get("error"), ValueError)
    assert "Stale MemoryProcessor candidate" in str(outcome["error"])


def test_r6_2_direct_processor_still_updates_unchanged_open_memory(tmp_path):
    store, log, links, memory_id, event = fixture(tmp_path)
    processor = new_processor(store, log, links)
    result = processor.process_event(event)
    assert result["action"] == "update"
    assert result["memory_id"] == memory_id
    assert "pressure changed" in store.get_memory(memory_id)["content"]
    assert store.source_events(memory_id) == [
        uid("ev_", 811), uid("ev_", 812),
    ]


def test_r6_2_raced_close_and_confirm_prevents_direct_update(tmp_path):
    store, log, links, memory_id, event = fixture(tmp_path)
    selected, proceed = ThreadEvent(), ThreadEvent()
    processor = new_processor(
        store, log, links, selected=selected, proceed=proceed,
    )
    thread, outcome = run_paused(processor, event, selected, proceed)

    try:
        lifecycle = MemoryLifecycle(memory_store=store)
        lifecycle.close(memory_id, closed_at=T1)
        layer = KnowledgeLayer(memory_store=store)
        claim = layer.create_candidate(
            domain="user",
            statement="Pressure was stable at measurement",
            source_memory_id=memory_id,
            created_at=T2,
        )["knowledge"]["id"]
        layer.confirm(claim, confirmed_at=T3)
        before_memory = store.get_memory(memory_id)
        before_sources = store.source_events(memory_id)
        before_knowledge = layer.get(claim)
        before_history = layer.history(claim)
        before_raw = log.log_file.read_bytes()
    finally:
        proceed.set()

    assert_rejected(thread, outcome, proceed)
    assert store.get_memory(memory_id) == before_memory
    assert store.source_events(memory_id) == before_sources
    assert layer.get(claim) == before_knowledge
    assert layer.history(claim) == before_history
    assert log.log_file.read_bytes() == before_raw
    assert before_memory["status"] == "closed"
    assert before_knowledge["status"] == "confirmed"
    assert uid("ev_", 812) not in store.source_events(memory_id)


def test_r6_2_raced_open_memory_update_prevents_lost_update(tmp_path):
    store, log, links, memory_id, event = fixture(tmp_path)
    selected, proceed = ThreadEvent(), ThreadEvent()
    processor = new_processor(
        store, log, links, selected=selected, proceed=proceed,
    )
    thread, outcome = run_paused(processor, event, selected, proceed)

    try:
        updated = store.update_memory(
            memory_id,
            content="r6pressure: independent writer update",
            updated_at=T2,
        )
        before_sources = store.source_events(memory_id)
    finally:
        proceed.set()

    assert_rejected(thread, outcome, proceed)
    assert store.get_memory(memory_id) == updated
    assert store.source_events(memory_id) == before_sources
    assert uid("ev_", 812) not in store.source_events(memory_id)


def test_r6_2_pause_in_composer_cannot_race_close_past_writer_lock(
    tmp_path,
):
    """The original audit's pause-only composer interleaving is serialized."""
    store, log, links, memory_id, event = fixture(tmp_path)
    entered, resume = ThreadEvent(), ThreadEvent()
    close_started, close_finished = ThreadEvent(), ThreadEvent()
    base_composer = RuleBasedComposer()

    class PauseOnlyComposer:
        def compose_create(self, text):
            return base_composer.compose_create(text)

        def compose_update(self, previous_content, text):
            entered.set()
            if not resume.wait(10):
                raise AssertionError("R6.2 composer scheduling timed out")
            return base_composer.compose_update(previous_content, text)

    processor = MemoryProcessor(
        memory_store=store, event_log=log, link_store=links,
        composer=PauseOnlyComposer(),
    )
    outcome = {}
    close_outcome = {}

    def update():
        try:
            outcome["result"] = processor.process_event(event)
        except Exception as error:
            outcome["error"] = error

    def close():
        close_started.set()
        try:
            close_outcome["result"] = MemoryLifecycle(
                memory_store=store
            ).close(memory_id, closed_at="2020-01-01T00:05:00+00:00")
        except Exception as error:
            close_outcome["error"] = error
        finally:
            close_finished.set()

    update_thread = Thread(target=update, daemon=True)
    close_thread = Thread(target=close, daemon=True)
    update_thread.start()
    try:
        assert entered.wait(10), "Processor did not reach compose_update"
        close_thread.start()
        assert close_started.wait(10)
        # The direct processor already holds BEGIN IMMEDIATE here:
        # competing lifecycle.close cannot commit until composer resumes.
        assert not close_finished.wait(0.1)
    finally:
        resume.set()

    update_thread.join(10)
    close_thread.join(10)
    assert not update_thread.is_alive()
    assert not close_thread.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert "error" not in close_outcome, close_outcome.get("error")
    assert outcome["result"]["action"] == "update"
    assert store.get_memory(memory_id)["status"] == "closed"
    assert "pressure changed" in store.get_memory(memory_id)["content"]
    assert store.source_events(memory_id) == [uid("ev_", 811), uid("ev_", 812)]

    # A Knowledge confirmation after both serialized writes sees the final
    # updated Memory; the prior defect changed an already confirmed source.
    layer = KnowledgeLayer(memory_store=store)
    claim = layer.create_candidate(
        domain="user",
        statement="Pressure changed in the latest measurement",
        source_memory_id=memory_id,
        created_at="2020-01-01T00:06:00+00:00",
    )["knowledge"]["id"]
    layer.confirm(claim, confirmed_at="2020-01-01T00:07:00+00:00")
    assert layer.get(claim)["status"] == "confirmed"


@pytest.mark.parametrize("supplied_connection", [False, True])
def test_r6_2_processor_defends_against_legacy_open_confirmed_source(
    tmp_path, supplied_connection,
):
    store, log, links, memory_id, event = fixture(tmp_path)
    lifecycle = MemoryLifecycle(memory_store=store)
    lifecycle.close(memory_id, closed_at=T1)
    layer = KnowledgeLayer(memory_store=store)
    claim = layer.create_candidate(
        domain="user", statement="Legacy corrupted confirmed source",
        source_memory_id=memory_id, created_at=T2,
    )["knowledge"]["id"]
    layer.confirm(claim, confirmed_at=T3)

    # Simulated *legacy SQL corruption* in this temporary database only.
    # The safe MemoryStore.update_memory API refuses such reopening.
    with store.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE memories SET status='open', closed_at=NULL "
            "WHERE public_id=?",
            (memory_id,),
        )
    before = store.get_memory(memory_id)
    before_sources = store.source_events(memory_id)
    before_history = layer.history(claim)
    processor = new_processor(store, log, links)

    with pytest.raises(ValueError, match="confirmed Knowledge evidence"):
        if supplied_connection:
            with store.transaction(immediate=True) as conn:
                processor.process_event(event, connection=conn)
        else:
            processor.process_event(event)

    assert store.get_memory(memory_id) == before
    assert store.source_events(memory_id) == before_sources
    assert layer.history(claim) == before_history
    assert uid("ev_", 812) not in store.source_events(memory_id)
