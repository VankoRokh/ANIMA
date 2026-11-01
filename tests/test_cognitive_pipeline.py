from dataclasses import replace
import json

import pytest

from anima.cognition import CognitivePipeline, FastResult
from anima.cognition.fast_llm import FastLLMBackend, FastLLMCallResult
from anima.cognition.pipeline import route_cognitive
from anima.core.event_bus import Event
from anima.core.identity import Identity
from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask, Evidence, FormalPolicy, HardConstraint
from anima.resolution import DeterministicOutcome, ResolutionRoute, resolve
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine

D = ResolutionRoute.DETERMINISTIC_RESULT
I = ResolutionRoute.INSUFFICIENT_DATA
C = ResolutionRoute.COGNITIVE_REQUIRED


class Backend:
    def __init__(self, response="answer"):
        self.requests = []
        self.response = response

    def complete_projected(self, request):
        self.requests.append(request)
        return FastResult(self.response)


class Builder:
    def __init__(self):
        self.calls = []

    def build(self, query, *, consumer):
        self.calls.append((query, consumer))
        return {"consumer": consumer, "query": query, "budget": {"max_items": 6, "max_chars": 1200},
                "knowledge": [], "memories": [], "events": [], "truncated": False}


class ForbiddenBuilder:
    def build(self, *args, **kwargs):
        raise AssertionError("structured task must never retrieve")


def task(operation="OPEN", **kwargs):
    return CanonicalTask("task", "sensor_source", operation, **kwargs)


def event(text):
    return Event("conversation.user", {"text": text}, source="user", session_id="session_00000001")


def action_task(**kwargs):
    defaults = dict(candidates=("CONTINUE", "CONNECT_CHARGER", "SHUTDOWN"),
                    state={"battery_percent": 54, "estimated_task_cost_percent": 4,
                           "shutdown_threshold_percent": 10, "active_task": True,
                           "preserve_active_task": True, "charger_available": True},
                    constraints=(HardConstraint("battery", "CONTINUE", "BATTERY_ABOVE_THRESHOLD"),
                                 HardConstraint("charger", "CONNECT_CHARGER", "CHARGER_AVAILABLE"),
                                 HardConstraint("preserve", "SHUTDOWN", "PRESERVE_ACTIVE_TASK")))
    defaults.update(kwargs)
    return task("CHOOSE_ACTION", **defaults)


def test_mixed_boundary_corpus_and_call_discipline():
    actions = action_task()
    cases = [
        (task("QUERY_FACT", subject="pet", predicate="color", evidence=(Evidence("f", "gray", "pet", "color"),)), D, "gray"),
        (task("QUERY_FACT", subject="pet", predicate="character"), I, None),
        (task("POWER_COMPATIBILITY", arguments={"power_supply.voltage_v": 5, "power_supply.max_current_a": 1.5,
                                              "device.required_voltage_v": 5, "device.required_current_a": 2}), D, "NO"),
        (replace(actions, state={**actions.state, "battery_percent": 11}), D, "CONNECT_CHARGER"),
        (actions, C, "CONTINUE"),
        (task("RESOLVE_CONFLICT", candidates=("old", "new"), output_contract="candidate",
              evidence=(Evidence("a", "old"), Evidence("b", "new"))), C, "new"),
        (replace(actions, state={**actions.state, "battery_percent": 10, "charger_available": False}), D, None),
        (replace(actions, policies=(FormalPolicy("p", priority=("CONTINUE", "CONNECT_CHARGER")),)), D, "CONTINUE"),
        (replace(actions, state={}), I, None),
    ]
    backend = Backend("CONTINUE")
    pipeline = CognitivePipeline(backend=backend, context_builder=ForbiddenBuilder())
    for value, route, expected in cases:
        before = len(backend.requests)
        backend.response = expected if route == C else "unexpected backend call"
        turn = pipeline.process_task(value)
        assert turn.resolution.route == route
        assert turn.final_result == expected
        expected_calls = int(route == C)
        assert len(backend.requests) - before == turn.model_call_count == expected_calls
        assert turn.model_called == bool(expected_calls)
        assert (turn.view is not None) == bool(expected_calls)
        assert turn.task.source_id == "sensor_source"
    assert len(backend.requests) == 2


def test_structured_task_has_no_fake_text_event_or_context():
    backend = Backend()
    turn = CognitivePipeline(backend=backend).process_task(task(goal="interpret supplied observation"))
    request = backend.requests[0]
    assert request.input_text is None
    assert request.input_event_id is None
    assert request.context_bundle is None
    assert request.input_source_id == "sensor_source"
    assert turn.model_call_count == 1


