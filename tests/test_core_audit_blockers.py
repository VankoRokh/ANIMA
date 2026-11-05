"""Mandatory P4-D regressions derived from independent Work mini-audit B1–B4.

All work is done with production CoreAssembly and temporary SQLite instances.
The hard-process cut uses a disposable subprocess to verify transactional
rollback beyond Python exception handling.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from anima.core.door_world import DOOR_SUBJECT, DOOR_PREDICATE
from anima.core.goal_decision import GoalCriterion
from tests.test_core_p4_acceptance import _core, _effects, _goal, _status


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"type": "symbol", "value": "closed"}


def _criterion(goal_id):
    return GoalCriterion(
        goal_id=goal_id,
        subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE,
        expected=dict(EXPECTED),
    )


def test_core_audit_b1_atomic_prepare_failure_rolls_back_all_rows(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core, notify=False)
    original = core.core_execution.store.create_operation

    def inject(action, **kwargs):
        def crash(stage):
            assert stage == "after_action_insert"
            raise RuntimeError("audit injected mid-transaction failure")
        return original(action, **kwargs, fault_hook=crash)

    core.core_execution.store.create_operation = inject
    with pytest.raises(RuntimeError, match="audit injected mid-transaction"):
        core.runtime.run_core_autonomous()
    assert _effects(core) == 0
    assert core.core_execution.store.list_operations(goal_id=goal) == []

    core.core_execution.store.create_operation = original
    core.runtime.run_core_autonomous()
    assert _status(core, goal) == ("completed", ["completed"])
    assert _effects(core) == 1


def test_core_audit_b1_os_exit_inside_atomic_prepare_recovers(tmp_path):
    child = subprocess.run(
        [sys.executable, "-m", "tests.core_audit_crash_worker", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, timeout=25, check=False,
    )
    assert child.returncode == 73, child.stdout + child.stderr
    goal = (tmp_path / "audit_goal.txt").read_text(encoding="utf-8")
    reopened = _core(tmp_path)
    assert reopened.core_execution.store.list_operations(goal_id=goal) == []
    assert _effects(reopened) == 0
    reopened.runtime.wake()
    assert _status(reopened, goal) == ("completed", ["completed"])
    assert _effects(reopened) == 1
    assert len(reopened.core_execution.store.list_operations(goal_id=goal)) == 1
    assert reopened.core_autonomy.pending_count() == 0


def test_core_audit_b1_legacy_missing_spec_is_local_and_next_goal_progresses(tmp_path):
    first = _core(tmp_path)
    broken = _goal(first, priority=9, title="legacy broken", notify=False)
    original = first.core_execution.store.create_operation

    def legacy_partial(action, *, registry, reason, verification_spec):
        # Deliberately simulate OLD split-commit legacy data for the same
        # single SQLite store. New Core code never uses this path.
        original(action, registry=registry, reason=reason)
        raise RuntimeError("audit simulated legacy partial preparation")

    first.core_execution.store.create_operation = legacy_partial
    with pytest.raises(RuntimeError, match="audit simulated legacy partial"):
        first.runtime.run_core_autonomous()
    assert _effects(first) == 0
    assert len(first.core_execution.store.list_operations(goal_id=broken)) == 1

    reopened = _core(tmp_path)
    other = _goal(reopened, priority=1, title="independent later Goal", notify=False)
    result = reopened.runtime.run_core_autonomous(max_steps=4)
    assert any(
        turn.goal_id == broken and turn.reason_code == "INCOMPLETE_EXECUTION_INTENT"
        for turn in result.turns
    )
    assert _status(reopened, other) == ("completed", ["completed"])
    assert _status(reopened, broken)[0] == "active"
    assert reopened.core_execution._proof(broken) is None
    assert _effects(reopened) == 1
    assert reopened.core_autonomy.pending_count() == 0


@pytest.mark.parametrize("cancel", ["goal", "task"])
def test_core_audit_b2_cancel_after_proof_does_not_poison_other_goals(tmp_path, cancel):
    first = _core(tmp_path)
    source = _goal(first, priority=9, title="cancel-after-proof", notify=False)

    def abort_after_proof(_observation):
        raise RuntimeError("audit proof committed before Stage2")

    first.internal_state.observe_goal = abort_after_proof
    with pytest.raises(RuntimeError, match="audit proof committed"):
        first.runtime.run_core_autonomous()
    proof = first.core_execution._proof(source)
    assert proof is not None and _effects(first) == 1

    reopened = _core(tmp_path)
    if cancel == "goal":
        reopened.internal_state.goals.transition_goal(
            source, to_status="cancelled", reason="operator supersedes Core proof",
        )
    else:
        reopened.core_decision.tasks.transition_task(
            proof["task_id"], "cancelled", reason="operator cancels pending Task",
        )
    other = _goal(reopened, priority=1, title="other eligible Goal", notify=False)
    turns = reopened.runtime.run_core_autonomous(max_steps=4)
    assert _status(reopened, other) == ("completed", ["completed"])
    assert _effects(reopened) == 1
    assert reopened.core_execution._proof(source) == proof  # historical evidence
    if cancel == "goal":
        assert _status(reopened, source)[0] == "cancelled"
    else:
        assert reopened.core_decision.tasks.get_task(proof["task_id"]).status == "cancelled"
        assert _status(reopened, source)[0] == "active"
    assert any(t.goal_id == other for t in turns.turns)


def test_core_audit_b3_same_runtime_retry_uses_identical_stage2_request(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core, notify=False)
    original = core.internal_state.goals.transition_goal

    def interrupt(*args, **kwargs):
        raise RuntimeError("audit Stage2 goal transition interrupted")

    core.internal_state.goals.transition_goal = interrupt
    with pytest.raises(RuntimeError, match="audit Stage2 goal transition"):
        core.runtime.run_core_autonomous()
    core.internal_state.goals.transition_goal = original
    assert core.internal_state.goals.get_goal(goal)["status"] == "active"
    proof = core.core_execution._proof(goal)
    assert proof and _effects(core) == 1

    # Do not rebuild Core: this is the path the independent audit exposed.
    core.runtime.run_core_autonomous()
    core.runtime.run_core_autonomous()
    core.runtime.wake()
    assert _status(core, goal) == ("completed", ["completed"])
    assert _effects(core) == 1
    assert core.core_execution._proof(goal) == proof


def test_core_audit_b4_blocked_to_active_resumes_parked_goal(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core, notify=False)
    core.internal_state.goals.transition_goal(
        goal, to_status="blocked", reason="temporary operator hold",
    )
    first = core.runtime.run_core_autonomous()
    assert first.turns == ()
    assert _status(core, goal)[0] == "blocked"
    assert core.core_autonomy.pending_count() == 1
    assert core.core_autonomy.attempts() == ()
    assert _effects(core) == 0

    core.internal_state.goals.transition_goal(
        goal, to_status="active", reason="operator resumes same Goal",
    )
    assert core.runtime.bind_core_goal(_criterion(goal)) is False
    assert _status(core, goal) == ("completed", ["completed"])
    assert _effects(core) == 1
    task = core.core_decision.tasks.list_tasks(goal_id=goal)
    assert len(task) == 1
    task_id = task[0].public_id

    reopened = _core(tmp_path)
    reopened.runtime.wake()
    assert _status(reopened, goal) == ("completed", ["completed"])
    assert _effects(reopened) == 1
    assert reopened.core_decision.tasks.list_tasks(goal_id=goal)[0].public_id == task_id
    assert reopened.core_autonomy.pending_count() == 0


def test_core_audit_t1_mandatory_test_identity_includes_module():
    from scripts.run_core_acceptance import P4_REQUIRED, required_coverage
    forged = [
        {
            "name": name,
            "classname": "tests.some_other_module",
            "status": "PASS",
            "seconds": 0.0,
        }
        for name in P4_REQUIRED
    ]
    assert set(required_coverage(forged).values()) == {"MISSING"}
