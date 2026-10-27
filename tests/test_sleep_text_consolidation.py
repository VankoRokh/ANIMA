from uuid import uuid4

import pytest

from anima.core.event_bus import Event
from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.memory_store import MemoryStore
from anima.sleep.contracts import SourceRef, WorkItem
from anima.sleep.text_consolidation import (
    DeterministicTextConsolidationProcessor,
    TextSourceReader,
)


def _source_fixture(tmp_path):
    event_log = EventLog(tmp_path / "events.jsonl")
    event = Event(
        "conversation.user",
        {
            "text": "  Alpha   beta  ",
            "note": "Beta",
            "nested": {"again": "Beta"},
        },
        source="user",
        timestamp="2026-10-27T10:00:00+00:00",
    )
    event_log.write(event)

    memory_store = MemoryStore(tmp_path / "memory.db")
    closed_memory = memory_store.create_memory(
        memory_type="episodic",
        domain="project",
        status="closed",
        content="  Closed   project memory  ",
        importance=2,
        created_at="2026-10-27T10:01:00+00:00",
        source_event_id=event.event_id,
    )
    open_memory = memory_store.create_memory(
        memory_type="episodic",
        domain="project",
        status="open",
        content="Open memory must not consolidate yet",
        importance=1,
        created_at="2026-10-27T10:01:30+00:00",
        source_event_id=event.event_id,
    )

    knowledge_layer = KnowledgeLayer(memory_store=memory_store)
    confirmed = knowledge_layer.create_candidate(
        domain="project",
        statement="  Confirmed   project knowledge  ",
        source_memory_id=closed_memory["id"],
        created_at="2026-10-27T10:02:00+00:00",
    )
    confirmed = knowledge_layer.confirm(
        confirmed["knowledge"]["id"],
        confirmed_at="2026-10-27T10:03:00+00:00",
    )
    provisional = knowledge_layer.create_candidate(
        domain="project",
        statement="Provisional knowledge",
        source_memory_id=closed_memory["id"],
        created_at="2026-10-27T10:04:00+00:00",
    )

    reader = TextSourceReader(
        event_log=event_log,
        memory_store=memory_store,
        knowledge_layer=knowledge_layer,
    )
    return {
        "event_log": event_log,
        "event": event,
        "memory_store": memory_store,
        "closed_memory": closed_memory,
        "open_memory": open_memory,
        "knowledge_layer": knowledge_layer,
        "confirmed": confirmed["knowledge"],
        "provisional": provisional["knowledge"],
        "reader": reader,
    }


def _work_item(source_ref):
    return WorkItem.create(
        job_id=f"sj_{uuid4()}",
        source_ref=source_ref,
        processor="deterministic-text",
        processor_version="1",
    )


def _chunk(source_ref, fragments):
    return {
        "source": source_ref.to_dict(),
        "fragments": fragments,
    }


def _run(processor, work_item, chunks):
    checkpoint = processor.initial_checkpoint(work_item)
    local_results = []
    for chunk in chunks:
        result = processor.process_chunk(
            work_item,
            chunk=chunk,
            checkpoint=checkpoint,
        )
        checkpoint = result.checkpoint
        local_results.append(result.local_result)
    return processor.finalize(work_item, checkpoint=checkpoint), local_results


def test_text_source_reader_maps_event_memory_and_knowledge_to_one_contract(tmp_path):
    fixture = _source_fixture(tmp_path)
    refs = [
        SourceRef("event", fixture["event"].event_id),
        SourceRef("memory", fixture["closed_memory"]["id"]),
        SourceRef("knowledge", fixture["confirmed"]["id"]),
    ]

    records = [fixture["reader"].read(ref) for ref in refs]

    assert [record.source_ref for record in records] == refs
    assert all(isinstance(record.to_chunk()["fragments"], list) for record in records)
    assert [len(record.fragments) for record in records] == [3, 1, 1]
    assert records[1].fragments[0].group == "memory:project:episodic"
    assert records[2].fragments[0].group == "knowledge:project"


def test_text_source_reader_enforces_baseline_memory_and_knowledge_eligibility(tmp_path):
    fixture = _source_fixture(tmp_path)

    with pytest.raises(ValueError, match="Ineligible memory source"):
        fixture["reader"].read(
            SourceRef("memory", fixture["open_memory"]["id"])
        )

    with pytest.raises(ValueError, match="Ineligible knowledge source"):
        fixture["reader"].read(
            SourceRef("knowledge", fixture["provisional"]["id"])
        )


def test_text_source_reader_rejects_asset_and_dangling_source(tmp_path):
    fixture = _source_fixture(tmp_path)

    with pytest.raises(ValueError, match="does not support source kind"):
        fixture["reader"].read(SourceRef("asset", f"asset_{uuid4()}"))

    with pytest.raises(ValueError, match="Dangling text source"):
        fixture["reader"].read(SourceRef("event", f"ev_{uuid4()}"))