def test_event_context_built_exactly_once_and_preserved():
    backend, builder = Backend(), Builder()
    source = event("hello")
    turn = CognitivePipeline(backend=backend, context_builder=builder).process_event(source)
    assert builder.calls == [("hello", "FAST")]
    assert len(backend.requests) == 1
    assert turn.fast_turn.request.input_text == "hello"
    assert turn.fast_turn.request.input_event_id == source.event_id
    assert turn.fast_turn.request.context_bundle["budget"] == {"max_items": 6, "max_chars": 1200}


def test_event_arithmetic_skips_model():
    backend, builder = Backend(), Builder()
    turn = CognitivePipeline(backend=backend, context_builder=builder).process_event(event("2+3"))
    assert turn.final_result == 5
    assert builder.calls == [("2+3", "FAST")]
    assert not backend.requests


def test_no_admissible_action_has_typed_deterministic_outcome():
    backend = Backend()
    original = action_task()
    turn = CognitivePipeline(backend=backend).process_task(replace(
        original, state={**original.state, "battery_percent": 10, "charger_available": False}))
    assert turn.resolution.outcome == DeterministicOutcome.NO_ADMISSIBLE_ACTION
    assert turn.resolution.reason == "no_admissible_action"
    assert not backend.requests


def test_rejected_cognitive_candidate_is_observable_without_retry():
    backend = Backend("SHUTDOWN")
    turn = CognitivePipeline(backend=backend).process_task(action_task())
    assert len(backend.requests) == 1
    assert turn.error == "invalid_output_candidate"
    assert turn.final_result is None
    assert turn.fast_turn.result.response_text == "SHUTDOWN"


def test_policy_conflict_and_malformed_policy_call_backend_once():
    for policies in (
        (FormalPolicy("a", priority=("CONTINUE", "CONNECT_CHARGER")),
         FormalPolicy("b", priority=("CONNECT_CHARGER", "CONTINUE"))),
        (FormalPolicy("a", priority=("CONTINUE",)),),
    ):
        backend = Backend("CONTINUE")
        turn = CognitivePipeline(backend=backend).process_task(action_task(policies=policies))
        assert turn.resolution.route == C
        assert turn.resolution.value is None
        assert turn.model_call_count == len(backend.requests) == 1
        assert "policies" in turn.view.data


def test_trace_reports_boundary_projection_and_result():
    trace = DiagnosticTrace()
    backend = Backend("CONTINUE")
    turn = CognitivePipeline(backend=backend, trace=trace).process_task(action_task())
    lines = "\n".join(trace.lines())
    assert "route=COGNITIVE_REQUIRED" in lines
    assert "rejected=" in lines and "SHUTDOWN" in lines
    assert "view=" in lines and "model_calls=1" in lines
    assert "final='CONTINUE'" in lines
    assert turn.resolution.remaining == ("CONTINUE", "CONNECT_CHARGER")


def test_backend_result_type_is_checked():
    class Invalid:
        def complete_projected(self, request):
            return "not a FastResult"
    with pytest.raises(TypeError, match="FastResult"):
        CognitivePipeline(backend=Invalid()).process_task(task())


def test_router_does_not_accept_resolved_task():
    value = task("QUERY_FACT", subject="pet", predicate="color")
    with pytest.raises(ValueError, match="COGNITIVE_REQUIRED"):
        route_cognitive(resolve(value))


def test_event_requires_context_but_structured_path_does_not():
    pipeline = CognitivePipeline(backend=Backend())
    with pytest.raises(TypeError, match="ContextBuilder"):
        pipeline.process_event(event("hello"))
    assert pipeline.process_task(task()).model_called


def test_projected_llm_backend_uses_existing_transport_contract():
    class Transport:
        def __init__(self):
            self.calls = []
        def complete(self, **kwargs):
            self.calls.append(kwargs)
            return FastLLMCallResult("fake", "replacement-model", "answer", False, 1.)
    transport = Transport()
    backend = FastLLMBackend(transport)
    turn = CognitivePipeline(backend=backend).process_task(task(goal="explain observation"))
    assert turn.final_result == "answer"
    assert len(transport.calls) == len(backend.call_history) == 1
    prompt = transport.calls[0]["user_prompt"]
    assert json.loads(prompt.split("\n", 1)[1])["goal"] == "explain observation"


