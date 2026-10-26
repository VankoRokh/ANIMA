import pytest

from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore


GOAL_ID = "goal_11111111-1111-4111-8111-111111111111"
SECOND_GOAL_ID = "goal_66666666-6666-4666-8666-666666666666"
CREATE_TRANSITION_ID = "gt_22222222-2222-4222-8222-222222222222"
BLOCK_TRANSITION_ID = "gt_33333333-3333-4333-8333-333333333333"
RESUME_TRANSITION_ID = "gt_44444444-4444-4444-8444-444444444444"
FINAL_TRANSITION_ID = "gt_55555555-5555-4555-8555-555555555555"
TIMESTAMP_0 = "2026-10-26T17:00:00+00:00"
TIMESTAMP_1 = "2026-10-26T17:01:00+00:00"
TIMESTAMP_2 = "2026-10-26T17:02:00+00:00"
TIMESTAMP_3 = "2026-10-26T17:03:00+00:00"


def make_goal_store(tmp_path):
    internal_state = InternalStateStore(tmp_path / "internal_state.db")
    return internal_state, GoalStore(internal_state)


def create_goal(goal_store, **overrides):
    values = {
        "source": "external",
        "priority": 2.0,
        "description": "Complete the controlled task",
        "success_criterion": "The expected result is independently verified",
        "reason": "External task accepted",
        "timestamp": TIMESTAMP_0,
        "public_id": GOAL_ID,
        "transition_id": CREATE_TRANSITION_ID,
    }
    values.update(overrides)
    return goal_store.create_goal(**values)


def test_goal_creation_is_active_and_records_initial_transition(tmp_path):
    _, goals = make_goal_store(tmp_path)

    goal = create_goal(goals)
    history = goals.list_goal_transitions(goal_id=GOAL_ID)

    assert goal["status"] == "active"
    assert goal["priority"] == 2.0
    assert goal["resolved_at"] is None
    assert goal["resolution_reason"] is None
    assert history == [
        {
            "id": CREATE_TRANSITION_ID,
            "goal_id": GOAL_ID,
            "timestamp": TIMESTAMP_0,
            "from_status": None,
            "to_status": "active",
            "source_id": None,
            "reason": "External task accepted",
        }
    ]


def test_goal_block_resume_complete_lifecycle_is_causal(tmp_path):
    _, goals = make_goal_store(tmp_path)
    create_goal(goals)

    goals.transition_goal(
        GOAL_ID,
        to_status="blocked",
        reason="Required input is unavailable",
        timestamp=TIMESTAMP_1,
        transition_id=BLOCK_TRANSITION_ID,
    )
    goals.transition_goal(
        GOAL_ID,
        to_status="active",
        reason="Required input became available",
        timestamp=TIMESTAMP_2,
        transition_id=RESUME_TRANSITION_ID,
    )
    completed = goals.transition_goal(
        GOAL_ID,
        to_status="completed",
        reason="Success criterion verified",
        timestamp=TIMESTAMP_3,
        transition_id=FINAL_TRANSITION_ID,
    )

    assert completed["status"] == "completed"
    assert completed["resolved_at"] == TIMESTAMP_3
    assert completed["resolution_reason"] == "Success criterion verified"
    assert [
        item["to_status"]
        for item in goals.list_goal_transitions(goal_id=GOAL_ID)
    ] == ["active", "blocked", "active", "completed"]


def test_terminal_goal_cannot_be_reactivated(tmp_path):
    _, goals = make_goal_store(tmp_path)
    create_goal(goals)
    goals.transition_goal(
        GOAL_ID,
        to_status="cancelled",
        reason="Owner cancelled the task",
        timestamp=TIMESTAMP_1,
        transition_id=BLOCK_TRANSITION_ID,
    )

    with pytest.raises(ValueError, match="Invalid Goal transition"):
        goals.transition_goal(
            GOAL_ID,
            to_status="active",
            reason="Terminal state must remain terminal",
            timestamp=TIMESTAMP_2,
            transition_id=RESUME_TRANSITION_ID,
        )


