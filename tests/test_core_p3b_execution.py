"""P3-B: guarded Stage6 door action and independent verified Goal completion."""

import json
import sqlite3

import pytest

from anima.core.assembly import build_core
from anima.core.belief import PropertyRule
from anima.core.door_world import (
    DOOR_SUBJECT, DOOR_PREDICATE, DOOR_SOURCE, DOOR_PRODUCER,
    DOOR_TOOL, DOOR_VERSION, VirtualDoorWorld, _door_close,
)
from anima.core.goal_decision import GoalCriterion
from anima.core.ingress import SourceRegistration
from anima.execution.contracts import ActionSpec


EXPECTED = {"type": "symbol", "value": "closed"}


def _actions(*, tool=DOOR_TOOL):
    key = (
        DOOR_SUBJECT, DOOR_PREDICATE,
        json.dumps(EXPECTED, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return {key: ActionSpec(
        candidate_id="door_close_01",
        tool=tool, tool_version=DOOR_VERSION,
        arguments={"subject_ref": DOOR_SUBJECT},
    )}


def _core(tmp_path, *, state="open", actions=None):
    world_root = tmp_path / "world"
    world = VirtualDoorWorld(world_root)
    world.seed(state=state, tick=40)
    sources = {
        DOOR_SOURCE: SourceRegistration(
            source_ref=DOOR_SOURCE,
            producer_ref=DOOR_PRODUCER,
            allowed_kinds=("state.property",),
        )
    }
    properties = {
        (DOOR_SUBJECT, DOOR_PREDICATE): PropertyRule(
            subject_ref=DOOR_SUBJECT,
            predicate_ref=DOOR_PREDICATE,
            value_type="symbol",
            clock_domain="lab_tick",
            allowed_sources=(DOOR_SOURCE,),
            freshness_ticks=2,
            allowed_symbols=("open", "closed"),
        )
    }
    return build_core(
        tmp_path / "runtime",
        sources=sources, properties=properties,
        goal_actions=_actions() if actions is None else actions,
        virtual_door_root=world_root,
    )


def _goal(core):
    goal = core.internal_state.goals.create_goal(
        source="test.operator",
        priority=5,
        description="Close one registered door once",
        success_criterion="registered world door state == closed",
        reason="P3-B explicit operator test",
    )
    core.runtime.bind_core_goal(GoalCriterion(
        goal_id=goal["id"],
        subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE,
        expected=dict(EXPECTED),
    ))
    return goal["id"]


def _ops(core, goal_id):
    return core.core_execution.store.list_operations(goal_id=goal_id)


def _world_effects(core):
    with sqlite3.connect(core.core_execution.world.path) as connection:
        return connection.execute("SELECT COUNT(*) FROM door_effects").fetchone()[0]


def test_p3b_open_door_close_via_stage6_executor_and_independent_verifier(tmp_path):
    core = _core(tmp_path)
    goal_id = _goal(core)

    result = core.runtime.run_core_door_goal(goal_id)

    assert result.outcome == "VERIFIED_SUCCESS"
    assert result.reason_code == "GOAL_SATISFIED"
    assert result.operation_id is not None
    assert result.receipt_status == "succeeded"
    assert result.evidence_event_id is not None
    assert core.core_execution.world.current()["state"] == "closed"
    assert _world_effects(core) == 1
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert core.core_decision.tasks.get_task(result.task_id).status == "completed"
    assert core.core_events.ingress.get_event(result.evidence_event_id)["source_ref"] == DOOR_SOURCE
    assert core.runtime.read_core_belief(
        DOOR_SUBJECT, DOOR_PREDICATE, as_of_tick=core.core_execution.world.current()["tick"]
    )["value"]["value"] == "closed"
    ops = _ops(core, goal_id)
    assert len(ops) == 1 and ops[0]["status"] == "succeeded"
    action = core.core_execution.store.load_action(ops[0]["id"])
    spec = core.core_execution.store.load_verification_spec(action.operation_id)
    assert spec.criterion_kind == "world.property_equals"
    assert spec.goal_id == goal_id
    assert len([row for row in core.event_log.load_events()
                if row["type"] == "world.observation"]) >= 3
    assert core.runtime.snapshot()["state"]["events_processed"] >= 3

    # Repeating the turn only reuses durable verified proof, never an effect.
    repeated = core.runtime.run_core_door_goal(goal_id)
    assert repeated.outcome == "RECOVERED_VERIFIED_SUCCESS"
    assert repeated.operation_id == result.operation_id
    assert _world_effects(core) == 1
    assert len(_ops(core, goal_id)) == 1


def test_p3b_closed_door_completes_by_two_independent_sensor_reads_without_action(tmp_path):
    core = _core(tmp_path, state="closed")
    goal_id = _goal(core)
    done = core.runtime.run_core_door_goal(goal_id)

    assert done.outcome == "VERIFIED_SUCCESS"
    assert done.reason_code == "NO_EFFECT_REQUIRED"
    assert done.operation_id is None
    assert done.receipt_status is None
    assert _ops(core, goal_id) == []
    assert _world_effects(core) == 0
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert core.core_decision.tasks.get_task(done.task_id).status == "completed"
    assert core.core_execution.world.current()["state"] == "closed"


def test_p3b_unbound_and_cancelled_goals_do_not_mutate_world(tmp_path):
    core = _core(tmp_path)
    goal = core.internal_state.goals.create_goal(
        source="test.operator", priority=1, description="unbound",
        success_criterion="unbound goal", reason="test",
    )
    result = core.runtime.run_core_door_goal(goal["id"])
    assert result.outcome == "DEFERRED"
    assert result.reason_code == "UNBOUND_GOAL"
    assert _world_effects(core) == 0

    goal_id = _goal(core)
    core.internal_state.goals.transition_goal(
        goal_id, to_status="cancelled", reason="operator cancelled"
    )
    result = core.runtime.run_core_door_goal(goal_id)
    assert result.outcome == "DEFERRED"
    assert result.reason_code == "GOAL_NOT_ACTIVE"
    assert _world_effects(core) == 0


def test_p3b_unregistered_capability_fails_policy_without_operation(tmp_path):
    core = _core(tmp_path, actions=_actions(tool="world.unregistered"))
    goal_id = _goal(core)
    result = core.runtime.run_core_door_goal(goal_id)
    assert result.outcome == "DENIED"
    assert result.reason_code == "UNREGISTERED_CAPABILITY"
    assert _ops(core, goal_id) == []
    assert _world_effects(core) == 0
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "active"


def test_p3b_successful_receipt_but_world_reopened_does_not_complete_goal(tmp_path):
    core = _core(tmp_path)
    goal_id = _goal(core)
    core.core_execution.after_effect_hook = lambda _goal: (
        core.core_execution.world.change_by_environment("open")
    )
    result = core.runtime.run_core_door_goal(goal_id)
    assert result.outcome == "UNVERIFIED"
    assert result.receipt_status == "succeeded"
    assert core.core_execution.world.current()["state"] == "open"
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "active"
    assert _ops(core, goal_id)[0]["status"] == "succeeded"
    assert _world_effects(core) == 1
    # Same Goal/Task must not silently execute the effect again.
    core.core_execution.after_effect_hook = None
    second = core.runtime.run_core_door_goal(goal_id)
    assert second.outcome == "UNVERIFIED"
    assert len(_ops(core, goal_id)) == 1
    assert _world_effects(core) == 1
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "active"


def test_p3b_pre_effect_goal_cancellation_denies_prepared_operation(tmp_path):
    core = _core(tmp_path)
    goal_id = _goal(core)

    def cancel(_goal):
        core.internal_state.goals.transition_goal(
            goal_id, to_status="cancelled", reason="operator cancelled before effect"
        )

    core.core_execution.before_execute_hook = cancel
    result = core.runtime.run_core_door_goal(goal_id)
    assert result.outcome == "DENIED"
    assert result.reason_code == "GOAL_NOT_ACTIVE"
    assert len(_ops(core, goal_id)) == 1
    assert _ops(core, goal_id)[0]["status"] == "prepared"
    assert core.core_execution.world.current()["state"] == "open"
    assert _world_effects(core) == 0


def test_p3b_crash_before_effect_keeps_prepared_operation_for_safe_resume(tmp_path):
    first = _core(tmp_path)
    goal_id = _goal(first)

    def fail(_goal):
        raise RuntimeError("controlled crash after durable prepare")

    first.core_execution.before_execute_hook = fail
    with pytest.raises(RuntimeError, match="controlled crash after durable prepare"):
        first.runtime.run_core_door_goal(goal_id)
    ops = _ops(first, goal_id)
    assert len(ops) == 1 and ops[0]["status"] == "prepared"
    assert _world_effects(first) == 0

    reopened = _core(tmp_path)
    done = reopened.runtime.run_core_door_goal(goal_id)
    assert done.outcome == "VERIFIED_SUCCESS"
    assert done.operation_id == ops[0]["id"]
    assert _world_effects(reopened) == 1
    assert reopened.internal_state.goals.get_goal(goal_id)["status"] == "completed"


def test_p3b_crash_after_world_effect_but_before_receipt_never_reexecutes(tmp_path):
    first = _core(tmp_path)
    goal_id = _goal(first)

    def lose_receipt(action, descriptor, handler):
        _door_close(first.core_execution.world.root,
                    action.to_dict()["arguments"], action.operation_id)
        raise RuntimeError("controlled missing worker receipt")

    first.core_execution.executor._run_worker = lose_receipt
    with pytest.raises(RuntimeError, match="controlled missing worker receipt"):
        first.runtime.run_core_door_goal(goal_id)
    ops = _ops(first, goal_id)
    assert len(ops) == 1 and ops[0]["status"] == "executing"
    assert first.core_execution.world.current()["state"] == "closed"
    assert _world_effects(first) == 1

    reopened = _core(tmp_path)
    result = reopened.runtime.run_core_door_goal(goal_id)
    assert result.outcome == "VERIFIED_SUCCESS"
    assert result.operation_id == ops[0]["id"]
    assert reopened.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert reopened.core_execution.store.get_operation(ops[0]["id"])["status"] == "succeeded"
    assert _world_effects(reopened) == 1


def test_p3b_crash_after_receipt_before_readback_recovers_without_duplicate(tmp_path):
    first = _core(tmp_path)
    goal_id = _goal(first)

    def crash(_goal):
        raise RuntimeError("controlled crash after action receipt")

    first.core_execution.after_effect_hook = crash
    with pytest.raises(RuntimeError, match="controlled crash after action receipt"):
        first.runtime.run_core_door_goal(goal_id)
    op = _ops(first, goal_id)[0]
    assert op["status"] == "succeeded"
    assert _world_effects(first) == 1
    assert first.internal_state.goals.get_goal(goal_id)["status"] == "active"

    reopened = _core(tmp_path)
    done = reopened.runtime.run_core_door_goal(goal_id)
    assert done.outcome == "VERIFIED_SUCCESS"
    assert done.operation_id == op["id"]
    assert _world_effects(reopened) == 1


def test_p3b_proof_persisted_before_goal_transition_is_recoverable(tmp_path):
    first = _core(tmp_path)
    goal_id = _goal(first)

    def fail(_observation):
        raise RuntimeError("controlled crash after proof before Goal transition")

    first.core_execution.internal_state.observe_goal = fail
    with pytest.raises(RuntimeError, match="controlled crash after proof"):
        first.runtime.run_core_door_goal(goal_id)
    assert first.internal_state.goals.get_goal(goal_id)["status"] == "active"
    assert first.core_execution._proof(goal_id)["event_id"]
    assert _world_effects(first) == 1

    reopened = _core(tmp_path)
    result = reopened.runtime.run_core_door_goal(goal_id)
    assert result.outcome == "RECOVERED_VERIFIED_SUCCESS"
    assert reopened.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert reopened.core_decision.tasks.get_task(result.task_id).status == "completed"
    assert _world_effects(reopened) == 1


def test_p3b_goal_completed_before_task_transition_is_recovered(tmp_path):
    first = _core(tmp_path)
    goal_id = _goal(first)

    def fail(_task_id):
        raise RuntimeError("controlled crash before Task completion")

    first.core_execution._finish_task = fail
    with pytest.raises(RuntimeError, match="controlled crash before Task completion"):
        first.runtime.run_core_door_goal(goal_id)
    assert first.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    proof = first.core_execution._proof(goal_id)
    assert proof["goal_id"] == goal_id
    assert first.core_decision.tasks.get_task(proof["task_id"]).status == "active"

    reopened = _core(tmp_path)
    result = reopened.runtime.run_core_door_goal(goal_id)
    assert result.outcome == "RECOVERED_VERIFIED_SUCCESS"
    assert reopened.core_decision.tasks.get_task(result.task_id).status == "completed"
    assert _world_effects(reopened) == 1


def test_p3b_recover_prepared_operation_without_verification_spec_fails_closed(tmp_path):
    # Deliberately emulate an OLD split-commit or legacy partial intent. New
    # Core preparation is atomic and cannot create this state on its own.
    first = _core(tmp_path)
    goal_id = _goal(first)
    original = first.core_execution.store.create_operation

    def legacy_partial(action, *, registry, reason, verification_spec):
        original(action, registry=registry, reason=reason)
        raise RuntimeError("controlled legacy partial intent")

    first.core_execution.store.create_operation = legacy_partial
    with pytest.raises(RuntimeError, match="controlled legacy partial"):
        first.runtime.run_core_door_goal(goal_id)
    op = _ops(first, goal_id)[0]
    assert op["status"] == "prepared"
    assert _world_effects(first) == 0

    reopened = _core(tmp_path)
    deferred = reopened.runtime.run_core_door_goal(goal_id)
    assert deferred.outcome == "DEFERRED"
    assert deferred.reason_code == "INCOMPLETE_EXECUTION_INTENT"
    assert deferred.operation_id == op["id"]
    assert reopened.internal_state.goals.get_goal(goal_id)["status"] == "active"
    assert _world_effects(reopened) == 0


def test_p3b_default_core_has_no_unrequested_virtual_executor(tmp_path):
    ordinary = build_core(tmp_path / "ordinary")
    assert ordinary.core_execution is None
    with pytest.raises(RuntimeError, match="not configured"):
        ordinary.runtime.run_core_door_goal("goal_invalid")
    assert not (tmp_path / "ordinary" / "execution.db").exists()


def test_p3b_world_sensor_is_not_derived_from_action_receipt(tmp_path):
    core = _core(tmp_path, state="closed")
    world = core.core_execution.world
    raw, tick = world.sense()
    assert raw["payload"]["value"] == {"type": "symbol", "value": "closed"}
    assert raw["payload"]["observed_at"]["value"] == tick
    assert _world_effects(core) == 0
    world.change_by_environment("open")
    changed, new_tick = world.sense()
    assert new_tick > tick
    assert changed["payload"]["value"] == {"type": "symbol", "value": "open"}
    assert _world_effects(core) == 0



def test_p3b_external_close_cancels_prepared_effect_after_independent_readback(tmp_path):
    first = _core(tmp_path)
    goal_id = _goal(first)

    def crash(_goal):
        raise RuntimeError("controlled crash after preparing operation")

    first.core_execution.before_execute_hook = crash
    with pytest.raises(RuntimeError, match="controlled crash after preparing"):
        first.runtime.run_core_door_goal(goal_id)
    operation = _ops(first, goal_id)[0]
    assert operation["status"] == "prepared"
    assert _world_effects(first) == 0

    first.core_execution.world.change_by_environment("closed")
    reopened = _core(tmp_path)
    done = reopened.runtime.run_core_door_goal(goal_id)
    assert done.outcome == "VERIFIED_SUCCESS"
    assert done.operation_id == operation["id"]
    assert reopened.core_execution.store.get_operation(operation["id"])["status"] == "cancelled"
    assert _world_effects(reopened) == 0
    assert reopened.internal_state.goals.get_goal(goal_id)["status"] == "completed"
