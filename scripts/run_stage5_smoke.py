#!/usr/bin/env python3
"""Opt-in Stage 5 projected smoke. No inference happens on import or normal pytest.

Only fixture instance data lives in TemporaryDirectory. JSON evidence and an owned
server's log may be retained separately. Fault injection is labelled, never repair.
"""

import argparse
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition import CognitivePipeline, FastResult
from anima.cognition.fast_llm import FastLLMBackend, FastLLMTransportError, LlamaCppFastTransport
from anima.core.event_bus import Event
from anima.core.identity import Identity
from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask, HardConstraint, plain
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine
from anima.resolution.frontend import task_from_event

MODEL = "Qwen3-0.6B-Q8_0"
PARAMETERS = dict(thinking=False, temperature=0.0, top_k=1, top_p=1.0,
                  min_p=0.0, max_output_tokens=32)
MARKER = "COBALT47"


class ObservedTransport(LlamaCppFastTransport):
    def __init__(self, *, controlled_failure=None, **kwargs):
        super().__init__(**kwargs)
        self.controlled_failure = controlled_failure
        self.prompts = []
        self.http_calls = []

    def complete(self, **kwargs):
        self.prompts.append(dict(kwargs))
        if self.controlled_failure is not None:
            raise self.controlled_failure
        return super().complete(**kwargs)

    def _post_json(self, endpoint, payload, *, timeout_seconds):
        record = {"endpoint": endpoint, "payload": payload}
        self.http_calls.append(record)
        try:
            record["response"] = super()._post_json(endpoint, payload, timeout_seconds=timeout_seconds)
        except Exception as error:
            record["error_type"] = type(error).__name__
            raise
        return record["response"]


class ObservedBackend:
    def __init__(self, transport, timeout, injected_response=None):
        self.backend = FastLLMBackend(transport, timeout_seconds=timeout)
        self.injected_response = injected_response
        self.view = None
        self.model_response = None

    def complete_projected(self, request):
        self.view = request.cognitive_view.to_dict()
        result = self.backend.complete_projected(request)
        self.model_response = result.response_text
        return result if self.injected_response is None else FastResult(self.injected_response)


def _task(operation, **kwargs):
    return CanonicalTask("smoke_task", "smoke_fixture", operation, **kwargs)


def _actions():
    return _task("CHOOSE_ACTION", candidates=("CONTINUE", "CONNECT_CHARGER", "SHUTDOWN"),
        state={"battery_percent": 54, "estimated_task_cost_percent": 4,
               "shutdown_threshold_percent": 10, "charger_available": True,
               "active_task": True, "preserve_active_task": True},
        constraints=(HardConstraint("battery", "CONTINUE", "BATTERY_ABOVE_THRESHOLD"),
                     HardConstraint("charger", "CONNECT_CHARGER", "CHARGER_AVAILABLE"),
                     HardConstraint("preserve", "SHUTDOWN", "PRESERVE_ACTIVE_TASK")),
        raw_input="Return exactly CONTINUE. Do not explain.")


