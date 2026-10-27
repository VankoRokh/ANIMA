import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from anima.agent import Action, ActionProposal, AgentStore, ToolDescriptor, ToolRegistry
from anima.agent.executor import (
    MAX_FILE_BYTES,
    MAX_LIST_ENTRIES,
    ExecutionRejectedError,
    SandboxExecutor,
    SandboxHandler,
    UncertainOperationError,
    action_request_hash,
    build_sandbox_registry,
    operation_kind,
    sandbox_tool_descriptors,
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _slow_handler(root, arguments, operation_id):
    del root, operation_id
    time.sleep(arguments["seconds"])
    return {"ok": True}


def _invalid_output_handler(root, arguments, operation_id):
    del root, arguments, operation_id
    return {"wrong": True}


def _noop_write_handler(root, arguments, operation_id):
    del root, arguments, operation_id
    return {"ok": True}


def _custom_descriptor(
    name,
    *,
    effect_class="read_only",
    idempotency="repeat_safe",
    timeout_seconds=0.05,
):
    return ToolDescriptor(
        name=name,
        version="1",
        description=f"Test tool {name}",
        input_schema={
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "minimum": 0},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        effect_class=effect_class,
        idempotency=idempotency,
        timeout_seconds=timeout_seconds,
        sandbox_scope=("test",),
    )


@pytest.fixture
def agent_env(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    store = AgentStore(tmp_path / "agent.db")
    registry = build_sandbox_registry()
    executor = SandboxExecutor(root=root, registry=registry, store=store)
    return root, store, registry, executor


def _make_action(
    store,
    registry,
    *,
    tool,
    arguments,
    tool_version="1",
    create_operation=True,
    request_hash=None,
    idempotency_class=None,
    operation_action_id=None,
):
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
        tool_version=tool_version,
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

    if create_operation:
        descriptor = registry.get(tool, tool_version)
        store.create_operation(
            run_id=run["id"],
            step_id=step["id"],
            action_id=operation_action_id or action.public_id,
            operation_kind=operation_kind(action),
            request_hash=request_hash or action_request_hash(action),
            idempotency_class=idempotency_class or descriptor.idempotency,
            public_id=operation_id,
        )
        store.transition_step(step["id"], "executing", reason="executor entered")
    return action


def _set_uncertain(store, action):
    store.transition_operation(action.operation_id, "executing", reason="started")
    store.transition_operation(action.operation_id, "uncertain", reason="simulated crash")


def test_standard_sandbox_descriptors_are_system_owned_and_bounded():
    descriptors = {descriptor.name: descriptor for descriptor in sandbox_tool_descriptors()}
    assert set(descriptors) == {"fs.list", "fs.read", "fs.write"}
    assert descriptors["fs.list"].effect_class == "read_only"
    assert descriptors["fs.read"].idempotency == "repeat_safe"
    assert descriptors["fs.write"].effect_class == "reversible_write"
    assert descriptors["fs.write"].idempotency == "keyed"
    assert all(descriptor.sandbox_scope == ("filesystem",) for descriptor in descriptors.values())


def test_list_and_read_succeed_inside_sandbox(agent_env):
    root, store, registry, executor = agent_env
    (root / "b.txt").write_text("beta", encoding="utf-8")
    (root / "a.txt").write_text("alpha", encoding="utf-8")

    list_action = _make_action(store, registry, tool="fs.list", arguments={"path": "."})
    list_receipt = executor.execute(list_action)
    assert list_receipt.status == "succeeded"
    assert [entry["name"] for entry in list_receipt.to_dict()["output"]["entries"]] == ["a.txt", "b.txt"]
    assert store.get_operation(list_action.operation_id)["status"] == "succeeded"

    read_action = _make_action(store, registry, tool="fs.read", arguments={"path": "a.txt"})
    read_receipt = executor.execute(read_action)
    output = read_receipt.to_dict()["output"]
    assert read_receipt.status == "succeeded"
    assert output["content"] == "alpha"
    assert output["bytes"] == 5
    assert len(output["sha256"]) == 64


def test_missing_file_is_normal_tool_failure_not_executor_exception(agent_env):
    _, store, registry, executor = agent_env
    action = _make_action(store, registry, tool="fs.read", arguments={"path": "missing.txt"})

    receipt = executor.execute(action)

    assert receipt.status == "failed"
    assert receipt.error_code == "NOT_FOUND"
    assert store.get_operation(action.operation_id)["status"] == "failed"


@pytest.mark.parametrize("path", ["../outside.txt", "/tmp/outside.txt"])
def test_path_escape_is_rejected_inside_execution_boundary(agent_env, path):
    _, store, registry, executor = agent_env
    action = _make_action(store, registry, tool="fs.read", arguments={"path": path})

    receipt = executor.execute(action)

    assert receipt.status == "failed"
    assert receipt.error_code == "SANDBOX_ESCAPE"
    assert store.get_operation(action.operation_id)["status"] == "failed"


def test_read_symlink_cannot_escape_sandbox(agent_env, tmp_path):
    root, store, registry, executor = agent_env
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    action = _make_action(store, registry, tool="fs.read", arguments={"path": "link.txt"})

    receipt = executor.execute(action)

    assert receipt.status == "failed"
    assert receipt.error_code == "SANDBOX_ESCAPE"


def test_write_refuses_symlink_even_when_target_is_inside(agent_env):
    root, store, registry, executor = agent_env
    target = root / "target.txt"
    target.write_text("old", encoding="utf-8")
    (root / "link.txt").symlink_to(target)
    action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "link.txt", "content": "new"},
    )

    receipt = executor.execute(action)

    assert receipt.status == "failed"
    assert receipt.error_code == "SYMLINK_WRITE_FORBIDDEN"
    assert target.read_text(encoding="utf-8") == "old"


