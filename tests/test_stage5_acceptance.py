"""Acceptance counterexamples with independently specified expected outcomes."""

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from anima.cognition import CognitivePipeline, FastCognition, FastRequest, FastResult
from anima.cognition.fast import ProjectedFastBackend, ProjectedFastRequest
from anima.cognition.fast_llm import FastLLMBackend, FastLLMCallResult, render_fast_prompts
from anima.cognition.projection import project
from anima.core.event_bus import Event
from anima.ir import CanonicalTask, Evidence, FormalPolicy, HardConstraint
from anima.resolution import DeterministicOutcome, ResolutionResult, ResolutionRoute, resolve
from anima.resolution.frontend import task_from_event

D = ResolutionRoute.DETERMINISTIC_RESULT
I = ResolutionRoute.INSUFFICIENT_DATA
C = ResolutionRoute.COGNITIVE_REQUIRED


def task(operation="OPEN", **kwargs):
    return CanonicalTask("acceptance", "api", operation, **kwargs)


def test_high_precision_subtraction_never_passes_through_float():
    text = "999999999999.999999 - 999999999999.999998"
    event = Event("conversation.user", {"text": text}, source="user")
    # Even a low ambient Decimal precision must not round the runtime operation.
    with localcontext() as context:
        context.prec = 2
        value = task_from_event(event)
        result = resolve(value)
    assert value.arguments["left"] == Decimal("999999999999.999999")
    assert result.route == D
    assert result.value == Decimal("0.000001")


@pytest.mark.parametrize("left,op,right,expected", [
    (Decimal("0.1"), "+", Decimal("0.2"), Decimal("0.3")),
    (Decimal("123.456"), "*", Decimal("0.001"), Decimal("0.123456")),
    (1, "/", 8, Decimal("0.125")),
    (10**400, "+", 2, 10**400 + 2),
    (1e308, "*", 1e308, 10**616),
])
def test_exact_arithmetic_without_context_rounding(left, op, right, expected):
    with localcontext() as context:
        context.prec = 2
        result = resolve(task("CALCULATE", arguments={"left": left, "right": right, "operator": op}))
    assert result.route == D
    assert result.value == expected


def test_nonterminating_decimal_is_not_arbitrarily_rounded():
    result = resolve(task("CALCULATE", arguments={"left": 1, "right": 3, "operator": "/"}))
    assert result.route == C
    assert result.value is None


@pytest.mark.parametrize("number", [float, Decimal])
def test_decimal_threshold_equality_rejects_continue(number):
    value = task("CHOOSE_ACTION", candidates=("CONTINUE",),
                 state={"battery_percent": number("20.3"), "estimated_task_cost_percent": number("10.2"),
                        "shutdown_threshold_percent": number("10.1")},
                 constraints=(HardConstraint("battery", "CONTINUE", "BATTERY_ABOVE_THRESHOLD"),))
    result = resolve(value)
    assert result.route == D
    assert result.outcome == DeterministicOutcome.NO_ADMISSIBLE_ACTION
    assert result.value is None
    assert result.derived["projected_battery_after_task_percent"] == Decimal("10.1")


def test_decimal_comparison_uses_exact_supplied_decimal_values():
    result = resolve(task("COMPARE", arguments={"left": Decimal("999999999999.999999"),
                                                "right": Decimal("999999999999.999998"), "operator": ">"}))
    assert (result.route, result.value) == (D, "YES")


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("policies", [(), (FormalPolicy("bad", type="UNKNOWN"),)])
def test_missing_supported_requirement_survives_unsupported_constraint(reverse, policies):
    constraints = (HardConstraint("known", "A", "CHARGER_AVAILABLE"),
                   HardConstraint("unsupported", "B", "UNKNOWN_RULE"))
    value = task("CHOOSE_ACTION", candidates=("A", "B"),
                 constraints=tuple(reversed(constraints)) if reverse else constraints, policies=policies)
    result = resolve(value)
    assert result.route == I
    assert result.missing == ("charger_available",)


def test_candidates_omitted_and_explicitly_empty_have_different_epistemic_results():
    unknown = task("CHOOSE_ACTION")
    known_empty = replace(unknown, candidates=())
    assert unknown.candidates is None
    assert resolve(unknown).route == I
    assert resolve(unknown).missing == ("candidates",)
    assert resolve(known_empty).route == D
    assert resolve(known_empty).outcome == DeterministicOutcome.NO_ADMISSIBLE_ACTION


