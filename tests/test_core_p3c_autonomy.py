"""P3-C: durable event/Goal-driven Core loop, bounded retries and crash recovery."""

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
from anima.core.ingress import CONTRACT, SourceRegistration
from anima.execution.contracts import ActionSpec


EXTERNAL = "sensor.external_door"
NOISE = "sensor.background_noise"
EXPECTED = {"type": "symbol", "value": "closed"}


def _actions():
    key = (DOOR_SUBJECT, DOOR_PREDICATE, json.dumps(
        EXPECTED, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ))
    return {key: ActionSpec(
        candidate_id="door_close_01", tool=DOOR_TOOL, tool_version=DOOR_VERSION,
        arguments={"subject_ref": DOOR_SUBJECT},
    )}


def _core(path, *, state="open", auto=True):
    world = VirtualDoorWorld(path / "world")
    world.seed(state=state, tick=40)
    sources = {
        ref: SourceRegistration(
            source_ref=ref, producer_ref="adapter.external/0.1"
            if ref != DOOR_SOURCE else DOOR_PRODUCER,
            allowed_kinds=("state.property",),
        )
        for ref in (DOOR_SOURCE, EXTERNAL, NOISE)
    }
    properties = {
        (DOOR_SUBJECT, DOOR_PREDICATE): PropertyRule(
            subject_ref=DOOR_SUBJECT, predicate_ref=DOOR_PREDICATE,
            value_type="symbol", clock_domain="lab_tick",
            allowed_sources=(DOOR_SOURCE, EXTERNAL),
            freshness_ticks=2, allowed_symbols=("open", "closed"),
        )
    }
    return build_core(
        path / "data", sources=sources, properties=properties,
        goal_actions=_actions(), virtual_door_root=path / "world",
        auto_core=auto,
    )


def _goal(core, *, priority=5, description="close once"):
    return core.internal_state.goals.create_goal(
        source="test.operator", priority=priority, description=description,
        success_criterion="registered door state equals closed",
        reason="explicit P3-C test Goal",
    )


def _bind(core, goal_id, *, use_runtime=True):
    criterion = GoalCriterion(
        goal_id=goal_id, subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE, expected=dict(EXPECTED),
    )
    return (
        core.runtime.bind_core_goal(criterion) if use_runtime
        else core.core_decision.bind(criterion)
    )


def _event(occurrence, *, subject=DOOR_SUBJECT, tick=60, value="closed"):
    when = {"domain": "lab_tick", "value": tick}
    return {
        "contract": CONTRACT, "occurrence_id": occurrence,
        "occurrence_version": 1, "kind": "state.property",
        "payload": {
            "subject_ref": subject, "predicate_ref": DOOR_PREDICATE,
            "observed_at": when,
            "temporal_scope": {"kind": "instant", "at": dict(when)},
            "source_revision": tick,
            "value": {"type": "symbol", "value": value},
        },
    }


def _effect_count(core):
    with sqlite3.connect(core.core_execution.world.path) as connection:
        return connection.execute("SELECT COUNT(*) FROM door_effects").fetchone()[0]


