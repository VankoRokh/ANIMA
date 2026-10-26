import pytest

from anima.internal_state.choice_engine import Candidate, ChoiceEngine
from anima.internal_state.goals import GoalStore
from anima.internal_state.store import InternalStateStore
from scripts.benchmark_stage2 import (
    HISTORY_LIMIT,
    MODES,
    _seed_state,
    base_evaluate,
    candidate_set,
    modifier_evaluate,
    run_case,
    run_matrix,
)


def _engine(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    goals = GoalStore(store)
    _seed_state(store)
    goal = goals.create_goal(
        source="test",
        priority=1.0,
        description="benchmark equivalence",
        success_criterion="choice measured",
        reason="test setup",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    return store, ChoiceEngine(store, goal_store=goals), goal["id"]


def test_candidate_set_is_deterministic_and_unique():
    first = candidate_set(100)
    second = candidate_set(100)

    assert first == second
    assert len(first) == 100
    assert len({item.candidate_id for item in first}) == 100
    assert all(isinstance(item, Candidate) for item in first)


def test_base_evaluation_is_deterministic():
    candidates = candidate_set(10)

    first = base_evaluate(candidates)
    second = base_evaluate(candidates)

    assert first == second
    assert len(first["scores"]) == 10


def test_modifier_mode_matches_production_choice_scores(tmp_path):
    _, engine, goal_id = _engine(tmp_path)
    candidates = candidate_set(10)
    snapshot = engine._state_snapshot()

    benchmark = modifier_evaluate(engine, candidates, snapshot)
    production = engine.choose(goal_id, candidates)

    production_scores = {
        item["candidate_id"]: item["final_score"]
        for item in production["evaluations"]
    }
    assert benchmark["selected_candidate_id"] == production["selected_candidate_id"]
    assert {
        candidate_id: score
        for candidate_id, score in benchmark["scores"]
    } == pytest.approx(production_scores)


@pytest.mark.parametrize("mode", MODES)
def test_run_case_reports_latency_cpu_and_memory(tmp_path, mode):
    result = run_case(
        3,
        mode,
        samples=2,
        warmup=0,
        workdir=tmp_path / mode,
    )

    assert result["candidate_count"] == 3
    assert result["mode"] == mode
    assert result["latency"]["samples"] == 2
    assert result["cpu"]["samples"] == 2
    assert result["latency"]["p95_ms"] >= result["latency"]["p50_ms"] >= 0
    assert result["cpu"]["p95_ms"] >= result["cpu"]["p50_ms"] >= 0
    assert result["memory"]["python_allocation_peak_kib"] >= 0
    assert result["memory"]["process_peak_rss_mb"] > 0


def test_full_mode_reads_bounded_history(tmp_path):
    result = run_case(
        2,
        "full_trace_history",
        samples=1,
        warmup=0,
        workdir=tmp_path / "full",
    )

    assert result["history_limit"] == HISTORY_LIMIT
    assert result["history_records"] == HISTORY_LIMIT


def test_run_matrix_covers_required_modes_and_counts(tmp_path):
    results = run_matrix(
        (2, 10),
        samples=1,
        warmup=0,
        workdir=tmp_path / "matrix",
    )

    assert {
        (item["candidate_count"], item["mode"])
        for item in results
    } == {
        (count, mode)
        for count in (2, 10)
        for mode in MODES
    }


@pytest.mark.parametrize(
    ("candidate_count", "mode", "samples", "warmup"),
    [
        (0, "base", 1, 0),
        (2, "unknown", 1, 0),
        (2, "base", 0, 0),
        (2, "base", 1, -1),
    ],
)
def test_invalid_benchmark_inputs_are_rejected(
    tmp_path,
    candidate_count,
    mode,
    samples,
    warmup,
):
    with pytest.raises(ValueError):
        run_case(
            candidate_count,
            mode,
            samples=samples,
            warmup=warmup,
            workdir=tmp_path / f"invalid-{candidate_count}-{mode}-{samples}-{warmup}",
        )
