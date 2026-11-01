"""Bounded failure accounting for the Stage 5 projected capability."""

from dataclasses import FrozenInstanceError, replace

import pytest

from anima.cognition import CognitivePipeline, FastResult
from anima.cognition.fast_llm import FastLLMBackend, FastLLMCallResult, FastLLMTransportError, _final_answer
from anima.cognition.pipeline import BackendFailureClassification as Failure
from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask


def task(operation="OPEN", **kwargs):
    return CanonicalTask("audit_task", "audit_source", operation, **kwargs)


class Backend:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0
        self.pipeline = None

    def complete_projected(self, request):
        self.calls += 1
        audit = self.pipeline.backend_audits[-1]
        assert audit.backend_attempts == 1
        assert audit.backend_completions == 0
        assert not audit.terminal_failure
        if self.error:
            raise self.error
        return FastResult("answer")


def stack(backend):
    trace = DiagnosticTrace()
    pipeline = CognitivePipeline(backend=backend, trace=trace)
    backend.pipeline = pipeline
    return pipeline, trace


@pytest.mark.parametrize("value", [
    task("CALCULATE", arguments={"left": 1, "right": 2, "operator": "+"}),
    task("QUERY_FACT", subject="pet", predicate="color"),
    task("CHOOSE_ACTION", candidates=()),
    task(candidates=(), output_contract="candidate"),
])
def test_zero_backend_routes_have_zero_attempts(value):
    backend = Backend()
    pipeline, _ = stack(backend)
    turn = pipeline.process_task(value)
    assert turn.backend_attempts == turn.backend_completions == backend.calls == 0
    assert pipeline.backend_audits == ()


def test_success_records_one_attempt_and_one_completion():
    backend = Backend()
    pipeline, trace = stack(backend)
    turn = pipeline.process_task(task())
    assert turn.backend_attempts == turn.backend_completions == backend.calls == 1
    audit, = pipeline.backend_audits
    assert audit == turn.backend_audit
    assert not audit.terminal_failure
    assert audit.failure_classification is None
    assert (audit.task_id, audit.source_id) == ("audit_task", "audit_source")
    assert "backend_completions=1 terminal_failure=false" in "\n".join(trace.lines())
    with pytest.raises(FrozenInstanceError):
        audit.backend_attempts = 2


@pytest.mark.parametrize("error,classification", [
    (RuntimeError("private payload must not enter audit"), Failure.BACKEND),
    (FastLLMTransportError("connection failed"), Failure.TRANSPORT),
    (TimeoutError("timed out"), Failure.TRANSPORT),
])
def test_backend_exception_is_terminal_classified_propagated_and_not_retried(error, classification):
    backend = Backend(error)
    pipeline, trace = stack(backend)
    with pytest.raises(type(error)) as raised:
        pipeline.process_task(task())
    assert raised.value is error
    audit, = pipeline.backend_audits
    assert backend.calls == audit.backend_attempts == 1
    assert audit.backend_completions == 0
    assert audit.terminal_failure
    assert audit.failure_classification == classification
    assert (audit.task_id, audit.source_id) == ("audit_task", "audit_source")
    lines = "\n".join(trace.lines())
    assert "terminal_failure=true" in lines
    assert f"failure_classification={classification.value}" in lines
    assert "task=audit_task source=audit_source" in lines
    assert "private payload" not in lines


def test_unusable_model_output_has_stable_classification_and_legacy_exception_boundary():
    class Transport:
        def complete(self, **kwargs):
            _final_answer("<think>unfinished model output")
    backend = FastLLMBackend(Transport())
    pipeline = CognitivePipeline(backend=backend)
    with pytest.raises(FastLLMTransportError):
        pipeline.process_task(task())
    audit, = pipeline.backend_audits
    assert audit.failure_classification == Failure.MODEL_OUTPUT
    assert audit.backend_attempts == 1 and audit.backend_completions == 0
    assert audit.terminal_failure
    assert backend.call_history == []


def test_invalid_backend_result_is_terminal_and_still_raises_type_error():
    class Invalid:
        def complete_projected(self, request):
            return "not FastResult"
    pipeline = CognitivePipeline(backend=Invalid())
    with pytest.raises(TypeError, match="FastResult"):
        pipeline.process_task(task())
    audit, = pipeline.backend_audits
    assert audit.failure_classification == Failure.INVALID_BACKEND_RESULT
    assert audit.terminal_failure and audit.backend_completions == 0


def test_successful_call_history_cannot_be_confused_with_attempt_history():
    class Transport:
        def __init__(self): self.calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise FastLLMTransportError("failed second attempt")
            return FastLLMCallResult("fake", "fake-model", "answer", False, 0.)
    transport = Transport()
    backend = FastLLMBackend(transport)
    pipeline = CognitivePipeline(backend=backend)
    first = pipeline.process_task(task())
    with pytest.raises(FastLLMTransportError):
        pipeline.process_task(replace(task(), task_id="second_task", source_id="second_source"))
    audits = pipeline.backend_audits
    assert len(audits) == transport.calls == 2
    assert sum(item.backend_attempts for item in audits) == 2
    assert sum(item.backend_completions for item in audits) == len(backend.call_history) == 1
    assert sum(item.terminal_failure for item in audits) == 1
    assert first.backend_audit == audits[0]
    assert (audits[1].task_id, audits[1].source_id) == ("second_task", "second_source")


def test_invalid_candidate_is_a_completed_backend_call_with_output_validation_error():
    class WrongCandidate:
        def complete_projected(self, request): return FastResult("not-allowed")
    pipeline = CognitivePipeline(backend=WrongCandidate())
    turn = pipeline.process_task(task(candidates=("allowed",), output_contract="candidate"))
    assert turn.error == "invalid_output_candidate"
    assert turn.backend_attempts == turn.backend_completions == 1
    assert not turn.backend_audit.terminal_failure


def test_transport_metadata_is_not_success_until_fast_result_validation_passes():
    class InvalidTextTransport:
        def complete(self, **kwargs):
            return FastLLMCallResult("fake", "fake-model", "", False, 0.)
    backend = FastLLMBackend(InvalidTextTransport())
    pipeline = CognitivePipeline(backend=backend)
    with pytest.raises(ValueError, match="response_text"):
        pipeline.process_task(task())
    audit, = pipeline.backend_audits
    assert audit.backend_attempts == 1 and audit.backend_completions == 0
    assert audit.terminal_failure
    assert backend.call_history == []
