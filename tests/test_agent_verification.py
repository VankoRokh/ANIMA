from dataclasses import replace
from uuid import uuid4

import pytest

from anima.agent import AgentStore, Observation, VerificationResult, VerificationSpec
from anima.agent.verification import (
    DETERMINISTIC_VERIFIER_NAME,
    DETERMINISTIC_VERIFIER_VERSION,
    FILE_CONTENT_EQUALS,
    DeterministicGoalVerifier,
    GoalVerificationBridge,
)
from tests.harness import AnimaTestHarness


T0 = "2026-10-27T18:00:00+00:00"
T1 = "2026-10-27T18:01:00+00:00"
T2 = "2026-10-27T18:02:00+00:00"
T3 = "2026-10-27T18:03:00+00:00"


def _id(prefix):
    return f"{prefix}{uuid4()}"


def _setup(tmp_path):
    anima = AnimaTestHarness(tmp_path / "anima")
    goal = anima.runtime.create_goal(
        source="test",
        priority=1.0,
        description="write expected result",
        success_criterion="result.txt contains 42",
        reason="verification test goal",
        timestamp=T0,
    )

    agent_store = AgentStore(tmp_path / "agent.db")
    run = agent_store.create_run(
        goal_id=goal["id"],
        planner="test",
        planner_version="1",
        created_at=T0,
    )
    agent_store.transition_run(
        run["id"],
        "running",
        reason="verification test run",
        timestamp=T1,
    )
    step = agent_store.create_step(
        run_id=run["id"],
        created_at=T1,
    )

    spec = VerificationSpec.create(
        run_id=run["id"],
        verifier=DETERMINISTIC_VERIFIER_NAME,
        verifier_version=DETERMINISTIC_VERIFIER_VERSION,
        criterion_kind=FILE_CONTENT_EQUALS,
        parameters={"path": "result.txt", "expected": "42"},
    )
    verifier = DeterministicGoalVerifier()
    bridge = GoalVerificationBridge(
        agent_store=agent_store,
        recovery=anima.internal_state.recovery,
    )
    return anima, goal, agent_store, run, step, spec, verifier, bridge


def _observation(kind, data, *, observed_at=T2):
    return Observation(
        public_id=_id("obs_"),
        action_id=_id("act_"),
        receipt_id=_id("er_"),
        source="test",
        kind=kind,
        data=data,
        observed_at=observed_at,
    )


def _verify(verifier, spec, step, observations, *, candidate_id=None, public_id=None, timestamp=T3):
    return verifier.verify(
        spec,
        step_id=step["id"],
        candidate_id=candidate_id or _id("ap_"),
        observations=observations,
        timestamp=timestamp,
        public_id=public_id,
    )


def test_no_observation_evidence_does_not_complete_or_mutate_goal(tmp_path):
    anima, goal, _, _, step, spec, verifier, bridge = _setup(tmp_path)
    before_states = anima.snapshot()["internal_state"]["states"]
    before_recovery = anima.internal_state.recovery.snapshot()

    result = _verify(verifier, spec, step, ())
    application = bridge.apply(spec=spec, result=result, observations=())

    assert result.outcome == "none"
    assert result.criterion_satisfied is False
    assert application.applied is False
    assert application.goal_observation is None
    assert anima.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    assert anima.snapshot()["internal_state"]["states"] == before_states
    assert anima.internal_state.recovery.snapshot() == before_recovery


def test_matching_file_content_completes_goal_only_through_stage2_progress(tmp_path):
    anima, goal, _, _, step, spec, verifier, bridge = _setup(tmp_path)
    candidate_id = _id("ap_")
    evidence = (_observation("file.content", {"path": "result.txt", "content": "42"}),)

    result = _verify(
        verifier,
        spec,
        step,
        evidence,
        candidate_id=candidate_id,
    )
    application = bridge.apply(spec=spec, result=result, observations=evidence)

    assert result.outcome == "success"
    assert result.criterion_satisfied is True
    assert application.applied is True
    assert application.goal_observation.source_id == result.public_id
    assert application.goal_observation.candidate_id == candidate_id
    assert application.progress_result.goal["status"] == "completed"
    transitions = anima.internal_state.goals.list_goal_transitions(goal_id=goal["id"])
    assert transitions[-1]["source_id"] == result.public_id
    assert transitions[-1]["to_status"] == "completed"


