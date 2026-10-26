import pytest

from anima.diagnostics.trace import DiagnosticTrace
from tests.harness import AnimaTestHarness


def test_trace_records_messages():
    trace = DiagnosticTrace()

    trace.record("runtime: wake requested")
    trace.record("event: system.wake processed")

    entries = trace.entries()

    assert len(entries) == 2

    assert (
        entries[0]["message"]
        == "runtime: wake requested"
    )

    assert (
        entries[1]["message"]
        == "event: system.wake processed"
    )

    lines = trace.lines()

    assert "runtime: wake requested" in lines[0]
    assert "event: system.wake processed" in lines[1]


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

    assert len(messages) == 10

    assert messages[0] == "runtime: wake requested"
    assert messages[1].startswith("memory_processor: event=ev_")
    assert "action=skip" in messages[1]
    assert "reasons=selection:event_type" in messages[1]
    assert messages[2] == "event: system.wake processed, memory=skip"

    assert messages[3] == "runtime: user_input received"
    assert messages[4].startswith("memory_processor: event=ev_")
    assert "action=create" in messages[4]
    assert "reasons=association:no_candidate" in messages[4]
    assert messages[5] == "event: conversation.user processed, memory=create"

    assert messages[6] == "runtime: sleep requested"
    assert messages[7].startswith("memory_processor: event=ev_")
    assert "action=skip" in messages[7]
    assert "reasons=selection:event_type" in messages[7]
    assert messages[8] == "event: system.sleep processed, memory=skip"
    assert messages[9] == "runtime: sleeping"


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
