from uuid import UUID

import pytest

from anima.sleep.contracts import SourceRef, SourceRegistry
from anima.sleep.selection import (
    SelectionBudget,
    SelectionCandidate,
    SleepSelector,
)
from anima.sleep.store import SleepStore


def _uuid(value):
    return str(UUID(int=value, version=4))


def _source(kind, value):
    prefixes = {
        "event": "ev_",
        "memory": "mem_",
        "knowledge": "kn_",
        "asset": "asset_",
    }
    return SourceRef(kind, prefixes[kind] + _uuid(value))


def _selector(tmp_path, sources):
    source_keys = {
        (source.kind, source.source_id)
        for source in sources
    }
    registry = SourceRegistry()
    for kind in {source.kind for source in sources}:
        registry.register(
            kind,
            lambda source_id, source_kind=kind: (
                source_kind,
                source_id,
            ) in source_keys,
        )
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    return store, job, SleepSelector(
        sleep_store=store,
        source_registry=registry,
    )


def test_selector_order_is_deterministic_and_repeated_selection_reuses_queue(tmp_path):
    event_a = _source("event", 1)
    event_b = _source("event", 2)
    memory = _source("memory", 3)
    asset = _source("asset", 4)
    sources = [event_a, event_b, memory, asset]
    store, job, selector = _selector(tmp_path, sources)

    candidates = [
        SelectionCandidate(memory, priority=5, cost_hint="normal"),
        SelectionCandidate(event_b, priority=5, cost_hint="cheap"),
        SelectionCandidate(asset, priority=7, cost_hint="expensive"),
        SelectionCandidate(event_a, priority=5, cost_hint="cheap"),
    ]
    budget = SelectionBudget(max_items=10, max_cost_units=20)

    first = selector.select(
        job_id=job["id"],
        candidates=candidates,
        processor="selector-test",
        processor_version="1",
        budget=budget,
    )
    second = selector.select(
        job_id=job["id"],
        candidates=reversed(candidates),
        processor="selector-test",
        processor_version="1",
        budget=budget,
    )

    expected_sources = [asset, event_a, event_b, memory]
    assert [item.source_ref for item in first.work_items] == expected_sources
    assert [item.source_ref for item in second.work_items] == expected_sources
    assert [item.public_id for item in second.work_items] == [
        item.public_id for item in first.work_items
    ]
    assert second.reused == 4
    assert len(store.list_work_items(job_id=job["id"])) == 4


def test_selector_uses_fixed_kind_and_source_id_tie_break(tmp_path):
    sources = [
        _source("memory", 4),
        _source("event", 3),
        _source("asset", 2),
        _source("knowledge", 1),
        _source("event", 1),
    ]
    _, job, selector = _selector(tmp_path, sources)
    candidates = [
        SelectionCandidate(source, priority=4, cost_hint="normal")
        for source in reversed(sources)
    ]

    result = selector.select(
        job_id=job["id"],
        candidates=candidates,
        processor="tie-break",
        processor_version="1",
        budget=SelectionBudget(max_items=10, max_cost_units=20),
    )

    assert [(item.source_ref.kind, item.source_ref.source_id) for item in result.work_items] == sorted(
        (source.kind, source.source_id) for source in sources
    )


def test_selector_respects_item_and_cost_budgets_and_can_skip_expensive_candidate(tmp_path):
    expensive = _source("asset", 1)
    normal = _source("memory", 2)
    cheap = _source("event", 3)
    extra = _source("knowledge", 4)
    _, job, selector = _selector(
        tmp_path,
        [expensive, normal, cheap, extra],
    )

    result = selector.select(
        job_id=job["id"],
        candidates=[
            SelectionCandidate(expensive, priority=10, cost_hint="expensive"),
            SelectionCandidate(normal, priority=9, cost_hint="normal"),
            SelectionCandidate(cheap, priority=8, cost_hint="cheap"),
            SelectionCandidate(extra, priority=7, cost_hint="cheap"),
        ],
        processor="budget-test",
        processor_version="1",
        budget=SelectionBudget(max_items=2, max_cost_units=3),
    )

    assert [item.source_ref for item in result.work_items] == [normal, cheap]
    assert result.total_cost_units == 3
    assert len(result.work_items) == 2
    assert result.skipped_budget == 2


