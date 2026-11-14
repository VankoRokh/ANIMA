"""ANIMA v0.1 provisional notebook acceptance: real Core, no LLM/Godot/Pi.

Returns scoped evidence, not a production-readiness verdict. Files are written
only to a new temporary instance and an optional non-overwritten JSON report.
"""

import argparse
import json
import math
import platform
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from anima.release_v01 import open_release

SCHEMA = "anima.v0_1.acceptance/0.1"
ROOT = Path(__file__).resolve().parents[1]


def _child(data_dir, commands, *, sandbox=False):
    args = [sys.executable, "-B", "-m", "anima.release_v01",
            "--data-dir", str(data_dir)]
    if sandbox:
        args.append("--sandbox-door")
    payload = "".join(
        json.dumps(cmd, ensure_ascii=False) + "\n" for cmd in commands
    )
    started = time.perf_counter()
    result = subprocess.run(
        args, cwd=ROOT, input=payload,
        text=True, capture_output=True, timeout=120, check=False,
    )
    if result.returncode:
        raise AssertionError(
            f"v0.1 child failed {result.returncode}: {result.stderr[-4000:]}"
        )
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    if len(rows) != len(commands) + 1:
        raise AssertionError("Missing or extra release protocol records")
    return rows, time.perf_counter() - started


def _percentile(values, quantile):
    ordered = sorted(values)
    return round(ordered[math.ceil(quantile * len(ordered)) - 1], 3)


def _git_sha():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def run_gate(events=128):
    if not isinstance(events, int) or isinstance(events, bool) or not 16 <= events <= 1000:
        raise ValueError("events must be an integer between 16 and 1000")
    with tempfile.TemporaryDirectory(prefix="anima-v01-acceptance-") as folder:
        root = Path(folder)
        base = root / "base"
        first, first_s = _child(base, [
            {"op": "report", "text": "ambercoil earlier reading 82 C tag oldheatstamp"},
            {"op": "report", "text": "ambercoil later reading 69 C tag newcoolstamp"},
            {"op": "stop"},
        ])
        ids = [first[1]["event_ids"][0], first[2]["event_ids"][0]]
        second, second_s = _child(base, [
            {"op": "search_events", "query": "oldheatstamp"},
            {"op": "search_events", "query": "newcoolstamp"},
            {"op": "context", "query": "ambercoil"},
            {"op": "stop"},
        ])
        assert first[0]["result"]["instance_id"] == second[0]["result"]["instance_id"]
        assert ids[0] != ids[1]
        assert [row["id"] for row in second[1]["result"]["results"]] == ids[:1]
        assert [row["id"] for row in second[2]["result"]["results"]] == ids[1:]
        assert second[1]["result"]["coverage"]["status"] == "complete"
        bundle = second[3]["result"]
        assert 0 < bundle["selection_stats"]["items_used"] <= 4
        assert bundle["selection_stats"]["chars_used"] <= 900

        sandbox = root / "sandbox"
        action, action_s = _child(sandbox, [
            {"op": "report", "text": "User claims the door is closed"},
            {"op": "ensure_sandbox_door_closed"},
            {"op": "stop"},
        ], sandbox=True)
        proof = action[2]
        assert proof["goal_status"] == "completed"
        assert proof["task_statuses"] == ["completed"]
        assert len(proof["operation_ids"]) == 1
        again, again_s = _child(sandbox, [
            {"op": "status"}, {"op": "stop"},
        ], sandbox=True)
        assert action[0]["result"]["instance_id"] == again[0]["result"]["instance_id"]
        with sqlite3.connect(sandbox / "sandbox_world" / "virtual_door.db") as conn:
            effect_count = conn.execute(
                "SELECT COUNT(*) FROM door_effects WHERE applied=1"
            ).fetchone()[0]
        assert effect_count == 1

        # Distinct resource baseline. No hidden real model/world,
        # no performance PASS without an agreed resource budget.
        latency = []
        perf = root / "perf"
        with open_release(perf) as instance:
            for i in range(events):
                started = time.perf_counter()
                row = instance.handle({
                    "op": "report",
                    "text": f"runtime check {i:04d} group-ambercoil token-{i:04d}",
                })
                latency.append((time.perf_counter() - started) * 1000)
                assert row["ok"] and len(row["event_ids"]) == 1
            indexed = instance._index_complete()
            assert indexed["status"] == "complete"
            assert indexed["indexed_events"] >= events
            memory_count = instance.core.memory_store.count()
            assert memory_count >= 1
            data = instance.core.memory_store.list_memories()
            mapped = {
                eid for memory in data
                for eid in instance.core.memory_store.source_events(memory["id"])
            }
            # A raw source must not silently disappear when Memory is compressed.
            report_ids = {
                event["id"] for event in instance.core.event_log.load_events()
                if event["type"] == "conversation.user"
            }
            assert len(report_ids) == events
            assert report_ids <= mapped
        with open_release(perf) as again:
            again._index_complete()
            for eid in report_ids:
                assert again.core.event_retrieval.get(eid) is not None

        sizes = {
            f.name: f.stat().st_size
            for f in perf.iterdir() if f.is_file() and f.suffix in {".db", ".jsonl"}
        }
        total_s = sum(latency) / 1000
        return {
            "schema": SCHEMA,
            "test_status": "FUNCTIONAL_GATE_PASS",
            "performance_status": "MEASURED_NOT_SLO_GATED",
            "source_sha": _git_sha(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "identity_reopen": True,
            "source_links": "ALL_ACCOUNTED",
            "event_index_complete": True,
            "sandbox_goal_status": proof["goal_status"],
            "sandbox_effects": effect_count,
            "model_calls": 0,
            "real_godot_used": False,
            "pi_tested": False,
            "power_loss_tested": False,
            "events": events,
            "memories": memory_count,
            "report_latency_ms": {
                "p50": _percentile(latency, 0.50),
                "p95": _percentile(latency, 0.95),
                "p99": _percentile(latency, 0.99),
            },
            "report_throughput_per_s": round(events / total_s, 2),
            "peak_self_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "storage_bytes": sizes,
            "two_process_m0_s": round(first_s + second_s, 3),
            "sandbox_action_and_reopen_s": round(action_s + again_s, 3),
        }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events", type=int, default=128)
    p.add_argument("--report", type=Path)
    args = p.parse_args(argv)
    result = run_gate(events=args.events)
    if args.report is not None:
        target = args.report.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=2, sort_keys=True)
            out.write("\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
