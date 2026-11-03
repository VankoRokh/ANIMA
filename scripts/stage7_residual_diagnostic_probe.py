"""Run the factorized Stage 7 REVISION diagnostic protocol against llama.cpp."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition.llm_transport import LlamaCppTransport
from anima.semantic import EvaluationPlan, evaluate_document, parse_and_validate_request
from anima.semantic.residual import ResidualModelError
from anima.semantic.residual_diagnostic import DiagnosticBackend, complete_with_diagnostic


FIXTURE_ROOT = ROOT / "tests/fixtures/stage7/classify_relation_0_1"
CASE_PATHS = {
    "CR-028": FIXTURE_ROOT / "block_c" / "CR-028",
    "CR-032": FIXTURE_ROOT / "block_c" / "CR-032",
    "CR-030-M": FIXTURE_ROOT / "model_residual" / "CR-030-M",
    "CR-050-M": FIXTURE_ROOT / "model_residual" / "CR-050-M",
}
CASES = tuple(CASE_PATHS)


def _call_details(backend):
    call = backend.call_history[-1] if backend.call_history else None
    metadata = call.to_dict() if call is not None and hasattr(call, "to_dict") else None
    model_output = getattr(call, "text", None) if call is not None else None
    return model_output, metadata


def run_case(case_id, transport, *, timeout_seconds):
    case_dir = CASE_PATHS[case_id]
    raw = (case_dir / "request.json").read_text(encoding="utf-8")
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    request = parse_and_validate_request(raw)
    plan = evaluate_document(raw)
    if not isinstance(plan, EvaluationPlan):
        raise RuntimeError(f"{case_id}: deterministic preflight returned {plan!r}")
    if plan.residual_facets != ("revision",):
        raise RuntimeError(f"{case_id}: expected REVISION residual, got {plan.residual_facets!r}")

    backend = DiagnosticBackend(transport, timeout_seconds=timeout_seconds)
    try:
        completed = complete_with_diagnostic(request, plan, backend)
    except ResidualModelError as error:
        model_output, metadata = _call_details(backend)
        return {
            "case": case_id,
            "status": "invalid_model_output",
            "error": str(error),
            "deterministic_facets": plan.determined_facets(),
            "model_output": model_output,
            "model_call": metadata,
        }, False
    except Exception as error:
        model_output, metadata = _call_details(backend)
        return {
            "case": case_id,
            "status": "backend_failure",
            "error": f"{type(error).__name__}: {error}",
            "deterministic_facets": plan.determined_facets(),
            "model_output": model_output,
            "model_call": metadata,
        }, False

    exact = completed.assessment == expected
    model_output, metadata = _call_details(backend)
    return {
        "case": case_id,
        "status": "pass" if exact else "semantic_mismatch",
        "assessment": completed.assessment,
        "expected": expected,
        "backend_calls": completed.backend_calls,
        "model_output": model_output,
        "model_call": metadata,
    }, exact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=(*CASES, "all"), default="all")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="Qwen3-0.6B-Q8_0")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-output-tokens", type=int, default=128)
    args = parser.parse_args()

    transport = LlamaCppTransport(
        base_url=args.base_url,
        model=args.model,
        thinking=False,
        max_output_tokens=args.max_output_tokens,
        temperature=0.0,
        top_k=1,
        top_p=1.0,
        min_p=0.0,
    )
    selected = CASES if args.case == "all" else (args.case,)
    results = []
    passed = 0
    for case_id in selected:
        result, exact = run_case(case_id, transport, timeout_seconds=args.timeout)
        results.append(result)
        passed += int(exact)

    payload = {
        "summary": {
            "protocol": "revision-factorized-diagnostic/0.1",
            "model": args.model,
            "passed": passed,
            "total": len(selected),
            "exact_rate": passed / len(selected),
        },
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