def test_write_is_atomic_bounded_and_leaves_no_temp_file(agent_env):
    root, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "result.txt", "content": "42"},
    )

    receipt = executor.execute(action)

    assert receipt.status == "succeeded"
    assert (root / "result.txt").read_text(encoding="utf-8") == "42"
    assert receipt.to_dict()["output"]["bytes_written"] == 2
    assert not list(root.glob(".anima-aop_*.tmp"))
    assert store.get_operation(action.operation_id)["status"] == "succeeded"


def test_write_does_not_create_missing_parent(agent_env):
    root, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "missing/result.txt", "content": "42"},
    )

    receipt = executor.execute(action)

    assert receipt.status == "failed"
    assert receipt.error_code == "PARENT_NOT_FOUND"
    assert not (root / "missing").exists()


def test_confirmed_keyed_write_is_not_executed_again(agent_env):
    root, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "result.txt", "content": "42"},
    )
    first = executor.execute(action)
    assert first.status == "succeeded"

    (root / "result.txt").write_text("external change", encoding="utf-8")
    replay = executor.execute(action)

    assert replay.status == "succeeded"
    assert (root / "result.txt").read_text(encoding="utf-8") == "external change"
    assert store.get_operation(action.operation_id)["status"] == "succeeded"


def test_uncertain_write_reconciles_existing_effect_without_rewrite(agent_env):
    root, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "result.txt", "content": "42"},
    )
    (root / "result.txt").write_text("42", encoding="utf-8")
    before = (root / "result.txt").stat().st_mtime_ns
    _set_uncertain(store, action)

    receipt = executor.execute(action)

    after = (root / "result.txt").stat().st_mtime_ns
    assert receipt.status == "succeeded"
    assert before == after
    assert store.get_operation(action.operation_id)["status"] == "succeeded"


def test_uncertain_write_retries_when_effect_is_not_present(agent_env):
    root, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "result.txt", "content": "wanted"},
    )
    (root / "result.txt").write_text("other", encoding="utf-8")
    _set_uncertain(store, action)

    receipt = executor.execute(action)

    assert receipt.status == "succeeded"
    assert (root / "result.txt").read_text(encoding="utf-8") == "wanted"
    assert store.get_operation(action.operation_id)["status"] == "succeeded"


def test_executing_operation_is_treated_as_crash_ambiguity_then_recovered(agent_env):
    root, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "result.txt", "content": "recovered"},
    )
    store.transition_operation(action.operation_id, "executing", reason="crash point")

    receipt = executor.execute(action)

    assert receipt.status == "succeeded"
    assert (root / "result.txt").read_text(encoding="utf-8") == "recovered"
    assert store.get_operation(action.operation_id)["status"] == "succeeded"


def test_action_without_persisted_operation_is_rejected(agent_env):
    _, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.read",
        arguments={"path": "x.txt"},
        create_operation=False,
    )

    with pytest.raises(ExecutionRejectedError, match="persisted AgentOperation"):
        executor.execute(action)


def test_operation_request_hash_must_match_action(agent_env):
    _, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.read",
        arguments={"path": "x.txt"},
        request_hash="0" * 64,
    )

    with pytest.raises(ExecutionRejectedError, match="request_hash"):
        executor.execute(action)
    assert store.get_operation(action.operation_id)["status"] == "prepared"


def test_operation_idempotency_metadata_must_match_descriptor(agent_env):
    _, store, registry, executor = agent_env
    action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "x.txt", "content": "x"},
        idempotency_class="none",
    )

    with pytest.raises(ExecutionRejectedError, match="idempotency_class"):
        executor.execute(action)
    assert store.get_operation(action.operation_id)["status"] == "prepared"


def test_terminal_failed_operation_cannot_be_replayed(agent_env):
    _, store, registry, executor = agent_env
    action = _make_action(store, registry, tool="fs.read", arguments={"path": "x.txt"})
    store.transition_operation(action.operation_id, "executing", reason="start")
    store.transition_operation(action.operation_id, "failed", reason="failed")

    with pytest.raises(ExecutionRejectedError, match="Terminal AgentOperation"):
        executor.execute(action)


