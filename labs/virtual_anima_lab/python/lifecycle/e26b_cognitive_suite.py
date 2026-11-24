"""E2.6b varied tasks using one native adapter and actual E2.4 captured Raw.

The operation gate is machine-checkable; natural-language conclusions are
retained for separate human review. No task-specific prompt adapters.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.completion import CompletionRequirement, evaluate_completion
from labs.virtual_anima_lab.python.cognition.claim_verification import ObservationClaim, ObservationClaimVerifier

CRATE = "lab.item.crate"
SHORTCUT = "lab.obstacle.shortcut"
CASES = (
    {"id": "C01", "task": "Find and verify previous observations of the crate.",
     "enabled": True, "targets": (CRATE,), "kind": "positive"},
    {"id": "C02", "task": "Search memory for previous observations of an elephant. Verify evidence if it exists.",
     "enabled": True, "targets": (), "kind": "negative", "query": "elephant"},
    {"id": "C03", "task": "Find and verify previous observations of both the crate and the shortcut obstacle.",
     "enabled": True, "targets": (CRATE, SHORTCUT), "kind": "positive"},
    {"id": "C06", "task": "Verify the past observation of the crate. Is the crate currently visible, or only remembered?",
     "enabled": True, "targets": (CRATE,), "kind": "positive"},
    {"id": "C09", "task": "What is 2 plus 2? This is a simple arithmetic question, not a question about the environment.",
     "enabled": True, "targets": (), "kind": "no_tool"},
    {"id": "C02_OFF", "task": "Find and verify previous observations of the crate.",
     "enabled": False, "targets": (), "kind": "negative", "query": "crate"},
    {"id": "C03_ALT", "task": "Find and verify earlier observations of the shortcut obstacle.",
     "enabled": True, "targets": (SHORTCUT,), "kind": "positive"},
)


def assess(case, report, trace, calls):
    completed = [o for o in report["outcomes"] if o["status"] == "COMPLETED"]
    verified = {entity for o in completed if o["operation_kind"] == "lookup_raw_evidence"
                for row in o["result"]["records"] if row["status"] == "verified_source_view"
                for entity in row["entities_observed"]}
    searches = [r for r in trace if r["proposal"] is not None
                and r["proposal"]["operation_kind"] == "retrieve_memory"
                and r["outcome"]["status"] == "COMPLETED"]
    checks = [r for r in searches
              if case.get("query", "").lower() in r["proposal"]["arguments"]["query"].lower()
              and not r["outcome"]["result"]["records"]]
    final = calls[-1].get("final_text") if calls else None
    # A denied call is still invalid. Separate the strict wire metric from
    # the recovery-aware objective, and require persisted denial plus feedback
    # in the very next actual model request (never silently repair a call).
    recovered = []
    for i, call in enumerate(calls[:-1]):
        if not call.get("feedback_eligible") or call["valid"]:
            continue
        reason_code = call.get("error_code")
        if reason_code not in ("UNEXPOSED_EVIDENCE_ID", "INVALID_TOOL_ARGUMENTS"):
            continue
        denial = any(o.get("step_index") == call.get("step_index")
            and o.get("status") == "REJECTED"
            and o.get("reason_code") == reason_code
            and o.get("execution_performed") is False for o in report["outcomes"])
        messages = calls[i+1].get("request", {}).get("messages", [])
        if denial and messages and messages[-1].get("role") == "tool" and messages[-1].get("tool_call_id") == call.get("tool_call_id"):
            error = json.loads(messages[-1]["content"])
            if error.get("error_code") == reason_code and error.get("execution_performed") is False:
                recovered.append(i)
    strict_valid = bool(calls and all(c["valid"] and c["transport_ok"] for c in calls))
    valid = bool(calls and all(c["transport_ok"] and (c["valid"] or i in recovered)
                               for i,c in enumerate(calls)))
    stopped = report["status"] == "STOPPED" and bool(final)
    if case["kind"] == "positive":
        objective = set(case["targets"]) <= verified
    elif case["kind"] == "negative":
        objective = bool(checks) and not verified
    else:
        objective = not report["outcomes"]
    # Exact repeated proposals in frozen context are diagnostic only.
    signatures = [json.dumps([r["proposal"]["operation_kind"], r["proposal"]["arguments"]],
                              sort_keys=True) for r in trace if r["proposal"] is not None]
    return {"operation_gate_pass": bool(valid and stopped and objective),
            "strict_operation_gate_pass": bool(strict_valid and stopped and objective),
            "feedback_deliveries": len(recovered),
            "recovered_objective": bool(recovered and valid and stopped and objective),
            "valid_model_outputs": sum(c["valid"] for c in calls),
            "normalized_calls": sum(bool(c.get("arguments_normalized")) for c in calls),
            "strict_wire_valid_outputs": sum(c["valid"] and not c.get("arguments_normalized", False) for c in calls),
            "transport_successes": sum(c["transport_ok"] for c in calls),
            "model_calls": len(calls), "verified_entities": sorted(verified),
            "completed_search_queries": [r["proposal"]["arguments"]["query"] for r in searches],
            "repeated_proposals": len(signatures) - len(set(signatures)),
            "turn_status": report["status"], "final_text": final,
            "semantic_review": "PENDING" if final else "NO_FINAL_RESPONSE",
            "latency_ms": [c.get("latency_ms") for c in calls],
            "input_tokens": [c.get("input_tokens") for c in calls],
            "output_tokens": [c.get("output_tokens") for c in calls]}


def information_requirement(case):
    # Trusted fixture mapping, not model input or a natural language parser.
    if case["kind"] == "positive":
        return CompletionRequirement("verified_observation", entities=case["targets"])
    if case["kind"] == "negative":
        return CompletionRequirement("empty_search", query=case["query"])
    if case["kind"] == "no_tool":
        return CompletionRequirement("no_service_read")
    raise ValueError("unknown case kind")


from labs.virtual_anima_lab.python.cognition.resource_budget import ResourceLimits


def run_cases(memory, coordinator, root, seed, *, base_url, model, check_world, check_core,
              variant="baseline", selected_cases=None):
    historical = {r["entity_ref"]: r for r in memory.world_model()["entities"]}
    if not {CRATE, SHORTCUT} <= set(historical):
        raise AssertionError("fixture missing expected observed entities")
    if historical[CRATE]["current_observation"] != "not_observed":
        raise AssertionError("fixture requires remembered but not currently observed crate")
    if any("elephant" in ref.lower() for ref in historical):
        raise AssertionError("unknown entity fixture is invalid")
    results = []
    for case in CASES:
        if selected_cases is not None and case["id"] not in selected_cases:
            continue
        turn_id = f"suite_{seed}_{case['id']}"
        adapter = NativeLabAdapter(base_url=base_url, model=model,
            trace_path=root / f"{turn_id}-model-calls.jsonl", task=case["task"],
            canonical_sets=variant in ("set", "combined", "compact", "ranked", "refined", "feedback", "feedback_probe", "continuation", "budgeted", "budget_probe", "claims"),
            temporal=variant in ("temporal", "combined", "compact", "ranked", "refined", "feedback", "feedback_probe", "continuation", "budgeted", "budget_probe", "claims"),
            compact_temporal=variant in ("compact", "refined", "feedback", "continuation", "budgeted", "budget_probe", "claims"),
            error_feedback=variant in ("feedback", "feedback_probe", "continuation", "budgeted", "budget_probe", "claims"),
            model_claims=variant == "claims")
        limits = (ResourceLimits() if variant in ("budgeted","claims") else
                  ResourceLimits(max_calls=1) if variant == "budget_probe" else None)
        report = coordinator.run_turn(adapter, turn_id=turn_id, memory_enabled=case["enabled"],
            completion_requirement=information_requirement(case) if variant in ("continuation","budgeted","budget_probe","claims") else None,
            resource_limits=limits)
        trace = coordinator.decision_records(turn_id)
        world_ok, core_ok = check_world(), check_core()
        if not world_ok or not core_ok:
            raise AssertionError("read-only invariant changed")
        result = {"seed": seed, "case": case["id"], "task": case["task"],
                  "variant": variant,
                  "memory_enabled": case["enabled"], "world_unchanged": world_ok,
                  "canonical_baseline_unchanged": core_ok,
                  **assess(case, report, trace, adapter.calls),
                  "information_completion": evaluate_completion(information_requirement(case), report, trace)}
        # Host-authored diagnostic claims, NOT extracted from model prose.
        # Never expose additional source IDs to the model or affect its gate.
        probes = []
        verifier = ObservationClaimVerifier(coordinator)
        if case["kind"] == "positive":
            for entity in case["targets"]:
                candidate = historical[entity]
                claim_args = (entity, "observed_in_sample")
                for value, scope in ((True,"source_sample"),(False,"source_sample"),
                                     (True,"latest_captured_sample")):
                    claim = ObservationClaim(*claim_args,value,
                        candidate["last_seen_event_id"],candidate["last_seen_sample"],scope)
                    probes.append(verifier.verify(turn_id,claim))
        result["host_claim_probes"] = probes
        result["continuation_decisions"] = report.get("continuation_decisions", [])
        result["continued"] = any(x["decision"] == "CONTINUE" for x in result["continuation_decisions"])
        result["resource_budget"] = report.get("resource_budget")
        if variant == "claims":
            from labs.virtual_anima_lab.python.cognition.model_claims import evaluate_model_claims
            evaluation = evaluate_model_claims(coordinator, report, adapter.calls)
            result["model_claims"] = evaluation
            result["claim_objective_pass"] = (evaluation["format_status"] == "VALID"
                and result["information_completion"]["information_requirement_satisfied"]
                and all(v["status"] == "VERIFIED" for v in evaluation["verdicts"])
                and (set(case["targets"]) <= set(evaluation["verified_positive_entities"])
                     if case["kind"] == "positive" else not evaluation["claims"]))
        if variant in ("continuation","budgeted","budget_probe","claims") and (report["model_calls_used"] != len(adapter.calls) or len(adapter.calls) > 4):
            raise AssertionError("model call budget/accounting mismatch")
        if not case["enabled"] and CRATE in result["verified_entities"]:
            raise AssertionError("memory ablation exposed crate history")
        (root / f"{turn_id}-result.json").write_text(
            json.dumps({"result":result, "turn":report, "trace":trace}, indent=2),
            encoding="utf-8")
        results.append(result)
        print(json.dumps(result), flush=True)
    return results


def main():
    from .e26a_real_fast_gate import case, require
    from .world_smoke import _binary
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--godot", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8085")
    ap.add_argument("--model", required=True)
    ap.add_argument("--model-file", type=Path, required=True)
    ap.add_argument("--evidence-dir", type=Path)
    ap.add_argument("--variant", choices=("baseline", "set", "temporal", "combined", "compact", "ranked", "refined", "feedback", "feedback_probe", "continuation", "budgeted", "budget_probe", "claims"), default="baseline")
    ap.add_argument("--case", action="append", choices=[c["id"] for c in CASES])
    args = ap.parse_args()
    url = urlsplit(args.base_url)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
            or url.port is None or url.path not in ("", "/")
            or url.username or url.password or url.query or url.fragment):
        ap.error("loopback llama-server only")
    with urllib.request.urlopen(args.base_url.rstrip("/") + "/v1/models", timeout=10) as response:
        models = json.loads(response.read(65536))
    require(any(x.get("id") == args.model for x in models["data"]), "model alias mismatch")
    out = args.evidence_dir or Path(tempfile.mkdtemp(prefix="anima-e26b-"))
    out.mkdir(parents=True, exist_ok=True)
    require(not any(out.iterdir()), "evidence directory must be empty")
    with args.model_file.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (out / "model-manifest.json").write_text(json.dumps({
        "model_alias":args.model, "local_file":args.model_file.name,
        "local_file_sha256":digest, "server_models":models,
        "file_hash_not_attested_by_server":True, "profile":"native",
        "temperature":0, "max_steps":4, "max_output_tokens":256,
        "variant":args.variant,
        "scenarios":[c for c in CASES if args.case is None or c["id"] in args.case]}, indent=2), encoding="utf-8")
    print(f"Evidence directory: {out}", flush=True)
    results = []
    for seed in (7, 8):
        results.extend(case(_binary(args.godot), seed, out, base_url=args.base_url,
                            model=args.model, profile="native", suite=True,
                            suite_variant=args.variant, suite_cases=args.case))
    total = sum(r["operation_gate_pass"] for r in results)
    report = {"schema":"anima.e26b.cognitive_suite/0.1",
              "status":"E26B_OPERATION_GATE_PASS" if total == len(results)
                       else "E26B_OPERATION_GATE_FAIL",
              "operation_passes":total, "cases":len(results), "variant":args.variant,
              "normalized_calls":sum(r["normalized_calls"] for r in results),
              "strict_operation_passes":sum(r["strict_operation_gate_pass"] for r in results),
              "feedback_deliveries":sum(r["feedback_deliveries"] for r in results),
              "recovered_objectives":sum(r["recovered_objective"] for r in results),
              "information_requirements_satisfied":sum(r["information_completion"]["information_requirement_satisfied"] for r in results),
              "model_stopped_with_missing_information":sum(r["information_completion"]["model_stopped"] and not r["information_completion"]["information_requirement_satisfied"] for r in results),
              "continued_turns":sum(r["continued"] for r in results),
              "continued_information_satisfied":sum(r["continued"] and r["information_completion"]["information_requirement_satisfied"] for r in results),
              "resource_stop_counts":{reason:sum((r.get("resource_budget") or {}).get("stop_reason") == reason for r in results)
                                      for reason in sorted({r["resource_budget"]["stop_reason"] for r in results if r.get("resource_budget") and r["resource_budget"]["stop_reason"]})},
              "model_claim_format_valid":sum(r.get("model_claims",{}).get("format_status") == "VALID" for r in results),
              "claim_objective_passes":sum(r.get("claim_objective_pass",False) for r in results),
              "model_claim_verdict_counts":{status:sum(v["status"] == status for r in results for v in r.get("model_claims",{}).get("verdicts",[])) for status in ("VERIFIED","CONTRADICTED","UNSUPPORTED")},
              "host_claim_probe_counts":{status:sum(p["status"] == status for r in results for p in r["host_claim_probes"])
                                         for status in ("VERIFIED","CONTRADICTED","UNSUPPORTED")},
              "semantic_review":"PENDING", "results":results}
    (out / "e26b-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    if total != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
