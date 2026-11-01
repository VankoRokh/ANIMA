from scripts.run_formal_policy_resolution_experiment import (
    BASE_TASK,
    CASES,
    DETERMINISTIC_RESULT,
    FAST_REQUIRED,
    POLICY_ACTION_PRIORITY,
    _priority_policy_winner,
    resolve_formal_action_policy,
    run_experiment,
)


def test_m1_case_matrix_passes_without_false_determinism():
    result = run_experiment()
    summary = result["summary"]

    assert result["production_modified"] is False
    assert result["llm_enabled"] is False
    assert summary["passed"] == summary["total"] == 3
    assert summary["pass_rate"] == 1.0
    assert summary["deterministic_results"] == 1
    assert summary["fast_required"] == 2
    assert summary["false_deterministic"] == 0
    assert summary["missed_deterministic"] == 0


def test_formal_priority_resolves_unique_safe_action_preference():
    case = next(item for item in CASES if item["id"] == "formal_policy_unique_choice")
    result = resolve_formal_action_policy(case["task"])

    assert result["route"] == DETERMINISTIC_RESULT
    assert result["value"] == "CONTINUE"
    assert result["reason"] == "formal_policies_agree_on_unique_action"
    assert result["derived"]["constraints"]["valid_options"] == [
        "CONTINUE",
        "CONNECT_CHARGER",
    ]


def test_missing_policy_preserves_cognitive_choice_for_fast():
    case = next(item for item in CASES if item["id"] == "no_policy_requires_fast")
    result = resolve_formal_action_policy(case["task"])

    assert result["route"] == FAST_REQUIRED
    assert result["value"] is None
    assert result["reason"] == "no_formal_policy"
    assert result["candidates"] == ["CONTINUE", "CONNECT_CHARGER"]


def test_conflicting_formal_policies_do_not_guess_precedence():
    case = next(item for item in CASES if item["id"] == "conflicting_policies_require_fast")
    result = resolve_formal_action_policy(case["task"])

    assert result["route"] == FAST_REQUIRED
    assert result["value"] is None
    assert result["reason"] == "formal_policy_conflict"
    assert result["derived"]["unique_policy_winners"] == [
        "CONNECT_CHARGER",
        "CONTINUE",
    ]


def test_policy_cannot_restore_action_rejected_by_hard_constraints():
    task = {
        **BASE_TASK,
        "policies": [
            {
                "policy_id": "prefer_shutdown",
                "type": POLICY_ACTION_PRIORITY,
                "priority": ["SHUTDOWN", "CONNECT_CHARGER", "CONTINUE"],
            }
        ],
    }
    result = resolve_formal_action_policy(task)

    assert "SHUTDOWN" not in result["derived"]["constraints"]["valid_options"]
    assert result["route"] == DETERMINISTIC_RESULT
    assert result["value"] == "CONNECT_CHARGER"


def test_incomplete_priority_policy_fails_closed_to_fast():
    task = {
        **BASE_TASK,
        "policies": [
            {
                "policy_id": "incomplete",
                "type": POLICY_ACTION_PRIORITY,
                "priority": ["CONTINUE"],
            }
        ],
    }
    result = resolve_formal_action_policy(task)

    assert result["route"] == FAST_REQUIRED
    assert result["value"] is None
    assert result["reason"] == "unsupported_or_incomplete_formal_policy"


def test_priority_helper_requires_complete_candidate_coverage():
    policy = {
        "policy_id": "incomplete",
        "type": POLICY_ACTION_PRIORITY,
        "priority": ["CONTINUE"],
    }

    assert _priority_policy_winner(policy, ["CONTINUE", "CONNECT_CHARGER"]) is None
