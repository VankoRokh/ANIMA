from uuid import uuid4

import pytest

from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.processors import (
    ChunkResult,
    FinalizeResult,
    ProcessorDescriptor,
    ProcessorRegistry,
    SleepProcessor,
)
from anima.sleep.selection import SelectionBudget, SelectionCandidate, SleepSelector
from anima.sleep.store import SleepStore


class CountingProcessor(SleepProcessor):
    def __init__(self, *, name="counting", version="1", source_kinds=None):
        super().__init__(
            ProcessorDescriptor(
                name=name,
                version=version,
                work_kind="CONSOLIDATE",
                source_kinds=frozenset(source_kinds or {"event"}),
            )
        )

    def initial_checkpoint(self, work_item):
        self.require_supported(work_item)
        return {"chunks": 0, "items": 0}

    def process_chunk(self, work_item, *, chunk, checkpoint):
        self.require_supported(work_item)
        if not isinstance(chunk, list):
            raise ValueError("CountingProcessor test chunk must be a list")
        next_checkpoint = {
            "chunks": checkpoint["chunks"] + 1,
            "items": checkpoint["items"] + len(chunk),
        }
        return ChunkResult(
            checkpoint=next_checkpoint,
            local_result={"items": len(chunk)},
        )

    def finalize(self, work_item, *, checkpoint):
        self.require_supported(work_item)
        return FinalizeResult.create(
            work_item=work_item,
            output={
                "chunks": checkpoint["chunks"],
                "items": checkpoint["items"],
            },
        )


class TaggedProcessor(SleepProcessor):
    def __init__(self):
        super().__init__(
            ProcessorDescriptor(
                name="tagged",
                version="2",
                work_kind="CONSOLIDATE",
                source_kinds=frozenset({"event", "asset"}),
            )
        )

    def initial_checkpoint(self, work_item):
        self.require_supported(work_item)
        return {"seen": []}

    def process_chunk(self, work_item, *, chunk, checkpoint):
        self.require_supported(work_item)
        values = list(checkpoint["seen"])
        values.append(str(chunk))
        return ChunkResult(
            checkpoint={"seen": values},
            local_result={"tag": str(chunk)},
        )

    def finalize(self, work_item, *, checkpoint):
        self.require_supported(work_item)
        return FinalizeResult.create(
            work_item=work_item,
            output={"tagged": checkpoint["seen"]},
        )


def _work_item(*, source_kind="event", processor="counting", version="1"):
    prefixes = {
        "event": "ev_",
        "memory": "mem_",
        "knowledge": "kn_",
        "asset": "asset_",
    }
    return WorkItem.create(
        job_id=f"sj_{uuid4()}",
        source_ref=SourceRef(source_kind, f"{prefixes[source_kind]}{uuid4()}"),
        processor=processor,
        processor_version=version,
    )


def test_processor_descriptor_validates_identity_and_capabilities():
    descriptor = ProcessorDescriptor(
        name="deterministic",
        version="1",
        work_kind="CONSOLIDATE",
        source_kinds=frozenset({"event", "memory"}),
    )

    assert descriptor.name == "deterministic"
    assert descriptor.source_kinds == frozenset({"event", "memory"})

    with pytest.raises(ValueError, match="Processor name must be a non-empty string"):
        ProcessorDescriptor(
            name="",
            version="1",
            work_kind="CONSOLIDATE",
            source_kinds=frozenset({"event"}),
        )

    with pytest.raises(ValueError, match="non-empty frozenset"):
        ProcessorDescriptor(
            name="test",
            version="1",
            work_kind="CONSOLIDATE",
            source_kinds=frozenset(),
        )

    with pytest.raises(ValueError, match="Unsupported processor source kinds"):
        ProcessorDescriptor(
            name="test",
            version="1",
            work_kind="CONSOLIDATE",
            source_kinds=frozenset({"video"}),
        )


def test_processor_registry_resolves_exact_name_and_version():
    processor = CountingProcessor()
    registry = ProcessorRegistry().register(processor)
    work_item = _work_item()

    assert registry.resolve(work_item) is processor

    wrong_version = _work_item(version="2")
    with pytest.raises(ValueError, match="No processor registered"):
        registry.resolve(wrong_version)


def test_processor_registry_rejects_duplicate_adapter_identity():
    registry = ProcessorRegistry().register(CountingProcessor())

    with pytest.raises(ValueError, match="Processor already registered"):
        registry.register(CountingProcessor())


def test_processor_registry_has_no_fallback_for_unsupported_source_kind():
    registry = ProcessorRegistry().register(CountingProcessor(source_kinds={"event"}))
    memory_item = _work_item(source_kind="memory")

    with pytest.raises(ValueError, match="does not support source kind"):
        registry.resolve(memory_item)


