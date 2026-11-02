from anima.cognition.proposals import (
    CognitiveProposal,
    ProposalKind,
    ProposalValidator,
)
from anima.experiments.stage6 import (
    ExperimentVerdict,
    REQUEST_CONTEXT_MAX_CHARS,
    REQUEST_CONTEXT_MAX_ITEMS,
    run_internal_state_choice_experiment,
    run_request_more_context_experiment,
    run_routing_policy_experiment,
)
from anima.memory.context_builder import ContextBuilder


class FixtureRetrieval:
    def retrieve(self, query, *, top_k, relation_hops, **options):
        if "marker" in query.lower():
            record = {
                "id": "kn_target",
                "statement": "The verified marker is COBALT47.",
            }
            score = 100.0
            reasons = ["fixture:target"]
        else:
            record = {
                "id": "kn_decoy",
                "statement": "The fallback marker is not present in this bounded context.",
            }
            score = 10.0
            reasons = ["fixture:decoy"]
        return {
            "results": [
                {
                    "kind": "knowledge",
                    "id": record["id"],
                    "score": score,
                    "reasons": reasons,
                    "record": record,
                }
            ],
            "stats": {
                "candidates": 1,
                "returned": 1,
            },
        }


class NoopProvenance:
    def knowledge(self, knowledge_id):
        raise AssertionError("FAST fixture must not request event provenance")

    def memory(self, memory_id):
        raise AssertionError("FAST fixture must not request event provenance")


class MarkerBackend:
    def complete(self, turn):
        statements = [
            item["record"]["statement"]
            for item in turn.context["knowledge"]
        ]
        if any("COBALT47" in item for item in statements):
            return CognitiveProposal.respond("COBALT47")
        return CognitiveProposal(
            ProposalKind.REQUEST_CONTEXT,
            {
                "query": "marker cobalt47",
                "need": "verified marker value",
                "max_items": 2,
                "max_chars": 512,
            },
        )


class LoopingBackend:
    def complete(self, turn):
        return CognitiveProposal(
            ProposalKind.REQUEST_CONTEXT,
            {
                "query": "marker cobalt47",
                "need": "keep asking forever",
                "max_items": 2,
                "max_chars": 512,
            },
        )


class OversizedRequestBackend:
    def complete(self, turn):
        return CognitiveProposal(
            ProposalKind.REQUEST_CONTEXT,
            {
                "query": "marker cobalt47",
                "need": "oversized budget",
                "max_items": REQUEST_CONTEXT_MAX_ITEMS + 1,
                "max_chars": REQUEST_CONTEXT_MAX_CHARS,
            },
        )


def _builder():
    return ContextBuilder(
        retrieval=FixtureRetrieval(),
        provenance=NoopProvenance(),
    )


def _coverage(bundle):
    statements = [
        item["record"]["statement"]
        for item in bundle["knowledge"]
    ]
    return 1.0 if any("COBALT47" in item for item in statements) else 0.0


def test_request_more_context_is_bounded_and_improves_fixture_coverage():
    result = run_request_more_context_experiment(
        context_builder=_builder(),
        backend=MarkerBackend(),
        initial_query="what is the verified code?",
        coverage_score=_coverage,
        initial_max_items=1,
        initial_max_chars=128,
    )

    assert result.mechanism_verdict == ExperimentVerdict.ACCEPTED
    assert result.quality_verdict == ExperimentVerdict.INCONCLUSIVE
    assert result.initial_coverage == 0.0
    assert result.final_coverage == 1.0
    assert result.coverage_delta == 1.0
    assert result.additional_retrievals == 1
    assert result.backend_calls == 2
    assert result.cycle_blocked is False
    assert result.final_proposal_kind == "RESPOND"
    assert result.final_response == "COBALT47"
    assert result.initial_source_ids == ("kn_decoy",)
    assert result.final_source_ids == ("kn_target",)


def test_request_more_context_blocks_second_request_instead_of_looping():
    result = run_request_more_context_experiment(
        context_builder=_builder(),
        backend=LoopingBackend(),
        initial_query="what is the verified code?",
        coverage_score=_coverage,
    )

    assert result.additional_retrievals == 1
    assert result.backend_calls == 2
    assert result.cycle_blocked is True
    assert result.mechanism_verdict == ExperimentVerdict.INCONCLUSIVE
    assert result.final_proposal_kind == "REQUEST_CONTEXT"


def test_request_more_context_rejects_model_requested_budget_over_cap():
    try:
        run_request_more_context_experiment(
            context_builder=_builder(),
            backend=OversizedRequestBackend(),
            initial_query="what is the verified code?",
            coverage_score=_coverage,
        )
    except ValueError as error:
        assert "exceeds experiment cap" in str(error)
    else:
        raise AssertionError("oversized REQUEST_CONTEXT budget must be rejected")


def test_production_proposal_validator_still_rejects_request_context():
    proposal = CognitiveProposal(
        ProposalKind.REQUEST_CONTEXT,
        {"query": "marker", "need": "value"},
    )
    validation = ProposalValidator().validate(proposal)

    assert validation.accepted is False
    assert validation.reason == "proposal_kind_not_enabled"


def test_routing_experiment_keeps_baseline_and_rejects_unproven_adaptive_cost():
    result = run_routing_policy_experiment()

    assert result.baseline_verdict == ExperimentVerdict.ACCEPTED
    assert result.adaptive_verdict == ExperimentVerdict.REJECTED
    assert result.deep_value_verdict == ExperimentVerdict.INCONCLUSIVE
    assert result.baseline_deep_calls == 2
    assert result.adaptive_deep_calls == 3
    assert result.fast_benchmark_passes == result.deep_benchmark_passes == 8
    assert result.deep_latency_ratio > 6.0
    assert result.adaptive_estimated_mean_ms > result.baseline_estimated_mean_ms
    assert result.all_deep_estimated_mean_ms > result.baseline_estimated_mean_ms
    assert [item["baseline"] for item in result.cases] == [
        "FAST",
        "FAST",
        "DEEP",
        "DEEP",
    ]


def test_internal_state_experiment_changes_choice_only_through_bounded_modifiers(tmp_path):
    result = run_internal_state_choice_experiment(tmp_path / "internal_state.db")

    assert result.verdict == ExperimentVerdict.ACCEPTED
    assert result.uncertainty_before == 0.0
    assert result.uncertainty_after == 1.0
    assert result.baseline_selected == "CONTINUE"
    assert result.elevated_uncertainty_selected == "INSPECT"
    assert result.repeated_selected == "INSPECT"
    assert result.selection_changed is True
    assert result.deterministic_repeat is True
    assert result.modifier_bounds_ok is True

    elevated = {
        item["candidate_id"]: item
        for item in result.elevated_evaluations
    }
    continue_modifiers = {
        item["name"]: item
        for item in elevated["CONTINUE"]["modifiers"]
    }
    inspect_modifiers = {
        item["name"]: item
        for item in elevated["INSPECT"]["modifiers"]
    }
    assert continue_modifiers["uncertainty_irreversible_risk_penalty"]["contribution"] == -0.2
    assert inspect_modifiers["uncertainty_information_gain_bonus"]["contribution"] == 0.2
