"""P3-A: typed Goals, persistent Task identity, bounded no-effect decisions."""

import json
import sqlite3

import pytest

from anima.core.assembly import build_core
from anima.core.belief import PropertyRule
from anima.core.goal_decision import GoalCriterion
from anima.core.ingress import CONTRACT, SourceRegistration
from anima.execution.contracts import ActionSpec


SUBJECT = "entity.door_01@registry-r1"
PREDICATE = "world.door_state@1"
SOURCE_A = "sensor.door_a"
SOURCE_B = "sensor.door_b"
EXPECTED = {"type": "symbol", "value": "closed"}


def _actions():
    key = (SUBJECT, PREDICATE, json.dumps(
        EXPECTED, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ))
    return {key: ActionSpec(
        candidate_id="close_door_01",
        tool="world.door.close",
        tool_version="0.1",
        arguments={"subject_ref": SUBJECT},
    )}


def _core(path, *, actions=None):
    sources = {
        source: SourceRegistration(
            source_ref=source,
            producer_ref="adapter.virtual_sensor/0.1",
            allowed_kinds=("state.property",),
        ) for source in (SOURCE_A, SOURCE_B)
    }
    properties = {(SUBJECT, PREDICATE): PropertyRule(
        subject_ref=SUBJECT,
        predicate_ref=PREDICATE,
        value_type="symbol",
        clock_domain="lab_tick",
        allowed_sources=(SOURCE_A, SOURCE_B),
        freshness_ticks=2,
        allowed_symbols=("open", "closed"),
    )}
    return build_core(
        path, sources=sources, properties=properties,
        goal_actions=_actions() if actions is None else actions,
    )


def _goal(core, *, priority=5.0, description="Ensure door is closed once"):
    return core.internal_state.goals.create_goal(
        source="test.operator",
        priority=priority,
        description=description,
        success_criterion="world.door_state is closed",
        reason="explicit P3-A test Goal",
    )


def _criterion(goal, *, expected=None):
    return GoalCriterion(
        goal_id=goal["id"],
        subject_ref=SUBJECT,
        predicate_ref=PREDICATE,
        expected=dict(EXPECTED if expected is None else expected),
    )


def _event(occurrence, *, tick=40, value="open"):
    observed = {"domain": "lab_tick", "value": tick}
    return {
        "contract": CONTRACT,
        "occurrence_id": occurrence,
        "occurrence_version": 1,
        "kind": "state.property",
        "payload": {
            "subject_ref": SUBJECT,
            "predicate_ref": PREDICATE,
            "observed_at": observed,
            "temporal_scope": {"kind": "instant", "at": dict(observed)},
            "source_revision": tick,
            "value": {"type": "symbol", "value": value},
        },
    }


