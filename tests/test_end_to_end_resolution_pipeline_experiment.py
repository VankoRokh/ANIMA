from types import SimpleNamespace

from anima.cognition.fast_llm import FastLLMCallResult
from scripts.run_deterministic_resolution_boundary_experiment import (
    DETERMINISTIC_RESULT,
    FAST_REQUIRED,
    INSUFFICIENT_DATA,
)
from scripts.run_end_to_end_resolution_pipeline_experiment import (
    CASES,
    evaluate_case,
    project_fast_task,
    run_case,
)


class FakeTransport:
    def __init__(self):
        self.calls = []

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "timeout_seconds": timeout_seconds,
            }
        )
        if "avoid unnecessary charging" in user_prompt:
            text = "RESULT=<CONTINUE>"
        elif "conversation_current" in user_prompt and "Batumi" in user_prompt:
            text = "RESULT=<Batumi>"
        else:
            raise AssertionError("unexpected FAST projection in test")
        return FastLLMCallResult(
            provider="fake",
            model="fake-fast",
            text=text,
            thinking=False,
            latency_ms=1.0,
            input_tokens=10,
            output_tokens=3,
            finish_reason="eos",
        )


def _args():
    return SimpleNamespace(timeout=5.0)


def _case(case_id):
    return next(case for case in CASES if case["id"] == case_id)


def test_corpus_has_all_three_boundary_routes():
    assert {case["expected_route"] for case in CASES} == {
        DETERMINISTIC_RESULT,
        INSUFFICIENT_DATA,
        FAST_REQUIRED,
    }


def test_deterministic_case_never_calls_fast():
    transport = FakeTransport()
    row = run_case(_case("power_insufficient"), transport, _args())
    assert row["boundary"]["route"] == DETERMINISTIC_RESULT
    assert row["final_value"] == "NO"
    assert row["model_called"] is False
    assert row["evaluation"]["passed"] is True
    assert transport.calls == []


def test_insufficient_data_never_calls_fast():
    transport = FakeTransport()
    row = run_case(_case("missing_fact"), transport, _args())
    assert row["boundary"]["route"] == INSUFFICIENT_DATA
    assert row["final_value"] is None
    assert row["model_called"] is False
    assert row["evaluation"]["passed"] is True
    assert transport.calls == []


def test_multiple_safe_actions_calls_fast_once():
    transport = FakeTransport()
    row = run_case(_case("multiple_safe_actions"), transport, _args())
    assert row["boundary"]["route"] == FAST_REQUIRED
    assert row["boundary"]["candidates"] == ["CONTINUE", "CONNECT_CHARGER"]
    assert row["projection"]["candidates"] == ["CONTINUE", "CONNECT_CHARGER"]
    assert row["final_value"] == "CONTINUE"
    assert row["evaluation"]["passed"] is True
    assert len(transport.calls) == 1


def test_conflict_calls_fast_with_only_conflict_evidence():
    transport = FakeTransport()
    row = run_case(_case("conflicting_location"), transport, _args())
    assert row["boundary"]["route"] == FAST_REQUIRED
    assert row["final_value"] == "Batumi"
    assert row["projection"]["task"] == "RESOLVE_CONFLICT"
    assert row["projection"]["candidates"] == ["Tbilisi", "Batumi"]
    assert len(row["projection"]["evidence"]) == 2
    assert row["evaluation"]["passed"] is True
    assert len(transport.calls) == 1


def test_projection_does_not_expose_raw_canonical_task():
    case = _case("multiple_safe_actions")
    boundary = {
        "route": FAST_REQUIRED,
        "value": None,
        "reason": "test",
        "candidates": ["CONTINUE", "CONNECT_CHARGER"],
        "derived": {"projected_battery_after_task_percent": 50.0},
    }
    projection = project_fast_task(case["task"], boundary)
    assert set(projection) == {
        "task",
        "goal",
        "candidates",
        "state",
        "derived",
        "preference",
    }
    assert "options" not in projection
    assert "preserve_active_task" not in projection


def test_evaluator_rejects_wrong_model_call_discipline():
    case = _case("exact_fact")
    boundary = {
        "route": DETERMINISTIC_RESULT,
        "value": "gray",
        "reason": "test",
        "candidates": [],
        "derived": {},
    }
    evaluation = evaluate_case(
        case,
        boundary,
        final_value="gray",
        model_called=True,
    )
    assert evaluation["route_ok"] is True
    assert evaluation["final_ok"] is True
    assert evaluation["model_call_ok"] is False
    assert evaluation["passed"] is False
