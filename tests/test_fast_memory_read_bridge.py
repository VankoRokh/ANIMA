from anima.cognition.fast import FastCognition, FastResult
from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


T1 = "2026-10-29T12:00:00+00:00"
T2 = "2026-10-29T12:10:00+00:00"

EV_PREFERENCE = "ev_11111111-1111-4111-8111-111111111111"
EV_PROJECT = "ev_22222222-2222-4222-8222-222222222222"
M_PREFERENCE = "mem_33333333-3333-4333-8333-333333333333"
M_PROJECT = "mem_44444444-4444-4444-8444-444444444444"


class RecordingFastBackend:
    def __init__(self):
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return FastResult(response_text="FAST received bounded memory context.")


def add_user_event(log, *, event_id, text, timestamp):
    event = Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000001",
        event_id=event_id,
        timestamp=timestamp,
    )
    log.write(event)
    return event


def build_real_fast_stack(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    log = EventLog(tmp_path / "events.jsonl")

    add_user_event(
        log,
        event_id=EV_PREFERENCE,
        text="My coffee preference is espresso.",
        timestamp=T1,
    )
    add_user_event(
        log,
        event_id=EV_PROJECT,
        text="The ANIMA project uses SQLite for Cognitive Memory.",
        timestamp=T2,
    )

    store.create_memory(
        memory_type="episodic",
        domain="user",
        content="User coffee preference is espresso.",
        status="closed",
        importance=2,
        created_at=T1,
        public_id=M_PREFERENCE,
        source_event_id=EV_PREFERENCE,
    )
    store.create_memory(
        memory_type="episodic",
        domain="project",
        content="ANIMA Cognitive Memory uses SQLite.",
        status="closed",
        importance=1,
        created_at=T2,
        public_id=M_PROJECT,
        source_event_id=EV_PROJECT,
    )

    retrieval = RetrievalEngine(memory_store=store, link_store=links)
    provenance = ProvenanceResolver(store, links, log)
    context_builder = ContextBuilder(
        retrieval=retrieval,
        provenance=provenance,
    )
    backend = RecordingFastBackend()
    cognition = FastCognition(
        context_builder=context_builder,
        backend=backend,
    )
    return cognition, backend, provenance


def current_user_event(text):
    return Event(
        "conversation.user",
        {"text": text},
        source="user",
        session_id="session_00000002",
    )


def memory_ids(bundle):
    return [entry["record"]["id"] for entry in bundle["memories"]]


def test_fast_reads_relevant_memory_through_real_context_builder(tmp_path):
    cognition, backend, _ = build_real_fast_stack(tmp_path)
    event = current_user_event("What is my coffee preference?")

    turn = cognition.process(event)

    assert len(backend.requests) == 1
    assert turn.request.input_event_id == event.event_id
    assert turn.request.input_text == "What is my coffee preference?"
    assert turn.request.context_bundle["query"] == turn.request.input_text
    assert memory_ids(turn.request.context_bundle) == [M_PREFERENCE]
    assert M_PROJECT not in memory_ids(turn.request.context_bundle)


def test_fast_memory_context_preserves_fast_budget_and_hides_raw_events(tmp_path):
    cognition, _, _ = build_real_fast_stack(tmp_path)

    turn = cognition.process(
        current_user_event("Tell me about my coffee preference and ANIMA memory")
    )
    bundle = turn.request.context_bundle
    stats = bundle["selection_stats"]

    assert bundle["consumer"] == "FAST"
    assert bundle["budget"] == {"max_items": 6, "max_chars": 1200}
    assert bundle["events"] == []
    assert stats["items_used"] <= bundle["budget"]["max_items"]
    assert stats["chars_used"] <= bundle["budget"]["max_chars"]


def test_fast_selected_memory_keeps_provenance_to_source_event(tmp_path):
    cognition, _, provenance = build_real_fast_stack(tmp_path)

    turn = cognition.process(
        current_user_event("What is my coffee preference?")
    )
    selected_memory_id = memory_ids(turn.request.context_bundle)[0]
    resolved = provenance.memory(selected_memory_id)

    assert selected_memory_id == M_PREFERENCE
    assert [event["id"] for event in resolved["events"]] == [EV_PREFERENCE]
    assert resolved["events"][0]["payload"]["text"] == (
        "My coffee preference is espresso."
    )
