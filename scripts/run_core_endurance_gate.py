#!/usr/bin/env python3
"""Core v0.1 endurance gate (independent of Godot and LLM).

Run from the repository root:
    .venv/bin/python scripts/run_core_endurance_gate.py \
        --episodes 180 --report /tmp/anima-core-endurance.json

Uses the real Core assembly and durable SQLite-backed virtual door. Scenarios
are seeded, include invalid sensor noise, duplicate delivery, cold restarts,
one-effect verification and a >64 blocked-goal scheduler backlog.

Reports measured timings and file growth; does NOT impose arbitrary speed
thresholds or claim hardware crash-safety. Never touches production data.
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anima.core.door_world import DOOR_SOURCE  # noqa: E402
from tests.test_core_p4_acceptance import (  # noqa: E402
    NOISE, _core, _effects, _event, _goal, _status,
)


def require(condition, description):
    if not condition:
        raise AssertionError(description)


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.5)))
    return round(ordered[index] * 1000, 2)


def disk_bytes(directory):
    return sum(item.stat().st_size for item in directory.rglob("*") if item.is_file())


def snapshot(index, started, intervals, directory):
    data = {
        "episodes": index,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "latest_p50_ms": percentile(intervals[-25:], 0.50),
        "latest_p95_ms": percentile(intervals[-25:], 0.95),
        "disk_bytes": disk_bytes(directory),
        # Linux ru_maxrss reports KiB; this is the main Python process only.
        "python_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    print(
        f"CORE_ENDURANCE_PROGRESS {index} "
        f"elapsed={data['elapsed_seconds']}s "
        f"p95_last25={data['latest_p95_ms']}ms "
        f"disk={data['disk_bytes']}B",
        flush=True,
    )
    return data


def endurance(directory, *, episodes, seed, restart_every, max_noise, checkpoint_every):
    rng = random.Random(seed)
    core = _core(directory, state="closed")
    original_identity = core.identity.get()["instance_id"]
    core.runtime.wake()
    expect_effects = 0
    proof_ids = set()
    goal_ids = set()
    times = []
    restart_times = []
    checkpoints = []
    noise_admissions = 0
    duplicates = 0
    began = time.monotonic()

    for i in range(episodes):
        if i and i % restart_every == 0:
            start = time.monotonic()
            core.runtime.sleep()
            core = _core(directory)
            require(core.identity.get()["instance_id"] == original_identity,
                    f"identity changed at episode {i}")
            core.runtime.wake()
            require(_effects(core) == expect_effects,
                    f"effect counter changed during restart {i}")
            restart_times.append(time.monotonic() - start)

        episode_started = time.monotonic()
        initial = rng.choice(("open", "closed"))
        core.core_execution.world.change_by_environment(initial)
        before = _effects(core)
        require(before == expect_effects, f"unexpected prior effect at {i}")
        noise_count = rng.randrange(max_noise + 1)
        for j in range(noise_count):
            raw = _event(
                f"endurance:{seed}:{i}:{j}",
                source=NOISE,
                subject="entity.unregistered_noise",
                tick=1000000 + i * 32 + j,
            )
            first = core.runtime.ingest_core_event(raw, source_ref=NOISE)
            require(first.status == "ACCEPTED", f"noise not journaled at {i}:{j}")
            outcome = core.core_events.ingress.observation_outcome(first.event_id)
            require(outcome["outcome"] == "REJECTED_INVALID",
                    f"invalid noise was not rejected at {i}:{j}")
            noise_admissions += 1
            if j == 0 and i % 2 == 0:
                replay = core.runtime.ingest_core_event(raw, source_ref=NOISE)
                require(replay.status == "ALREADY_SEEN",
                        f"replay changed observation at {i}:{j}")
                duplicates += 1
        require(_effects(core) == before, f"noise caused an effect at {i}")

        goal_id = _goal(core, title=f"endurance seed={seed} episode={i}")
        require(goal_id not in goal_ids, f"repeated goal ID at {i}")
        goal_ids.add(goal_id)
        require(_status(core, goal_id) == ("completed", ["completed"]),
                f"goal/task not completed at {i}")
        should_apply = int(initial == "open")
        expect_effects += should_apply
        ops = core.core_execution.store.list_operations(goal_id=goal_id)
        require(len(ops) == should_apply and all(
            operation["status"] == "succeeded" for operation in ops
        ), f"operation mismatch at {i}")
        require(_effects(core) == expect_effects,
                f"duplicate or missing world effect at {i}")
        require(core.core_execution.world.current()["state"] == "closed",
                f"world state mismatch at {i}")
        proof = core.core_execution._proof(goal_id)
        require(proof is not None and proof["event_id"] not in proof_ids,
                f"missing/duplicate proof at {i}")
        evidence = core.core_events.ingress.get_event(proof["event_id"])
        require(evidence is not None and evidence["source_ref"] == DOOR_SOURCE
                and evidence["payload"]["value"] == {
                    "type": "symbol", "value": "closed",
                }, f"invalid proof source/value at {i}")
        proof_ids.add(proof["event_id"])
        require(core.core_autonomy.pending_count() == 0,
                f"scheduler left pending work at {i}")
        if i % 20 == 19:
            require(core.runtime.run_core_autonomous(max_steps=2).turns == (),
                    f"idle scheduler generated extra work at {i}")
            require(_effects(core) == expect_effects,
                    f"idle scheduler applied extra effect at {i}")

        times.append(time.monotonic() - episode_started)
        if (i + 1) % checkpoint_every == 0 or i + 1 == episodes:
            checkpoints.append(snapshot(i + 1, began, times, directory))

    start = time.monotonic()
    core.runtime.sleep()
    core = _core(directory)
    require(core.identity.get()["instance_id"] == original_identity,
            "final cold restart changed identity")
    core.runtime.wake()
    restart_times.append(time.monotonic() - start)

    require(core.runtime.run_core_autonomous().turns == (),
            "final idle run generated new work")
    require(core.core_autonomy.pending_count() == 0,
            "final scheduler has pending work")
    require(_effects(core) == expect_effects,
            "final effect count changed on restart")

    operations = core.core_execution.store.list_operations()
    require(len(operations) == expect_effects,
            "durable execution operation count mismatch")
    require(len({op["id"] for op in operations}) == len(operations),
            "duplicate operation IDs")
    require(all(op["status"] == "succeeded" for op in operations),
            "unfinished operation after cold restart")

    tasks = core.core_decision.tasks.list_tasks()
    require(len(tasks) == episodes and all(task.status == "completed" for task in tasks),
            "lost or unfinished Task after cold restart")
    attempts = core.core_autonomy.attempts()
    require(len(attempts) == episodes and all(
        row["status"] == "finished" and row["outcome"] == "VERIFIED_SUCCESS"
        for row in attempts
    ), "unexpected/missing scheduler attempts")
    require(len(proof_ids) == episodes, "not every episode has independent proof")

    outcome = {
        "seed": seed,
        "episodes": episodes,
        "cold_restarts": len(restart_times),
        "valid_goals_completed": len(goal_ids),
        "distinct_proof_events": len(proof_ids),
        "effects_applied": expect_effects,
        "invalid_noise_admitted_and_rejected": noise_admissions,
        "exact_duplicate_deliveries": duplicates,
        "goal_latency_ms": {
            "p50": percentile(times, 0.50),
            "p95": percentile(times, 0.95),
            "p99": percentile(times, 0.99),
            "first_quarter_median": percentile(times[:max(1, episodes // 4)], 0.50),
            "last_quarter_median": percentile(times[-max(1, episodes // 4):], 0.50),
        },
        "cold_restart_latency_ms": {
            "p50": percentile(restart_times, 0.50),
            "p95": percentile(restart_times, 0.95),
        },
        "checkpoints": checkpoints,
        "final_disk_bytes": disk_bytes(directory),
    }
    core.runtime.sleep()
    print(f"CORE_ENDURANCE_INTEGRITY_PASS goals={episodes} effects={expect_effects}",
          flush=True)
    return outcome


def scheduler_backlog(directory, *, blocked):
    """Show forward progress beyond the scheduler's first-64 scan window."""
    core = _core(directory, state="closed")
    core.runtime.wake()
    parked = []
    for i in range(blocked):
        goal_id = _goal(core, title=f"parked-{i}", priority=1, notify=False)
        core.internal_state.goals.transition_goal(
            goal_id, to_status="blocked", reason="endurance scheduler test")
        parked.append(goal_id)

    eligible = _goal(core, title="new eligible priority 9", priority=9, notify=False)
    drains = 0
    for _ in range(12):
        drains += 1
        core.runtime.run_core_autonomous(max_steps=1)
        if _status(core, eligible)[0] == "completed":
            break
    require(_status(core, eligible) == ("completed", ["completed"]),
            "eligible Goal starved by blocked backlog")
    require(all(_status(core, goal)[0] == "blocked" for goal in parked),
            "blocked Goal was spuriously activated")
    require(_effects(core) == 0, "closed-door workload created effect")

    core.internal_state.goals.transition_goal(
        parked[0], to_status="active", reason="explicit resume test")
    for _ in range(12):
        core.runtime.run_core_autonomous(max_steps=1)
        if _status(core, parked[0])[0] == "completed":
            break
    require(_status(core, parked[0]) == ("completed", ["completed"]),
            "reactivated parked Goal was not resumed")
    require(all(_status(core, goal)[0] == "blocked" for goal in parked[1:]),
            "other parked Goals were disturbed")

    core.runtime.sleep()
    reopened = _core(directory)
    reopened.runtime.wake()
    require(_effects(reopened) == 0,
            "cold restart generated unexpected effect in parked scenario")
    require(_status(reopened, eligible)[0] == "completed"
            and _status(reopened, parked[0])[0] == "completed",
            "completed Goals changed status after restart")
    require(all(_status(reopened, goal)[0] == "blocked" for goal in parked[1:]),
            "blocked backlog status changed after restart")
    reopened.runtime.sleep()
    print(f"CORE_SCHEDULER_BACKLOG_PASS parked={blocked} drains_to_new_goal={drains}",
          flush=True)
    return {"parked_goals": blocked, "drains_to_new_goal": drains,
            "resumed_goal_completed": True, "unexpected_effects": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=180)
    parser.add_argument("--seed", type=int, default=131)
    parser.add_argument("--restart-every", type=int, default=11)
    parser.add_argument("--max-noise", type=int, default=6)
    parser.add_argument("--checkpoint-every", type=int, default=30)
    parser.add_argument("--blocked-goals", type=int, default=128)
    parser.add_argument("--report", type=Path, default=Path("/tmp/anima-core-endurance.json"))
    args = parser.parse_args()
    if not (24 <= args.episodes <= 1000):
        parser.error("--episodes must be 24..1000")
    if not (1 <= args.restart_every <= args.episodes):
        parser.error("--restart-every must be 1..episodes")
    if not (0 <= args.max_noise <= 16):
        parser.error("--max-noise must be 0..16")
    if not (1 <= args.checkpoint_every <= args.episodes):
        parser.error("--checkpoint-every must be 1..episodes")
    if not (65 <= args.blocked_goals <= 512):
        parser.error("--blocked-goals must be 65..512")
    if args.report.resolve().is_relative_to(ROOT):
        parser.error("--report must be outside the ANIMA repository")
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                      cwd=ROOT, text=True).strip()
        git_status = subprocess.check_output(["git", "status", "--porcelain"],
                                             cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        parser.error(f"Cannot determine Git snapshot: {error}")
    print(f"CORE_ENDURANCE_SHA {sha}", flush=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="anima-core-endurance-") as tmp:
        root = Path(tmp)
        runs = endurance(
            root / "long_run", episodes=args.episodes, seed=args.seed,
            restart_every=args.restart_every, max_noise=args.max_noise,
            checkpoint_every=args.checkpoint_every,
        )
        backlog = scheduler_backlog(root / "scheduler", blocked=args.blocked_goals)
    report = {
        "schema": "anima.core.endurance-gate/0.1",
        "commit": sha,
        "checkout_clean": not git_status,
        "overall_elapsed_seconds": round(time.monotonic() - started, 3),
        "requirements": {
            "no_duplicate_effects": True,
            "independent_proof_for_every_goal": True,
            "no_scheduler_starvation": True,
            "stable_identity_and_recovery": True,
        },
        "endurance": runs,
        "scheduler_backlog": backlog,
        "limits": [
            "One in-process virtual door, not an arbitrary multi-tool environment",
            "Performance timings are observations, not machine-independent limits",
            "Peak RSS measures parent Python process, not tool workers",
            "No physical power-loss, hardware-fsync or multihost guarantees",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(f"CORE_ENDURANCE_REPORT {args.report}", flush=True)
    print("CORE_ENDURANCE_GATE_PASS", flush=True)


if __name__ == "__main__":
    main()
