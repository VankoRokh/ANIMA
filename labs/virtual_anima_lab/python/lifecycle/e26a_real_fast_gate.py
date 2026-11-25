"""E2.6a genuine local llama.cpp proposals on captured Godot observations."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import tempfile
import hashlib
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.cognition.local_fast import (
    LocalFastEvidenceAdapter, LocalFastChoiceAdapter,
)
from labs.virtual_anima_lab.python.cognition.native_lab import NativeLabAdapter
from labs.virtual_anima_lab.python.cognition.coordinator import (
    E25LabCognitiveCoordinator, TwoStepEvidenceStub,
)
from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .e21_gateway_live_gate import finish
from .egocentric import E23ObserverPort
from .e24_memory_live_gate import turn
from .e24_working_memory import (
    E24WorkingMemory, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)
from .world_smoke import PROJECT, _binary, _port, _wait


def require(ok, msg):
    if not ok:
        raise AssertionError(msg)


def operator_truth(port, key):
    with LabClient(port, role="operator", protocol=PROTOCOL_V2) as client:
        return client.call("inspect", auth=key)["data"]


def case(binary: str, seed: int, root: Path, *, base_url, model, profile, suite=False,
         suite_variant="baseline", suite_cases=None, project_path=None):
    project = PROJECT if project_path is None else Path(project_path)
    port = _port()
    keys = tuple(secrets.token_urlsafe(32) for _ in range(3))
    logfile = (root / f"e26a-world-{seed}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [binary, "--headless", "--path", str(project),
         "res://LifecycleWorld.tscn", "--",
         "--lifecycle-port", str(port), "--lifecycle-seed", str(seed),
         "--lifecycle-guarded", "--lifecycle-effects", "--lifecycle-ledger",
         "--lifecycle-egocentric", "--lifecycle-debug-ui"],
        cwd=project, stdout=logfile, stderr=subprocess.STDOUT,
        env={**os.environ,
             "ANIMA_LIFECYCLE_OBSERVER_KEY": keys[0],
             "ANIMA_LIFECYCLE_EXECUTOR_KEY": keys[1],
             "ANIMA_LIFECYCLE_OPERATOR_KEY": keys[2]},
    )
    try:
        ready = _wait(process, port)
        ready.close()
        instance = build_core(
            root / f"e26a-core-{seed}",
            sources={SOURCE: vision_source_registration()},
            properties={(SUBJECT, PREDICATE): vision_digest_rule()},
        )
        memory = E24WorkingMemory(
            instance, E23ObserverPort(port=port, observer_key=keys[0]),
        )
        first = memory.observe_and_record()
        require("lab.item.crate" not in {
            x["entity_ref"] for x in memory.world_model()["entities"]
        }, "crate must not be initially visible")
        turn(port, keys[1], memory.raw_evidence(first.sample_id).as_dict(), f"e25turn1_{seed}")
        second = memory.observe_and_record()
        require("lab.item.crate" in {
            x["entity_ref"] for x in memory.world_model()["entities"]
        }, "crate should be visible when east-facing")
        turn(port, keys[1], memory.raw_evidence(second.sample_id).as_dict(), f"e25turn2_{seed}")
        third = memory.observe_and_record()
        require("lab.item.crate" not in {
            x["entity_ref"] for x in memory.world_model(memory_enabled=False)["entities"]
        }, "crate must no longer be visible")
        world_before = operator_truth(port, keys[2])
        coordinator = E25LabCognitiveCoordinator(memory, max_steps=4,
            ranked=suite and suite_variant in ("ranked", "refined", "feedback", "continuation", "budgeted", "budget_probe", "claims", "claims_separated", "temporal_sources", "temporal_completion"),
            error_feedback=suite and suite_variant in ("feedback", "feedback_probe", "continuation", "budgeted", "budget_probe", "claims", "claims_separated", "temporal_sources", "temporal_completion"),
            latest_observation=suite and suite_variant in ("temporal_sources","temporal_completion"))
        if suite:
            from .e26b_cognitive_suite import run_cases
            return run_cases(memory, coordinator, root, seed, base_url=base_url, model=model,
                             variant=suite_variant, selected_cases=suite_cases,
                             check_world=lambda: operator_truth(port, keys[2]) == world_before,
                             check_core=lambda: len(instance.event_log.load_events()) == 3
                             and instance.memory_store.count() == 0
                             and instance.core_execution is None)
        results = []
        for enabled in (True, False):
            for mode in ("STUB", "FAST"):
                turn_id = f"{mode.lower()}_{seed}_{'on' if enabled else 'off'}"
                trace_path = root / f"{turn_id}-model-calls.jsonl"
                if mode == "STUB":
                    adapter = TwoStepEvidenceStub()
                elif profile in ("native", "native_required"):
                    adapter = NativeLabAdapter(base_url=base_url, model=model,
                        trace_path=trace_path, task="Find and verify previous observations of the crate.",
                        first_tool_required=(profile == "native_required"))
                else:
                    adapter_type = LocalFastChoiceAdapter if profile == "choice" else LocalFastEvidenceAdapter
                    adapter = adapter_type(base_url=base_url, model=model, trace_path=trace_path)
                report = coordinator.run_turn(adapter, turn_id=turn_id,
                                               memory_enabled=enabled)
                trace = coordinator.decision_records(turn_id)
                require(operator_truth(port, keys[2]) == world_before,
                        "read-only cognition mutated world")
                require(len(instance.event_log.load_events()) == 3
                        and instance.memory_store.count() == 0
                        and instance.core_execution is None,
                        "read-only turn mutated canonical state")
                rows = [row for o in report["outcomes"]
                        if o["status"] == "COMPLETED" and
                        o["operation_kind"] == "retrieve_memory"
                        for row in o["result"]["records"]
                        if row["entity_ref"] == "lab.item.crate"]
                proofs = [row for o in report["outcomes"]
                          if o["status"] == "COMPLETED" and
                          o["operation_kind"] == "lookup_raw_evidence"
                          for row in o["result"]["records"]
                          if row["status"] == "verified_source_view"
                          and "lab.item.crate" in row["entities_observed"]]
                calls = [] if mode == "STUB" else adapter.calls
                if not enabled:
                    require(not rows and not proofs, "memory-off exposed crate history")
                success = (
                    report["status"] == "STOPPED" and
                    (bool(proofs) if enabled else not rows and not proofs) and
                    (enabled or any(o["operation_kind"] == "retrieve_memory"
                                    and o["status"] == "COMPLETED"
                                    for o in report["outcomes"])) and
                    (mode == "STUB" or bool(calls) and all(c["valid"] for c in calls))
                )
                searched_crate = any(r["proposal"] is not None
                                     and r["proposal"]["operation_kind"] == "retrieve_memory"
                                     and "crate" in r["proposal"]["arguments"]["query"].lower()
                                     and r["outcome"]["status"] == "COMPLETED" for r in trace)
                result = {"seed": seed, "mode": mode, "memory_enabled": enabled,
                          "profile": profile if mode == "FAST" else "stub",
                          "searched_crate": searched_crate,
                          "target_quality_pass": bool(success and (enabled or searched_crate)),
                          "safe_stop_without_search": bool(not enabled and not rows and not proofs
                              and report["status"] == "STOPPED" and not report["outcomes"]),
                          "turn_status": report["status"], "quality_pass": bool(success),
                          "operations": [o.get("operation_kind") for o in report["outcomes"]],
                          "remembered_crate": bool(rows), "verified_crate_source": bool(proofs),
                          "model_calls": len(calls),
                          "transport_successes": sum(c["transport_ok"] for c in calls),
                          "valid_model_outputs": sum(c["valid"] for c in calls),
                          "latency_ms": [c.get("latency_ms") for c in calls],
                          "input_tokens": [c.get("input_tokens") for c in calls],
                          "output_tokens": [c.get("output_tokens") for c in calls],
                          "world_unchanged": True,
                          "final_text": calls[-1].get("final_text") if calls else None,
                          "native_tool_calls": sum("tool_name" in c for c in calls),
                          "native_result_messages_sent": sum(
                              sum(m["role"] == "tool" for m in c.get("request", {}).get("messages", []))
                              for c in calls),
                          "model_stopped": report["status"] == "STOPPED" and mode == "FAST",
                          "first_tool_required": mode == "FAST" and profile == "native_required",
                          "first_call_valid_tool": bool(calls and calls[0]["valid"] and
                                                        "tool_name" in calls[0])}
                (root / f"{turn_id}-result.json").write_text(
                    json.dumps({"result": result, "turn": report, "trace": trace},
                               ensure_ascii=False, indent=2), encoding="utf-8")
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if mode == "STUB":
                    require(success, "stub regression")
        return results
    finally:
        finish(process, logfile)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--godot", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8085")
    ap.add_argument("--model", default="Qwen3-0.6B-Q8_0")
    ap.add_argument("--model-file", type=Path, required=True)
    ap.add_argument("--evidence-dir", type=Path)
    ap.add_argument("--profile", choices=("legacy", "choice", "native", "native_required"), default="legacy")
    args = ap.parse_args()
    url = urlsplit(args.base_url)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
            or url.port is None or url.path not in ("", "/")
            or url.username or url.password or url.query or url.fragment):
        ap.error("loopback llama-server only")
    with urllib.request.urlopen(args.base_url.rstrip("/") + "/v1/models", timeout=10) as response:
        server_models = json.loads(response.read(65536))
    require(any(x.get("id") == args.model for x in server_models["data"]),
            "server model ID differs from requested alias")
    with args.model_file.open("rb") as stream:
        model_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    out = args.evidence_dir or Path(tempfile.mkdtemp(prefix="anima-e26a-"))
    out.mkdir(parents=True, exist_ok=True)
    require(not any(out.iterdir()), "evidence directory must be empty; preserve prior runs")
    print(f"Evidence directory: {out}", flush=True)
    manifest = {"profile": args.profile,
                "first_tool_required": args.profile == "native_required", "model_alias": args.model, "local_file": args.model_file.name,
                "local_file_sha256": model_hash, "server_models": server_models,
                "file_hash_not_attested_by_server": True,
                "temperature": 0, "max_output_tokens": 256, "max_steps": 4}
    (out / "model-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    cases = []
    for seed in (7, 8):
        cases.extend(case(_binary(args.godot), seed, out,
                          base_url=args.base_url, model=args.model, profile=args.profile))
    fast = [c for c in cases if c["mode"] == "FAST"]
    transport_ok = all(c["model_calls"] > 0 and
                       c["transport_successes"] == c["model_calls"] for c in fast)
    report = {"schema": "anima.e26a.real_fast_readonly/0.1",
              "status": "E2_6A_MODEL_RUN_COMPLETE" if transport_ok else "E2_6A_TRANSPORT_FAIL",
              "profile": args.profile,
              "fast_target_quality_passes": sum(c["target_quality_pass"] for c in fast),
              "fast_quality_passes": sum(c["quality_pass"] for c in fast),
              "fast_cases": len(fast), "cases": cases,
              "world_action_authority": False, "no_fallback": True,
              "scope": "real Godot captured Raw; read-only model proposals"}
    (out / "e26a-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, sort_keys=True), flush=True)
    if not transport_ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
