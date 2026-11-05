"""Regression: Core proof recovery must not open one Goal/Task DB connection per old proof.

Checks the NO-OP historical hot path and the pending-proof recovery path.
No absolute timings: the correctness gate is implementation-neutral and stable.
"""

import pytest

from tests.test_core_p4_acceptance import _core, _effects, _goal, _status


def test_completed_proof_history_uses_batched_lifecycle_reads(tmp_path, monkeypatch):
    core = _core(tmp_path, state="closed")
    core.runtime.wake()
    goals = [_goal(core, title=f"completed-{i}") for i in range(32)]
    assert all(_status(core, goal) == ("completed", ["completed"]) for goal in goals)
    assert _effects(core) == 0

    # No historical completed proof should trigger one get_goal / get_task
    # query. Bulk status snapshots preserve missing-identity validation.
    def per_proof_read_forbidden(_public_id):
        raise AssertionError("historical proof triggered per-row SQLite lookup")

    monkeypatch.setattr(core.core_decision.goals, "get_goal", per_proof_read_forbidden)
    monkeypatch.setattr(core.core_decision.tasks, "get_task", per_proof_read_forbidden)
    for _ in range(5):
        assert core.core_execution.recover_proofs(limit=4) == ()


def test_pending_proof_still_recovers_after_batch_optimization(tmp_path):
    core = _core(tmp_path)
    core.runtime.wake()
    goal_id = _goal(core, title="partially committed proof", notify=False)

    original = core.internal_state.observe_goal

    def interrupt_after_proof(_observation):
        raise RuntimeError("test cut after proof commit")

    core.internal_state.observe_goal = interrupt_after_proof
    try:
        with pytest.raises(RuntimeError, match="after proof commit"):
            core.runtime.run_core_autonomous(max_steps=1)
    finally:
        core.internal_state.observe_goal = original

    proof = core.core_execution._proof(goal_id)
    assert proof is not None
    assert _status(core, goal_id)[0] == "active"
    assert _effects(core) == 1

    result = core.core_execution.recover_proofs(limit=4)
    assert len(result) == 1
    assert result[0].goal_id == goal_id
    assert result[0].outcome == "RECOVERED_VERIFIED_SUCCESS"
    assert _status(core, goal_id) == ("completed", ["completed"])
    assert core.core_execution._proof(goal_id) == proof
    assert _effects(core) == 1
    assert core.core_execution.recover_proofs(limit=4) == ()
