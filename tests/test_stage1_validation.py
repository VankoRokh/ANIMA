from types import SimpleNamespace

from anima.core.event_bus import Event
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.lifecycle import MemoryLifecycle
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


SQLITE_ENTITY = "ent_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OLD_KNOWLEDGE = "kn_bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NEW_KNOWLEDGE = "kn_cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PROCEDURAL_MEMORY = "mem_dddddddd-dddd-4ddd-8ddd-dddddddddddd"


CORPUS = [
    {"label": "s1_wake", "type": "system.wake", "session": 1, "time": "2026-10-26T12:00:00+00:00"},
    {
        "label": "sqlite_initial",
        "type": "conversation.user",
        "session": 1,
        "time": "2026-10-26T12:01:00+00:00",
        "text": "SQLite default mode is sufficient for concurrent writes.",
        "sqlite": True,
    },
    {
        "label": "sqlite_followup",
        "type": "conversation.user",
        "session": 1,
        "time": "2026-10-26T12:05:00+00:00",
        "text": "SQLite default mode is sufficient for concurrent writes local database baseline.",
        "sqlite": True,
    },
    {"label": "s1_sleep", "type": "system.sleep", "session": 1, "time": "2026-10-26T12:10:00+00:00"},
    {"label": "s2_wake", "type": "system.wake", "session": 2, "time": "2026-10-26T12:30:00+00:00"},
    {
        "label": "cm5_initial",
        "type": "conversation.user",
        "session": 2,
        "time": "2026-10-26T12:31:00+00:00",
        "text": "CM5 hardware planning.",
    },
    {
        "label": "cm5_followup",
        "type": "conversation.user",
        "session": 2,
        "time": "2026-10-26T12:35:00+00:00",
        "text": "CM5 hardware power planning.",
    },
    {"label": "s2_sleep", "type": "system.sleep", "session": 2, "time": "2026-10-26T12:40:00+00:00"},
    {"label": "s3_wake", "type": "system.wake", "session": 3, "time": "2026-10-26T13:00:00+00:00"},
    {
        "label": "documentation",
        "type": "conversation.user",
        "session": 3,
        "time": "2026-10-26T13:01:00+00:00",
        "text": "ANIMA documentation canonical source of truth.",
    },
    {"label": "s3_sleep", "type": "system.sleep", "session": 3, "time": "2026-10-26T13:10:00+00:00"},
    {"label": "s4_wake", "type": "system.wake", "session": 4, "time": "2026-10-26T13:30:00+00:00"},
    {
        "label": "testing",
        "type": "conversation.user",
        "session": 4,
        "time": "2026-10-26T13:31:00+00:00",
        "text": "Testing representative evidence report.",
    },
    {"label": "s4_sleep", "type": "system.sleep", "session": 4, "time": "2026-10-26T13:40:00+00:00"},
    {"label": "s5_wake", "type": "system.wake", "session": 5, "time": "2026-10-26T14:00:00+00:00"},
    {
        "label": "cyberdeck_initial",
        "type": "conversation.user",
        "session": 5,
        "time": "2026-10-26T14:01:00+00:00",
        "text": "Cyberdeck battery autonomy planning.",
    },
    {
        "label": "cyberdeck_followup",
        "type": "conversation.user",
        "session": 5,
        "time": "2026-10-26T14:05:00+00:00",
        "text": "Cyberdeck battery autonomy target eight hours.",
    },
    {"label": "s5_sleep", "type": "system.sleep", "session": 5, "time": "2026-10-26T14:10:00+00:00"},
    {"label": "s6_wake", "type": "system.wake", "session": 6, "time": "2026-10-26T14:30:00+00:00"},
    {
        "label": "english",
        "type": "conversation.user",
        "session": 6,
        "time": "2026-10-26T14:31:00+00:00",
        "text": "English B1 course practice.",
    },
    {"label": "s6_sleep", "type": "system.sleep", "session": 6, "time": "2026-10-26T14:40:00+00:00"},
    {"label": "s7_wake", "type": "system.wake", "session": 7, "time": "2026-10-26T15:00:00+00:00"},
    {
        "label": "serbia",
        "type": "conversation.user",
        "session": 7,
        "time": "2026-10-26T15:01:00+00:00",
        "text": "Serbia relocation Novi Sad.",
    },
    {"label": "s7_sleep", "type": "system.sleep", "session": 7, "time": "2026-10-26T15:10:00+00:00"},
    {"label": "s8_wake", "type": "system.wake", "session": 8, "time": "2026-10-26T15:30:00+00:00"},
    {
        "label": "krita",
        "type": "conversation.user",
        "session": 8,
        "time": "2026-10-26T15:31:00+00:00",
        "text": "Krita Wayland tablet setup.",
    },
    {"label": "s8_sleep", "type": "system.sleep", "session": 8, "time": "2026-10-26T15:40:00+00:00"},
    {"label": "s9_wake", "type": "system.wake", "session": 9, "time": "2026-10-26T16:00:00+00:00"},
    {
        "label": "provenance",
        "type": "conversation.user",
        "session": 9,
        "time": "2026-10-26T16:01:00+00:00",
        "text": "Memory provenance audit trail.",
    },
    {
        "label": "backup_tool",
        "type": "action.tool",
        "session": 9,
        "time": "2026-10-26T16:05:00+00:00",
        "payload": {
            "text": "Procedure: create backup before memory migration.",
            "tool": "backup",
            "result": "success",
        },
    },
    {"label": "s9_sleep", "type": "system.sleep", "session": 9, "time": "2026-10-26T16:10:00+00:00"},
    {"label": "s10_wake", "type": "system.wake", "session": 10, "time": "2026-10-27T12:00:00+00:00"},
    {
        "label": "sqlite_benchmark",
        "type": "conversation.user",
        "session": 10,
        "time": "2026-10-27T12:01:00+00:00",
        "text": "SQLite default mode benchmark failed concurrent writes.",
        "sqlite": True,
    },
    {"label": "s10_sleep", "type": "system.sleep", "session": 10, "time": "2026-10-27T12:10:00+00:00"},
    {"label": "s11_wake", "type": "system.wake", "session": 11, "time": "2026-10-27T13:00:00+00:00"},
    {
        "label": "sqlite_wal_result",
        "type": "conversation.user",
        "session": 11,
        "time": "2026-10-27T13:01:00+00:00",
        "text": "Result: SQLite WAL mode satisfies concurrent write benchmark.",
        "sqlite": True,
    },
    {"label": "s11_sleep", "type": "system.sleep", "session": 11, "time": "2026-10-27T13:10:00+00:00"},
]