def test_contradictory_no_admissible_action_is_rejected():
    with pytest.raises(ValueError, match="possible candidates"):
        ResolutionResult(D, "no_admissible_action", outcome=DeterministicOutcome.NO_ADMISSIBLE_ACTION,
                         remaining=("A",))
    with pytest.raises(ValueError, match="possible candidates"):
        ResolutionResult(D, "no_admissible_action", outcome=DeterministicOutcome.NO_ADMISSIBLE_ACTION,
                         unverified=("A",))


class RecordingProjectedBackend:
    def __init__(self, answer="A"):
        self.calls = []
        self.answer = answer

    def complete_projected(self, request):
        assert isinstance(request, ProjectedFastRequest)
        self.calls.append(request)
        return FastResult(self.answer)


def test_missing_supported_requirement_and_unknown_rule_make_zero_calls():
    backend = RecordingProjectedBackend()
    value = task("CHOOSE_ACTION", candidates=("A", "B"), constraints=(
        HardConstraint("unknown", "B", "UNKNOWN_RULE"),
        HardConstraint("known", "A", "CHARGER_AVAILABLE")),
        policies=(FormalPolicy("unknown_policy", type="UNKNOWN"),))
    turn = CognitivePipeline(backend=backend).process_task(value)
    assert turn.resolution.route == I
    assert turn.resolution.missing == ("charger_available",)
    assert not backend.calls
    assert turn.model_call_count == 0


def test_unverified_only_candidates_do_not_cause_impossible_model_call():
    backend = RecordingProjectedBackend()
    value = task("CHOOSE_ACTION", candidates=("A",), constraints=(HardConstraint("unknown", "A", "UNKNOWN"),))
    turn = CognitivePipeline(backend=backend).process_task(value)
    assert turn.resolution.route == C
    assert turn.resolution.unverified == ("A",)
    assert not turn.resolution.remaining
    assert turn.error == "no_admissible_candidates"
    assert turn.final_result is None
    assert not backend.calls
    assert turn.model_call_count == 0
    assert turn.view.data["constraints"][0]["rule"] == "UNKNOWN"


def test_known_rejections_survive_unknown_rules():
    backend = RecordingProjectedBackend()
    value = task("CHOOSE_ACTION", candidates=("A", "B"), state={"charger_available": False}, constraints=(
        HardConstraint("charger", "A", "CHARGER_AVAILABLE"), HardConstraint("unknown", "B", "UNKNOWN")))
    turn = CognitivePipeline(backend=backend).process_task(value)
    assert turn.resolution.rejected == {"A": ("charger",)}
    assert turn.resolution.unverified == ("B",)
    assert turn.error == "no_admissible_candidates"
    assert not backend.calls


@pytest.mark.parametrize("operation,calls", [("QUERY_FACT", 0), ("OPEN", 1)])
def test_final_allowed_output_validation_is_uniform(operation, calls):
    backend = RecordingProjectedBackend("white")
    value = task(operation, subject="pet", predicate="color", output_contract="candidate", candidates=("gray",),
                 evidence=(Evidence("fact", "white", "pet", "color"),))
    turn = CognitivePipeline(backend=backend).process_task(value)
    assert turn.final_result is None
    assert turn.error == "invalid_output_candidate"
    assert len(backend.calls) == turn.model_call_count == calls
    if operation == "QUERY_FACT":
        assert turn.resolution.route == D
        assert turn.resolution.value == "white"  # Preserve the true fact for audit.


def test_unknown_candidates_and_known_empty_no_action_make_zero_calls():
    backend = RecordingProjectedBackend()
    pipeline = CognitivePipeline(backend=backend)
    unknown = pipeline.process_task(task("CHOOSE_ACTION"))
    empty = pipeline.process_task(task("CHOOSE_ACTION", candidates=(), output_contract="candidate"))
    assert unknown.resolution.route == I
    assert empty.resolution.outcome == DeterministicOutcome.NO_ADMISSIBLE_ACTION
    assert empty.error is None
    assert not backend.calls