def test_text_processor_is_deterministic_across_chunk_order_and_deduplicates():
    source = SourceRef("event", f"ev_{uuid4()}")
    work_item = _work_item(source)
    processor = DeterministicTextConsolidationProcessor(
        max_items=10,
        max_chars=100,
    )
    first_chunk = _chunk(
        source,
        [
            {"group": "zeta", "text": " Zed "},
            {"group": "alpha", "text": "Alpha   beta"},
        ],
    )
    second_chunk = _chunk(
        source,
        [
            {"group": "alpha", "text": "Alpha beta"},
            {"group": "alpha", "text": "Gamma"},
        ],
    )

    forward, _ = _run(processor, work_item, [first_chunk, second_chunk])
    reverse, _ = _run(processor, work_item, [second_chunk, first_chunk])

    assert forward.output == reverse.output
    assert forward.output["groups"] == [
        {"group": "alpha", "items": ["Alpha beta", "Gamma"]},
        {"group": "zeta", "items": ["Zed"]},
    ]
    assert forward.output["stats"]["input_fragments"] == 4
    assert forward.output["stats"]["unique_fragments"] == 3
    assert forward.output["stats"]["dropped_duplicates"] == 1


def test_text_processor_applies_item_and_char_bounds_after_sorting():
    source = SourceRef("event", f"ev_{uuid4()}")
    work_item = _work_item(source)
    processor = DeterministicTextConsolidationProcessor(
        max_items=2,
        max_chars=4,
    )

    final, _ = _run(
        processor,
        work_item,
        [
            _chunk(
                source,
                [
                    {"group": "g", "text": "c"},
                    {"group": "g", "text": "bbb"},
                    {"group": "g", "text": "aa"},
                ],
            )
        ],
    )

    assert final.output["groups"] == [
        {"group": "g", "items": ["aa", "c"]}
    ]
    assert final.output["output_chars"] == 3
    assert final.output["stats"]["output_fragments"] == 2
    assert final.output["stats"]["dropped_budget"] == 1


def test_text_processor_filters_empty_fragments_and_normalizes_whitespace():
    source = SourceRef("event", f"ev_{uuid4()}")
    work_item = _work_item(source)
    processor = DeterministicTextConsolidationProcessor()

    final, local_results = _run(
        processor,
        work_item,
        [
            _chunk(
                source,
                [
                    {"group": "g", "text": "   "},
                    {"group": "g", "text": " one\n two\tthree "},
                ],
            )
        ],
    )

    assert local_results == [
        {"input_fragments": 2, "accepted_fragments": 1}
    ]
    assert final.output["groups"] == [
        {"group": "g", "items": ["one two three"]}
    ]
    assert final.output["stats"]["dropped_empty"] == 1


def test_text_processor_rejects_chunk_for_another_source():
    source = SourceRef("event", f"ev_{uuid4()}")
    other = SourceRef("event", f"ev_{uuid4()}")
    work_item = _work_item(source)
    processor = DeterministicTextConsolidationProcessor()
    checkpoint = processor.initial_checkpoint(work_item)

    with pytest.raises(ValueError, match="source does not match WorkItem"):
        processor.process_chunk(
            work_item,
            chunk=_chunk(other, [{"group": "g", "text": "text"}]),
            checkpoint=checkpoint,
        )


def test_text_processor_explicitly_rejects_asset_work_item():
    work_item = _work_item(SourceRef("asset", f"asset_{uuid4()}"))
    processor = DeterministicTextConsolidationProcessor()

    with pytest.raises(ValueError, match="does not support source kind"):
        processor.initial_checkpoint(work_item)


def test_real_source_records_remain_unchanged_after_consolidation(tmp_path):
    fixture = _source_fixture(tmp_path)
    refs = [
        SourceRef("event", fixture["event"].event_id),
        SourceRef("memory", fixture["closed_memory"]["id"]),
        SourceRef("knowledge", fixture["confirmed"]["id"]),
    ]
    before_events = fixture["event_log"].load_events()
    before_memory = fixture["memory_store"].get_memory(
        fixture["closed_memory"]["id"]
    )
    before_knowledge = fixture["knowledge_layer"].describe(
        fixture["confirmed"]["id"]
    )

    processor = DeterministicTextConsolidationProcessor()
    for ref in refs:
        record = fixture["reader"].read(ref)
        work_item = _work_item(ref)
        final, _ = _run(processor, work_item, [record.to_chunk()])
        assert final.source_ref == ref
        assert final.processor == "deterministic-text"
        assert final.processor_version == "1"

    assert fixture["event_log"].load_events() == before_events
    assert fixture["memory_store"].get_memory(
        fixture["closed_memory"]["id"]
    ) == before_memory
    assert fixture["knowledge_layer"].describe(
        fixture["confirmed"]["id"]
    ) == before_knowledge
    assert fixture["knowledge_layer"].get(
        fixture["confirmed"]["id"]
    )["status"] == "confirmed"


@pytest.mark.parametrize(
    ("max_items", "max_chars", "message"),
    [
        (-1, 10, "max_items must be a non-negative integer"),
        (True, 10, "max_items must be a non-negative integer"),
        (10, -1, "max_chars must be a non-negative integer"),
        (10, True, "max_chars must be a non-negative integer"),
    ],
)
def test_text_processor_limit_validation(max_items, max_chars, message):
    with pytest.raises(ValueError, match=message):
        DeterministicTextConsolidationProcessor(
            max_items=max_items,
            max_chars=max_chars,
        )


def test_zero_limits_produce_empty_but_well_formed_derived_output():
    source = SourceRef("event", f"ev_{uuid4()}")
    work_item = _work_item(source)
    processor = DeterministicTextConsolidationProcessor(
        max_items=0,
        max_chars=0,
    )

    final, _ = _run(
        processor,
        work_item,
        [_chunk(source, [{"group": "g", "text": "value"}])],
    )

    assert final.output["groups"] == []
    assert final.output["stats"]["output_fragments"] == 0
    assert final.output["stats"]["dropped_budget"] == 1
    assert final.output["source"] == source.to_dict()