def build_stack(data_dir):
    store = MemoryStore(data_dir / "memory.db")
    event_log = EventLog(data_dir / "events.jsonl")
    links = LinkStore(store)
    processor = MemoryProcessor(
        memory_store=store,
        event_log=event_log,
        link_store=links,
    )
    coordinator = EventProcessingCoordinator(
        memory_store=store,
        memory_processor=processor,
        event_log=event_log,
    )
    lifecycle = MemoryLifecycle(memory_store=store)
    knowledge = KnowledgeLayer(memory_store=store)
    provenance = ProvenanceResolver(store, links, event_log)
    retrieval = RetrievalEngine(memory_store=store, link_store=links)
    context = ContextBuilder(retrieval=retrieval, provenance=provenance)
    return SimpleNamespace(
        store=store,
        event_log=event_log,
        links=links,
        processor=processor,
        coordinator=coordinator,
        lifecycle=lifecycle,
        knowledge=knowledge,
        provenance=provenance,
        retrieval=retrieval,
        context=context,
    )


def corpus_event(index, spec):
    event_type = spec["type"]
    if event_type == "conversation.user":
        payload = {"text": spec["text"]}
        source = "user"
    elif event_type.startswith("system."):
        payload = None
        source = "runtime"
    else:
        payload = spec["payload"]
        source = "tool"

    references = []
    if spec.get("sqlite"):
        references = [{"kind": "entity", "id": SQLITE_ENTITY}]

    return Event(
        event_type,
        payload,
        source=source,
        session_id=f"session_{spec['session']:08d}",
        references=references,
        event_id=f"ev_{index:08x}-1111-4111-8111-{index:012x}",
        timestamp=spec["time"],
    )


def materialize_corpus(tmp_path):
    stack = build_stack(tmp_path)
    stack.links.create_entity(
        entity_type="technology",
        canonical_name="SQLite",
        aliases=["SQLite3"],
        public_id=SQLITE_ENTITY,
    )

    pairs = [
        (spec, corpus_event(index, spec))
        for index, spec in enumerate(CORPUS, start=1)
    ]
    events = {spec["label"]: event for spec, event in pairs}
    results = {}

    for spec, event in pairs[:18]:
        stack.event_log.write(event)
        results[spec["label"]] = stack.coordinator.process(event)

    first_memory_count = stack.store.count()
    stack = build_stack(tmp_path)
    recovery = stack.coordinator.recover()

    before_replay = stack.store.count()
    replay = stack.coordinator.process(events["sqlite_initial"])
    after_replay = stack.store.count()

    for spec, event in pairs[18:]:
        stack.event_log.write(event)
        results[spec["label"]] = stack.coordinator.process(event)

    return SimpleNamespace(
        stack=stack,
        events=events,
        results=results,
        recovery=recovery,
        replay=replay,
        first_memory_count=first_memory_count,
        before_replay=before_replay,
        after_replay=after_replay,
    )