def test_processor_requires_matching_work_item_identity():
    processor = CountingProcessor()

    with pytest.raises(ValueError, match="Processor name mismatch"):
        processor.require_supported(_work_item(processor="other"))

    with pytest.raises(ValueError, match="Processor version mismatch"):
        processor.require_supported(_work_item(version="9"))


def test_chunk_result_requires_serializable_checkpoint_and_local_result():
    result = ChunkResult(
        checkpoint={"cursor": 2},
        local_result={"accepted": [1, 2]},
    )
    assert result.checkpoint == {"cursor": 2}

    with pytest.raises(ValueError, match="checkpoint must be JSON-serializable"):
        ChunkResult(checkpoint={"bad": {1, 2}})

    with pytest.raises(ValueError, match="local_result must be JSON-serializable"):
        ChunkResult(checkpoint={}, local_result=float("nan"))


def test_finalize_result_keeps_processor_version_source_and_work_identity():
    work_item = _work_item()
    result = FinalizeResult.create(
        work_item=work_item,
        output={"summary": "done"},
    )

    assert result.work_item_id == work_item.public_id
    assert result.source_ref == work_item.source_ref
    assert result.processor == "counting"
    assert result.processor_version == "1"
    assert result.output == {"summary": "done"}

    with pytest.raises(ValueError, match="output must be JSON-serializable"):
        FinalizeResult.create(work_item=work_item, output={"bad": object()})


def test_processor_contract_supports_checkpoint_chunk_and_finalize_cycle():
    work_item = _work_item()
    processor = CountingProcessor()

    checkpoint = processor.initial_checkpoint(work_item)
    first = processor.process_chunk(
        work_item,
        chunk=["a", "b"],
        checkpoint=checkpoint,
    )
    second = processor.process_chunk(
        work_item,
        chunk=["c"],
        checkpoint=first.checkpoint,
    )
    final = processor.finalize(work_item, checkpoint=second.checkpoint)

    assert first.local_result == {"items": 2}
    assert second.checkpoint == {"chunks": 2, "items": 3}
    assert final.output == {"chunks": 2, "items": 3}


def test_scheduler_can_select_same_source_for_two_replaceable_processors(tmp_path):
    source = SourceRef("event", f"ev_{uuid4()}")
    source_registry = SourceRegistry().register(
        "event",
        lambda source_id: source_id == source.source_id,
    )
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    selector = SleepSelector(
        sleep_store=store,
        source_registry=source_registry,
    )
    budget = SelectionBudget(max_items=1, max_cost_units=2)
    candidates = [SelectionCandidate(source, priority=5, cost_hint="normal")]

    first = selector.select(
        job_id=job["id"],
        candidates=candidates,
        processor="counting",
        processor_version="1",
        budget=budget,
    ).work_items[0]
    second = selector.select(
        job_id=job["id"],
        candidates=candidates,
        processor="tagged",
        processor_version="2",
        budget=budget,
    ).work_items[0]

    registry = ProcessorRegistry()
    registry.register(CountingProcessor())
    registry.register(TaggedProcessor())

    assert registry.resolve(first).descriptor.name == "counting"
    assert registry.resolve(second).descriptor.name == "tagged"
    assert first.source_ref == second.source_ref == source
    assert first.public_id != second.public_id


def test_second_adapter_uses_same_contract_for_asset_without_scheduler_changes(tmp_path):
    source = SourceRef("asset", f"asset_{uuid4()}")
    source_registry = SourceRegistry().register("asset", lambda source_id: True)
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    selector = SleepSelector(
        sleep_store=store,
        source_registry=source_registry,
    )

    work_item = selector.select(
        job_id=job["id"],
        candidates=[SelectionCandidate(source, priority=1, cost_hint="cheap")],
        processor="tagged",
        processor_version="2",
        budget=SelectionBudget(max_items=1, max_cost_units=1),
    ).work_items[0]

    processor = ProcessorRegistry().register(TaggedProcessor()).resolve(work_item)
    checkpoint = processor.initial_checkpoint(work_item)
    chunk_result = processor.process_chunk(
        work_item,
        chunk={"opaque": "asset-chunk"},
        checkpoint=checkpoint,
    )
    final = processor.finalize(work_item, checkpoint=chunk_result.checkpoint)

    assert final.source_ref.kind == "asset"
    assert final.processor == "tagged"
    assert final.processor_version == "2"
    assert final.output == {"tagged": ["{'opaque': 'asset-chunk'}"]}