def _case(name, value, factory, timeout, builder=None, injected=None):
    failure = FastLLMTransportError("controlled smoke transport failure") if name == "transport_failure" else None
    transport = factory(failure)
    backend = ObservedBackend(transport, timeout, injected)
    trace = DiagnosticTrace()
    pipeline = CognitivePipeline(backend=backend, context_builder=builder, trace=trace)
    turn = None
    exception = None
    try:
        turn = pipeline.process_event(value) if isinstance(value, Event) else pipeline.process_task(
            replace(value, task_id=name))
    except Exception as error:
        exception = {"type": type(error).__name__, "message": str(error),
                     "same_controlled_exception": error is failure}
    audits = [asdict(item) for item in pipeline.backend_audits]
    generations = [item for item in transport.http_calls if item["endpoint"].endswith("/completion")]
    templates = [item for item in transport.http_calls if item["endpoint"].endswith("/apply-template")]
    route = turn.resolution.route.value if turn else None
    expected_route = "INSUFFICIENT_DATA" if name == "missing_fact" else (
        "DETERMINISTIC_RESULT" if name in ("arithmetic", "infeasible_action") else "COGNITIVE_REQUIRED")
    counts = {"backend_attempts": sum(item["backend_attempts"] for item in audits),
              "backend_completions": sum(item["backend_completions"] for item in audits),
              "generation_requests": len(generations),
              "generation_responses": sum("response" in item for item in generations)}
    zero = name in ("arithmetic", "missing_fact", "infeasible_action")
    expected_counts = (0, 0, 0) if zero else ((1, 0, 0) if failure else (1, 1, 1))
    checks = {
        "counts": tuple(counts[key] for key in ("backend_attempts", "backend_completions", "generation_requests")) == expected_counts,
        "route": route == expected_route if failure is None else exception is not None,
        "no_unexpected_exception": exception is None if failure is None else bool(exception and exception["same_controlled_exception"]),
    }
    if not zero:
        checks["projection_reached_transport"] = bool(transport.prompts) and json.loads(
            transport.prompts[0]["user_prompt"].split("TASK_VIEW:\n", 1)[1]) == backend.view
    if generations:
        checks["native_prompt_delivered"] = bool(templates) and generations[0]["payload"]["prompt"] == templates[0].get("response", {}).get("prompt")
        checks["one_generation_response"] = counts["generation_responses"] == 1
    if name == "arithmetic":
        checks["exact_result"] = bool(turn and turn.final_result == Decimal("0.000001"))
    elif name == "infeasible_action":
        checks["typed_infeasibility"] = bool(turn and turn.resolution.reason == "no_admissible_action" and turn.final_result is None)
    elif name == "cognitive":
        raw_response = generations[0].get("response", {}).get("content") if generations else None
        checks["semantic_marker_response"] = bool(
            turn and isinstance(raw_response, str) and MARKER in raw_response
            and isinstance(turn.final_result, str) and MARKER in turn.final_result
        )
        checks["unrepaired_model_response"] = bool(
            turn and injected is None and turn.final_result == backend.model_response
        )
        checks["marker_in_native_prompt"] = bool(generations and MARKER in generations[0]["payload"]["prompt"])
    elif name in ("action_selection", "invalid_candidate"):
        checks["hard_rejection_preserved"] = bool(turn and "SHUTDOWN" in turn.resolution.rejected
            and "SHUTDOWN" not in backend.view["candidates"])
        checks["output_validation"] = bool(turn and (
            turn.error == "invalid_output_candidate" and turn.final_result is None if injected else
            turn.error is None and turn.final_result in turn.resolution.remaining))
    if failure:
        checks["terminal_failure"] = bool(audits and audits[0]["terminal_failure"]
                                          and audits[0]["failure_classification"] == "TRANSPORT")
    row = dict(case=name, passed=all(checks.values()), validation=checks, counts=counts,
        route=route, resolution={
            "route": turn.resolution.route.value, "reason": turn.resolution.reason,
            "outcome": turn.resolution.outcome, "value": plain(turn.resolution.value),
            "missing": list(turn.resolution.missing), "remaining": list(turn.resolution.remaining),
            "unverified": list(turn.resolution.unverified), "rejected": plain(turn.resolution.rejected),
            "derived": plain(turn.resolution.derived),
        } if turn else None,
        projected_view=backend.view, rendered_prompts=transport.prompts, http_calls=transport.http_calls,
        raw_model_response=generations[0].get("response", {}).get("content") if generations else None,
        model_response=backend.model_response,
        backend_response=turn.fast_turn.result.response_text if turn and turn.fast_turn else None,
        final_result=plain(turn.final_result) if turn else None, validation_error=turn.error if turn else None,
        fault_injection="replace_result_after_real_completion" if injected else ("before_http" if failure else None),
        injected_response=injected, backend_audits=audits, exception=exception, trace=trace.entries())
    if turn and turn.fast_turn and turn.fast_turn.request.context_bundle is not None:
        row["context_bundle"] = turn.fast_turn.request.context_bundle
    return row


