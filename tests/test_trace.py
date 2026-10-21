import pytest

from anima.diagnostics.trace import DiagnosticTrace


def test_trace_records_messages():
    trace = DiagnosticTrace()

    trace.record("runtime: wake requested")
    trace.record("event: wake processed")

    entries = trace.entries()

    assert len(entries) == 2

    assert (
        entries[0]["message"]
        == "runtime: wake requested"
    )

    assert (
        entries[1]["message"]
        == "event: wake processed"
    )

    lines = trace.lines()

    assert "runtime: wake requested" in lines[0]
    assert "event: wake processed" in lines[1]


def test_trace_rejects_invalid_messages():
    trace = DiagnosticTrace()

    with pytest.raises(
        ValueError,
        match="must be a string",
    ):
        trace.record(123)

    with pytest.raises(
        ValueError,
        match="must not be empty",
    ):
        trace.record("   ")


def test_trace_can_be_cleared():
    trace = DiagnosticTrace()

    trace.record("test message")

    assert len(trace.entries()) == 1

    trace.clear()

    assert trace.entries() == []


from tests.harness import AnimaTestHarness


def test_runtime_produces_human_readable_trace(
    tmp_path,
):
    anima = AnimaTestHarness(tmp_path)

    anima.runtime.wake()
    anima.runtime.user_input("hello")
    anima.runtime.sleep()

    messages = [
        entry["message"]
        for entry in anima.trace.entries()
    ]

    assert messages == [
        "runtime: wake requested",
        "event: wake processed, memory=skipped",
        "runtime: user_input received",
        "event: user_input processed, memory=stored",
        "runtime: sleep requested",
        "event: sleep processed, memory=skipped",
        "runtime: sleeping",
    ]


def test_trace_reports_skipped_sleep(tmp_path):
    anima = AnimaTestHarness(tmp_path)

    anima.runtime.wake()
    anima.runtime.sleep()
    anima.runtime.sleep()

    messages = [
        entry["message"]
        for entry in anima.trace.entries()
    ]

    assert (
        messages[-1]
        == "runtime: sleep skipped, already sleeping"
    )