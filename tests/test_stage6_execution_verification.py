from datetime import datetime, timezone
from uuid import uuid4

import pytest

from anima.agent.executor import build_sandbox_registry
from anima.cognition.action_choice import ActionChoiceCoordinator
from anima.execution.contracts import ActionSpec, ExecutionAction, VerificationSpec
from anima.execution.coordinator import ExecutionCoordinator
from anima.execution.sandbox import ExecutionRejectedError, SandboxExecutor
from anima.execution.store import ExecutionStore, action_request_hash
from anima.execution.verification import (
    DeterministicGoalVerifier,
    FILE_CONTENT_EQUALS,
    FileObserver,
    GoalVerificationBridge,
)
from anima.internal_state.choice_engine import Candidate
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore
from anima.ir import CanonicalTask
from anima.resolution import resolve
from anima.tasks.store import TaskStore


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _environment(tmp_path):
    state = InternalStateStore(tmp_path / "internal_state.db")
    runtime = InternalStateRuntime(state)
    goal = runtime.goals.create_goal(
        source="test",
        priority=1.0,
        description="produce verified result",
        success_criterion="result.txt contains 42",
        reason="Stage 6.4 test",
        timestamp=_now(),
    )
    tasks = TaskStore(tmp_path / "tasks.db")
    task = tasks.create_task(
        source="test",
        description="write result",
        reason="Stage 6.4 test",
        goal_id=goal["id"],
        timestamp=_now(),
    )
    task = tasks.transition_task(
        task.public_id,
        "active",
        reason="activate execution task",
        timestamp=_now(),
    )

    canonical = CanonicalTask(
        task_id=f"ct_{uuid4()}",
        source_id=f"src_{uuid4()}",
        operation="CHOOSE_ACTION",
        candidates=("WRITE_RESULT", "READ_INPUT"),
        output_contract="candidate",
    )
    resolution = resolve(canonical)
    choice = ActionChoiceCoordinator(
        task_store=tasks,
        choice_engine=runtime.choice_engine,
    ).choose(
        task.public_id,
        canonical,
        resolution,
        [
            Candidate("WRITE_RESULT", 0.70),
            Candidate("READ_INPUT", 0.60, information_gain=1.0),
        ],
    )
    assert choice.selected_candidate_id == "WRITE_RESULT"

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "input.txt").write_text("input", encoding="utf-8")
    registry = build_sandbox_registry()
    execution_store = ExecutionStore(tmp_path / "execution.db")
    executor = SandboxExecutor(
        root=sandbox,
        registry=registry,
        store=execution_store,
    )
    coordinator = ExecutionCoordinator(
        task_store=tasks,
        execution_store=execution_store,
        registry=registry,
        executor=executor,
    )
    specs = (
        ActionSpec(
            "WRITE_RESULT",
            "fs.write",
            "1",
            {"path": "result.txt", "content": "42"},
        ),
        ActionSpec(
            "READ_INPUT",
            "fs.read",
            "1",
            {"path": "input.txt"},
        ),
    )
    verification = VerificationSpec.create(
        goal_id=goal["id"],
        criterion_kind=FILE_CONTENT_EQUALS,
        parameters={"path": "result.txt", "expected": "42"},
    )
    return {
        "runtime": runtime,
        "goal": goal,
        "tasks": tasks,
        "task": task,
        "choice": choice,
        "sandbox": sandbox,
        "registry": registry,
        "execution_store": execution_store,
        "executor": executor,
        "coordinator": coordinator,
        "specs": specs,
        "verification": verification,
    }


def test_execution_uses_task_goal_operation_not_agent_run_or_step(tmp_path):
    env = _environment(tmp_path)
    action = env["coordinator"].prepare(
        env["choice"],
        env["specs"],
        created_at=_now(),
    )
    operation = env["execution_store"].get_operation(action.operation_id)

    assert action.persistent_task_id == env["task"].public_id
    assert action.goal_id == env["goal"]["id"]
    assert action.candidate_id == "WRITE_RESULT"
    assert operation["task_id"] == env["task"].public_id
    assert operation["goal_id"] == env["goal"]["id"]
    assert operation["candidate_id"] == "WRITE_RESULT"
    assert "run_id" not in operation
    assert "step_id" not in operation
    assert "planner" not in operation


def test_action_specs_must_match_choice_candidate_set_exactly(tmp_path):
    env = _environment(tmp_path)
    with pytest.raises(ValueError, match="exactly match Choice evaluations"):
        env["coordinator"].prepare(
            env["choice"],
            (env["specs"][0],),
            created_at=_now(),
        )


def test_successful_receipt_does_not_complete_goal_without_verification(tmp_path):
    env = _environment(tmp_path)
    turn = env["coordinator"].prepare_and_execute(
        env["choice"],
        env["specs"],
        created_at=_now(),
    )

    assert turn.receipt.status == "succeeded"
    assert (env["sandbox"] / "result.txt").read_text(encoding="utf-8") == "42"
    assert env["runtime"].goals.get_goal(env["goal"]["id"])["status"] == "active"
    assert env["tasks"].get_task(env["task"].public_id).status == "active"


