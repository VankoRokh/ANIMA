"""P4-C reproducible multi-episode acceptance for the bounded Core v0.1.

Seed controls environment state and registered-but-invalid noise. The suite
never feeds test-world truth directly into decision/Belief; all successes go
through the P3-B authorized adapter and independent observer.
"""

import random
import sqlite3
from contextlib import closing

import pytest

from tests.test_core_p4_acceptance import (
    EXTERNAL, NOISE, _core, _effects, _event, _goal, _status,
)
from anima.core.door_world import DOOR_SUBJECT, DOOR_PREDICATE


SEEDS = (7, 31, 73)
EPISODES = 24
RESTART_EVERY = 5


def _plan(seed, episodes):
    if type(seed) is not int or type(episodes) is not int or episodes < 1:
        raise ValueError("Seed/episodes must be finite exact integers")
    rng = random.Random(seed)
    return tuple(
        {
            "initial_state": rng.choice(("open", "closed")),
            "invalid_noise": rng.randrange(0, 4),
            "replay": rng.random() < 0.5,
        }
        for _ in range(episodes)
    )


def _run_seeded(root, *, seed, episodes=EPISODES, restart_every=RESTART_EVERY):
    plan = _plan(seed, episodes)
    core = _core(root, state="closed")
    stable_id = core.identity.get()["instance_id"]
    core.runtime.wake()
    total_effects = 0
    verified = []
    goal_ids = []

    for index, case in enumerate(plan):
        if index and index % restart_every == 0:
            core.runtime.sleep()
            core = _core(root)
            assert core.identity.get()["instance_id"] == stable_id
            core.runtime.wake()
            assert _effects(core) == total_effects

        core.core_execution.world.change_by_environment(case["initial_state"])
        before = _effects(core)
        for noise_index in range(case["invalid_noise"]):
            raw = _event(
                f"seed:{seed}:ep:{index}:noise:{noise_index}",
                source=NOISE, subject="entity.unregistered_noise",
                tick=1000 + index * 10 + noise_index,
            )
            admission = core.runtime.ingest_core_event(raw, source_ref=NOISE)
            assert admission.status == "ACCEPTED"
            assert core.core_events.ingress.observation_outcome(
                admission.event_id
            )["outcome"] == "REJECTED_INVALID"
            if case["replay"] and noise_index == 0:
                assert core.runtime.ingest_core_event(
                    raw, source_ref=NOISE
                ).status == "ALREADY_SEEN"

        assert _effects(core) == before  # no goal from noise
        goal_id = _goal(core, title=f"seed={seed} episode={index}")
        goal_ids.append(goal_id)
        assert _status(core, goal_id) == ("completed", ["completed"])
        expected_operation = int(case["initial_state"] == "open")
        total_effects += expected_operation
        operations = core.core_execution.store.list_operations(goal_id=goal_id)
        assert len(operations) == expected_operation
        assert all(row["status"] == "succeeded" for row in operations)
        assert _effects(core) == total_effects
        assert core.core_execution.world.current()["state"] == "closed"
        assert core.core_autonomy.pending_count() == 0

        proof = core.core_execution._proof(goal_id)
        assert proof is not None
        assert proof["event_id"]
        event = core.core_events.ingress.get_event(proof["event_id"])
        assert event["source_ref"] == "sensor.door_01"
        assert event["payload"]["value"] == {
            "type": "symbol", "value": "closed"
        }
        verified.append(event["event_id"])

    core.runtime.sleep()
    cold = _core(root)
    cold.runtime.wake()
    assert cold.identity.get()["instance_id"] == stable_id
    assert _effects(cold) == total_effects
    assert cold.core_autonomy.pending_count() == 0
    assert cold.runtime.run_core_autonomous().turns == ()
    assert len(set(goal_ids)) == episodes
    assert len(set(verified)) == episodes
    assert len(cold.core_decision.tasks.list_tasks()) == episodes
    assert len(cold.core_autonomy.attempts()) == episodes
    assert all(a["status"] == "finished" for a in cold.core_autonomy.attempts())
    assert all(
        a["outcome"] == "VERIFIED_SUCCESS"
        for a in cold.core_autonomy.attempts()
    )
    with closing(sqlite3.connect(cold.core_execution.world.path)) as connection:
        assert connection.execute(
            "SELECT COUNT(DISTINCT operation_id) FROM door_effects"
        ).fetchone()[0] == total_effects
    return {
        "seed": seed, "episodes": episodes,
        "expected_effects": total_effects,
        "completed": len(goal_ids),
        "verified": len(verified),
        "pending": cold.core_autonomy.pending_count(),
    }


