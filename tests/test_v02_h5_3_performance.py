"""H5.3 synthetic benchmark harness contract (no production data).

All end-to-end tests run against temporary, disposable Memory and Raw files.
The 160/640 measurement itself is opt-in CLI work, not part of pytest.
"""

import json
import sys

import pytest

from labs import v02_h5_performance as perf


def test_h5_3_nearest_rank_p95_and_median_are_explicit():
    assert perf.percentile_nearest_rank(list(range(1, 101)), 95) == 95
    assert perf.percentile_nearest_rank([8, 2, 4, 6], 50) == 4
    measured = perf.latency_summary([
        1_000_000, 2_000_000, 4_000_000, 10_000_000,
    ])
    assert measured == {
        "samples": 4,
        "p50_ms": 3.0,
        "p95_ms": 10.0,
        "max_ms": 10.0,
    }


def test_h5_3_invalid_statistics_refuse_fabricated_data():
    with pytest.raises(ValueError, match="At least one sample"):
        perf.percentile_nearest_rank([], 95)
    with pytest.raises(ValueError, match="Percentile"):
        perf.percentile_nearest_rank([1], 0)
    with pytest.raises(ValueError, match="No latency samples"):
        perf.latency_summary([])


def test_h5_3_case_validates_bounded_event_count():
    for invalid in (0, 1, 7, 5001, 10.5, True, "160"):
        with pytest.raises(ValueError, match="event_count"):
            perf.run_case(invalid)


def test_h5_3_tiny_end_to_end_case_has_provenance_and_idempotence():
    case = perf.run_case(12)
    assert case["schema"] == perf.SCHEMA
    assert case["event_count"] == 12
    assert case["processing_finalized"] == 12
    assert case["source_links"] == 12
    assert sum(case["processing_actions"].values()) == 12
    assert 1 <= case["memory_count"] <= 12
    assert case["throughput_events_s"] > 0
    assert case["ingest_wall_s"] > 0
    for metric in ("append", "process", "event_search",
                   "memory_search", "context_build"):
        assert case[metric]["samples"] >= 5
        assert case[metric]["max_ms"] >= case[metric]["p95_ms"]
        assert case[metric]["p95_ms"] >= case[metric]["p50_ms"]
    for path in ("memory.db", "event_index.db", "events.jsonl"):
        assert case["storage_bytes"][path] > 0
    assert case["index_initial_sync_ms"] > 0
    assert case["recovery_first_ms"] > 0
    assert case["recovery_repeat_ms"] > 0
    if sys.platform == "linux":
        assert case["peak_rss_mib"] > 0


def test_h5_3_worker_isolated_subprocess_emits_one_record():
    case = perf._run_worker(8, timeout=120)
    assert case["event_count"] == 8
    assert case["processing_finalized"] == 8
    assert case["source_links"] == 8
    assert case["event_search"]["samples"] == perf.QUERY_SAMPLES


def test_h5_3_report_compares_growth_without_inventing_latency_slo(
    monkeypatch,
):
    def fake_worker(count, _timeout):
        return {
            "event_count": count,
            "process": {"p95_ms": count / 20},
            "recovery_first_ms": count / 4,
        }

    monkeypatch.setattr(
        perf, "_run_worker", lambda count, timeout: fake_worker(count, timeout)
    )
    monkeypatch.setattr(
        perf, "_git_snapshot",
        lambda: {
            "head": "a" * 40,
            "branch": "work/h5",
            "dirty": False,
        },
    )
    result = perf.build_report([640, 160])
    assert result["measurement_status"] == "MEASURED_NO_RELEASE_SLO"
    assert [c["event_count"] for c in result["scenarios"]] == [640, 160]
    growth = result["growth"]
    assert len(growth) == 1
    assert growth[0]["from_events"] == 160
    assert growth[0]["to_events"] == 640
    assert growth[0]["size_ratio"] == 4
    assert growth[0]["process_p95_ratio"] == 4
    assert growth[0]["recovery_first_ratio"] == 4
    assert any("threshold" in line for line in result["limits"])


def test_h5_3_report_rejects_duplicates_and_unbounded_runs():
    for invalid in ([], [160, 160], [1], [6000], [True]):
        with pytest.raises(ValueError):
            perf.build_report(invalid)
    with pytest.raises(ValueError, match="Timeout"):
        perf.build_report([160], timeout=0)


def test_h5_3_cli_output_file_refuses_existing_evidence_overwrite(
    tmp_path, monkeypatch,
):
    output = tmp_path / "h53.json"
    sentinel = '{"immutable":true}\n'
    output.write_text(sentinel, encoding="utf-8")
    monkeypatch.setattr(
        perf, "build_report",
        lambda _counts, timeout: {
            "measurement_status": "MEASURED_NO_RELEASE_SLO"
        },
    )
    with pytest.raises(FileExistsError):
        perf.main(["--events", "8", "--output", str(output)])
    assert output.read_text(encoding="utf-8") == sentinel