def test_selector_excludes_ineligible_and_terminal_candidates(tmp_path):
    eligible = _source("event", 1)
    ineligible = _source("memory", 2)
    terminal = _source("knowledge", 3)
    _, job, selector = _selector(
        tmp_path,
        [eligible, ineligible, terminal],
    )

    result = selector.select(
        job_id=job["id"],
        candidates=[
            SelectionCandidate(eligible, priority=1),
            SelectionCandidate(ineligible, priority=99, eligible=False),
            SelectionCandidate(terminal, priority=100, terminal=True),
        ],
        processor="eligibility-test",
        processor_version="1",
        budget=SelectionBudget(max_items=10, max_cost_units=20),
    )

    assert [item.source_ref for item in result.work_items] == [eligible]
    assert result.considered == 3
    assert result.skipped_ineligible == 1
    assert result.skipped_terminal == 1


def test_selector_collapses_exact_duplicate_candidates(tmp_path):
    source = _source("event", 1)
    store, job, selector = _selector(tmp_path, [source])
    candidate = SelectionCandidate(source, priority=3, cost_hint="cheap")

    result = selector.select(
        job_id=job["id"],
        candidates=[candidate, candidate],
        processor="duplicate-test",
        processor_version="1",
        budget=SelectionBudget(max_items=10, max_cost_units=20),
    )

    assert result.considered == 1
    assert len(result.work_items) == 1
    assert len(store.list_work_items(job_id=job["id"])) == 1


def test_selector_rejects_conflicting_duplicate_candidates(tmp_path):
    source = _source("event", 1)
    _, job, selector = _selector(tmp_path, [source])

    with pytest.raises(ValueError, match="Conflicting selection candidates"):
        selector.select(
            job_id=job["id"],
            candidates=[
                SelectionCandidate(source, priority=1),
                SelectionCandidate(source, priority=2),
            ],
            processor="conflict-test",
            processor_version="1",
            budget=SelectionBudget(max_items=10, max_cost_units=20),
        )


def test_selector_reports_dangling_selected_source_without_partial_insert(tmp_path):
    valid = _source("event", 1)
    dangling = _source("event", 2)
    registry = SourceRegistry().register(
        "event",
        lambda source_id: source_id == valid.source_id,
    )
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    selector = SleepSelector(sleep_store=store, source_registry=registry)

    with pytest.raises(ValueError, match="Dangling source"):
        selector.select(
            job_id=job["id"],
            candidates=[
                SelectionCandidate(valid, priority=20),
                SelectionCandidate(dangling, priority=10),
            ],
            processor="dangling-test",
            processor_version="1",
            budget=SelectionBudget(max_items=10, max_cost_units=20),
        )

    assert store.list_work_items(job_id=job["id"]) == []


def test_selector_rejects_changed_metadata_for_existing_logical_work(tmp_path):
    source = _source("event", 1)
    _, job, selector = _selector(tmp_path, [source])
    budget = SelectionBudget(max_items=10, max_cost_units=20)

    selector.select(
        job_id=job["id"],
        candidates=[SelectionCandidate(source, priority=2, cost_hint="cheap")],
        processor="metadata-test",
        processor_version="1",
        budget=budget,
    )

    with pytest.raises(ValueError, match="metadata conflicts"):
        selector.select(
            job_id=job["id"],
            candidates=[SelectionCandidate(source, priority=3, cost_hint="cheap")],
            processor="metadata-test",
            processor_version="1",
            budget=budget,
        )


@pytest.mark.parametrize(
    ("max_items", "max_cost_units", "message"),
    [
        (-1, 1, "max_items must be a non-negative integer"),
        (True, 1, "max_items must be a non-negative integer"),
        (1, -1, "max_cost_units must be a non-negative integer"),
        (1, True, "max_cost_units must be a non-negative integer"),
    ],
)
def test_selection_budget_validation(max_items, max_cost_units, message):
    with pytest.raises(ValueError, match=message):
        SelectionBudget(max_items=max_items, max_cost_units=max_cost_units)


def test_zero_budget_creates_empty_queue_without_resolving_sources(tmp_path):
    source = _source("event", 1)
    registry = SourceRegistry().register("event", lambda source_id: False)
    store = SleepStore(tmp_path / "sleep.db")
    job = store.create_job()
    selector = SleepSelector(sleep_store=store, source_registry=registry)

    result = selector.select(
        job_id=job["id"],
        candidates=[SelectionCandidate(source, priority=10)],
        processor="zero-budget",
        processor_version="1",
        budget=SelectionBudget(max_items=0, max_cost_units=0),
    )

    assert result.work_items == ()
    assert result.total_cost_units == 0
    assert result.skipped_budget == 1
    assert store.list_work_items(job_id=job["id"]) == []
