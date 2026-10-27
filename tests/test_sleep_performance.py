import pytest

from anima.sleep.contracts import SourceRef
from anima.sleep.large_data import MIB
from scripts.benchmark_stage3 import (
    MODES,
    asset_id,
    candidate_set,
    parse_sizes,
    public_id,
    run_checkpoint_case,
    run_large_source_case,
    run_provenance_case,
    run_selection_case,
)


def _assert_measurement(result, mode, count):
    assert result["mode"] == mode
    assert result["work_item_count"] == count
    assert result["latency"]["samples"] >= 1
    assert result["latency"]["p95_ms"] >= result["latency"]["p50_ms"] >= 0
    assert result["cpu"]["p95_ms"] >= result["cpu"]["p50_ms"] >= 0
    assert result["memory"]["process_peak_rss_mb"] > 0
    assert result["storage"]["total_mb"] > 0


def test_public_id_and_candidate_set_are_deterministic():
    assert public_id("asset_", 42) == public_id("asset_", 42)
    source = SourceRef("asset", asset_id(42))
    assert source.source_id == asset_id(42)

    first = candidate_set(12)
    second = candidate_set(12)
    assert first == second
    assert len(first) == 12
    assert len({candidate.source_ref.source_id for candidate in first}) == 12


def test_selection_benchmark_uses_complete_seeded_queue(tmp_path):
    result = run_selection_case(12, samples=2, workdir=tmp_path / "selection")

    _assert_measurement(result, "selection", 12)
    assert result["details"]["selected"] == 12
    assert result["details"]["reused"] == 12
    assert result["details"]["considered"] == 12
    assert result["throughput_per_s"] > 0


def test_checkpoint_benchmark_reports_commit_lookup_and_history(tmp_path):
    result = run_checkpoint_case(
        12,
        samples=2,
        history_depth=3,
        workdir=tmp_path / "checkpoint",
    )

    _assert_measurement(result, "checkpoint", 12)
    assert result["details"]["history_depth_before"] == 3
    assert result["details"]["history_depth_after"] == 5
    assert result["details"]["latest_lookup_latency"]["samples"] == 2
    assert result["details"]["history_list_latency"]["samples"] == 2


def test_provenance_benchmark_commits_real_derived_results(tmp_path):
    result = run_provenance_case(
        12,
        samples=2,
        workdir=tmp_path / "provenance",
    )

    _assert_measurement(result, "provenance", 12)
    assert result["details"]["derived_results"] == 2
    assert result["details"]["sources_per_result"] == 1
    assert result["details"]["transformation_steps"] == 2


def test_large_source_benchmark_measures_interrupt_and_direct_resume(tmp_path):
    result = run_large_source_case(
        logical_size_bytes=8 * MIB,
        chunk_size_bytes=1 * MIB,
        interrupt_after=3,
        workdir=tmp_path / "large",
    )

    _assert_measurement(result, "large_source", 1)
    assert result["details"]["chunk_count"] == 8
    assert result["details"]["first_run"]["processed_chunks"] == 3
    assert result["details"]["resume"]["resumed_from_sequence"] == 3
    assert result["details"]["resume"]["processed_chunks"] == 5
    assert result["throughput_per_s"] > 0


def test_parse_sizes_preserves_order_and_removes_duplicates():
    assert parse_sizes(["1000", "100", "1000"]) == [1000, 100]
    assert set(MODES) == {"selection", "checkpoint", "provenance"}


@pytest.mark.parametrize(
    "call",
    [
        lambda tmp_path: run_selection_case(0, workdir=tmp_path / "a"),
        lambda tmp_path: run_checkpoint_case(1, samples=0, workdir=tmp_path / "b"),
        lambda tmp_path: run_provenance_case(1, samples=2, workdir=tmp_path / "c"),
        lambda tmp_path: run_large_source_case(
            logical_size_bytes=2 * MIB,
            chunk_size_bytes=1 * MIB,
            interrupt_after=2,
            workdir=tmp_path / "d",
        ),
    ],
)
def test_invalid_benchmark_inputs_are_rejected(tmp_path, call):
    with pytest.raises(ValueError):
        call(tmp_path)
