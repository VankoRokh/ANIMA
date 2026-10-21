import pytest

from anima.diagnostics.metrics import DiagnosticMetrics


def test_metrics_measure_operation():
    metrics = DiagnosticMetrics()

    result = metrics.measure(
        "example",
        lambda: "done",
    )

    assert result == "done"

    timings = metrics.timings()

    assert len(timings) == 1
    assert timings[0]["name"] == "example"

    assert (
        timings[0]["duration_seconds"]
        >= 0
    )


def test_metrics_report_process_resources():
    metrics = DiagnosticMetrics()

    resources = metrics.resources()

    assert resources["cpu_user_seconds"] >= 0
    assert resources["cpu_system_seconds"] >= 0
    assert resources["max_rss_kb"] > 0


def test_metrics_snapshot_is_structured():
    metrics = DiagnosticMetrics()

    metrics.measure(
        "test",
        lambda: None,
    )

    snapshot = metrics.snapshot()

    assert "timings" in snapshot
    assert "resources" in snapshot

    assert len(snapshot["timings"]) == 1


def test_metrics_reject_invalid_measurements():
    metrics = DiagnosticMetrics()

    with pytest.raises(
        ValueError,
        match="Metric name must be a string",
    ):
        metrics.measure(
            123,
            lambda: None,
        )

    with pytest.raises(
        ValueError,
        match="Metric name must not be empty",
    ):
        metrics.measure(
            "   ",
            lambda: None,
        )

    with pytest.raises(
        ValueError,
        match="Measured operation must be callable",
    ):
        metrics.measure(
            "test",
            None,
        )


def test_metrics_can_be_cleared():
    metrics = DiagnosticMetrics()

    metrics.measure(
        "test",
        lambda: None,
    )

    assert len(metrics.timings()) == 1

    metrics.clear()

    assert metrics.timings() == []


from tests.harness import AnimaTestHarness


def test_runtime_collects_lifecycle_metrics(
    tmp_path,
):
    anima = AnimaTestHarness(tmp_path)

    anima.runtime.wake()
    anima.runtime.user_input("hello")
    anima.runtime.sleep()

    timings = anima.metrics.timings()

    assert [
        timing["name"]
        for timing in timings
    ] == [
        "runtime.wake",
        "runtime.user_input",
        "runtime.sleep",
    ]

    assert all(
        timing["duration_seconds"] >= 0
        for timing in timings
    )

    snapshot = anima.metrics.snapshot()

    assert (
        snapshot["resources"]["max_rss_kb"]
        > 0
    )

def test_runtime_snapshot_contains_metrics(
    tmp_path,
):
    anima = AnimaTestHarness(tmp_path)

    anima.runtime.wake()
    anima.runtime.user_input("hello")
    anima.runtime.sleep()

    snapshot = anima.runtime.snapshot()

    metrics = snapshot["diagnostics"]["metrics"]

    assert metrics is not None

    assert len(metrics["timings"]) == 3

    assert (
        metrics["resources"]["max_rss_kb"]
        > 0
    )