def test_environment_change_after_success_causes_verification_failure(tmp_path):
    env = _environment(tmp_path)
    turn = env["coordinator"].prepare_and_execute(
        env["choice"],
        env["specs"],
        created_at=_now(),
    )
    assert turn.receipt.status == "succeeded"

    (env["sandbox"] / "result.txt").write_text("99", encoding="utf-8")
    observation = FileObserver(env["sandbox"]).observe(
        turn.action,
        turn.receipt,
        path="result.txt",
    )
    result = DeterministicGoalVerifier().verify(
        env["verification"],
        candidate_id=turn.action.candidate_id,
        observations=(observation,),
    )

    assert observation.kind == "file.content"
    assert result.outcome == "failure"
    assert result.criterion_satisfied is False
    application = GoalVerificationBridge(env["runtime"]).apply(result)
    assert application.applied is True
    assert env["runtime"].goals.get_goal(env["goal"]["id"])["status"] == "active"


def test_independent_observation_can_confirm_goal_success(tmp_path):
    env = _environment(tmp_path)
    turn = env["coordinator"].prepare_and_execute(
        env["choice"],
        env["specs"],
        created_at=_now(),
    )
    observation = FileObserver(env["sandbox"]).observe(
        turn.action,
        turn.receipt,
        path="result.txt",
    )
    result = DeterministicGoalVerifier().verify(
        env["verification"],
        candidate_id=turn.action.candidate_id,
        observations=(observation,),
    )

    assert result.outcome == "success"
    assert result.criterion_satisfied is True
    application = GoalVerificationBridge(env["runtime"]).apply(result)
    assert application.applied is True
    assert application.progress_result.goal["status"] == "completed"
    assert env["runtime"].goals.get_goal(env["goal"]["id"])["status"] == "completed"
    # Verification owns Goal success; execution itself still does not mutate Task.
    assert env["tasks"].get_task(env["task"].public_id).status == "active"


def test_keyed_success_replay_does_not_repeat_write_side_effect(tmp_path):
    env = _environment(tmp_path)
    action = env["coordinator"].prepare(
        env["choice"],
        env["specs"],
        created_at=_now(),
    )
    first = env["coordinator"].execute(action)
    assert first.receipt.status == "succeeded"

    target = env["sandbox"] / "result.txt"
    target.write_text("external-change", encoding="utf-8")
    replay = env["coordinator"].execute(action)

    assert replay.receipt.status == "succeeded"
    assert target.read_text(encoding="utf-8") == "external-change"
    assert env["execution_store"].get_operation(action.operation_id)["status"] == "succeeded"


def test_uncertain_keyed_write_reconciles_existing_effect_without_rewrite(tmp_path):
    env = _environment(tmp_path)
    action = env["coordinator"].prepare(
        env["choice"],
        env["specs"],
        created_at=_now(),
    )
    env["execution_store"].transition_operation(
        action.operation_id,
        "executing",
        reason="simulated crash point",
    )
    env["execution_store"].transition_operation(
        action.operation_id,
        "uncertain",
        reason="simulated crash ambiguity",
    )
    target = env["sandbox"] / "result.txt"
    target.write_text("42", encoding="utf-8")
    before = target.stat().st_mtime_ns

    turn = env["coordinator"].execute(action)

    assert turn.receipt.status == "succeeded"
    assert target.stat().st_mtime_ns == before
    assert env["execution_store"].get_operation(action.operation_id)["status"] == "succeeded"


def test_operation_binding_rejects_same_id_with_different_action_intent(tmp_path):
    env = _environment(tmp_path)
    action = env["coordinator"].prepare(
        env["choice"],
        env["specs"],
        created_at=_now(),
    )
    tampered = ExecutionAction.from_spec(
        ActionSpec(
            "WRITE_RESULT",
            "fs.write",
            "1",
            {"path": "result.txt", "content": "evil"},
        ),
        registry=env["registry"],
        persistent_task_id=action.persistent_task_id,
        goal_id=action.goal_id,
        created_at=_now(),
        operation_id=action.operation_id,
    )

    assert action_request_hash(tampered) != action_request_hash(action)
    with pytest.raises(ExecutionRejectedError, match="does not match"):
        env["executor"].execute(tampered)


def test_execution_store_reopens_with_operation_state(tmp_path):
    env = _environment(tmp_path)
    action = env["coordinator"].prepare(
        env["choice"],
        env["specs"],
        created_at=_now(),
    )
    env["coordinator"].execute(action)

    reopened = ExecutionStore(tmp_path / "execution.db")
    operation = reopened.get_operation(action.operation_id)
    assert reopened.schema_version() == 1
    assert operation["status"] == "succeeded"
    assert operation["request_hash"] == action_request_hash(action)
