#!/usr/bin/env python3
"""Run reproducible Stage 6.7 mini experiments and emit one JSON report."""

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition.proposals import CognitiveProposal, ProposalKind
from anima.experiments.stage6 import (
    run_internal_state_choice_experiment,
    run_request_more_context_experiment,
    run_routing_policy_experiment,
)
from anima.memory.context_builder import ContextBuilder


class FixtureRetrieval:
    """Tiny controlled retrieval corpus with known ground truth for EXP-004."""

    def retrieve(self, query, *, top_k, relation_hops, **options):
        if "marker" in query.lower():
            record = {
                "id": "kn_exp004_target",
                "statement": "The verified marker is COBALT47.",
            }
            score = 100.0
            reasons = ["fixture:target"]
        else:
            record = {
                "id": "kn_exp004_decoy",
                "statement": "The initial bounded context does not contain the verified marker.",
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
            "stats": {"candidates": 1, "returned": 1},
        }


class NoopProvenance:
    def knowledge(self, knowledge_id):
        raise RuntimeError("EXP-004 FAST fixture must not request event provenance")

    def memory(self, memory_id):
        raise RuntimeError("EXP-004 FAST fixture must not request event provenance")


class MarkerBackend:
    """Deterministic stand-in: asks for context only when target evidence is absent."""

    def complete(self, turn):
        statements = [
            item["record"]["statement"]
            for item in turn.context["knowledge"]
        ]
        if any("COBALT47" in statement for statement in statements):
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


def coverage_score(bundle):
    statements = [
        item["record"]["statement"]
        for item in bundle["knowledge"]
    ]
    return 1.0 if any("COBALT47" in statement for statement in statements) else 0.0


def run_all():
    context_builder = ContextBuilder(
        retrieval=FixtureRetrieval(),
        provenance=NoopProvenance(),
    )
    request_context = run_request_more_context_experiment(
        context_builder=context_builder,
        backend=MarkerBackend(),
        initial_query="What is the verified marker?",
        coverage_score=coverage_score,
        initial_max_items=1,
        initial_max_chars=128,
    )
    routing = run_routing_policy_experiment()
    with TemporaryDirectory(prefix="anima-stage6-exp-") as tmp:
        internal_state = run_internal_state_choice_experiment(
            Path(tmp) / "internal_state.db"
        )

    return {
        "stage": "6.7",
        "experiments": {
            "EXP-004_request_more_context": request_context.to_dict(),
            "EXP-005_fast_deep_routing": routing.to_dict(),
            "EXP-009_internal_state_choice_effect": internal_state.to_dict(),
        },
        "production_changes_enabled": {
            "request_more_context": False,
            "adaptive_routing": False,
            "choice_rules_modified": False,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. The report is always printed to stdout.",
    )
    args = parser.parse_args()
    report = run_all()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