def add_semantic_layer(corpus):
    stack = corpus.stack
    results = corpus.results

    initial_memory = results["sqlite_initial"]["memory_id"]
    benchmark_memory = results["sqlite_benchmark"]["memory_id"]
    wal_memory = results["sqlite_wal_result"]["memory_id"]

    stack.lifecycle.close(
        initial_memory,
        closed_at="2026-10-26T12:15:00+00:00",
    )
    stack.lifecycle.close(
        benchmark_memory,
        closed_at="2026-10-27T12:15:00+00:00",
    )
    stack.lifecycle.close(
        wal_memory,
        closed_at="2026-10-27T13:15:00+00:00",
    )

    backup_event = corpus.events["backup_tool"]
    procedural = stack.store.create_memory(
        memory_type="procedural",
        domain="system",
        content="Procedure: create backup before memory migration.",
        status="open",
        importance=2,
        created_at=backup_event.timestamp,
        public_id=PROCEDURAL_MEMORY,
        source_event_id=backup_event.event_id,
    )
    stack.lifecycle.close(
        procedural["id"],
        closed_at="2026-10-26T16:06:00+00:00",
    )

    stack.knowledge.create_candidate(
        domain="user",
        statement="SQLite default mode is sufficient for concurrent writes.",
        source_memory_id=initial_memory,
        created_at="2026-10-27T14:00:00+00:00",
        public_id=OLD_KNOWLEDGE,
    )
    stack.knowledge.confirm(
        OLD_KNOWLEDGE,
        confirmed_at="2026-10-27T14:05:00+00:00",
    )
    stack.knowledge.challenge(
        OLD_KNOWLEDGE,
        benchmark_memory,
        challenged_at="2026-10-27T14:10:00+00:00",
    )
    superseded = stack.knowledge.supersede(
        OLD_KNOWLEDGE,
        statement="SQLite WAL mode is required for concurrent writes.",
        source_memory_id=wal_memory,
        superseded_at="2026-10-27T14:20:00+00:00",
        public_id=NEW_KNOWLEDGE,
    )
    stack.links.create_relation(
        source_kind="knowledge",
        source_id=NEW_KNOWLEDGE,
        relation_type="about",
        target_kind="entity",
        target_id=SQLITE_ENTITY,
        source_memory_id=wal_memory,
        created_at="2026-10-27T14:21:00+00:00",
    )

    return SimpleNamespace(
        initial_memory=initial_memory,
        benchmark_memory=benchmark_memory,
        wal_memory=wal_memory,
        procedural_memory=PROCEDURAL_MEMORY,
        superseded=superseded,
    )


def ids(entries):
    return [entry["id"] for entry in entries]


def context_ids(entries):
    return [entry["record"]["id"] for entry in entries]


def test_stage1_corpus_survives_restart_and_replay(tmp_path):
    corpus = materialize_corpus(tmp_path)
    stack = corpus.stack
    results = corpus.results

    assert len(CORPUS) == 37
    assert len(stack.event_log.load_events()) == 37
    assert stack.coordinator.finalized_count() == 37

    assert corpus.recovery == {
        "adopted": 0,
        "retried": 0,
        "finalized": 18,
    }
    assert corpus.replay["action"] == "already_done"
    assert corpus.before_replay == corpus.after_replay
    assert corpus.first_memory_count == corpus.before_replay

    assert results["sqlite_initial"]["action"] == "create"
    assert results["sqlite_followup"]["action"] == "update"
    assert (
        results["sqlite_followup"]["memory_id"]
        == results["sqlite_initial"]["memory_id"]
    )
    assert results["cm5_initial"]["action"] == "create"
    assert results["cm5_followup"]["action"] == "update"
    assert (
        results["cm5_followup"]["memory_id"]
        == results["cm5_initial"]["memory_id"]
    )
    assert results["cyberdeck_followup"]["action"] == "update"
    assert (
        results["cyberdeck_followup"]["memory_id"]
        == results["cyberdeck_initial"]["memory_id"]
    )
    assert results["backup_tool"]["action"] == "skip"
    assert results["sqlite_benchmark"]["action"] == "create_related"
    assert results["sqlite_wal_result"]["action"] == "create_related"
    assert stack.store.count() == 11

    initial_id = results["sqlite_initial"]["memory_id"]
    assert stack.store.source_events(initial_id) == [
        corpus.events["sqlite_initial"].event_id,
        corpus.events["sqlite_followup"].event_id,
    ]

    benchmark_relation = stack.links.get_relation(
        results["sqlite_benchmark"]["relation_id"]
    )
    assert benchmark_relation["type"] == "related_to"
    assert benchmark_relation["target_id"] == initial_id

    sqlite_about = stack.links.relations_for(
        "memory",
        initial_id,
        direction="outgoing",
        relation_types={"about"},
    )
    assert [relation["target_id"] for relation in sqlite_about] == [
        SQLITE_ENTITY
    ]

    print(
        "[stage1] raw_events=37 finalized=37 memories=11 "
        "restart_retried=0 replay=already_done"
    )


