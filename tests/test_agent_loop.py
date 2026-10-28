from dataclasses import replace
from pathlib import Path

import pytest

from anima.agent import (
    AgentLoop,
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


def _build(tmp_path, strategy, *, context_provider=None, path="result.txt", expected="42", loop_type=AgentLoop):
    data_dir = Path(tmp_path)
    sandbox = data_dir / "sandbox"
    sandbox.mkdir()

    agent_store = AgentStore(data_dir / "agent.db")
    internal_store = InternalStateStore(data_dir / "internal_state.db")
    internal = InternalStateRuntime(internal_store)
    registry = build_sandbox_registry()
    planner = DeterministicPlanner(strategy)
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
    loop = loop_type(
        store=agent_store,
        registry=registry,
        planner=planner,
        choice=choice,
        executor=executor,
        verifier=verifier,
        verification_bridge=bridge,
        context_provider=context_provider,
    )
    goal = internal.create_goal(
        source="test",
        priority=1.0,
        description=f"write {expected!r} to {path} and verify it",
        success_criterion=f"{path} content equals {expected!r}",
        reason="Stage 4.8 test goal",
    )
    run = loop.start_run(goal["id"])
    spec = VerificationSpec.create(
        run_id=run["id"],
        verifier=DETERMINISTIC_VERIFIER_NAME,
        verifier_version=DETERMINISTIC_VERIFIER_VERSION,
        criterion_kind=FILE_CONTENT_EQUALS,
        parameters={"path": path, "expected": expected},
    )
    return sandbox, agent_store, internal, loop, goal, run, spec


@pytest.mark.parametrize("path, expected", [("result.txt", "42"), ("answer.txt", "hello")])
@pytest.mark.parametrize("missing_target", [False, True])
def test_canonical_multistep_loop_replans_after_failure_and_verifies_readback(tmp_path, path, expected, missing_target):
    def strategy(request):
        if not request.recent_observations:
            return PlannerDecision(
                status="proposals_available",
                proposals=(
                    _proposal(
                        "fs.read",
                        {"path": path if missing_target else "missing-input.txt"},
                        "try the initially assumed input path",
                    ),
                ),
            )
        latest = request.recent_observations[-1]
        if missing_target and latest["kind"] == "file.unavailable":
            assert latest["data"]["path"] == path
            assert latest["data"]["error_code"] == "NOT_FOUND"
        if latest["kind"] == "file.unavailable":
            return PlannerDecision(
                status="proposals_available",
                proposals=(
                    _proposal(
                        "fs.write",
                        {"path": path, "content": expected},
                        "write the required result after the failed assumption",
                    ),
                ),
            )
        if latest["kind"] == "file.write":
            return PlannerDecision(
                status="proposals_available",
                proposals=(
                    _proposal(
                        "fs.read",
                        {"path": path},
                        "read back the result for independent verification",
                    ),
                ),
            )
        return PlannerDecision(status="cannot_progress")

    sandbox, store, _, loop, goal, run, spec = _build(tmp_path, strategy, path=path, expected=expected)

    result = loop.run(run["id"], spec, max_steps=5)

    assert result.completed is True
    assert result.stop_reason == "goal_completed"
    assert result.goal["id"] == goal["id"]
    assert result.goal["status"] == "completed"
    assert result.run["status"] == "completed"
    assert (sandbox / path).read_text(encoding="utf-8") == expected

    assert len(result.turns) == 3
    assert [turn.action.tool for turn in result.turns] == [
        "fs.read",
        "fs.write",
        "fs.read",
    ]
    assert [turn.receipt.status for turn in result.turns] == [
        "failed",
        "succeeded",
        "succeeded",
    ]
    assert [turn.observation.kind for turn in result.turns] == [
        "file.unavailable",
        "file.write",
        "file.content",
    ]
    assert [turn.verification_result.outcome for turn in result.turns] == [
        "failure" if missing_target else "none",
        "failure" if missing_target else "none",
        "success",
    ]

    steps = store.list_steps(run_id=run["id"])
    operations = store.list_operations(run_id=run["id"])
    assert len(steps) == len(operations) == 3
    assert all(step["status"] == "completed" for step in steps)
    assert all(operation["status"] in {"succeeded", "failed"} for operation in operations)


def test_successful_write_receipt_does_not_complete_goal_without_readback(tmp_path):
    def strategy(_request):
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

    sandbox, _, _, loop, _, run, spec = _build(tmp_path, strategy)

    result = loop.run(run["id"], spec, max_steps=1)

    assert (sandbox / "result.txt").read_text(encoding="utf-8") == "42"
    assert result.turns[0].receipt.status == "succeeded"
    assert result.turns[0].observation.kind == "file.write"
    assert result.turns[0].verification_result.outcome == "none"
    assert result.goal["status"] == "active"
    assert result.run["status"] == "interrupted"
    assert result.stop_reason == "max_steps_reached"


def test_repeated_missing_target_reads_stop_at_step_budget(tmp_path):
    def strategy(_request):
        return PlannerDecision(
            status="proposals_available",
            proposals=(
                _proposal(
                    "fs.read",
                    {"path": "result.txt"},
                    "check the required result file",
                ),
            ),
        )

    _, store, internal, loop, _, run, spec = _build(tmp_path, strategy)

    result = loop.run(run["id"], spec, max_steps=3)

    assert len(result.turns) == 3
    assert all(turn.receipt.status == "failed" for turn in result.turns)
    assert result.turns[0].receipt.status == "failed"
    assert result.turns[0].observation.kind == "file.unavailable"
    assert all(turn.verification_result.outcome == "failure" for turn in result.turns)
    assert result.goal["status"] == "active"
    assert result.run["status"] == "interrupted"
    assert result.stop_reason == "max_steps_reached"
    assert store.list_steps(run_id=run["id"])[0]["status"] == "completed"
    assert internal.store.get_state("frustration")["value"] > 0.0


def test_cannot_progress_finishes_step_without_action_and_fails_only_run(tmp_path):
    def strategy(_request):
        return PlannerDecision(
            status="cannot_progress",
            plan_summary="no safe proposal available",
        )

    _, store, _, loop, goal, run, spec = _build(tmp_path, strategy)

    result = loop.run(run["id"], spec, max_steps=3)

    assert result.stop_reason == "planner_cannot_progress"
    assert result.run["status"] == "failed"
    assert result.goal["id"] == goal["id"]
    assert result.goal["status"] == "active"
    assert len(result.turns) == 1
    assert result.turns[0].action is None
    assert result.turns[0].receipt is None
    assert store.list_operations(run_id=run["id"]) == []
    assert store.list_steps(run_id=run["id"])[0]["status"] == "completed"


def test_planner_receives_prior_observation_and_remaining_step_budget(tmp_path):
    seen = []

    def context_provider(goal, observations, history):
        return {
            "goal_id": goal["id"],
            "observations_seen": len(observations),
            "history_seen": len(history),
        }

    def strategy(request):
        seen.append(
            {
                "recent": len(request.recent_observations),
                "remaining": request.remaining_budget["steps"],
                "context": dict(request.context),
            }
        )
        if not request.recent_observations:
            return PlannerDecision(
                status="proposals_available",
                proposals=(
                    _proposal(
                        "fs.write",
                        {"path": "result.txt", "content": "42"},
                        "write result",
                    ),
                ),
            )
        return PlannerDecision(
            status="proposals_available",
            proposals=(
                _proposal(
                    "fs.read",
                    {"path": "result.txt"},
                    "verify result",
                ),
            ),
        )

    _, _, _, loop, _, run, spec = _build(
        tmp_path,
        strategy,
        context_provider=context_provider,
    )

    result = loop.run(run["id"], spec, max_steps=4)

    assert result.completed is True
    assert seen[0]["recent"] == 0
    assert seen[0]["remaining"] == 4
    assert seen[0]["context"]["observations_seen"] == 0
    assert seen[1]["recent"] == 1
    assert seen[1]["remaining"] == 3
    assert seen[1]["context"]["observations_seen"] == 1
    assert seen[1]["context"]["history_seen"] == 1


@pytest.mark.parametrize("loop_type", [AgentLoop, RecoverableAgentLoop])
def test_trusted_goal_blocker_still_interrupts_run(tmp_path, loop_type):
    def strategy(_request):
        return PlannerDecision(
            status="proposals_available",
            proposals=(_proposal("fs.list", {"path": "."}, "inspect sandbox"),),
        )

    class TrustedBlockerVerifier(DeterministicGoalVerifier):
        def verify(self, spec, **kwargs):
            result = super().verify(spec, **kwargs)
            # Independent trusted policy fixture, not an inference from a failed read.
            return replace(
                result, outcome="blocked",
                reason="required external authorization is unavailable (trusted policy)",
            )

    _, _, internal, loop, _, run, spec = _build(tmp_path, strategy, loop_type=loop_type)
    loop.verifier = TrustedBlockerVerifier()
    result = loop.run(run["id"], spec, max_steps=3)

    assert len(result.turns) == 1
    assert result.turns[0].receipt.status == "succeeded"
    assert result.turns[0].verification_result.outcome == "blocked"
    assert result.turns[0].verification_application.goal_observation.kind == "blocked"
    assert result.goal["status"] == "blocked"
    assert result.run["status"] == "interrupted"
    assert result.stop_reason == "goal_blocked"
    assert internal.goals.list_active_goals() == []
