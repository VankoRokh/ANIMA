from uuid import uuid4

import pytest

from anima.cognition.coordinator import (
    CognitiveCoordinator,
    CoordinatorDirective,
)
from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask, Evidence
from anima.resolution import ResolutionRoute
from anima.tasks.store import TaskStore


def active_task(store, *, description="coordinate one cognitive turn"):
    task = store.create_task(
        source="test",
        description=description,
        reason="test task created",
    )
    return store.transition_task(
        task.public_id,
        "active",
        reason="test task activated",
    )


def canonical(operation="OPEN", **kwargs):
    return CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation=operation,
        **kwargs,
    )


def test_coordinator_maps_deterministic_resolution_without_mutating_task(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = active_task(store)
    before = store.list_transitions(task.public_id)
    coordinator = CognitiveCoordinator(task_store=store)
    request = canonical(
        "QUERY_FACT",
        subject="device",
        predicate="state",
        evidence=(Evidence("fact_1", "ready", "device", "state"),),
    )

    turn = coordinator.process(task.public_id, request)

    assert turn.persistent_task_id == task.public_id
    assert turn.canonical_task_id == request.task_id
    assert turn.resolution.route == ResolutionRoute.DETERMINISTIC_RESULT
    assert turn.directive == CoordinatorDirective.FINAL
    assert turn.final_result == "ready"
    assert store.get_task(task.public_id).status == "active"
    assert store.list_transitions(task.public_id) == before


def test_coordinator_maps_insufficient_data_without_guessing(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = active_task(store)
    coordinator = CognitiveCoordinator(task_store=store)
    request = canonical(
        "QUERY_FACT",
        subject="device",
        predicate="location",
    )

    turn = coordinator.process(task.public_id, request)

    assert turn.resolution.route == ResolutionRoute.INSUFFICIENT_DATA
    assert turn.resolution.missing == ("device.location",)
    assert turn.directive == CoordinatorDirective.NEEDS_DATA
    assert turn.final_result is None


def test_coordinator_exposes_cognitive_remainder_without_calling_model(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = active_task(store)
    coordinator = CognitiveCoordinator(task_store=store)
    request = canonical("OPEN", raw_input="Consider the next step")

    turn = coordinator.process(task.public_id, request)

    assert turn.resolution.route == ResolutionRoute.COGNITIVE_REQUIRED
    assert turn.directive == CoordinatorDirective.ROUTE_COGNITION
    assert turn.final_result is None
    assert not hasattr(coordinator, "backend")
    assert not hasattr(coordinator, "model")
    assert not hasattr(coordinator, "router")


def test_coordinator_trace_links_persistent_and_canonical_task(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = active_task(store)
    trace = DiagnosticTrace()
    coordinator = CognitiveCoordinator(task_store=store, trace=trace)
    request = canonical("OPEN", raw_input="Need cognition")

    coordinator.process(task.public_id, request)

    messages = [entry["message"] for entry in trace.entries()]
    assert len(messages) == 2
    assert task.public_id in messages[0]
    assert request.task_id in messages[0]
    assert request.source_id in messages[0]
    assert task.public_id in messages[1]
    assert request.task_id in messages[1]
    assert "COGNITIVE_REQUIRED" in messages[1]
    assert "ROUTE_COGNITION" in messages[1]


def test_coordinator_uses_reopened_persistent_task(tmp_path):
    database = tmp_path / "tasks.db"
    first = TaskStore(database)
    task = active_task(first)

    reopened = TaskStore(database)
    coordinator = CognitiveCoordinator(task_store=reopened)
    request = canonical("CALCULATE", arguments={"left": 7, "right": 8, "operator": "*"})

    turn = coordinator.process(task.public_id, request)

    assert turn.directive == CoordinatorDirective.FINAL
    assert turn.final_result == 56
    assert reopened.get_task(task.public_id).status == "active"


def test_coordinator_requires_existing_active_task(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    queued = store.create_task(
        source="test",
        description="still queued",
        reason="created",
    )
    coordinator = CognitiveCoordinator(task_store=store)
    request = canonical()

    with pytest.raises(RuntimeError, match="active persistent Task"):
        coordinator.process(queued.public_id, request)

    unknown = f"task_{uuid4()}"
    with pytest.raises(ValueError, match="Unknown persistent Task"):
        coordinator.process(unknown, request)


def test_coordinator_rejects_invalid_boundaries(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = active_task(store)

    with pytest.raises(TypeError, match="task_store"):
        CognitiveCoordinator(task_store=object())
    with pytest.raises(TypeError, match="trace"):
        CognitiveCoordinator(task_store=store, trace=object())

    coordinator = CognitiveCoordinator(task_store=store)
    with pytest.raises(TypeError, match="CanonicalTask"):
        coordinator.process(task.public_id, object())
