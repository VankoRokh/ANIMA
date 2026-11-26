"""R9.3-C6 integration: rejected generation cannot become a cognitive result."""
import pytest

from anima.cognition.deep_llm import DeepLLMBackend
from anima.cognition.fast import FastCognition
from anima.cognition.fast_llm import FastLLMBackend, FastLLMModelOutputError
from anima.cognition.llm_transport import LLMCallResult, LLMModelOutputError
from anima.cognition.pipeline import BackendFailureClassification, CognitivePipeline
from anima.cognition.proposals import CognitiveDispatcher, ProposalValidator
from anima.cognition.routing import CognitiveDestination, CognitiveRouter
from anima.ir import CanonicalTask
from anima.resolution import resolve
from anima.tasks.store import TaskStore
from tests.test_deep_dispatch_integration import (
    RecordingFastBackend, active_task, conflict_task,
)
from tests.test_fast_cognition import StubContextBuilder, user_event


class IncompleteTransport:
    wire_protocol = "chat_completion"

    def __init__(self, finish, text):
        self.finish = finish
        self.text = text
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        return LLMCallResult("test", "test", self.text, False, 1.0,
                             input_tokens=20, output_tokens=8,
                             finish_reason=self.finish)


@pytest.mark.parametrize("finish", ["length", None, "tool_calls", "eos"])
def test_fast_pipeline_never_promotes_rejected_candidate(finish):
    transport = IncompleteTransport(finish, "A")
    backend = FastLLMBackend(transport)
    pipeline = CognitivePipeline(backend=backend)
    task = CanonicalTask("terminal-probe", "test", "OPEN",
                         goal="Choose a response", candidates=("A", "B"),
                         output_contract="candidate")
    with pytest.raises(FastLLMModelOutputError, match="generation not confirmed complete"):
        pipeline.process_task(task)
    audit, = pipeline.backend_audits
    assert audit.task_id == task.task_id
    assert audit.backend_attempts == 1 and audit.backend_completions == 0
    assert audit.terminal_failure
    assert audit.failure_classification == BackendFailureClassification.MODEL_OUTPUT
    assert transport.calls == 1
    assert not backend.call_history
    record, = backend.rejected_generation_history
    assert (record["input_tokens"], record["output_tokens"]) == (20, 8)


@pytest.mark.parametrize("finish", ["length", None, "tool_calls", "eos"])
def test_legacy_fast_never_returns_rejected_answer(finish):
    transport = IncompleteTransport(finish, "Plausible answer")
    backend = FastLLMBackend(transport)
    context = StubContextBuilder()
    cognition = FastCognition(context_builder=context, backend=backend)
    with pytest.raises(FastLLMModelOutputError, match="generation not confirmed complete"):
        cognition.process(user_event())
    assert len(context.calls) == transport.calls == 1
    assert not backend.call_history
    assert len(backend.rejected_generation_history) == 1


@pytest.mark.parametrize("finish", ["length", None, "tool_calls", "eos"])
def test_deep_rejection_precedes_validation_and_preserves_task(tmp_path, monkeypatch, finish):
    store = TaskStore(tmp_path / "tasks.db")
    persistent = active_task(store)
    transitions = store.list_transitions(persistent.public_id)
    task = conflict_task()
    resolution = resolve(task)
    decision = CognitiveRouter().route(task, resolution)
    assert decision.destination == CognitiveDestination.DEEP
    fast = RecordingFastBackend()
    transport = IncompleteTransport(finish, "Newer evidence supports B.")
    deep = DeepLLMBackend(transport)

    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected generation reached proposal validation")

    monkeypatch.setattr(ProposalValidator, "validate", forbidden)
    dispatcher = CognitiveDispatcher(fast_backend=fast, deep_backend=deep)
    with pytest.raises(LLMModelOutputError, match="generation not confirmed complete"):
        dispatcher.dispatch(decision, persistent_task_id=persistent.public_id,
                            task=task, resolution=resolution)
    assert not fast.calls
    assert transport.calls == 1
    assert not deep.call_history
    record, = deep.rejected_generation_history
    assert (record["input_tokens"], record["output_tokens"]) == (20, 8)
    assert store.get_task(persistent.public_id).status == "active"
    assert store.list_transitions(persistent.public_id) == transitions