def test_real_memory_budget_provenance_and_backend_replacement(tmp_path):
    path = tmp_path / "memory.db"
    store = MemoryStore(path)
    links = LinkStore(store)
    log = EventLog(tmp_path / "events.jsonl")
    source = event("Coffee preference is espresso")
    log.write(source)
    memory = store.create_memory(memory_type="episodic", domain="user", content="Coffee preference is espresso",
                                 status="closed", importance=2, source_event_id=source.event_id)
    provenance = ProvenanceResolver(store, links, log)
    builder = ContextBuilder(retrieval=RetrievalEngine(memory_store=store, link_store=links), provenance=provenance)
    before = path.read_bytes()
    identity_path = tmp_path / "identity.json"
    original_identity = Identity(identity_path).get()
    identity_bytes = identity_path.read_bytes()
    turns = []
    class ReadingBackend(Backend):
        def complete_projected(self, request):
            values = [item["value"] for item in request.cognitive_view.data["evidence"]]
            assert values == ["Coffee preference is espresso"]
            self.requests.append(request)
            return FastResult(f"{self.response}: {values[0]}")

    for response in ("first backend", "replacement backend"):
        # Reconstruct the read stack as well as replacing the cognitive backend.
        reopened = MemoryStore(path)
        reopened_links = LinkStore(reopened)
        builder = ContextBuilder(
            retrieval=RetrievalEngine(memory_store=reopened, link_store=reopened_links),
            provenance=ProvenanceResolver(reopened, reopened_links, log),
        )
        assert Identity(identity_path).get() == original_identity
        backend = ReadingBackend(response)
        pipeline = CognitivePipeline(backend=backend, context_builder=builder)
        turns.append(pipeline.process_event(event("Coffee preference")))
        assert len(backend.requests) == 1
        assert path.read_bytes() == before
        assert identity_path.read_bytes() == identity_bytes
    for turn in turns:
        bundle = turn.fast_turn.request.context_bundle
        assert bundle["budget"] == {"max_items": 6, "max_chars": 1200}
        assert not bundle["events"]
        assert bundle["selection_stats"]["items_used"] <= 6
        assert bundle["selection_stats"]["chars_used"] <= 1200
        assert turn.task.evidence[0].evidence_id == memory["id"]
        assert turn.task.evidence[0].subject is None
        assert provenance.memory(memory["id"])["events"][0]["id"] == source.event_id
    assert turns[1].final_result == "replacement backend: Coffee preference is espresso"


def test_unsupported_constraint_remains_visible_and_cannot_authorize_a_candidate():
    backend = Backend("CONTINUE")
    value = action_task(constraints=(HardConstraint("unknown", "CONTINUE", "UNSUPPORTED_RULE"),))
    turn = CognitivePipeline(backend=backend).process_task(value)
    assert turn.resolution.route == C
    assert turn.view.data["constraints"][0]["rule"] == "UNSUPPORTED_RULE"
    assert turn.error == "invalid_output_candidate"
    assert turn.final_result is None
    assert turn.model_call_count == 1


def test_candidate_output_contract_is_enforced_for_open_task():
    backend = Backend("invented")
    turn = CognitivePipeline(backend=backend).process_task(task(candidates=("a", "b"), output_contract="candidate"))
    assert turn.final_result is None
    assert turn.error == "invalid_output_candidate"


def test_backend_failure_is_not_retried_and_attempt_is_traced():
    class Failing(Backend):
        def complete_projected(self, request):
            self.requests.append(request)
            raise RuntimeError("transport failed")
    backend, trace = Failing(), DiagnosticTrace()
    with pytest.raises(RuntimeError, match="transport failed"):
        CognitivePipeline(backend=backend, trace=trace).process_task(task())
    assert len(backend.requests) == 1
    assert "model_calls=1" in "\n".join(trace.lines())


def test_deterministic_and_missing_trace_have_zero_calls():
    trace = DiagnosticTrace()
    pipeline = CognitivePipeline(backend=Backend(), trace=trace)
    pipeline.process_task(task("QUERY_FACT", subject="pet", predicate="color"))
    pipeline.process_task(task("CALCULATE", arguments={"left": 1, "right": 2, "operator": "+"}))
    lines = "\n".join(trace.lines())
    assert "route=INSUFFICIENT_DATA" in lines
    assert "route=DETERMINISTIC_RESULT" in lines
    assert lines.count("model_calls=0") == 2
