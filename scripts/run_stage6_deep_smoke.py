#!/usr/bin/env python3
"""Opt-in Stage 6.2b smoke for the first real DEEP candidate.

Starts one owned llama-server process on a dedicated localhost port, routes an
explicit evidence conflict through the production Stage 6 router/dispatcher and
checks that SmolLM3 produces the bounded response expected by the scenario.
Nothing here runs during import or normal pytest.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.cognition.deep_llm import DeepLLMProfile, build_llama_cpp_deep_backend
from anima.cognition.proposals import CognitiveDispatcher, CognitiveProposal
from anima.cognition.routing import CognitiveDestination, CognitiveRouter
from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask, Evidence
from anima.resolution import resolve
from anima.tasks.store import TaskStore


DEFAULT_BINARY = Path.home() / "Projects/llama.cpp/build/bin/llama-server"
DEFAULT_MODEL = (
    Path.home()
    / "Projects/models/tool-benchmark/smollm3-3b/SmolLM3-Q8_0.gguf"
)
DEFAULT_MODEL_LABEL = "SmolLM3-3B-Q8_0"
DEFAULT_PORT = 8082


class ForbiddenFastBackend:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        raise AssertionError("FAST must not be called for the DEEP smoke conflict")


def _get_json(url):
    with urllib.request.urlopen(url, timeout=2.0) as response:
        return json.load(response)


@contextmanager
def owned_llama_server(*, binary, model, alias, port, log_file, startup_timeout):
    base_url = f"http://127.0.0.1:{port}"
    try:
        _get_json(base_url + "/health")
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ConnectionRefusedError):
            raise RuntimeError("DEEP smoke port is occupied or unavailable") from error
    else:
        raise RuntimeError("DEEP smoke port is already occupied")

    command = [
        str(binary),
        "--model", str(model),
        "--alias", alias,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--device", "none",
        "--ctx-size", "4096",
        "--parallel", "1",
        "--threads", "4",
        "--threads-batch", "4",
        "--batch-size", "2048",
        "--ubatch-size", "512",
        "--cache-type-k", "f16",
        "--cache-type-v", "f16",
        "--cache-ram", "0",
        "--no-cache-prompt",
        "--flash-attn", "auto",
        "--fit", "off",
        "--no-cont-batching",
        "--no-context-shift",
        "--warmup",
    ]

    with log_file.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + startup_timeout
        try:
            while True:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"llama-server exited during startup with code {process.returncode}"
                    )
                try:
                    health = _get_json(base_url + "/health")
                except (urllib.error.URLError, TimeoutError, OSError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("llama-server readiness timeout")
                    time.sleep(0.25)
                    continue
                if isinstance(health, dict) and health.get("status") in {
                    "ok", "no slot available", "loading model",
                }:
                    if health.get("status") == "loading model":
                        if time.monotonic() >= deadline:
                            raise RuntimeError("llama-server model loading timeout")
                        time.sleep(0.25)
                        continue
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"unexpected llama-server health: {health!r}")
                time.sleep(0.25)
            yield base_url, command
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)


def deep_conflict_task():
    return CanonicalTask(
        task_id="stage6-deep-smoke",
        source_id="stage6-deep-smoke-source",
        operation="QUERY_FACT",
        subject="device",
        predicate="location",
        raw_input=(
            "Use only the supplied evidence metadata. If one fact is both newer "
            "and has higher confidence, reply exactly with that fact value. "
            "Otherwise reply exactly AMBIGUOUS."
        ),
        evidence=(
            Evidence(
                "old",
                "A",
                "device",
                "location",
                ("mem_old",),
                0.8,
                "2026-11-01T10:00:00+04:00",
            ),
            Evidence(
                "new",
                "B",
                "device",
                "location",
                ("mem_new",),
                1.0,
                "2026-11-02T10:00:00+04:00",
            ),
        ),
    )


def run_smoke(*, base_url, model_label, timeout_seconds):
    with tempfile.TemporaryDirectory(prefix="anima-stage6-deep-smoke-") as directory:
        store = TaskStore(Path(directory) / "tasks.db")
        persistent = store.create_task(
            source="stage6-deep-smoke",
            description="verify first real DEEP candidate",
            reason="smoke setup",
        )
        persistent = store.transition_task(
            persistent.public_id,
            "active",
            reason="smoke activated",
        )

        task = deep_conflict_task()
        resolution = resolve(task)
        trace = DiagnosticTrace()
        router = CognitiveRouter(trace=trace)
        decision = router.route(task, resolution)
        fast = ForbiddenFastBackend()
        profile = DeepLLMProfile(model=model_label)
        deep = build_llama_cpp_deep_backend(
            base_url=base_url,
            profile=profile,
            timeout_seconds=timeout_seconds,
        )
        dispatcher = CognitiveDispatcher(
            fast_backend=fast,
            deep_backend=deep,
            trace=trace,
        )

        started = time.perf_counter()
        turn = dispatcher.dispatch(
            decision,
            persistent_task_id=persistent.public_id,
            task=task,
            resolution=resolution,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        response = turn.proposal.payload["text"] if turn.proposal is not None else None
        passed = bool(
            decision.destination == CognitiveDestination.DEEP
            and turn.accepted
            and isinstance(response, str)
            and response.strip().upper() == "B"
            and fast.calls == 0
            and store.get_task(persistent.public_id).status == "active"
            and len(deep.call_history) == 1
        )
        call = deep.call_history[0].to_dict() if deep.call_history else None
        return {
            "passed": passed,
            "model": model_label,
            "routing_destination": decision.destination.value,
            "routing_reason": decision.reason,
            "proposal": turn.proposal.to_dict() if turn.proposal else None,
            "validation": {
                "accepted": turn.validation.accepted,
                "reason": turn.validation.reason,
            },
            "fast_calls": fast.calls,
            "persistent_task_status": store.get_task(persistent.public_id).status,
            "latency_ms": latency_ms,
            "model_call": call,
            "trace": trace.entries(),
        }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--model-label", default=DEFAULT_MODEL_LABEL)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--call-timeout", type=float, default=120.0)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.binary.is_file():
        print(f"[FAIL] llama-server not found: {args.binary}", file=sys.stderr)
        return 2
    if not args.model.is_file():
        print(f"[FAIL] model not found: {args.model}", file=sys.stderr)
        return 2
    if not args.model_label.strip():
        print("[FAIL] --model-label must be non-empty", file=sys.stderr)
        return 2
    if not 1 <= args.port <= 65535:
        print("[FAIL] --port must be within 1..65535", file=sys.stderr)
        return 2
    if args.startup_timeout <= 0 or args.call_timeout <= 0:
        print("[FAIL] timeouts must be positive", file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir or ROOT / ".benchmarks/stage6-deep-smoke" / stamp
    output.mkdir(parents=True, exist_ok=False)
    log_file = output / "server.log"

    try:
        with owned_llama_server(
            binary=args.binary,
            model=args.model,
            alias=args.model_label,
            port=args.port,
            log_file=log_file,
            startup_timeout=args.startup_timeout,
        ) as (base_url, command):
            evidence = run_smoke(
                base_url=base_url,
                model_label=args.model_label,
                timeout_seconds=args.call_timeout,
            )
            evidence["server_command"] = command
            evidence["model_path"] = str(args.model)
    except Exception as error:
        evidence = {
            "passed": False,
            "setup_or_runtime_error": {
                "type": type(error).__name__,
                "message": str(error),
            },
            "model": args.model_label,
            "model_path": str(args.model),
        }

    (output / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    status = "PASS" if evidence.get("passed") else "FAIL"
    print(f"[{status}] Stage 6 DEEP smoke: {args.model_label}")
    print(f"Evidence: {output / 'evidence.json'}")
    if evidence.get("proposal"):
        print("Response:", evidence["proposal"]["payload"].get("text"))
    if evidence.get("setup_or_runtime_error"):
        print(
            "Error:",
            evidence["setup_or_runtime_error"]["message"],
            file=sys.stderr,
        )
    return 0 if evidence.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
