"""H5.3b diagnosis regression tests; only disposable benchmark fixtures.

The 160/640 x 3 measured runs are CLI tasks, not pytest dependencies.
"""

from pathlib import Path

import pytest

from labs import v02_h5_scaling_diagnostics as scaling


def test_h53b_streams_define_independent_text_anchors_without_entity_claims():
    first = scaling.synthetic_event(1, 2)
    second = scaling.synthetic_event(2, 2)
    third = scaling.synthetic_event(3, 2)
    assert first.payload["text"].startswith("h53group00:")
    assert second.payload["text"].startswith("h53group01:")
    assert third.payload["text"].startswith("h53group00:")
    assert first.references == second.references == []
    assert len({first.event_id, second.event_id, third.event_id}) == 3


def test_h53b_single_stream_preserves_original_h53_workload():
    original = scaling.synthetic_event(17, 1)
    assert original.payload["text"] == (
        "h53perf sensor batch1 "
        "reading000017 calibration status verified on synthetic rig"
    )


@pytest.mark.parametrize("streams", [1, 2])
def test_h53b_disposable_case_preserves_raw_and_memory_integrity(streams):
    case = scaling.measure_case(12, streams)
    assert case["count"] == 12
    assert case["streams"] == streams
    assert case["source_links"] == 12
    assert 1 <= case["memory_count"] <= 12
    assert case["false_cross_group_memory_count"] == 0
    assert case["raw_scans_total"] >= 12
    assert case["raw_scans_per_event_p50"] >= 1
    assert case["throughput_events_s"] > 0
    assert case["recovery_ms"] > 0
    for name in ("raw_scan", "raw_guard", "association", "process"):
        assert case[name]["samples"] >= 12
        assert case[name]["p95_ms"] >= case[name]["p50_ms"]
        assert case[name]["max_ms"] >= case[name]["p95_ms"]


def test_h53b_isolated_worker_returns_measured_evidence():
    result = scaling._worker(8, 2, timeout=60)
    assert result["count"] == 8
    assert result["streams"] == 2
    assert result["source_links"] == 8
    assert result["process"]["samples"] == 8


def test_h53b_report_aggregates_three_independent_repetitions(monkeypatch):
    calls = []

    def fake_worker(count, streams, timeout=300):
        calls.append((count, streams, timeout))
        return {
            "count": count, "streams": streams,
            "process": {"p95_ms": 5 + len(calls)},
            "raw_guard": {"p95_ms": 1},
            "association": {"p95_ms": 2},
            "throughput_events_s": 100 / len(calls),
            "memory_count": streams,
            "false_cross_group_memory_count": 0,
            "extra_memory_fragments": 0,
        }

    monkeypatch.setattr(scaling, "_worker", fake_worker)
    monkeypatch.setattr(scaling, "_git_snapshot", lambda: {
        "head": "f" * 40, "branch": "work/h53b", "dirty": False
    })
    report = scaling.build_report([160], [1, 8], 3)
    assert report["measurement_status"] == "MEASURED_NO_RELEASE_SLO"
    assert report["synthetic_grouping_status"] == (
        "NO_CROSS_GROUP_MERGE_OBSERVED"
    )
    assert len(report["runs"]) == 6
    assert len(report["summary"]) == 2
    assert report["summary"][0]["count"] == 160
    assert report["summary"][0]["process_p95_ms"] == {
        "min": 6, "median": 7, "max": 8
    }
    assert report["summary"][1]["process_p95_ms"] == {
        "min": 9, "median": 10, "max": 11
    }
    assert report["summary"][1]["memory_count_range"] == [8, 8]


def test_h53b_rejects_invalid_profiles_before_worker_start(monkeypatch):
    monkeypatch.setattr(
        scaling, "_worker",
        lambda *_args, **_kw: pytest.fail("Invalid profile launched worker"),
    )
    for counts, streams, repeats in (
        ([], [1], 3),
        ([160, 160], [1], 3),
        ([160], [1, 1], 3),
        ([160], [161], 3),
        ([7], [1], 3),
        ([160], [0], 3),
        ([160], [1], 0),
        ([160], [1], 6),
        ([True], [1], 2),
    ):
        with pytest.raises(ValueError):
            scaling.build_report(counts, streams, repeats)


def test_h53b_does_not_overwrite_previous_measurements(tmp_path, monkeypatch):
    target = tmp_path / "h53b.json"
    sentinel = "SAVED RESULTS\n"
    target.write_text(sentinel, encoding="utf-8")
    monkeypatch.setattr(
        scaling, "build_report",
        lambda *_args, **_kw: {
            "measurement_status": "MEASURED_NO_RELEASE_SLO",
        },
    )
    with pytest.raises(FileExistsError):
        scaling.main(["--events", "8", "--streams", "1",
                      "--repeats", "1", "--output", str(target)])
    assert target.read_text(encoding="utf-8") == sentinel
