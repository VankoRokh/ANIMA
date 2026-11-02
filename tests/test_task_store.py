import sqlite3
from uuid import uuid4

import pytest

from anima.tasks.contracts import Task, TaskTransition
from anima.tasks.store import TaskStore


def goal_id():
    return f"goal_{uuid4()}"


def task_id():
    return f"task_{uuid4()}"


def transition_id():
    return f"tt_{uuid4()}"


def test_task_store_create_and_reopen_preserves_task_and_history(tmp_path):
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    goal = goal_id()

    created = store.create_task(
        source="user",
        source_id="ev_source",
        goal_id=goal,
        description="Inspect the requested state",
        reason="user request accepted",
        timestamp="2026-11-02T12:00:00+00:00",
    )

    assert isinstance(created, Task)
    assert created.public_id.startswith("task_")
    assert created.status == "queued"
    assert created.goal_id == goal
    assert created.source == "user"
    assert created.source_id == "ev_source"
    assert created.resolved_at is None
    assert created.terminal_reason is None

    transitions = store.list_transitions(created.public_id)
    assert len(transitions) == 1
    assert isinstance(transitions[0], TaskTransition)
    assert transitions[0].from_status is None
    assert transitions[0].to_status == "queued"
    assert transitions[0].reason == "user request accepted"

    reopened = TaskStore(database)
    assert reopened.schema_version() == 1
    assert reopened.get_task(created.public_id) == created
    assert reopened.list_transitions(created.public_id) == transitions


def test_task_lifecycle_interrupt_resume_and_completion(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    created = store.create_task(
        source="system",
        description="Complete one recoverable unit of work",
        reason="task admitted",
        timestamp="2026-11-02T12:00:00+00:00",
    )

    active = store.transition_task(
        created.public_id,
        "active",
        reason="work started",
        timestamp="2026-11-02T12:01:00+00:00",
    )
    interrupted = store.transition_task(
        created.public_id,
        "interrupted",
        reason="sleep requested",
        source_id="system.sleep",
        timestamp="2026-11-02T12:02:00+00:00",
    )
    resumed = store.transition_task(
        created.public_id,
        "active",
        reason="wake resumed task",
        source_id="system.wake",
        timestamp="2026-11-02T12:03:00+00:00",
    )
    completed = store.transition_task(
        created.public_id,
        "completed",
        reason="verified result satisfied task",
        timestamp="2026-11-02T12:04:00+00:00",
    )

    assert active.status == "active"
    assert interrupted.status == "interrupted"
    assert resumed.status == "active"
    assert completed.status == "completed"
    assert completed.resolved_at == "2026-11-02T12:04:00+00:00"
    assert completed.terminal_reason == "verified result satisfied task"

    transitions = store.list_transitions(created.public_id)
    assert [item.to_status for item in transitions] == [
        "queued",
        "active",
        "interrupted",
        "active",
        "completed",
    ]

    with pytest.raises(ValueError, match="Invalid Task transition"):
        store.transition_task(
            created.public_id,
            "active",
            reason="terminal task must not resume",
            timestamp="2026-11-02T12:05:00+00:00",
        )


def test_invalid_transition_does_not_mutate_task_or_history(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    created = store.create_task(
        source="user",
        description="Remain queued until activated",
        reason="created",
        timestamp="2026-11-02T12:00:00+00:00",
    )

    with pytest.raises(ValueError, match="Invalid Task transition: queued -> completed"):
        store.transition_task(
            created.public_id,
            "completed",
            reason="cannot complete before activation",
            timestamp="2026-11-02T12:01:00+00:00",
        )

    assert store.get_task(created.public_id).status == "queued"
    assert [item.to_status for item in store.list_transitions(created.public_id)] == [
        "queued"
    ]


def test_transition_and_history_commit_atomically(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    created = store.create_task(
        source="system",
        description="Atomic transition test",
        reason="created",
        timestamp="2026-11-02T12:00:00+00:00",
    )
    duplicate_transition = transition_id()

    store.transition_task(
        created.public_id,
        "active",
        reason="started",
        timestamp="2026-11-02T12:01:00+00:00",
        transition_id=duplicate_transition,
    )

    with pytest.raises(ValueError, match="Cannot transition Task"):
        store.transition_task(
            created.public_id,
            "interrupted",
            reason="must roll back because transition id collides",
            timestamp="2026-11-02T12:02:00+00:00",
            transition_id=duplicate_transition,
        )

    assert store.get_task(created.public_id).status == "active"
    assert [item.to_status for item in store.list_transitions(created.public_id)] == [
        "queued",
        "active",
    ]


def test_task_list_filters_by_status_and_goal(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    first_goal = goal_id()
    second_goal = goal_id()

    first = store.create_task(
        source="user",
        goal_id=first_goal,
        description="First task",
        reason="created",
        timestamp="2026-11-02T12:00:00+00:00",
    )
    second = store.create_task(
        source="user",
        goal_id=second_goal,
        description="Second task",
        reason="created",
        timestamp="2026-11-02T12:01:00+00:00",
    )
    store.transition_task(
        first.public_id,
        "active",
        reason="started",
        timestamp="2026-11-02T12:02:00+00:00",
    )

    assert [item.public_id for item in store.list_tasks(status="active")] == [
        first.public_id
    ]
    assert [item.public_id for item in store.list_tasks(goal_id=second_goal)] == [
        second.public_id
    ]
    assert store.list_tasks(status="active", goal_id=second_goal) == []


def test_task_goal_reference_is_validated_but_not_owned(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")

    with pytest.raises(ValueError, match="Task goal_id"):
        store.create_task(
            source="user",
            goal_id="not-a-goal",
            description="Invalid goal reference",
            reason="created",
        )

    external_goal = goal_id()
    created = store.create_task(
        source="user",
        goal_id=external_goal,
        description="Logical cross-store reference",
        reason="created",
    )
    assert created.goal_id == external_goal

    with sqlite3.connect(store.database_file) as connection:
        foreign_keys = connection.execute("PRAGMA foreign_key_list(tasks)").fetchall()
    assert foreign_keys == []


def test_task_store_rejects_unknown_schema_version(tmp_path):
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    assert store.schema_version() == 1

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'"
        )
        connection.commit()

    with pytest.raises(ValueError, match="Unsupported TaskStore schema"):
        TaskStore(database)


def test_task_contract_rejects_terminal_metadata_on_non_terminal_task():
    with pytest.raises(ValueError, match="Non-terminal Task"):
        Task(
            public_id=task_id(),
            source="system",
            source_id=None,
            goal_id=None,
            description="Bad contract",
            status="active",
            created_at="2026-11-02T12:00:00+00:00",
            updated_at="2026-11-02T12:00:00+00:00",
            resolved_at="2026-11-02T12:00:00+00:00",
            terminal_reason="should not exist",
        )
