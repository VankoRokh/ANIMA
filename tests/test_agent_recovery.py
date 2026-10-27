from pathlib import Path

import pytest

from anima.agent import (
    AgentRecoveryJournal,
    AgentStore,
    DeterministicGoalVerifier,
    DeterministicPlanner,
    GoalVerificationBridge,
    PlannerDecision,
    ProposalChoiceCoordinator,
    ProposalDraft,
    RecoverableAgentLoop,
    SandboxExecutor,
    VerificationSpec,
    build_sandbox_registry,
)
from anima.agent.verification import (
    DETERMINISTIC_VERIFIER_NAME,
    DETERMINISTIC_VERIFIER_VERSION,
    FILE_CONTENT_EQUALS,
)
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore


def _proposal(tool, arguments, rationale):
    return ProposalDraft(
        tool=tool,
        tool_version="1",
        arguments=arguments,
        expected_observation="factual sandbox observation",
        rationale_summary=rationale,
    )


def _strategy(request):
    if not request.recent_observations:
        return PlannerDecision(
            status="proposals_available",
            proposals=(
                _proposal(
                    "fs.write",
                    {"path": "result.txt", "content": "42"},
                    "write the requested result",
                ),
            ),
        )
    latest = request.recent_observations[-1]
    if latest["kind"] == "file.write":
        return PlannerDecision(
            status="proposals_available",
            proposals=(
                _proposal(
                    "fs.read",
                    {"path": "result.txt"},
                    "read back the result for independent verification",
                ),
            ),
        )
    return PlannerDecision(status="cannot_progress")


class CrashAt:
    def __init__(self, name, occurrence=1):
        self.name = name
        self.occurrence = occurrence
        self.seen = 0

    def __call__(self, name, context):
        del context
        if name != self.name:
            return
        self.seen += 1
        if self.seen == self.occurrence:
            raise RuntimeError(f"simulated crash at {name}")


def _open_runtime(data_dir, *, fault_hook=None):
    data_dir = Path(data_dir)
    sandbox = data_dir / "sandbox"
    sandbox.mkdir(exist_ok=True)
    agent_store = AgentStore(data_dir / "agent.db")
    internal_store = InternalStateStore(data_dir / "internal_state.db")
    internal = InternalStateRuntime(internal_store)
    registry = build_sandbox_registry()
    planner = DeterministicPlanner(_strategy)
    choice = ProposalChoiceCoordinator(
        registry=registry,
        choice_engine=internal.choice_engine,
    )
    executor = SandboxExecutor(
        root=sandbox,
        registry=registry,
        store=agent_store,
    )
    verifier = DeterministicGoalVerifier()
    bridge = GoalVerificationBridge(
        agent_store=agent_store,
        recovery=internal.recovery,
    )
    loop = RecoverableAgentLoop(
        store=agent_store,
        registry=registry,
        planner=planner,
        choice=choice,
        executor=executor,
        verifier=verifier,
        verification_bridge=bridge,
        fault_hook=fault_hook,
    )
    return sandbox, agent_store, internal, bridge, loop


def _new_run(tmp_path, *, fault_hook=None):
    sandbox, store, internal, bridge, loop = _open_runtime(
        tmp_path,
        fault_hook=fault_hook,
    )
    goal = internal.create_goal(
        source="test",
        priority=1.0,
        description="write 42 to result.txt and verify it",
        success_criterion="result.txt content equals 42",
        reason="Stage 4.11 recovery test goal",
    )
    run = loop.start_run(goal["id"])
    spec = VerificationSpec.create(
        run_id=run["id"],
        verifier=DETERMINISTIC_VERIFIER_NAME,
        verifier_version=DETERMINISTIC_VERIFIER_VERSION,
        criterion_kind=FILE_CONTENT_EQUALS,
        parameters={"path": "result.txt", "expected": "42"},
    )
    return sandbox, store, internal, bridge, loop, goal, run, spec


