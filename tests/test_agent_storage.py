import sqlite3
from uuid import uuid4

import pytest

from anima.agent.store import AgentStore


def _goal_id():
    return f"goal_{uuid4()}"


def _running_run(store, *, goal_id=None):
    run = store.create_run(
        goal_id=goal_id or _goal_id(),
        planner="deterministic",
        planner_version="1",
    )
    return store.transition_run(run["id"], "running", reason="start")


def _selected_step(store, run_id):
    step = store.create_step(run_id=run_id)
    step = store.transition_step(step["id"], "planned", reason="plan ready")
    return store.transition_step(step["id"], "selected", reason="choice selected")


def test_agent_store_initializes_schema_and_queued_run(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    goal_id = _goal_id()
    run = store.create_run(
        goal_id=goal_id,
        planner="deterministic",
        planner_version="1",
        created_at="2026-10-27T16:00:00+00:00",
    )

    assert store.schema_version() == 1
    assert run["id"].startswith("ar_")
    assert run["goal_id"] == goal_id
    assert run["planner"] == "deterministic"
    assert run["planner_version"] == "1"
    assert run["status"] == "queued"
    assert run["terminal_reason"] is None
    assert run["created_at"] == "2026-10-27T16:00:00+00:00"
    assert run["updated_at"] == run["created_at"]

    transitions = store.list_run_transitions(run["id"])
    assert len(transitions) == 1
    assert transitions[0]["from_status"] is None
    assert transitions[0]["to_status"] == "queued"


def test_agent_store_reopens_without_losing_run_step_or_operation(tmp_path):
    database = tmp_path / "agent.db"
    first = AgentStore(database)
    run = _running_run(first)
    step = _selected_step(first, run["id"])
    operation = first.create_operation(
        run_id=run["id"],
        step_id=step["id"],
        action_id=f"act_{uuid4()}",
        operation_kind="tool.execute",
        request_hash="a" * 64,
        idempotency_class="keyed",
    )
    first.transition_operation(operation["id"], "executing", reason="started")
    first.transition_operation(operation["id"], "uncertain", reason="crash boundary")

    reopened = AgentStore(database)

    assert reopened.get_run(run["id"])["status"] == "running"
    assert reopened.get_step(step["id"])["status"] == "selected"
    restored_operation = reopened.get_operation(operation["id"])
    assert restored_operation["id"] == operation["id"]
    assert restored_operation["status"] == "uncertain"
    assert restored_operation["request_hash"] == "a" * 64


def test_agent_store_allows_only_one_non_terminal_run_per_goal(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    goal_id = _goal_id()
    first = store.create_run(
        goal_id=goal_id,
        planner="deterministic",
        planner_version="1",
    )

    with pytest.raises(ValueError, match="Cannot create AgentRun"):
        store.create_run(
            goal_id=goal_id,
            planner="deterministic",
            planner_version="1",
        )

    store.transition_run(first["id"], "failed", reason="attempt failed")
    second = store.create_run(
        goal_id=goal_id,
        planner="deterministic",
        planner_version="1",
    )

    assert second["id"] != first["id"]
    assert [run["status"] for run in store.list_runs(goal_id=goal_id)] == [
        "failed",
        "queued",
    ]


def test_agent_run_lifecycle_supports_interruption_resume_and_completion(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = store.create_run(
        goal_id=_goal_id(),
        planner="deterministic",
        planner_version="1",
    )

    for status, reason in [
        ("running", "start"),
        ("interrupted", "controlled stop"),
        ("running", "resume"),
        ("completed", "goal already verified"),
    ]:
        run = store.transition_run(run["id"], status, reason=reason)

    assert run["status"] == "completed"
    assert run["terminal_reason"] == "goal already verified"
    assert [
        item["to_status"] for item in store.list_run_transitions(run["id"])
    ] == ["queued", "running", "interrupted", "running", "completed"]


@pytest.mark.parametrize(
    ("initial_steps", "invalid_status"),
    [
        ([], "completed"),
        ([], "queued"),
        (["running", "completed"], "running"),
        (["running", "interrupted"], "queued"),
        (["failed"], "running"),
    ],
)
def test_agent_run_rejects_invalid_transitions(
    tmp_path,
    initial_steps,
    invalid_status,
):
    store = AgentStore(tmp_path / "agent.db")
    run = store.create_run(
        goal_id=_goal_id(),
        planner="deterministic",
        planner_version="1",
    )

    for index, status in enumerate(initial_steps):
        run = store.transition_run(run["id"], status, reason=f"step {index}")

    before = store.get_run(run["id"])
    transition_count = len(store.list_run_transitions(run["id"]))

    with pytest.raises(ValueError, match="Invalid AgentRun transition"):
        store.transition_run(run["id"], invalid_status, reason="invalid")

    assert store.get_run(run["id"]) == before
    assert len(store.list_run_transitions(run["id"])) == transition_count


def test_agent_step_requires_running_run_and_sequences_after_terminal_step(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = store.create_run(
        goal_id=_goal_id(),
        planner="deterministic",
        planner_version="1",
    )

    with pytest.raises(ValueError, match="requires a running AgentRun"):
        store.create_step(run_id=run["id"])

    run = store.transition_run(run["id"], "running", reason="start")
    first = store.create_step(run_id=run["id"])
    assert first["sequence"] == 0
    assert first["status"] == "planning"

    with pytest.raises(ValueError, match="Cannot create AgentStep"):
        store.create_step(run_id=run["id"])

    first = store.transition_step(first["id"], "planned", reason="plan")
    first = store.transition_step(first["id"], "completed", reason="cannot progress")
    assert first["terminal_reason"] == "cannot progress"

    second = store.create_step(run_id=run["id"])
    assert second["sequence"] == 1


def test_agent_step_full_lifecycle_and_transitions_are_recorded(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = _running_run(store)
    step = store.create_step(run_id=run["id"])

    for status, reason in [
        ("planned", "proposals ready"),
        ("selected", "choice selected"),
        ("executing", "tool call started"),
        ("executed", "tool returned"),
        ("observed", "environment observed"),
        ("verified", "result checked"),
        ("completed", "step done"),
    ]:
        step = store.transition_step(step["id"], status, reason=reason)

    assert step["status"] == "completed"
    assert step["terminal_reason"] == "step done"
    assert [
        item["to_status"] for item in store.list_step_transitions(step["id"])
    ] == [
        "planning",
        "planned",
        "selected",
        "executing",
        "executed",
        "observed",
        "verified",
        "completed",
    ]


def test_agent_step_cannot_cancel_during_execution(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = _running_run(store)
    step = _selected_step(store, run["id"])
    step = store.transition_step(step["id"], "executing", reason="started")

    with pytest.raises(ValueError, match="Invalid AgentStep transition"):
        store.transition_step(step["id"], "cancelled", reason="unsafe cancel")


def test_run_cannot_terminate_with_non_terminal_step(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = _running_run(store)
    store.create_step(run_id=run["id"])

    with pytest.raises(
        ValueError,
        match="Cannot terminate AgentRun with a non-terminal AgentStep",
    ):
        store.transition_run(run["id"], "failed", reason="technical failure")

    assert store.get_run(run["id"])["status"] == "running"


def test_agent_operation_lifecycle_supports_uncertain_reconciliation(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = _running_run(store)
    step = _selected_step(store, run["id"])
    operation = store.create_operation(
        run_id=run["id"],
        step_id=step["id"],
        action_id=f"act_{uuid4()}",
        operation_kind="tool.execute",
        request_hash="b" * 64,
        idempotency_class="keyed",
    )

    operation = store.transition_operation(
        operation["id"],
        "executing",
        reason="tool entered",
    )
    operation = store.transition_operation(
        operation["id"],
        "uncertain",
        reason="process died before receipt",
    )
    operation = store.transition_operation(
        operation["id"],
        "executing",
        reason="reconcile with same logical key",
    )
    operation = store.transition_operation(
        operation["id"],
        "succeeded",
        reason="effect confirmed",
    )

    assert operation["status"] == "succeeded"
    assert operation["status_reason"] == "effect confirmed"
    assert operation["idempotency_class"] == "keyed"


def test_agent_operation_requires_selected_step_and_matching_run(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run_a = _running_run(store)
    run_b = _running_run(store)
    step = store.create_step(run_id=run_a["id"])

    with pytest.raises(ValueError, match="requires a selected AgentStep"):
        store.create_operation(
            run_id=run_a["id"],
            step_id=step["id"],
            operation_kind="tool.execute",
            request_hash="c" * 64,
            idempotency_class="repeat_safe",
        )

    step = store.transition_step(step["id"], "planned", reason="plan")
    step = store.transition_step(step["id"], "selected", reason="selected")

    with pytest.raises(ValueError, match="must belong to the supplied AgentRun"):
        store.create_operation(
            run_id=run_b["id"],
            step_id=step["id"],
            operation_kind="tool.execute",
            request_hash="c" * 64,
            idempotency_class="repeat_safe",
        )


def test_agent_operation_validates_hash_idempotency_and_action_id(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = _running_run(store)
    step = _selected_step(store, run["id"])

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        store.create_operation(
            run_id=run["id"],
            step_id=step["id"],
            operation_kind="tool.execute",
            request_hash="XYZ",
            idempotency_class="repeat_safe",
        )

    with pytest.raises(ValueError, match="Unknown AgentOperation idempotency_class"):
        store.create_operation(
            run_id=run["id"],
            step_id=step["id"],
            operation_kind="tool.execute",
            request_hash="d" * 64,
            idempotency_class="magic",
        )

    with pytest.raises(ValueError, match="act_UUIDv4"):
        store.create_operation(
            run_id=run["id"],
            step_id=step["id"],
            action_id="action_123",
            operation_kind="tool.execute",
            request_hash="d" * 64,
            idempotency_class="repeat_safe",
        )


def test_step_and_run_cannot_terminate_with_non_terminal_operation(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = _running_run(store)
    step = _selected_step(store, run["id"])
    operation = store.create_operation(
        run_id=run["id"],
        step_id=step["id"],
        operation_kind="tool.execute",
        request_hash="e" * 64,
        idempotency_class="none",
    )

    with pytest.raises(
        ValueError,
        match="Cannot terminate AgentStep with a non-terminal AgentOperation",
    ):
        store.transition_step(step["id"], "failed", reason="abort")

    store.transition_operation(operation["id"], "cancelled", reason="not executed")
    store.transition_step(step["id"], "failed", reason="abort")

    # Once the Step has resolved its operation it can become terminal, and then the
    # Run may also terminate without losing a reconciliation obligation.
    failed = store.transition_run(run["id"], "failed", reason="run aborted")
    assert failed["status"] == "failed"


def test_agent_store_transaction_rolls_back(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = store.create_run(
        goal_id=_goal_id(),
        planner="deterministic",
        planner_version="1",
    )

    with pytest.raises(RuntimeError, match="rollback test"):
        with store.transaction() as connection:
            connection.execute(
                "UPDATE agent_runs SET status = 'running' WHERE public_id = ?",
                (run["id"],),
            )
            raise RuntimeError("rollback test")

    assert store.get_run(run["id"])["status"] == "queued"


def test_agent_store_database_constraints_and_foreign_keys(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    run = store.create_run(
        goal_id=_goal_id(),
        planner="deterministic",
        planner_version="1",
    )

    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE agent_runs SET status = 'unknown' WHERE public_id = ?",
                (run["id"],),
            )

    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_steps(
                    public_id, run_id, sequence, status,
                    terminal_reason, created_at, updated_at
                ) VALUES (?, ?, 0, 'planning', NULL, ?, ?)
                """,
                (
                    f"ast_{uuid4()}",
                    f"ar_{uuid4()}",
                    "2026-10-27T16:00:00+00:00",
                    "2026-10-27T16:00:00+00:00",
                ),
            )


def test_agent_store_reports_invalid_database_file(tmp_path):
    database = tmp_path / "agent.db"
    database.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(ValueError, match="Cannot initialize Agent database"):
        AgentStore(database)


def test_agent_store_default_database_uses_anima_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIMA_DATA_DIR", str(tmp_path))

    store = AgentStore()

    assert store.database_file == tmp_path / "agent.db"
    assert store.database_file.exists()


def test_agent_run_validates_ids_and_timestamps(tmp_path):
    store = AgentStore(tmp_path / "agent.db")

    with pytest.raises(ValueError, match="ar_UUIDv4"):
        store.create_run(
            public_id="run_123",
            goal_id=_goal_id(),
            planner="deterministic",
            planner_version="1",
        )

    with pytest.raises(ValueError, match="goal_UUIDv4"):
        store.create_run(
            goal_id="goal_bad",
            planner="deterministic",
            planner_version="1",
        )

    with pytest.raises(ValueError, match="UTC offset"):
        store.create_run(
            goal_id=_goal_id(),
            planner="deterministic",
            planner_version="1",
            created_at="2026-10-27T16:00:00",
        )