def test_empty_allowed_output_cannot_make_a_useless_cognitive_call():
    backend = RecordingProjectedBackend()
    turn = CognitivePipeline(backend=backend).process_task(task(candidates=(), output_contract="candidate"))
    assert turn.error == "no_admissible_candidates"
    assert turn.model_call_count == 0
    assert not backend.calls


def test_raw_unresolved_action_preference_is_preserved_alongside_structured_context():
    raw = "Choose A if urgency applies, otherwise B; urgency applies."
    value = task("CHOOSE_ACTION", candidates=("A", "B"), raw_input=raw,
                 goal="preserve availability", preference="avoid disruption",
                 evidence=(Evidence("text", "An urgent task is pending."),))
    backend = RecordingProjectedBackend()
    turn = CognitivePipeline(backend=backend).process_task(value)
    view = backend.calls[0].cognitive_view.data
    assert view["input"] == raw
    assert view["goal"] == "preserve availability"
    assert view["preference"] == "avoid disruption"
    assert view["evidence"][0]["value"] == "An urgent task is pending."
    assert turn.final_result == "A"


def test_textual_open_evidence_survives_resolved_subject_and_predicate():
    value = task("OPEN", subject="pet", predicate="color", raw_input="Explain this property",
                 evidence=(Evidence("prose", "Pet is gray; this is approximate."),))
    view = project(value, resolve(value))
    assert view.data["evidence"][0]["value"] == "Pet is gray; this is approximate."
    backend = RecordingProjectedBackend("It is approximately gray.")
    CognitivePipeline(backend=backend).process_task(value)
    assert backend.calls[0].cognitive_view.data["evidence"] == view.data["evidence"]


def test_legacy_request_consuming_backend_keeps_nonnullable_contract():
    class LegacyBackend:
        def __init__(self):
            self.calls = []
        def complete(self, request):
            assert isinstance(request, FastRequest)
            self.calls.append(request)
            assert request.context_bundle["consumer"] == "FAST"
            return FastResult(request.input_text.upper())
    class Builder:
        def build(self, query, *, consumer):
            return {"consumer": consumer}
    backend = LegacyBackend()
    event = Event("conversation.user", {"text": "hello"}, source="user")
    result = FastCognition(backend=backend, context_builder=Builder()).process(event)
    assert result.result.response_text == "HELLO"
    with pytest.raises(TypeError, match="requires ProjectedFastBackend.complete_projected"):
        CognitivePipeline(backend=backend)
    assert len(backend.calls) == 1
    assert not isinstance(backend, ProjectedFastBackend)


def test_llm_backend_explicitly_supports_both_request_capabilities():
    class Transport:
        def __init__(self): self.prompts = []
        def complete(self, **kwargs):
            self.prompts.append(kwargs["user_prompt"])
            return FastLLMCallResult("fake", "replacement", "answer", False, 0.)
    transport = Transport()
    backend = FastLLMBackend(transport)
    assert isinstance(backend, ProjectedFastBackend)
    backend.complete(FastRequest("ev_example", "hello", {"consumer": "FAST"}))
    CognitivePipeline(backend=backend).process_task(task(goal="explain observation"))
    assert len(transport.prompts) == 2
    assert "hello" in transport.prompts[0]
    assert "explain observation" in transport.prompts[1]
    assert "TASK_VIEW" in transport.prompts[1]
    with pytest.raises(TypeError, match="Legacy FAST completion"):
        value = task()
        backend.complete(ProjectedFastRequest("api", project(value, resolve(value))))


def test_decimal_projection_serialization_preserves_digits():
    value = task("OPEN", arguments={"measurement": Decimal("999999999999.999999")})
    view = project(value, resolve(value))
    _, prompt = render_fast_prompts(ProjectedFastRequest("api", view))
    assert '"measurement":"999999999999.999999"' in prompt
    assert value.arguments["measurement"] == Decimal("999999999999.999999")


def test_electrical_derived_margin_has_exact_decimal_semantics():
    with localcontext() as context:
        context.prec = 2
        result = resolve(task("POWER_COMPATIBILITY", arguments={
            "power_supply.voltage_v": Decimal("5.0"), "power_supply.max_current_a": Decimal("0.3"),
            "device.required_voltage_v": Decimal("5.0"), "device.required_current_a": Decimal("0.2")}))
    assert result.route == D
    assert result.value == "YES"
    assert result.derived["current_margin_a"] == Decimal("0.1")