def test_stage1_knowledge_retrieval_context_and_provenance(tmp_path):
    corpus = materialize_corpus(tmp_path)
    semantic = add_semantic_layer(corpus)
    stack = corpus.stack

    assert stack.store.count() == 12

    old = stack.knowledge.describe(OLD_KNOWLEDGE)
    new = stack.knowledge.describe(NEW_KNOWLEDGE)
    assert old["knowledge"]["status"] == "superseded"
    assert old["superseded_by"] == [NEW_KNOWLEDGE]
    assert new["knowledge"]["status"] == "confirmed"
    assert new["supersedes"] == [OLD_KNOWLEDGE]
    assert new["supporting_sources"] == [semantic.wal_memory]

    assert [
        entry["operation"]
        for entry in stack.knowledge.history(OLD_KNOWLEDGE)
    ] == ["create", "confirm", "challenge", "supersede"]
    assert [
        entry["operation"]
        for entry in stack.knowledge.history(NEW_KNOWLEDGE)
    ] == ["create_superseding"]

    old_provenance = stack.provenance.knowledge(OLD_KNOWLEDGE)
    old_event_ids = {
        event["id"]
        for source in old_provenance["sources"]
        for event in source["events"]
    }
    assert corpus.events["sqlite_initial"].event_id in old_event_ids
    assert corpus.events["sqlite_followup"].event_id in old_event_ids
    assert corpus.events["sqlite_benchmark"].event_id in old_event_ids

    new_provenance = stack.provenance.knowledge(NEW_KNOWLEDGE)
    assert {
        event["id"]
        for source in new_provenance["sources"]
        for event in source["events"]
    } == {corpus.events["sqlite_wal_result"].event_id}

    procedural = stack.provenance.memory(semantic.procedural_memory)
    assert [event["id"] for event in procedural["events"]] == [
        corpus.events["backup_tool"].event_id
    ]

    current = stack.retrieval.retrieve(
        "SQLite concurrent writes",
        top_k=5,
    )
    current_ids = ids(current["results"])
    assert NEW_KNOWLEDGE in current_ids
    assert OLD_KNOWLEDGE not in current_ids

    exact_old = stack.retrieval.retrieve(OLD_KNOWLEDGE, top_k=3)
    assert ids(exact_old["results"])[0] == OLD_KNOWLEDGE

    by_entity = stack.retrieval.retrieve(
        entity_names=["sqlite3"],
        relation_hops=0,
        top_k=10,
    )
    assert NEW_KNOWLEDGE in ids(by_entity["results"])
    assert OLD_KNOWLEDGE not in ids(by_entity["results"])

    procedural_search = stack.retrieval.retrieve(
        "backup memory migration",
        kinds={"memory"},
        domain="system",
        memory_types={"procedural"},
        memory_statuses={"closed"},
        relation_hops=0,
        top_k=3,
    )
    assert ids(procedural_search["results"])[0] == PROCEDURAL_MEMORY

    fast = stack.context.build(
        "SQLite concurrent writes",
        consumer="FAST",
        max_items=4,
        max_chars=600,
    )
    assert context_ids(fast["knowledge"])[0] == NEW_KNOWLEDGE
    assert fast["events"] == []
    assert fast["selection_stats"]["items_used"] <= 4
    assert fast["selection_stats"]["chars_used"] <= 600

    deep = stack.context.build(
        "SQLite concurrent writes",
        consumer="DEEP",
        max_items=30,
        max_chars=5000,
    )
    assert NEW_KNOWLEDGE in context_ids(deep["knowledge"])
    assert corpus.events["sqlite_wal_result"].event_id in context_ids(
        deep["events"]
    )
    assert deep["selection_stats"]["items_used"] <= 30
    assert deep["selection_stats"]["chars_used"] <= 5000

    print(
        "[stage1] knowledge=superseded->confirmed procedural=closed "
        f"retrieval_rank={current_ids.index(NEW_KNOWLEDGE) + 1} "
        f"deep_items={deep['selection_stats']['items_used']}"
    )