@pytest.mark.parametrize(
    ("checkpoint", "occurrence"),
    [
        ("after_planner_persisted", 1),
        ("after_action_persisted", 1),
        ("after_tool_execution", 1),
        ("after_receipt_persisted", 1),
        ("after_observation_persisted", 1),
        ("after_verification_persisted", 1),
        ("after_goal_applied", 2),
        ("after_step_completed", 2),
    ],
)
def test_resume_crosses_persisted_crash_boundaries_without_duplicate_effect(
    tmp_path,
    checkpoint,
    occurrence,
):
    crash = CrashAt(checkpoint, occurrence)
    sandbox, store, _, _, loop, _, run, spec = _new_run(
        tmp_path,
        fault_hook=crash,
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        loop.run(run["id"], spec, max_steps=4)

    target = sandbox / "result.txt"
    inode_after_crash = target.stat().st_ino if target.exists() else None

    sandbox2, reopened_store, _, _, reopened_loop = _open_runtime(tmp_path)
    result = reopened_loop.resume(run["id"], max_steps=4)

    assert result.completed is True
    assert result.stop_reason == "goal_completed"
    assert result.goal["status"] == "completed"
    assert result.run["status"] == "completed"
    assert (sandbox2 / "result.txt").read_text(encoding="utf-8") == "42"

    write_operations = [
        item
        for item in reopened_store.list_operations(run_id=run["id"])
        if item["operation_kind"] == "tool:fs.write@1"
    ]
    assert len(write_operations) == 1
    assert write_operations[0]["status"] == "succeeded"

    if checkpoint in {
        "after_tool_execution",
        "after_receipt_persisted",
        "after_observation_persisted",
        "after_verification_persisted",
    } and occurrence == 1:
        assert inode_after_crash is not None
        assert (sandbox2 / "result.txt").stat().st_ino == inode_after_crash


def test_recovery_replays_same_verification_source_after_cross_store_crash(
    tmp_path,
    monkeypatch,
):
    sandbox, store, internal, bridge, loop, goal, run, spec = _new_run(tmp_path)
    original_apply = bridge.apply
    crashed = False

    def apply_then_crash(*, spec, result, observations):
        nonlocal crashed
        applied = original_apply(
            spec=spec,
            result=result,
            observations=observations,
        )
        if result.outcome == "success" and not crashed:
            crashed = True
            raise RuntimeError("simulated cross-store crash after Stage 2 apply")
        return applied

    monkeypatch.setattr(bridge, "apply", apply_then_crash)

    with pytest.raises(RuntimeError, match="cross-store crash"):
        loop.run(run["id"], spec, max_steps=4)

    assert (sandbox / "result.txt").read_text(encoding="utf-8") == "42"
    assert internal.goal_store.get_goal(goal["id"])["status"] == "completed"

    journal = AgentRecoveryJournal(store)
    recovery_rows = journal.list_steps(run["id"])
    success_artifact = next(
        item
        for item in recovery_rows
        if item.verification_result is not None
        and item.verification_result.outcome == "success"
    )
    assert success_artifact.goal_applied is False
    verification_id = success_artifact.verification_result.public_id

    _, _, reopened_internal, _, reopened_loop = _open_runtime(tmp_path)
    result = reopened_loop.resume(run["id"], max_steps=4)

    assert result.completed is True
    transitions = reopened_internal.goal_store.list_goal_transitions(
        goal_id=goal["id"]
    )
    completed = [
        item
        for item in transitions
        if item["to_status"] == "completed"
        and item["source_id"] == verification_id
    ]
    assert len(completed) == 1
    assert reopened_internal.recovery.ledger.get(verification_id)["status"] == "done"

    state_transitions = [
        item
        for item in reopened_internal.store.list_state_transitions()
        if item["source_id"] == verification_id
    ]
    assert state_transitions
    assert len({item["rule_id"] for item in state_transitions}) == len(
        state_transitions
    )


def test_recovery_journal_is_persistent_and_artifacts_are_immutable(tmp_path):
    crash = CrashAt("after_receipt_persisted")
    _, store, _, _, loop, _, run, spec = _new_run(tmp_path, fault_hook=crash)

    with pytest.raises(RuntimeError):
        loop.run(run["id"], spec, max_steps=4)

    first = AgentRecoveryJournal(store)
    persisted_spec = first.get_verification_spec(run["id"])
    assert persisted_spec.to_dict() == spec.to_dict()

    selected = next(
        item
        for item in first.list_steps(run["id"])
        if item.action is not None
    )
    assert selected.receipt is not None

    reopened_store = AgentStore(Path(tmp_path) / "agent.db")
    reopened = AgentRecoveryJournal(reopened_store)
    restored = reopened.load_step(selected.step_id)
    assert restored.action.to_dict() == selected.action.to_dict()
    assert restored.receipt.to_dict() == selected.receipt.to_dict()

    changed = selected.action.to_dict()
    changed["arguments"] = {"path": "other.txt", "content": "different"}
    from anima.agent.contracts import Action

    with pytest.raises(ValueError, match="cannot be replaced"):
        reopened.save_action(selected.step_id, Action.from_dict(changed))
