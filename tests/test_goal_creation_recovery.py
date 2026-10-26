import pytest

from tests.harness import AnimaTestHarness


T0 = "2026-10-26T10:00:00+00:00"


def _goal_kwargs():
    return {
        "source": "test",
        "priority": 2.0,
        "description": "Idempotent goal creation",
        "success_criterion": "created once",
        "reason": "goal creation replay test",
        "source_id": "goal_create_once",
        "timestamp": T0,
    }


def test_replayed_goal_creation_returns_same_goal(tmp_path):
    anima = AnimaTestHarness(tmp_path)
    kwargs = _goal_kwargs()

    first = anima.runtime.create_goal(**kwargs)
    second = anima.runtime.create_goal(**kwargs)

    assert second["id"] == first["id"]
    assert len(anima.internal_state.goals.list_goals()) == 1
    assert len(
        anima.internal_state.goals.list_goal_transitions(goal_id=first["id"])
    ) == 1
    assert anima.snapshot()["internal_state"]["recovery"] == {
        "processing_operations": 0,
        "completed_operations": 1,
    }


def test_restart_recovers_goal_creation_after_journal_write(tmp_path, monkeypatch):
    anima = AnimaTestHarness(tmp_path)
    kwargs = _goal_kwargs()
    kwargs["source_id"] = "goal_create_pending"
    kwargs["description"] = "Recover pending goal creation"
    kwargs["reason"] = "simulate crash after journal write"

    def fail_create_goal(**kwargs):
        raise RuntimeError("simulated crash before Goal insert")

    monkeypatch.setattr(
        anima.internal_state.goals,
        "create_goal",
        fail_create_goal,
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        anima.runtime.create_goal(**kwargs)

    assert anima.internal_state.goals.goal_count() == 0
    assert anima.snapshot()["internal_state"]["recovery"] == {
        "processing_operations": 1,
        "completed_operations": 0,
    }

    recovered = AnimaTestHarness(tmp_path)
    goals = recovered.internal_state.goals.list_goals()

    assert len(goals) == 1
    assert goals[0]["source"] == "test"
    assert goals[0]["description"] == "Recover pending goal creation"
    assert len(
        recovered.internal_state.goals.list_goal_transitions(goal_id=goals[0]["id"])
    ) == 1
    assert recovered.snapshot()["internal_state"]["recovery"] == {
        "processing_operations": 0,
        "completed_operations": 1,
    }
