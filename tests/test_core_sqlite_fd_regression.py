"""Regression: SQLite connections must close without relying on cyclic GC.

Linux-only /proc/self/fd assertion; no global resource limits are modified.
The test cannot prove absence of every fd leak, only these bounded pathways.
"""

import gc
from pathlib import Path

import pytest

from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore
from tests.test_core_p4c_release import _run_seeded


def _fds():
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():
        pytest.skip("Linux /proc/self/fd required for file-descriptor regression")
    return len(list(fd_dir.iterdir()))


def test_goal_store_reads_release_sqlite_connections_without_gc(tmp_path):
    state = InternalStateStore(tmp_path / "internal_state.db")
    goals = GoalStore(state)
    created = goals.create_goal(
        source="test", priority=1.0, description="FD lifecycle",
        success_criterion="No connection leakage", reason="Regression probe",
    )
    goal_id = created["id"]

    gc.collect()
    before = _fds()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(72):
            assert goals.get_goal(goal_id)["status"] == "active"
            assert len(goals.list_goals()) == 1
            assert len(goals.list_active_goals()) == 1
            assert len(goals.list_goal_transitions(goal_id=goal_id)) == 1
            assert goals.goal_count() == 1
        after = _fds()
    finally:
        if was_enabled:
            gc.enable()
        gc.collect()

    assert after - before <= 4, (
        f"GoalStore leaked {after - before} file descriptors across 360 reads"
    )


def test_p4c_rebuilds_and_episodes_do_not_accumulate_fds_without_gc(tmp_path):
    gc.collect()
    before = _fds()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        result = _run_seeded(
            tmp_path / "fd_endurance", seed=7, episodes=8, restart_every=3,
        )
        assert result["completed"] == 8
        assert result["pending"] == 0
        after = _fds()
    finally:
        if was_enabled:
            gc.enable()
        gc.collect()

    assert after - before <= 12, (
        f"P4-C scenario leaked {after - before} descriptors across cold restarts"
    )
