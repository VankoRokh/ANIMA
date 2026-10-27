from datetime import datetime, timezone
from uuid import uuid4

from anima.agent import Action, ActionProposal, AgentStore
from anima.agent.executor import (
    MAX_FILE_BYTES,
    SandboxExecutor,
    action_request_hash,
    build_sandbox_registry,
    operation_kind,
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _prepare_action(store, registry, *, tool, arguments):
    run = store.create_run(
        goal_id=f"goal_{uuid4()}",
        planner="test",
        planner_version="1",
    )
    store.transition_run(run["id"], "running", reason="test run")
    step = store.create_step(run_id=run["id"])
    store.transition_step(step["id"], "planned", reason="proposal ready")
    proposal = ActionProposal.create(
        rank=1,
        tool=tool,
        tool_version="1",
        arguments=arguments,
        expected_observation="test observation",
        rationale_summary="test proposal",
    )
    operation_id = f"aop_{uuid4()}"
    action = Action.from_proposal(
        proposal,
        registry=registry,
        run_id=run["id"],
        step_id=step["id"],
        operation_id=operation_id,
        created_at=_now(),
    )
    store.transition_step(step["id"], "selected", reason="proposal selected")
    descriptor = registry.get(tool, "1")
    store.create_operation(
        run_id=run["id"],
        step_id=step["id"],
        action_id=action.public_id,
        operation_kind=operation_kind(action),
        request_hash=action_request_hash(action),
        idempotency_class=descriptor.idempotency,
        public_id=operation_id,
    )
    store.transition_step(step["id"], "executing", reason="executor entered")
    return action


def test_large_read_result_does_not_deadlock_worker_pipe(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    content = "x" * min(250_000, MAX_FILE_BYTES)
    (root / "large.txt").write_text(content, encoding="utf-8")
    store = AgentStore(tmp_path / "agent.db")
    registry = build_sandbox_registry()
    executor = SandboxExecutor(root=root, registry=registry, store=store)
    action = _prepare_action(
        store,
        registry,
        tool="fs.read",
        arguments={"path": "large.txt"},
    )

    receipt = executor.execute(action)

    assert receipt.status == "succeeded"
    assert receipt.to_dict()["output"]["content"] == content
    assert store.get_operation(action.operation_id)["status"] == "succeeded"


def test_completed_repeat_safe_read_can_be_replayed_without_new_side_effect(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    target = root / "value.txt"
    target.write_text("one", encoding="utf-8")
    store = AgentStore(tmp_path / "agent.db")
    registry = build_sandbox_registry()
    executor = SandboxExecutor(root=root, registry=registry, store=store)
    action = _prepare_action(
        store,
        registry,
        tool="fs.read",
        arguments={"path": "value.txt"},
    )

    first = executor.execute(action)
    assert first.to_dict()["output"]["content"] == "one"
    target.write_text("two", encoding="utf-8")
    replay = executor.execute(action)

    assert replay.status == "succeeded"
    assert replay.to_dict()["output"]["content"] == "two"
    assert store.get_operation(action.operation_id)["status"] == "succeeded"
