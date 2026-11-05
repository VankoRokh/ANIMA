"""P4-A: multi-step Core system acceptance with real persistence boundaries.

All scenarios use isolated local DBs and actual composed Runtime. They test
the bounded one-door ensure_once profile, not unrestricted LLM autonomy.
"""

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


EXTERNAL = "sensor.environment"
NOISE = "sensor.noise"
EXPECTED = {"type": "symbol", "value": "closed"}


def _registries(*, tool=DOOR_TOOL):
    sources = {
        source: SourceRegistration(
            source_ref=source, producer_ref=(
                DOOR_PRODUCER if source == DOOR_SOURCE else "adapter.external/0.1"
            ), allowed_kinds=("state.property",),
        ) for source in (DOOR_SOURCE, EXTERNAL, NOISE)
    }
    properties = {(DOOR_SUBJECT, DOOR_PREDICATE): PropertyRule(
        subject_ref=DOOR_SUBJECT, predicate_ref=DOOR_PREDICATE,
        value_type="symbol", clock_domain="lab_tick",
        allowed_sources=(DOOR_SOURCE, EXTERNAL), freshness_ticks=2,
        allowed_symbols=("open", "closed"),
    )}
    key = (
        DOOR_SUBJECT, DOOR_PREDICATE,
        json.dumps(EXPECTED, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    )
    actions = {key: ActionSpec(
        candidate_id="door_close", tool=tool, tool_version=DOOR_VERSION,
        arguments={"subject_ref": DOOR_SUBJECT},
    )}
    return sources, properties, actions


def _core(root, *, state="open", tool=DOOR_TOOL):
    world = VirtualDoorWorld(root / "world")
    world.seed(state=state, tick=40)
    sources, properties, actions = _registries(tool=tool)
    return build_core(
        root / "data", sources=sources, properties=properties,
        goal_actions=actions, virtual_door_root=root / "world", auto_core=True,
    )


def _goal(core, *, priority=5, title="ensure door once", notify=True):
    goal = core.internal_state.goals.create_goal(
        source="test.operator", priority=priority, description=title,
        success_criterion="door state == closed", reason="P4 authorized test",
    )
    criterion = GoalCriterion(
        goal_id=goal["id"], subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE, expected=dict(EXPECTED),
    )
    if notify:
        core.runtime.bind_core_goal(criterion)
    else:
        core.core_decision.bind(criterion)
    return goal["id"]


def _event(tag, *, source=EXTERNAL, tick=39, state="open", subject=DOOR_SUBJECT):
    observed = {"domain": "lab_tick", "value": tick}
    return {
        "contract": CONTRACT, "occurrence_id": tag,
        "occurrence_version": 1, "kind": "state.property",
        "payload": {
            "subject_ref": subject, "predicate_ref": DOOR_PREDICATE,
            "observed_at": observed,
            "temporal_scope": {"kind": "instant", "at": dict(observed)},
            "source_revision": tick,
            "value": {"type": "symbol", "value": state},
        },
    }


def _effects(core):
    with sqlite3.connect(core.core_execution.world.path) as connection:
        return connection.execute("SELECT COUNT(*) FROM door_effects").fetchone()[0]


def _status(core, goal_id):
    goal = core.internal_state.goals.get_goal(goal_id)
    tasks = core.core_decision.tasks.list_tasks(goal_id=goal_id)
    return goal["status"], [task.status for task in tasks]


def test_p4_priority_two_goals_and_repeat_goal_after_restart(tmp_path):
    core = _core(tmp_path)
    identity = core.identity.get()["instance_id"]
    low = _goal(core, priority=1, title="low", notify=False)
    high = _goal(core, priority=9, title="high", notify=False)

    first = core.runtime.run_core_autonomous(max_steps=1)
    assert [turn.goal_id for turn in first.turns] == [high]
    assert _status(core, high) == ("completed", ["completed"])
    assert _status(core, low)[0] == "active"
    assert _effects(core) == 1

    second = core.runtime.run_core_autonomous(max_steps=1)
    assert [turn.goal_id for turn in second.turns] == [low]
    assert _status(core, low) == ("completed", ["completed"])
    assert _effects(core) == 1
    assert core.runtime.run_core_autonomous().turns == ()

    restarted = _core(tmp_path)
    assert restarted.identity.get()["instance_id"] == identity
    third = _goal(restarted, title="new one-shot")
    assert _status(restarted, third) == ("completed", ["completed"])
    assert _effects(restarted) == 1
    assert len(restarted.core_execution.store.list_operations()) == 1
    assert restarted.core_autonomy.pending_count() == 0


def test_p4_conflicts_duplicates_late_and_noise_not_trusted_as_truth(tmp_path):
    core = _core(tmp_path)
    first = core.runtime.ingest_core_event(_event("e1", tick=39), source_ref=EXTERNAL)
    assert first.status == "ACCEPTED"
    assert core.runtime.ingest_core_event(
        _event("e1", tick=39), source_ref=EXTERNAL
    ).status == "ALREADY_SEEN"
    # Distinct source with same tick conflicting with EXTERNAL is tested by
    # the P2-B cross-sensor fixtures; here test rejected and late reports.
    noise = core.runtime.ingest_core_event(
        _event("noise", source=NOISE, subject="entity.fake", tick=39),
        source_ref=NOISE,
    )
    assert noise.status == "ACCEPTED"
    assert core.core_events.ingress.observation_outcome(
        noise.event_id
    )["outcome"] == "REJECTED_INVALID"
    stale = core.runtime.ingest_core_event(
        _event("older", tick=38, state="closed"), source_ref=EXTERNAL
    )
    assert core.core_events.ingress.observation_outcome(
        stale.event_id
    )["outcome"] == "HISTORY_ONLY"
    assert core.runtime.read_core_belief(DOOR_SUBJECT, DOOR_PREDICATE)["revision"] == 1
    assert _effects(core) == 0

    goal = _goal(core)
    assert _status(core, goal) == ("completed", ["completed"])
    assert _effects(core) == 1
    assert core.core_autonomy.pending_count() == 0


def test_p4_false_success_then_new_external_evidence_completes_without_retry(tmp_path):
    core = _core(tmp_path)
    core.core_execution.after_effect_hook = lambda _: (
        core.core_execution.world.change_by_environment("open")
    )
    goal = _goal(core)
    assert _status(core, goal)[0] == "active"
    assert core.core_autonomy.attempts()[0]["outcome"] == "UNVERIFIED"
    assert _effects(core) == 1

    core.core_execution.after_effect_hook = None
    for i in range(10):
        core.runtime.ingest_core_event(
            _event(f"fake{i}", source=NOISE, subject="entity.junk", tick=100 + i),
            source_ref=NOISE,
        )
    assert _effects(core) == 1
    assert _status(core, goal)[0] == "active"

    core.core_execution.world.change_by_environment("closed")
    tick = core.core_execution.world.current()["tick"]
    core.runtime.ingest_core_event(
        _event("changed", tick=tick, state="closed"), source_ref=EXTERNAL
    )
    assert _status(core, goal) == ("completed", ["completed"])
    assert _effects(core) == 1
    assert core.runtime.run_core_autonomous().turns == ()


def test_p4_crash_after_applied_effect_reconciles_without_double_execution(tmp_path):
    core = _core(tmp_path)
    goal = core.internal_state.goals.create_goal(
        source="test.operator", priority=5, description="door once",
        success_criterion="closed", reason="P4 controlled crash",
    )
    criterion = GoalCriterion(
        goal_id=goal["id"], subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE, expected=dict(EXPECTED),
    )
    def dropped_receipt(action, descriptor, handler):
        _door_close(
            core.core_execution.world.root,
            action.to_dict()["arguments"], action.operation_id,
        )
        raise RuntimeError("P4 injected lost receipt")

    core.core_execution.executor._run_worker = dropped_receipt
    with pytest.raises(RuntimeError, match="P4 injected lost receipt"):
        core.runtime.bind_core_goal(criterion)
    assert _effects(core) == 1
    assert _status(core, goal["id"])[0] == "active"
    assert core.core_autonomy.attempts()[0]["status"] == "started"

    restarted = _core(tmp_path)
    restarted.runtime.wake()
    assert _status(restarted, goal["id"]) == ("completed", ["completed"])
    assert _effects(restarted) == 1
    assert len(restarted.core_execution.store.list_operations(goal_id=goal["id"])) == 1
    assert restarted.core_autonomy.attempts()[0]["status"] == "finished"


def test_p4_missing_capability_never_acts_even_after_restart(tmp_path):
    core = _core(tmp_path, tool="world.unregistered")
    goal = _goal(core)
    assert _status(core, goal)[0] == "active"
    assert core.core_autonomy.attempts()[0]["outcome"] == "DENIED"
    assert _effects(core) == 0
    assert core.core_execution.store.list_operations(goal_id=goal) == []

    restarted = _core(tmp_path, tool="world.unregistered")
    restarted.runtime.wake()
    assert _status(restarted, goal)[0] == "active"
    assert _effects(restarted) == 0
    assert restarted.core_autonomy.pending_count() == 0


def test_p4_recover_verified_goal_without_task_completion(tmp_path):
    core = _core(tmp_path)
    def fail(_task_id):
        raise RuntimeError("P4 injected Task transition crash")

    core.core_execution._finish_task = fail
    goal = core.internal_state.goals.create_goal(
        source="test.operator", priority=5, description="door once",
        success_criterion="closed", reason="P4 controlled crash",
    )
    with pytest.raises(RuntimeError, match="P4 injected Task transition crash"):
        core.runtime.bind_core_goal(GoalCriterion(
            goal_id=goal["id"], subject_ref=DOOR_SUBJECT,
            predicate_ref=DOOR_PREDICATE, expected=dict(EXPECTED),
        ))
    assert _status(core, goal["id"])[0] == "completed"
    assert _effects(core) == 1

    restarted = _core(tmp_path)
    restarted.runtime.wake()
    assert _status(restarted, goal["id"]) == ("completed", ["completed"])
    assert _effects(restarted) == 1
    assert restarted.runtime.run_core_autonomous().turns == ()


def test_p4_many_irrelevant_events_advance_cursor_without_effects(tmp_path):
    core = _core(tmp_path, state="closed")
    goal = _goal(core)
    assert _status(core, goal) == ("completed", ["completed"])
    for i in range(130):
        core.core_events.ingress.admit(
            _event(f"junk:{i}", source=NOISE, subject="entity.junk", tick=100 + i),
            source_ref=NOISE,
        )
    first = core.core_autonomy.drain(max_steps=1, max_new_events=64)
    assert first.more_input_events
    assert first.turns == ()
    second = core.core_autonomy.drain(max_steps=1, max_new_events=64)
    assert second.more_input_events
    assert second.turns == ()
    third = core.core_autonomy.drain(max_steps=1, max_new_events=64)
    assert not third.more_input_events
    assert third.turns == ()
    assert core.core_autonomy.pending_count() == 0
    assert _effects(core) == 0
    with sqlite3.connect(core.data_dir / "core_work.db") as connection:
        cursor = connection.execute(
            "SELECT integer_value FROM core_autonomy_meta WHERE name='event_cursor'"
        ).fetchone()[0]
    assert cursor >= 130