def test_success_replay_is_idempotent_via_verification_result_id(tmp_path):
    anima, goal, _, _, step, spec, verifier, bridge = _setup(tmp_path)
    evidence = (_observation("file.content", {"path": "result.txt", "content": "42"}),)
    result = _verify(verifier, spec, step, evidence)

    first = bridge.apply(spec=spec, result=result, observations=evidence)
    state_count = anima.internal_state_store.transition_count()
    goal_transition_count = len(
        anima.internal_state.goals.list_goal_transitions(goal_id=goal["id"])
    )
    second = bridge.apply(spec=spec, result=result, observations=evidence)

    assert first.progress_result.goal["status"] == "completed"
    assert second.progress_result.goal["status"] == "completed"
    assert anima.internal_state_store.transition_count() == state_count
    assert len(
        anima.internal_state.goals.list_goal_transitions(goal_id=goal["id"])
    ) == goal_transition_count
    assert anima.internal_state.recovery.ledger.get(result.public_id)["status"] == "done"


def test_file_exists_is_progress_not_success(tmp_path):
    anima, goal, _, _, step, spec, verifier, bridge = _setup(tmp_path)
    evidence = (_observation("file.exists", {"path": "result.txt", "exists": True}),)

    result = _verify(verifier, spec, step, evidence)
    application = bridge.apply(spec=spec, result=result, observations=evidence)

    assert result.outcome == "progress"
    assert result.criterion_satisfied is False
    assert application.progress_result.goal["status"] == "active"
    assert anima.internal_state.goals.get_goal(goal["id"])["status"] == "active"


def test_wrong_file_content_is_failure_but_does_not_cancel_goal(tmp_path):
    anima, goal, _, _, step, spec, verifier, bridge = _setup(tmp_path)
    evidence = (_observation("file.content", {"path": "result.txt", "content": "99"}),)

    result = _verify(verifier, spec, step, evidence)
    application = bridge.apply(spec=spec, result=result, observations=evidence)

    assert result.outcome == "failure"
    assert result.criterion_satisfied is False
    assert application.progress_result.goal["status"] == "active"
    assert anima.internal_state.goals.get_goal(goal["id"])["status"] == "active"


@pytest.mark.parametrize("error_code", ["NOT_FOUND", "NOT_FILE", "FILE_TOO_LARGE", "UNSUPPORTED_ENCODING"])
@pytest.mark.parametrize("path, expected", [("result.txt", "42"), ("answer.txt", "hello")])
def test_unavailable_target_readback_is_failure_and_keeps_goal_active(tmp_path, error_code, path, expected):
    anima, goal, _, _, step, spec, verifier, bridge = _setup(tmp_path)
    spec = replace(spec, parameters={"path": path, "expected": expected})
    evidence = (_observation("file.unavailable", {"path": path, "error_code": error_code}),)

    result = _verify(verifier, spec, step, evidence)
    application = bridge.apply(spec=spec, result=result, observations=evidence)

    assert result.outcome == "failure"
    assert result.criterion_satisfied is False
    assert "readback is unavailable" in result.reason
    assert application.goal_observation.kind == "failure"
    assert application.progress_result.goal_transition is None
    assert application.progress_result.goal["status"] == "active"
    assert anima.internal_state.goals.get_goal(goal["id"])["status"] == "active"


def test_verifier_uses_stronger_content_evidence_before_exists_signal(tmp_path):
    _, _, _, _, step, spec, verifier, _ = _setup(tmp_path)
    evidence = (
        _observation("file.exists", {"path": "result.txt", "exists": True}),
        _observation("file.content", {"path": "result.txt", "content": "42"}),
    )

    result = _verify(verifier, spec, step, evidence)

    assert result.outcome == "success"
    assert result.observation_ids == tuple(item.public_id for item in evidence)