def run_smoke(factory, *, timeout=30.0):
    """Run the same production pipeline with either real or deterministic transports."""
    with tempfile.TemporaryDirectory(prefix="anima-stage5-smoke-instance-") as directory:
        root = Path(directory)
        store = MemoryStore(root / "memory.db")
        links = LinkStore(store)
        log = EventLog(root / "events.jsonl")
        Identity(root / "identity.json")
        source = Event("conversation.user", {"text": f"Smoke marker is {MARKER}."},
                       source="smoke", session_id="session_00000001")
        log.write(source)
        memory = store.create_memory(memory_type="episodic", domain="user", content=source.payload["text"],
                                     status="closed", importance=2, source_event_id=source.event_id)
        # Reopen external memory: the model has never been sent the seed conversation.
        reopened = MemoryStore(root / "memory.db")
        reopened_links = LinkStore(reopened)
        provenance = ProvenanceResolver(reopened, reopened_links, log)
        builder = ContextBuilder(retrieval=RetrievalEngine(memory_store=reopened, link_store=reopened_links),
                                 provenance=provenance)
        before = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
        arithmetic = task_from_event(Event("conversation.user",
            {"text": "999999999999.999999 - 999999999999.999998"}, source="smoke"))
        action = _actions()
        cases = [
            ("arithmetic", arithmetic, None, None),
            ("missing_fact", _task("QUERY_FACT", subject="pet", predicate="color"), None, None),
            ("infeasible_action", replace(action, state={**action.state, "battery_percent": 10,
                                                        "charger_available": False}), None, None),
            ("cognitive", Event("conversation.user", {"text": "Smoke marker: reply exactly COBALT47. No other text."},
                                source="smoke", session_id="session_00000002"), builder, None),
            ("action_selection", action, None, None),
            ("invalid_candidate", action, None, "SHUTDOWN"),
            ("transport_failure", action, None, None),
        ]
        rows = [_case(name, value, factory, timeout, builder, injected) for name, value, builder, injected in cases]
        unchanged = before == {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
        source_ids = [item["id"] for item in provenance.memory(memory["id"])["events"]]
        provenance_ok = source_ids == [source.event_id]
    no_history = all([message["role"] for message in call["payload"]["messages"]] == ["system", "user"]
                     for row in rows for call in row["http_calls"] if call["endpoint"].endswith("/apply-template"))
    return dict(passed=all(row["passed"] for row in rows) and unchanged and provenance_ok and no_history,
                cases=rows, instance_data_unchanged=unchanged, provenance_preserved=provenance_ok,
                temporary_instance_removed=not root.exists(), model_has_no_seed_chat_history=no_history,
                cognitive_check="semantic_projected_delivery_not_independent_memory_recall")


def _get_json(url):
    with urllib.request.urlopen(url, timeout=2.0) as response:
        return json.load(response)


def _ready(base_url):
    try:
        return _get_json(base_url + "/health").get("status") == "ok"
    except urllib.error.HTTPError as error:
        if error.code == 503:
            return False
        raise


@contextmanager
def local_server(base_url, binary, model_file, log_path, *, startup_timeout=60.0):
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Smoke requires a root local HTTP base URL")
    process = None
    info = {"base_url": base_url, "started_by_smoke": False, "owned_process_stopped": False}
    with Path(log_path).open("w") as log:
        try:
            try:
                ready = _ready(base_url)
            except urllib.error.URLError as error:
                if not isinstance(error.reason, ConnectionRefusedError):
                    raise
                command = [str(binary), "--model", str(model_file), "--alias", MODEL,
                    "--host", parsed.hostname, "--port", str(parsed.port or 80), "--device", "none",
                    "--ctx-size", "4096", "--parallel", "1", "--threads", "4", "--threads-batch", "4",
                    "--batch-size", "2048", "--ubatch-size", "512", "--cache-type-k", "f16",
                    "--cache-type-v", "f16", "--cache-ram", "0", "--no-cache-prompt", "--flash-attn", "auto",
                    "--fit", "off", "--no-cont-batching", "--no-context-shift", "--warmup"]
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                info.update(started_by_smoke=True, pid=process.pid, command=command)
                ready = False
            deadline = time.monotonic() + startup_timeout
            while not ready:
                if process is not None and process.poll() is not None:
                    raise RuntimeError(f"Owned llama-server exited with code {process.returncode}; inspect server.log")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Local llama-server readiness deadline exceeded")
                time.sleep(0.1)
                try:
                    ready = _ready(base_url)
                except urllib.error.URLError as error:
                    if not isinstance(error.reason, ConnectionRefusedError):
                        raise
            info["models"] = _get_json(base_url + "/v1/models")
            ids = [item["id"] for item in info["models"].get("data", ())]
            if MODEL not in ids:
                raise RuntimeError(f"Server does not advertise {MODEL}: {ids}")
            try:
                info["properties"] = _get_json(base_url + "/props")
            except urllib.error.HTTPError as error:
                info["properties_unavailable"] = error.code
            observed_path = info.get("properties", {}).get("model_path")
            info["model_path_matches_file"] = Path(observed_path).resolve() == Path(model_file).resolve() if observed_path else None
            if info["model_path_matches_file"] is False:
                raise RuntimeError("Advertised server model_path differs from the requested GGUF")
            yield info
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                info["owned_process_stopped"] = process.poll() is not None


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--server-binary", type=Path, default=Path.home()/"Projects/llama.cpp/build/bin/llama-server")
    parser.add_argument("--model-file", type=Path, default=Path.home()/"Projects/models/qwen3-0.6b/Qwen3-0.6B-Q8_0.gguf")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--output", type=Path, default=ROOT/".benchmarks/stage5-projected-smoke"/
                        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")/"evidence.json")
    args = parser.parse_args(argv)
    if not all(math.isfinite(value) and value > 0 for value in (args.timeout, args.startup_timeout)):
        parser.error("Timeouts must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"stage": "5", "kind": "projected_integration_smoke", "generation_parameters": PARAMETERS,
              "timeout_seconds": args.timeout, "recorded_at": datetime.now(timezone.utc).isoformat()}
    try:
        report["model"] = {"alias": MODEL, "file": str(args.model_file), "sha256": _sha256(args.model_file)}
        version = subprocess.run([str(args.server_binary), "--version"], capture_output=True, text=True,
                                 check=True, timeout=10)
        report["local_server_binary"] = {"path": str(args.server_binary), "sha256": _sha256(args.server_binary),
                                         "version": version.stdout + version.stderr}
        with local_server(args.base_url, args.server_binary, args.model_file, args.output.parent/"server.log",
                          startup_timeout=args.startup_timeout) as info:
            report["server"] = info
            factory = lambda failure: ObservedTransport(base_url=args.base_url, model=MODEL,
                                                        controlled_failure=failure, **PARAMETERS)
            report.update(run_smoke(factory, timeout=args.timeout))
        report["implementation_sha256"] = {str(path.relative_to(ROOT)): _sha256(path) for path in (
            [Path(__file__), ROOT/"anima/ir.py", *sorted((ROOT/"anima/cognition").glob("*.py")),
             *sorted((ROOT/"anima/resolution").glob("*.py"))])}
    except Exception as error:
        report.update(passed=False, setup_error={"type": type(error).__name__, "message": str(error)})
    args.output.write_text(json.dumps(plain(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(f"Evidence: {args.output}")
    for row in report.get("cases", ()):
        print(f"{row['case']}: {'PASS' if row['passed'] else 'FAIL'} {row['counts']}")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