@pytest.mark.parametrize("seed", SEEDS)
def test_p4c_seeded_24_episode_endurance_with_cold_restarts(tmp_path, seed):
    result = _run_seeded(tmp_path / f"seed_{seed}", seed=seed)
    assert result["completed"] == EPISODES
    assert result["verified"] == EPISODES
    assert result["expected_effects"] == sum(
        case["initial_state"] == "open" for case in _plan(seed, EPISODES)
    )
    assert result["pending"] == 0


def test_p4c_seed_plan_replays_same_workload_independent_of_uuid(tmp_path):
    # World/Goal IDs are random, but workload and measured aggregate outcome
    # must be reproducible for a fixed seed.
    assert _plan(101, 8) == _plan(101, 8)
    first = _run_seeded(tmp_path / "left", seed=101, episodes=8, restart_every=3)
    second = _run_seeded(tmp_path / "right", seed=101, episodes=8, restart_every=3)
    assert first == second


def test_p4c_bounded_no_work_idle_does_not_mutate_world(tmp_path):
    core = _core(tmp_path, state="open")
    before = core.core_execution.world.current()
    assert core.runtime.run_core_autonomous(max_steps=1).turns == ()
    assert core.runtime.run_core_autonomous(max_steps=1).turns == ()
    assert _effects(core) == 0
    assert core.core_execution.world.current() == before
    assert core.core_autonomy.pending_count() == 0


def test_p4c_readonly_belief_unknown_without_event_and_no_goal(tmp_path):
    core = _core(tmp_path)
    initial = core.runtime.read_core_belief(
        DOOR_SUBJECT, DOOR_PREDICATE, as_of_tick=40
    )
    assert initial["status"] == "unknown"
    assert initial["freshness"] == "undetermined"
    assert initial["revision"] == 0
    assert core.runtime.run_core_autonomous().turns == ()
    assert _effects(core) == 0



def test_p4c_registered_untrusted_source_cannot_forge_door_completion(tmp_path):
    core = _core(tmp_path, state="open")
    raw = _event(
        "forged:closed", source=NOISE, subject=DOOR_SUBJECT,
        tick=41, state="closed",
    )
    admission = core.runtime.ingest_core_event(raw, source_ref=NOISE)
    assert admission.status == "ACCEPTED"  # event journal remains auditable
    outcome = core.core_events.ingress.observation_outcome(admission.event_id)
    assert outcome == {
        "outcome": "REJECTED_UNAUTHORIZED",
        "reason_code": "SOURCE_NOT_AUTHORIZED",
    }
    belief = core.runtime.read_core_belief(DOOR_SUBJECT, DOOR_PREDICATE)
    assert belief["status"] == "unknown"
    assert belief["revision"] == 0
    assert _effects(core) == 0

    goal = _goal(core, title="reject forged success; read registered world")
    assert _status(core, goal) == ("completed", ["completed"])
    assert _effects(core) == 1
    assert core.core_execution.world.current()["state"] == "closed"
    proof = core.core_execution._proof(goal)
    trusted = core.core_events.ingress.get_event(proof["event_id"])
    assert trusted["source_ref"] == "sensor.door_01"
    assert trusted["event_id"] != admission.event_id