def test_latest_content_observation_wins_for_same_criterion(tmp_path):
    _, _, _, _, step, spec, verifier, _ = _setup(tmp_path)
    evidence = (
        _observation(
            "file.content",
            {"path": "result.txt", "content": "99"},
            observed_at=T1,
        ),
        _observation(
            "file.content",
            {"path": "result.txt", "content": "42"},
            observed_at=T2,
        ),
    )

    result = _verify(verifier, spec, step, evidence)

    assert result.outcome == "success"


def test_bridge_rejects_result_step_from_different_run(tmp_path):
    _, _, agent_store, _, step, spec, verifier, bridge = _setup(tmp_path)
    other_run = agent_store.create_run(
        goal_id=_id("goal_"),
        planner="test",
        planner_version="1",
        created_at=T0,
    )
    agent_store.transition_run(other_run["id"], "running", reason="other run", timestamp=T1)
    other_step = agent_store.create_step(run_id=other_run["id"], created_at=T1)
    result = _verify(verifier, spec, other_step, ())

    with pytest.raises(ValueError, match="does not belong"):
        bridge.apply(spec=spec, result=result, observations=())


def test_bridge_rejects_verification_before_evidence_timestamp(tmp_path):
    _, _, _, _, step, spec, verifier, bridge = _setup(tmp_path)
    evidence = (
        _observation(
            "file.content",
            {"path": "result.txt", "content": "42"},
            observed_at=T3,
        ),
    )
    result = _verify(verifier, spec, step, evidence, timestamp=T2)

    with pytest.raises(ValueError, match="cannot precede"):
        bridge.apply(spec=spec, result=result, observations=evidence)


def test_reused_verification_result_id_with_different_payload_is_rejected(tmp_path):
    _, _, _, _, step, spec, verifier, bridge = _setup(tmp_path)
    public_id = _id("vr_")
    progress_evidence = (
        _observation("file.exists", {"path": "result.txt", "exists": True}),
    )
    progress = _verify(
        verifier,
        spec,
        step,
        progress_evidence,
        public_id=public_id,
    )
    bridge.apply(spec=spec, result=progress, observations=progress_evidence)

    failure_evidence = (
        _observation("file.content", {"path": "result.txt", "content": "99"}),
    )
    conflicting = VerificationResult.create(
        run_id=progress.run_id,
        step_id=progress.step_id,
        verification_spec_id=progress.verification_spec_id,
        observation_ids=[item.public_id for item in failure_evidence],
        outcome="failure",
        criterion_satisfied=False,
        reason="different verification payload",
        importance=progress.importance,
        candidate_id=progress.candidate_id,
        timestamp=T3,
        public_id=public_id,
    )

    with pytest.raises(ValueError, match="different payload"):
        bridge.apply(spec=spec, result=conflicting, observations=failure_evidence)


def test_verifier_rejects_wrong_verifier_and_criterion_contract(tmp_path):
    _, _, _, run, step, _, verifier, _ = _setup(tmp_path)
    wrong_verifier = VerificationSpec.create(
        run_id=run["id"],
        verifier="other",
        verifier_version="1",
        criterion_kind=FILE_CONTENT_EQUALS,
        parameters={"path": "result.txt", "expected": "42"},
    )
    with pytest.raises(ValueError, match="does not target"):
        _verify(verifier, wrong_verifier, step, ())

    wrong_criterion = VerificationSpec.create(
        run_id=run["id"],
        verifier=DETERMINISTIC_VERIFIER_NAME,
        verifier_version=DETERMINISTIC_VERIFIER_VERSION,
        criterion_kind="file.other",
        parameters={},
    )
    with pytest.raises(ValueError, match="Unsupported deterministic criterion"):
        _verify(verifier, wrong_criterion, step, ())


def test_verifier_v2_rejects_version1_spec_instead_of_reinterpreting_it(tmp_path):
    _, _, _, _, step, spec, verifier, _ = _setup(tmp_path)
    assert verifier.version == DETERMINISTIC_VERIFIER_VERSION == "2"
    legacy_spec = replace(spec, verifier_version="1", parameters=dict(spec.parameters))
    with pytest.raises(ValueError, match="does not target"):
        _verify(verifier, legacy_spec, step, ())