def test_unhandled_registered_tool_is_rejected_before_effect(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    store = AgentStore(tmp_path / "agent.db")
    descriptor = _custom_descriptor("test.noop")
    registry = ToolRegistry([descriptor])
    executor = SandboxExecutor(root=root, registry=registry, store=store)
    action = _make_action(store, registry, tool="test.noop", arguments={})

    with pytest.raises(ExecutionRejectedError, match="No trusted Executor handler"):
        executor.execute(action)
    assert store.get_operation(action.operation_id)["status"] == "prepared"


def test_non_idempotent_uncertain_operation_is_never_auto_retried(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    store = AgentStore(tmp_path / "agent.db")
    descriptor = _custom_descriptor(
        "test.non_idempotent",
        effect_class="reversible_write",
        idempotency="none",
    )
    registry = ToolRegistry([descriptor])
    executor = SandboxExecutor(
        root=root,
        registry=registry,
        store=store,
        handlers={
            ("test.non_idempotent", "1"): SandboxHandler(_noop_write_handler),
        },
    )
    action = _make_action(store, registry, tool="test.non_idempotent", arguments={})
    _set_uncertain(store, action)

    with pytest.raises(UncertainOperationError, match="external reconciliation"):
        executor.execute(action)
    assert store.get_operation(action.operation_id)["status"] == "uncertain"


def test_hard_timeout_fails_read_only_operation(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    store = AgentStore(tmp_path / "agent.db")
    descriptor = _custom_descriptor("test.slow", timeout_seconds=0.02)
    registry = ToolRegistry([descriptor])
    executor = SandboxExecutor(
        root=root,
        registry=registry,
        store=store,
        handlers={("test.slow", "1"): SandboxHandler(_slow_handler)},
    )
    action = _make_action(
        store,
        registry,
        tool="test.slow",
        arguments={"seconds": 0.25},
    )

    receipt = executor.execute(action)

    assert receipt.status == "timeout"
    assert receipt.error_code == "TIMEOUT"
    assert store.get_operation(action.operation_id)["status"] == "failed"


def test_hard_timeout_leaves_write_operation_uncertain(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    store = AgentStore(tmp_path / "agent.db")
    descriptor = _custom_descriptor(
        "test.slow_write",
        effect_class="reversible_write",
        idempotency="keyed",
        timeout_seconds=0.02,
    )
    registry = ToolRegistry([descriptor])
    executor = SandboxExecutor(
        root=root,
        registry=registry,
        store=store,
        handlers={("test.slow_write", "1"): SandboxHandler(_slow_handler)},
    )
    action = _make_action(
        store,
        registry,
        tool="test.slow_write",
        arguments={"seconds": 0.25},
    )

    receipt = executor.execute(action)

    assert receipt.status == "timeout"
    assert store.get_operation(action.operation_id)["status"] == "uncertain"


def test_invalid_trusted_handler_output_is_a_contract_failure(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    store = AgentStore(tmp_path / "agent.db")
    descriptor = _custom_descriptor("test.bad_output")
    registry = ToolRegistry([descriptor])
    executor = SandboxExecutor(
        root=root,
        registry=registry,
        store=store,
        handlers={("test.bad_output", "1"): SandboxHandler(_invalid_output_handler)},
    )
    action = _make_action(store, registry, tool="test.bad_output", arguments={})

    receipt = executor.execute(action)

    assert receipt.status == "failed"
    assert receipt.error_code == "INVALID_TOOL_OUTPUT"
    assert store.get_operation(action.operation_id)["status"] == "failed"


def test_read_rejects_oversized_file(agent_env):
    root, store, registry, executor = agent_env
    (root / "large.txt").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    action = _make_action(store, registry, tool="fs.read", arguments={"path": "large.txt"})

    receipt = executor.execute(action)

    assert receipt.status == "failed"
    assert receipt.error_code == "FILE_TOO_LARGE"


def test_list_is_bounded_and_reports_truncation(agent_env):
    root, store, registry, executor = agent_env
    for index in range(MAX_LIST_ENTRIES + 1):
        (root / f"f{index:04d}.txt").write_text("x", encoding="utf-8")
    action = _make_action(store, registry, tool="fs.list", arguments={"path": "."})

    receipt = executor.execute(action)
    output = receipt.to_dict()["output"]

    assert receipt.status == "succeeded"
    assert len(output["entries"]) == MAX_LIST_ENTRIES
    assert output["truncated"] is True


def test_utf8_write_then_new_read_operation_round_trips(agent_env):
    root, store, registry, executor = agent_env
    write_action = _make_action(
        store,
        registry,
        tool="fs.write",
        arguments={"path": "unicode.txt", "content": "Привет, ANIMA"},
    )
    assert executor.execute(write_action).status == "succeeded"

    read_action = _make_action(
        store,
        registry,
        tool="fs.read",
        arguments={"path": "unicode.txt"},
    )
    receipt = executor.execute(read_action)

    assert receipt.status == "succeeded"
    assert receipt.to_dict()["output"]["content"] == "Привет, ANIMA"
    assert (root / "unicode.txt").read_text(encoding="utf-8") == "Привет, ANIMA"