def test_same_status_transition_is_rejected(tmp_path):
    _, goals = make_goal_store(tmp_path)
    create_goal(goals)

    with pytest.raises(ValueError, match="active -> active"):
        goals.transition_goal(
            GOAL_ID,
            to_status="active",
            reason="No actual lifecycle change",
            timestamp=TIMESTAMP_1,
            transition_id=BLOCK_TRANSITION_ID,
        )

    assert goals.get_goal(GOAL_ID)["status"] == "active"
    assert len(goals.list_goal_transitions(goal_id=GOAL_ID)) == 1


def test_older_goal_transition_rolls_back(tmp_path):
    _, goals = make_goal_store(tmp_path)
    create_goal(
        goals,
        timestamp=TIMESTAMP_1,
    )

    with pytest.raises(ValueError, match="earlier"):
        goals.transition_goal(
            GOAL_ID,
            to_status="blocked",
            reason="Out-of-order history",
            timestamp=TIMESTAMP_0,
            transition_id=BLOCK_TRANSITION_ID,
        )

    assert goals.get_goal(GOAL_ID)["status"] == "active"
    assert len(goals.list_goal_transitions(goal_id=GOAL_ID)) == 1


def test_duplicate_goal_transition_id_rolls_back_goal_update(tmp_path):
    _, goals = make_goal_store(tmp_path)
    create_goal(goals)
    goals.transition_goal(
        GOAL_ID,
        to_status="blocked",
        reason="Waiting",
        timestamp=TIMESTAMP_1,
        transition_id=BLOCK_TRANSITION_ID,
    )

    with pytest.raises(ValueError, match="Cannot apply GoalTransition"):
        goals.transition_goal(
            GOAL_ID,
            to_status="active",
            reason="Must roll back because transition ID already exists",
            timestamp=TIMESTAMP_2,
            transition_id=BLOCK_TRANSITION_ID,
        )

    assert goals.get_goal(GOAL_ID)["status"] == "blocked"
    assert len(goals.list_goal_transitions(goal_id=GOAL_ID)) == 2


def test_duplicate_goal_id_does_not_leave_extra_creation_history(tmp_path):
    _, goals = make_goal_store(tmp_path)
    create_goal(goals)

    with pytest.raises(ValueError, match="Cannot create Goal"):
        create_goal(
            goals,
            transition_id=FINAL_TRANSITION_ID,
        )

    assert goals.goal_count() == 1
    assert len(goals.list_goal_transitions(goal_id=GOAL_ID)) == 1


def test_only_active_goals_are_actionable_baseline(tmp_path):
    _, goals = make_goal_store(tmp_path)
    create_goal(goals)

    goals.create_goal(
        source="system",
        priority=5.0,
        description="Blocked maintenance task",
        success_criterion="Maintenance result verified",
        reason="System task created",
        timestamp=TIMESTAMP_0,
        public_id=SECOND_GOAL_ID,
        transition_id=FINAL_TRANSITION_ID,
    )
    goals.transition_goal(
        SECOND_GOAL_ID,
        to_status="blocked",
        reason="Dependency unavailable",
        timestamp=TIMESTAMP_1,
        transition_id=RESUME_TRANSITION_ID,
    )

    assert [goal["id"] for goal in goals.list_active_goals()] == [GOAL_ID]


def test_goal_priority_and_timestamp_validation(tmp_path):
    _, goals = make_goal_store(tmp_path)

    with pytest.raises(ValueError, match="priority"):
        create_goal(
            goals,
            priority=float("nan"),
        )

    with pytest.raises(ValueError, match="UTC offset"):
        create_goal(
            goals,
            public_id=SECOND_GOAL_ID,
            transition_id=FINAL_TRANSITION_ID,
            timestamp="2026-10-26T17:00:00",
        )


def test_goal_store_reopens_with_lifecycle_history(tmp_path):
    database = tmp_path / "internal_state.db"
    first_state = InternalStateStore(database)
    first_goals = GoalStore(first_state)
    create_goal(
        first_goals,
        source="system",
    )
    first_goals.transition_goal(
        GOAL_ID,
        to_status="blocked",
        reason="Waiting for dependency",
        timestamp=TIMESTAMP_1,
        transition_id=BLOCK_TRANSITION_ID,
    )

    reopened_state = InternalStateStore(database)
    reopened_goals = GoalStore(reopened_state)

    assert reopened_goals.get_goal(GOAL_ID)["status"] == "blocked"
    assert len(reopened_goals.list_goal_transitions(goal_id=GOAL_ID)) == 2
