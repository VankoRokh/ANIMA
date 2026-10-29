#!/usr/bin/env python3
"""Run the ANIMA Tool Model Benchmark against a local Qwen-Agent backend.

The benchmark uses temporary ANIMA data and writes local evidence under
.benchmarks/. It never touches the normal ANIMA data directory.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from urllib import request

from anima.benchmarks.tool_models import (
    BenchmarkTurn,
    RunObservation,
    ToolCallObservation,
    append_comparison_csv,
    evaluate_case,
    model_file_metadata,
    observation_to_dict,
    render_markdown_report,
    slugify,
    summarize_observations,
    write_case_csv,
    write_comparison_markdown,
    write_json_report,
)
from anima.benchmarks.tool_model_corpus import (
    BENCHMARK_SYSTEM_PROMPT,
    BENCHMARK_VERSION,
    MEMORY_FIXTURES,
    benchmark_cases,
)
from anima.cognition.qwen_agent_tools import (
    AnimaReadOnlyToolGateway,
    QwenAgentToolLoop,
    build_qwen_agent_chat_model,
)
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.retrieval import RetrievalEngine


def seed_memory(store: MemoryStore) -> None:
    for public_id, event_id, timestamp, domain, content, importance in MEMORY_FIXTURES:
        store.create_memory(
            memory_type="episodic",
            domain=domain,
            content=content,
            status="closed",
            importance=importance,
            created_at=timestamp,
            public_id=public_id,
            source_event_id=event_id,
        )


def build_gateway(root: Path) -> AnimaReadOnlyToolGateway:
    memory_store = MemoryStore(root / "memory.db")
    links = LinkStore(memory_store)
    seed_memory(memory_store)
    retrieval = RetrievalEngine(memory_store=memory_store, link_store=links)

    state_store = InternalStateStore(root / "internal_state.db")
    state_runtime = InternalStateRuntime(state_store)
    state_runtime.create_goal(
        source="benchmark",
        priority=2.0,
        description="Evaluate tool-model candidates",
        success_criterion="Complete the fixed ten-scenario benchmark",
        reason="Benchmark fixture",
        timestamp="2026-10-29T13:00:00+00:00",
        public_id="goal_88888888-8888-4888-8888-888888888888",
        transition_id="gt_99999999-9999-4999-8999-999999999999",
    )

    return AnimaReadOnlyToolGateway(
        retrieval=retrieval,
        internal_state_runtime=state_runtime,
    )


def qwen_turn_to_benchmark(turn) -> BenchmarkTurn:
    return BenchmarkTurn(
        response_text=turn.response_text,
        rounds=turn.rounds,
        tool_calls=tuple(
            ToolCallObservation(
                round_index=call.round_index,
                name=call.name,
                arguments=dict(call.arguments),
                result=dict(call.result),
            )
            for call in turn.tool_calls
        ),
    )


def check_server(base_url: str, timeout: float = 3.0) -> None:
    url = base_url.rstrip("/") + "/models"
    try:
        with request.urlopen(url, timeout=timeout) as response:
            if response.status >= 400:
                raise RuntimeError(f"server health check returned HTTP {response.status}")
    except Exception as error:
        raise RuntimeError(
            f"OpenAI-compatible server is unavailable at {url}: {error}"
        ) from error


def discover_llama_server_pid() -> int | None:
    candidates = []
    proc = Path("/proc")
    if not proc.exists():
        return None
    for child in proc.iterdir():
        if not child.name.isdigit():
            continue
        try:
            comm = (child / "comm").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if comm in {"llama-server", "server"}:
            candidates.append(int(child.name))
    return candidates[0] if len(candidates) == 1 else None


def _read_proc_memory(pid: int) -> dict:
    status_path = Path(f"/proc/{pid}/status")
    try:
        lines = status_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"rss_mib": None, "vmhwm_mib": None}
    values = {}
    for line in lines:
        if line.startswith(("VmRSS:", "VmHWM:")):
            key, raw = line.split(":", 1)
            number = raw.strip().split()[0]
            values[key] = int(number) / 1024.0
    return {
        "rss_mib": values.get("VmRSS"),
        "vmhwm_mib": values.get("VmHWM"),
    }


def _gpu_memory_mib(pid: int) -> float | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    total = 0.0
    found = False
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            row_pid = int(parts[0])
            memory = float(parts[1])
        except ValueError:
            continue
        if row_pid == pid:
            total += memory
            found = True
    return total if found else None


class ServerResourceMonitor:
    def __init__(self, pid: int | None, interval=0.25):
        self.pid = pid
        self.interval = interval
        self.rss_before_mib = None
        self.rss_peak_mib = None
        self.vmhwm_mib = None
        self.gpu_vram_peak_mib = None
        self._stop = threading.Event()
        self._thread = None

    def _sample(self):
        if self.pid is None:
            return
        memory = _read_proc_memory(self.pid)
        rss = memory["rss_mib"]
        hwm = memory["vmhwm_mib"]
        if rss is not None:
            self.rss_peak_mib = (
                rss if self.rss_peak_mib is None else max(self.rss_peak_mib, rss)
            )
        if hwm is not None:
            self.vmhwm_mib = (
                hwm if self.vmhwm_mib is None else max(self.vmhwm_mib, hwm)
            )
        gpu = _gpu_memory_mib(self.pid)
        if gpu is not None:
            self.gpu_vram_peak_mib = (
                gpu
                if self.gpu_vram_peak_mib is None
                else max(self.gpu_vram_peak_mib, gpu)
            )

    def _run(self):
        while not self._stop.wait(self.interval):
            self._sample()

    def start(self):
        if self.pid is None:
            return
        initial = _read_proc_memory(self.pid)
        self.rss_before_mib = initial["rss_mib"]
        self.vmhwm_mib = initial["vmhwm_mib"]
        self._sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self.pid is None:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval * 4))
        self._sample()

    def as_dict(self):
        return {
            "server_pid": self.pid,
            "rss_before_mib": self.rss_before_mib,
            "rss_peak_mib": self.rss_peak_mib,
            "vmhwm_mib": self.vmhwm_mib,
            "gpu_vram_peak_mib": self.gpu_vram_peak_mib,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="Qwen3-0.6B-Q8_0")
    parser.add_argument(
        "--model-file",
        default=None,
        help="GGUF path, used only for size metadata",
    )
    parser.add_argument("--parameters-b", type=float, default=0.6)
    parser.add_argument("--quantization", default="Q8_0")
    parser.add_argument("--thinking", choices=("off", "on"), default="off")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--server-pid", type=int, default=None)
    parser.add_argument("--output-dir", default=".benchmarks/tool-models")
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.max_tokens < 32:
        parser.error("--max-tokens must be at least 32")

    check_server(args.base_url)
    model_file = model_file_metadata(args.model_file)
    server_pid = (
        args.server_pid
        if args.server_pid is not None
        else discover_llama_server_pid()
    )

    llm = build_qwen_agent_chat_model(
        model=args.model,
        model_server=args.base_url,
        thinking=args.thinking == "on",
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    observations: list[RunObservation] = []
    resource_monitor = ServerResourceMonitor(server_pid)
    resource_monitor.start()

    try:
        with tempfile.TemporaryDirectory(
            prefix="anima_tool_model_bench_"
        ) as temp_dir:
            gateway = build_gateway(Path(temp_dir))
            loop = QwenAgentToolLoop(
                llm=llm,
                gateway=gateway,
                system_prompt=BENCHMARK_SYSTEM_PROMPT,
                max_tool_rounds=4,
            )

            for case in benchmark_cases():
                for repeat in range(1, args.repeats + 1):
                    started = time.perf_counter()
                    turn = None
                    error_text = None
                    try:
                        qwen_turn = loop.run(case.query)
                        turn = qwen_turn_to_benchmark(qwen_turn)
                    except Exception as error:
                        error_text = f"{type(error).__name__}: {error}"
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    evaluation = evaluate_case(case, turn, error=error_text)
                    observation = RunObservation(
                        case_id=case.id,
                        repeat=repeat,
                        latency_ms=latency_ms,
                        turn=turn,
                        evaluation=evaluation,
                        error=error_text,
                    )
                    observations.append(observation)
                    tools = (
                        "—"
                        if turn is None or not turn.tool_calls
                        else ">".join(call.name for call in turn.tool_calls)
                    )
                    status = "PASS" if evaluation.passed else "FAIL"
                    print(
                        f"[{status}] {case.id} repeat={repeat}/{args.repeats} "
                        f"latency={latency_ms:.1f}ms tools={tools}"
                    )
                    if error_text:
                        print(f"        error: {error_text}")
    finally:
        resource_monitor.stop()

    summary = summarize_observations(observations)
    resources = resource_monitor.as_dict()
    resources["model_size_bytes"] = model_file["size_bytes"]
    resources["model_size_mib"] = model_file["size_mib"]
    resources["model_file"] = model_file["path"]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{slugify(args.model)}"
    payload = {
        "benchmark": BENCHMARK_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": {
            "name": args.model,
            "adapter": "qwen-agent-nous",
            "parameters_b": args.parameters_b,
            "quantization": args.quantization,
            "base_url": args.base_url,
            "thinking": args.thinking,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
        },
        "repeats": args.repeats,
        "cases": [asdict(case) for case in benchmark_cases()],
        "summary": summary,
        "resources": resources,
        "observations": [observation_to_dict(item) for item in observations],
    }

    output_root = Path(args.output_dir)
    run_dir = output_root / run_id
    write_json_report(run_dir / "results.json", payload)
    write_case_csv(run_dir / "cases.csv", observations)
    (run_dir / "report.md").write_text(
        render_markdown_report(payload),
        encoding="utf-8",
    )
    comparison_csv = output_root / "comparison.csv"
    append_comparison_csv(comparison_csv, payload)
    write_comparison_markdown(comparison_csv, output_root / "comparison.md")

    print("\nSUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nRESOURCES")
    print(json.dumps(resources, ensure_ascii=False, indent=2))
    print(f"\nEvidence: {run_dir}")


if __name__ == "__main__":
    main()