def test_p3c_goal_binding_triggers_safe_operation_without_manual_run(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    assert core.runtime.bind_core_goal(GoalCriterion(
        goal_id=goal["id"], subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE, expected=dict(EXPECTED),
    )) is True

    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "completed"
    tasks = core.core_decision.tasks.list_tasks(goal_id=goal["id"])
    assert len(tasks) == 1 and tasks[0].status == "completed"
    assert core.core_execution.world.current()["state"] == "closed"
    assert _effect_count(core) == 1
    attempts = core.core_autonomy.attempts()
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "VERIFIED_SUCCESS"
    assert attempts[0]["trigger_key"] == "goal:" + goal["id"]

    # Our own P3-B verification events must never schedule new attempts.
    extra = core.runtime.run_core_autonomous()
    assert extra.turns == ()
    assert extra.pending_triggers == 0
    assert len(core.core_autonomy.attempts()) == 1
    assert _effect_count(core) == 1


def test_p3c_closed_door_finishes_by_noop_without_action(tmp_path):
    core = _core(tmp_path, state="closed")
    goal = _goal(core)
    _bind(core, goal["id"])
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "completed"
    assert core.core_execution.world.current()["state"] == "closed"
    assert _effect_count(core) == 0
    assert core.core_execution.store.list_operations(goal_id=goal["id"]) == []
    assert core.core_autonomy.attempts()[0]["reason_code"] == "NO_EFFECT_REQUIRED"


def test_p3c_does_not_execute_without_registered_goal_or_autonomy(tmp_path):
    default = build_core(tmp_path / "ordinary")
    assert default.core_autonomy is None
    with pytest.raises(RuntimeError, match="not configured"):
        default.runtime.run_core_autonomous()
    assert not (tmp_path / "ordinary" / "core_work.db").exists()

    manual = _core(tmp_path / "manual", auto=False)
    goal = _goal(manual)
    _bind(manual, goal["id"])
    assert manual.core_autonomy is None
    assert manual.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    assert _effect_count(manual) == 0


def test_p3c_ignores_external_invalid_noise_and_internal_feedback(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    # One intentional failed verification keeps the Goal active. It must not
    # generate a self-sustaining feedback chain after the first auto run.
    core.core_execution.after_effect_hook = lambda _: (
        core.core_execution.world.change_by_environment("open")
    )
    _bind(core, goal["id"])
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    assert core.core_autonomy.attempts()[0]["outcome"] == "UNVERIFIED"
    core.core_execution.after_effect_hook = None
    prior = len(core.core_autonomy.attempts())

    for i in range(5):
        admitted = core.runtime.ingest_core_event(
            _event(f"noise:{i}", subject="entity.noise", tick=100 + i),
            source_ref=NOISE,
        )
        assert admitted.status == "ACCEPTED"
        assert core.core_events.ingress.observation_outcome(
            admitted.event_id
        )["outcome"] == "REJECTED_INVALID"

    # Neither invalid world claims nor the driver's own sensor evidence
    # authorize extra execution attempts.
    assert len(core.core_autonomy.attempts()) == prior
    assert _effect_count(core) == 1
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "active"


def test_p3c_external_registered_observation_resumes_failed_goal_without_new_effect(tmp_path):
    core = _core(tmp_path)
    goal = _goal(core)
    core.core_execution.after_effect_hook = lambda _: (
        core.core_execution.world.change_by_environment("open")
    )
    _bind(core, goal["id"])
    assert core.core_autonomy.attempts()[0]["outcome"] == "UNVERIFIED"
    assert _effect_count(core) == 1

    core.core_execution.after_effect_hook = None
    core.core_execution.world.change_by_environment("closed")
    tick = core.core_execution.world.current()["tick"]
    admitted = core.runtime.ingest_core_event(
        _event("external:closed", tick=tick, value="closed"),
        source_ref=EXTERNAL,
    )
    assert admitted.status == "ACCEPTED"
    assert core.internal_state.goals.get_goal(goal["id"])["status"] == "completed"
    assert _effect_count(core) == 1
    attempts = core.core_autonomy.attempts()
    assert [a["trigger_key"] for a in attempts] == [
        "goal:" + goal["id"], "event:" + admitted.event_id,
    ]
    assert attempts[1]["outcome"] == "VERIFIED_SUCCESS"
    assert core.runtime.run_core_autonomous().turns == ()


def test_p3c_bounded_priority_fairness_across_two_existing_goals(tmp_path):
    core = _core(tmp_path)
    low = _goal(core, priority=1, description="low priority door")
    high = _goal(core, priority=9, description="high priority door")
    # Bind in the canonical Goal manager without the Runtime's immediate
    # notification, then exercise bounded startup catch-up.
    _bind(core, low["id"], use_runtime=False)
    _bind(core, high["id"], use_runtime=False)

    first = core.runtime.run_core_autonomous(max_steps=1)
    assert len(first.turns) == 1
    assert first.turns[0].goal_id in {low["id"], high["id"]}
    assert _effect_count(core) == 1
    assert sum(
        core.internal_state.goals.get_goal(g["id"])["status"] == "completed"
        for g in (high, low)
    ) == 1

    second = core.runtime.run_core_autonomous(max_steps=1)
    assert len(second.turns) == 1
    assert second.turns[0].goal_id != first.turns[0].goal_id
    assert all(
        core.internal_state.goals.get_goal(g["id"])["status"] == "completed"
        for g in (high, low)
    )
    assert _effect_count(core) == 1
    assert len(core.core_decision.tasks.list_tasks()) == 2
    assert core.runtime.run_core_autonomous().turns == ()


def test_p3c_restart_discovers_goal_binding_after_crash_before_notification(tmp_path):
    first = _core(tmp_path)
    goal = _goal(first)
    _bind(first, goal["id"], use_runtime=False)
    assert first.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    assert _effect_count(first) == 0

    restarted = _core(tmp_path)
    restarted.runtime.wake()
    assert restarted.internal_state.goals.get_goal(goal["id"])["status"] == "completed"
    assert _effect_count(restarted) == 1
    assert len(restarted.core_autonomy.attempts()) == 1
    assert restarted.runtime.run_core_autonomous().turns == ()


def test_p3c_crash_after_world_effect_replays_without_duplicate(tmp_path):
    first = _core(tmp_path)
    goal = _goal(first)

    def fail(action, descriptor, handler):
        _door_close(
            first.core_execution.world.root,
            action.to_dict()["arguments"], action.operation_id,
        )
        raise RuntimeError("controlled receipt loss inside autonomous turn")

    first.core_execution.executor._run_worker = fail
    with pytest.raises(RuntimeError, match="controlled receipt loss"):
        _bind(first, goal["id"])
    assert first.internal_state.goals.get_goal(goal["id"])["status"] == "active"
    assert _effect_count(first) == 1
    attempts = first.core_autonomy.attempts()
    assert len(attempts) == 1 and attempts[0]["status"] == "started"

    restarted = _core(tmp_path)
    restarted.runtime.wake()
    assert restarted.internal_state.goals.get_goal(goal["id"])["status"] == "completed"
    assert _effect_count(restarted) == 1
    assert restarted.core_autonomy.attempts()[0]["status"] == "finished"
    assert restarted.runtime.run_core_autonomous().turns == ()


def test_p3c_completed_goal_incomplete_task_recovered_without_active_goal(tmp_path):
    first = _core(tmp_path)
    goal = _goal(first)

    def fail(_task_id):
        raise RuntimeError("controlled failure after Goal completion")

    first.core_execution._finish_task = fail
    with pytest.raises(RuntimeError, match="controlled failure after Goal completion"):
        _bind(first, goal["id"])
    assert first.internal_state.goals.get_goal(goal["id"])["status"] == "completed"
    proof = first.core_execution._proof(goal["id"])
    assert proof is not None
    assert first.core_decision.tasks.get_task(proof["task_id"]).status == "active"

    restarted = _core(tmp_path)
    restarted.runtime.wake()
    assert restarted.internal_state.goals.get_goal(goal["id"])["status"] == "completed"
    assert restarted.core_decision.tasks.get_task(proof["task_id"]).status == "completed"
    assert _effect_count(restarted) == 1


def test_p3c_bounded_event_scan_resumes_after_noise_flood(tmp_path):
    core = _core(tmp_path)
    for i in range(75):
        admitted = core.core_events.ingress.admit(
            _event(f"flood:{i}", subject="entity.unregistered_noise", tick=100 + i),
            source_ref=NOISE,
        )
        assert admitted.status == "ACCEPTED"
    first = core.core_autonomy.drain(max_steps=1, max_new_events=32)
    assert first.more_input_events is True
    assert first.turns == ()
    assert first.pending_triggers == 0
    second = core.core_autonomy.drain(max_steps=1, max_new_events=64)
    assert second.more_input_events is False
    assert second.turns == ()
    assert second.pending_triggers == 0
    assert _effect_count(core) == 0
    with sqlite3.connect(core.data_dir / "core_work.db") as connection:
        cursor = connection.execute(
            "SELECT integer_value FROM core_autonomy_meta WHERE name='event_cursor'"
        ).fetchone()[0]
    assert cursor == 75


@pytest.mark.parametrize(
    "opts",
    [{"max_steps": 0}, {"max_steps": True}, {"max_triggers": -1},
     {"max_new_events": 0}],
)
def test_p3c_rejects_invalid_budgets(tmp_path, opts):
    core = _core(tmp_path)
    with pytest.raises(ValueError):
        core.runtime.run_core_autonomous(**opts)