def test_p3a_unbound_goal_is_deferred_without_task(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    turn = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert turn.kind == "DEFER"
    assert turn.reason_code == "UNBOUND_GOAL"
    assert turn.task_id is None
    assert core.core_decision.tasks.list_tasks(goal_id=goal["id"]) == []
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"


def test_p3a_goal_binding_is_idempotent_and_cannot_be_overwritten(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    criterion = _criterion(goal)
    assert core.runtime.bind_core_goal(criterion) is True
    assert core.runtime.bind_core_goal(_criterion(goal)) is False
    with pytest.raises(ValueError, match="cannot be changed"):
        core.runtime.bind_core_goal(_criterion(goal, expected={
            "type": "symbol", "value": "open"
        }))
    criterion.expected["value"] = "open"  # should not mutate stored binding
    turn = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert turn.kind == "REQUEST_OBSERVATION"
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"


def test_p3a_missing_stale_and_disputed_state_never_proposes_action(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    core.runtime.bind_core_goal(_criterion(goal))

    missing = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert missing.kind == "REQUEST_OBSERVATION"
    assert missing.candidate is None
    assert core.core_decision.tasks.get_task(missing.task_id).status == "queued"

    core.runtime.ingest_core_event(_event("a"), source_ref=SOURCE_A)
    stale = core.runtime.plan_core_step(goal["id"], as_of_tick=43)
    assert stale.kind == "REQUEST_OBSERVATION"
    assert stale.task_id == missing.task_id
    assert stale.candidate is None

    core.runtime.ingest_core_event(_event("b", value="closed"), source_ref=SOURCE_B)
    disputed = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert disputed.kind == "REQUEST_OBSERVATION"
    assert disputed.task_id == missing.task_id
    assert disputed.candidate is None


def test_p3a_explicit_action_proposal_is_not_execution_or_goal_completion(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    core.runtime.bind_core_goal(_criterion(goal))
    event = core.runtime.ingest_core_event(_event("open"), source_ref=SOURCE_A)
    turn = core.runtime.plan_core_step(goal["id"], as_of_tick=40)

    assert turn.kind == "PROPOSE_ACTION"
    assert turn.reason_code == "TARGET_DIFFERS"
    assert turn.candidate.candidate_id == "close_door_01"
    assert turn.candidate.tool == "world.door.close"
    assert turn.belief_revision == 1
    assert turn.evidence_event_ids == (event.event_id,)
    assert core.core_decision.tasks.get_task(turn.task_id).status == "active"
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    assert core.runtime.read_core_belief(SUBJECT, PREDICATE)["value"]["value"] == "open"
    assert not (tmp_path / "execution.db").exists()

    repeated = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert repeated.task_id == turn.task_id
    assert len(core.core_decision.tasks.list_tasks(goal_id=goal["id"])) == 1
    assert len(core.core_decision.history(goal["id"])) == 2


def test_p3a_already_satisfied_goal_requires_independent_verification(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    core.runtime.bind_core_goal(_criterion(goal))
    core.runtime.ingest_core_event(_event("closed", value="closed"), source_ref=SOURCE_A)

    turn = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert turn.kind == "NOOP"
    assert turn.reason_code == "TARGET_ALREADY_OBSERVED"
    assert turn.candidate is None
    assert core.core_decision.tasks.get_task(turn.task_id).status == "active"
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    assert not (tmp_path / "execution.db").exists()


def test_p3a_no_registered_action_deferred_without_capability(tmp_path):
    core = _core(tmp_path, actions={})
    goal = _goal(core)
    core.runtime.bind_core_goal(_criterion(goal))
    core.runtime.ingest_core_event(_event("open"), source_ref=SOURCE_A)
    turn = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert turn.kind == "DEFER"
    assert turn.reason_code == "NO_REGISTERED_ACTION"
    assert turn.candidate is None
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"


def test_p3a_recovery_reuses_reserved_task_after_crash_before_task_creation(tmp_path):
    first = _core(tmp_path)
    goal = _goal(first)
    first.runtime.bind_core_goal(_criterion(goal))
    first.runtime.ingest_core_event(_event("open"), source_ref=SOURCE_A)

    original_create = first.core_decision.tasks.create_task
    def crash(*args, **kwargs):
        raise RuntimeError("controlled TaskStore creation failure")

    first.core_decision.tasks.create_task = crash
    with pytest.raises(RuntimeError, match="controlled TaskStore creation"):
        first.runtime.plan_core_step(goal["id"], as_of_tick=40)
    first.core_decision.tasks.create_task = original_create
    with sqlite3.connect(tmp_path / "core_work.db") as connection:
        reserved = connection.execute(
            "SELECT task_id FROM core_task_intents WHERE goal_id=?", (goal["id"],)
        ).fetchone()[0]
    assert first.core_decision.tasks.get_task(reserved) is None

    reopened = _core(tmp_path)
    turn = reopened.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert turn.task_id == reserved
    assert turn.kind == "PROPOSE_ACTION"
    assert len(reopened.core_decision.tasks.list_tasks(goal_id=goal["id"])) == 1
    assert reopened.internal_state.goals.get_goal(goal["id"])["status"] == "active"


def test_p3a_recovery_reuses_task_after_failed_decision_audit(tmp_path):
    first = _core(tmp_path)
    goal = _goal(first)
    first.runtime.bind_core_goal(_criterion(goal))
    first.runtime.ingest_core_event(_event("open"), source_ref=SOURCE_A)

    def crash(_turn):
        raise RuntimeError("controlled decision audit failure")

    first.core_decision._audit = crash
    with pytest.raises(RuntimeError, match="controlled decision audit"):
        first.runtime.plan_core_step(goal["id"], as_of_tick=40)
    created = first.core_decision.tasks.list_tasks(goal_id=goal["id"])
    assert len(created) == 1
    assert created[0].status == "active"

    reopened = _core(tmp_path)
    again = reopened.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert again.task_id == created[0].public_id
    assert len(reopened.core_decision.tasks.list_tasks(goal_id=goal["id"])) == 1


def test_p3a_goal_arbitrator_reuses_priority_without_inventing_goals(tmp_path):
    core = _core(tmp_path)
    assert core.runtime.plan_next_core_step(as_of_tick=40) is None
    low = _goal(core, priority=1.0, description="Low priority door state")
    high = _goal(core, priority=9.0, description="High priority door state")
    core.runtime.bind_core_goal(_criterion(low))
    core.runtime.bind_core_goal(_criterion(high))

    selected = core.runtime.plan_next_core_step(as_of_tick=40)
    assert selected.goal_id == high["id"]
    assert selected.kind == "REQUEST_OBSERVATION"
    assert len(core.internal_state.goals.list_active_goals()) == 2
    assert core.core_decision.tasks.list_tasks(goal_id=low["id"]) == []


def test_p3a_inactive_goal_never_schedules_or_proposes(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    core.runtime.bind_core_goal(_criterion(goal))
    core.internal_state.goals.transition_goal(
        goal["id"], to_status="cancelled", reason="explicit operator cancellation"
    )
    turn = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert turn.kind == "DEFER"
    assert turn.reason_code == "GOAL_NOT_ACTIVE"
    assert turn.task_id is None


@pytest.mark.parametrize("bad", [
    {"type": "symbol", "value": "unregistered"},
    {"type": "boolean", "value": True},
    {"type": "symbol", "value": "open", "extra": "x"},
])
def test_p3a_invalid_typed_criterion_is_rejected(tmp_path, bad):
    core = _core(tmp_path)
    goal = _goal(core)
    with pytest.raises(ValueError, match="criterion value"):
        core.runtime.bind_core_goal(_criterion(goal, expected=bad))
    assert core.runtime.plan_core_step(goal["id"], as_of_tick=40).kind == "DEFER"


def test_p3a_invalid_ticks_and_no_implicit_planner(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    core.runtime.bind_core_goal(_criterion(goal))
    for tick in (-1, True, 0.5):
        with pytest.raises(ValueError, match="as_of_tick"):
            core.runtime.plan_core_step(goal["id"], as_of_tick=tick)
    default = build_core(tmp_path / "default")
    assert default.core_decision is None
    with pytest.raises(RuntimeError, match="not configured"):
        default.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert not (tmp_path / "default" / "core_work.db").exists()


def test_p3a_rechecks_updated_belief_and_interrupts_stale_active_task(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    core.runtime.bind_core_goal(_criterion(goal))
    core.runtime.ingest_core_event(_event("open", tick=40), source_ref=SOURCE_A)
    proposed = core.runtime.plan_core_step(goal["id"], as_of_tick=40)
    assert proposed.kind == "PROPOSE_ACTION"
    assert core.core_decision.tasks.get_task(proposed.task_id).status == "active"

    stale = core.runtime.plan_core_step(goal["id"], as_of_tick=44)
    assert stale.kind == "REQUEST_OBSERVATION"
    assert core.core_decision.tasks.get_task(proposed.task_id).status == "interrupted"

    core.runtime.ingest_core_event(
        _event("closed", tick=45, value="closed"), source_ref=SOURCE_A
    )
    no_op = core.runtime.plan_core_step(goal["id"], as_of_tick=45)
    assert no_op.kind == "NOOP"
    assert no_op.task_id == proposed.task_id
    assert no_op.candidate is None
    assert core.core_decision.tasks.get_task(proposed.task_id).status == "active"
    assert len(core.core_decision.tasks.list_tasks(goal_id=goal["id"])) == 1
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"
