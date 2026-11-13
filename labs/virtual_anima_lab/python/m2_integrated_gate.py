#!/usr/bin/env python3
"""M2: real Godot P6 door + source-backed Memory + bounded FAST + Core recovery.

Launches/cleans up fresh headless Godot worlds on random loopback ports.
Hard-exit cut points reuse P6's Executor seam. os._exit is NOT SIGKILL.
No production data, no actual LLM, no physical tools or power-loss claims.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile

from anima.cognition.fast import FastCognition, FastResult
from anima.core.door_world import DOOR_PREDICATE, DOOR_SOURCE, DOOR_SUBJECT
from anima.core.goal_decision import GoalCriterion
from anima.memory.context_builder import ContextBuilder
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine

from .p6_core_crash_recovery_gate import (
    ROOT, call, effect_events, free_port, operations, start_godot, stop_child,
)
from .run_core_demo import make_core

SCHEMA = "anima.memory_v1.integrated_godot_m2/0.1"
MODES = ("normal", "before", "after")
HISTORY = "Unverified earlier report claims that the virtual door is closed."
QUERY = "What did the earlier report claim about the virtual door state?"
MANIFEST = "m2_manifest.json"
EXPECTED = {"type": "symbol", "value": "closed"}
P6_PRODUCER = "adapter.val_door_port/0.1"


class FrozenHistory:
    """Test-only context snapshot read BEFORE storing the current question."""

    def __init__(self, query, bundle):
        self.query = query
        self.bundle = bundle

    def build(self, query, *, consumer="FAST"):
        if query != self.query or consumer != "FAST":
            raise ValueError("Frozen context belongs only to one FAST query")
        return self.bundle


class AdvisoryFast:
    """Records a retrieval request without model use or Core authority."""

    def __init__(self):
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return FastResult(response_text="Earlier user report is not a sensor reading.")


def _sync(index):
    if index is None:
        raise AssertionError("M2 must opt into Event Retrieval")
    for _ in range(32):
        state = index.sync(max_events=32)
        if state["status"] == "complete":
            return state
    raise AssertionError("M2 index did not complete within bounded sync")


def _memories(core, event_id):
    return sorted(
        m["id"] for m in core.memory_store.list_memories()
        if event_id in core.memory_store.source_events(m["id"])
    )


def _knowledge_count(core):
    with sqlite3.connect(core.memory_store.database_file) as db:
        return db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]


def _prepare(core, data, mode):
    """Persist false historical claim, build read-only context, then real query."""
    core.runtime.wake()
    history = core.runtime.user_input(HISTORY)
    assert len(history) == 1
    history_id = history[0].event_id
    selected_source = _memories(core, history_id)
    assert selected_source, "Unverified source was not recorded in Memory"
    assert _sync(core.event_retrieval)["status"] == "complete"
    assert core.event_retrieval.get(history_id)["payload"]["text"] == HISTORY

    provenance = ProvenanceResolver(
        core.memory_store, core.link_store, core.event_log,
        event_retrieval=core.event_retrieval,
    )
    context = ContextBuilder(
        retrieval=RetrievalEngine(
            memory_store=core.memory_store, link_store=core.link_store,
        ),
        provenance=provenance,
    ).build(QUERY, consumer="FAST", retrieval_options={"kinds": ("memory",)})
    assert context["consumer"] == "FAST"
    assert context["events"] == [] and context["knowledge"] == []
    assert context["budget"] == {"max_items": 6, "max_chars": 1200}
    assert context["selection_stats"]["items_used"] <= 6
    assert context["selection_stats"]["chars_used"] <= 1200
    chosen_ids = sorted(x["record"]["id"] for x in context["memories"])
    assert set(selected_source) & set(chosen_ids), "Missing historical source in FAST context"
    captured_sources = sorted({
        event_id for entry in context["memories"]
        for event_id in core.memory_store.source_events(entry["record"]["id"])
    })
    assert history_id in captured_sources
    for mid in selected_source:
        assert history_id in {
            x["id"] for x in provenance.memory(mid)["events"]
        }, "Indexed raw Event not resolvable by Memory provenance"

    query_event = core.runtime.user_input(QUERY)
    assert len(query_event) == 1
    query_id = query_event[0].event_id
    assert query_id not in captured_sources, "Current question self-cited as history"
    backend = AdvisoryFast()
    fast = FastCognition(
        context_builder=FrozenHistory(QUERY, context), backend=backend,
    )
    turn = fast.process(query_event[0])
    assert turn.request.input_event_id == query_id
    assert len(backend.requests) == 1
    assert turn.request.context_bundle is context
    assert _knowledge_count(core) == 0
    assert core.core_execution.store.list_operations() == []
    assert _sync(core.event_retrieval)["status"] == "complete"

    goal_id = core.internal_state.goals.create_goal(
        source="test.operator.m2", priority=5,
        description="Close the real Godot p6_door using Core's registered sensor",
        success_criterion="Independent Godot sensor reading is closed",
        reason="Explicit M2 integration gate; no Goal from Memory",
    )["id"]
    manifest = {
        "schema": SCHEMA, "mode": mode, "goal_id": goal_id,
        "history_id": history_id, "query_id": query_id,
        "memory_ids": selected_source, "selected_ids": chosen_ids,
        "captured_sources": captured_sources,
        "fast_chars": context["selection_stats"]["chars_used"],
        "fast_items": context["selection_stats"]["items_used"],
    }
    with (data / MANIFEST).open("x", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write("\n")
    return goal_id


def seed(mode, data, port):
    if mode not in MODES:
        raise ValueError("Unsupported M2 mode")
    if not data.is_dir() or any(data.iterdir()):
        raise ValueError("M2 requires a fresh empty data-dir")
    core = make_core(data, port=port, enable_event_retrieval=True)
    goal_id = _prepare(core, data, mode)
    if mode != "normal":
        def cut_point(action, descriptor, handler):
            # Operation is already durably 'executing'. No receipt is returned.
            if mode == "after":
                output = handler.execute(
                    str(core.core_execution.world.root),
                    action.to_dict()["arguments"],
                    action.operation_id,
                )
                assert output == {
                    "operation_id": action.operation_id, "applied": True,
                }
            (data / "crash_marker.txt").write_text(
                f"{mode}:{action.operation_id}", encoding="utf-8"
            )
            os._exit(73 if mode == "after" else 74)
        core.core_execution.executor._run_worker = cut_point

    assert core.runtime.bind_core_goal(GoalCriterion(
        goal_id=goal_id, subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE, expected=dict(EXPECTED),
    )) is True
    if mode != "normal":
        raise AssertionError("M2 crash hook never reached")
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert core.core_execution._proof(goal_id) is not None
    assert len(core.core_execution.store.list_operations(goal_id=goal_id)) == 1
    assert _knowledge_count(core) == 0
    core.runtime.sleep()
    print("M2_NORMAL_SEED_PASS", flush=True)


def recover(mode, data, port):
    with (data / MANIFEST).open(encoding="utf-8") as fp:
        saved = json.load(fp)
    assert saved["schema"] == SCHEMA and saved["mode"] == mode
    goal_id = saved["goal_id"]
    core = make_core(data, port=port, enable_event_retrieval=True)
    core.runtime.wake()
    # Bounded replay: P3-C reconciles ambiguous prior effect; never blindly retries.
    core.runtime.run_core_autonomous(max_steps=4)
    core.runtime.run_core_autonomous(max_steps=4)
    index_state = _sync(core.event_retrieval)
    assert core.event_retrieval.get(saved["history_id"])["payload"]["text"] == HISTORY
    assert core.event_retrieval.get(saved["query_id"])["payload"]["text"] == QUERY
    assert _memories(core, saved["history_id"]) == saved["memory_ids"]
    assert saved["history_id"] in saved["captured_sources"]
    assert saved["query_id"] not in saved["captured_sources"]
    assert set(saved["memory_ids"]) & set(saved["selected_ids"])
    provenance = ProvenanceResolver(
        core.memory_store, core.link_store, core.event_log,
        event_retrieval=core.event_retrieval,
    )
    for mid in saved["memory_ids"]:
        assert saved["history_id"] in {
            event["id"] for event in provenance.memory(mid)["events"]
        }
    assert _knowledge_count(core) == 0

    goal = core.internal_state.goals.get_goal(goal_id)
    ops = core.core_execution.store.list_operations(goal_id=goal_id)
    proof = core.core_execution._proof(goal_id)
    assert len(ops) == 1
    if mode == "before":
        assert goal["status"] == "active", (goal, ops)
        assert ops[0]["status"] == "uncertain", ops
        assert proof is None
        expected_effects = 0
        proof_indexed = False
    else:
        assert goal["status"] == "completed", (goal, ops)
        assert ops[0]["status"] == "succeeded", ops
        assert proof is not None, "No independent proof of success"
        event = core.core_events.ingress.get_event(proof["event_id"])
        assert event is not None
        assert event["source_ref"] == DOOR_SOURCE
        assert event["producer_ref"] == P6_PRODUCER
        assert event["kind"] == "state.property"
        assert event["payload"]["value"] == EXPECTED
        assert core.event_retrieval.get(proof["event_id"])["id"] == proof["event_id"]
        proof_indexed = True
        expected_effects = 1

    # Idempotence after another explicit bounded recovery attempt.
    ops_before = [(x["id"], x["status"]) for x in ops]
    core.runtime.run_core_autonomous(max_steps=4)
    assert [(x["id"], x["status"]) for x in core.core_execution.store.list_operations(
        goal_id=goal_id
    )] == ops_before
    assert _knowledge_count(core) == 0
    core.runtime.sleep()
    output = {
        "phase": "recover", "schema": SCHEMA, "mode": mode,
        "status": "M2_CASE_PASS",
        "goal_id": goal_id, "goal_status": goal["status"],
        "operation_status": ops[0]["status"],
        "expected_effects": expected_effects,
        "proof_event_id": proof["event_id"] if proof else None,
        "proof_indexed": proof_indexed,
        "historical_raw_event_recovered": True,
        "historical_memory_recovered": True,
        "fast_memory_ids": saved["selected_ids"],
        "fast_items": saved["fast_items"], "fast_chars": saved["fast_chars"],
        "current_query_excluded_from_prior_context": True,
        "knowledge_count": 0, "index_status": index_state["status"],
        "godot_real_process": True, "llm_used": False,
        "real_sigkill_tested": False,
    }
    (data / "recovery.json").write_text(
        json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(output, sort_keys=True), flush=True)


def _worker(phase, mode, data, port):
    cmd = [
        sys.executable, "-m", "labs.virtual_anima_lab.python.m2_integrated_gate",
        "--phase", phase, "--mode", mode, "--data-dir", str(data),
        "--port", str(port),
    ]
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=45,
    )


def run_case(mode, godot, root):
    port = free_port()
    data = root / f"core_{mode}"
    data.mkdir()
    lab = None
    log_file = root / f"godot_{mode}.log"
    with log_file.open("wb") as log:
        try:
            lab = start_godot(godot, port, log)
            hello = call(port, "agent", "hello")["data"]
            assert hello["scenario"] == "p6_door"
            initial = call(port, "agent", "observe")["data"]
            assert any(
                x["subject_ref"] == "lab.door.01"
                and x["typed_value"] == {"type": "symbol", "value": "open"}
                for x in initial["readings"]
            )
            assert effect_events(port) == []
            seed_result = _worker("seed", mode, data, port)
            expected_rc = {"normal": 0, "before": 74, "after": 73}[mode]
            assert seed_result.returncode == expected_rc, (
                f"M2 {mode} seed returned {seed_result.returncode}, "
                f"expected {expected_rc}: {seed_result.stdout[-1500:]}; "
                f"{seed_result.stderr[-3500:]}"
            )
            manifest = json.loads((data / MANIFEST).read_text(encoding="utf-8"))
            assert manifest["mode"] == mode
            effect_before = effect_events(port)
            expected = 0 if mode == "before" else 1
            assert len(effect_before) == expected, effect_before
            if mode != "normal":
                marker = (data / "crash_marker.txt").read_text(encoding="utf-8")
                assert marker.startswith(mode + ":"), marker
                op_id = marker.split(":", 1)[1]
                assert operations(data, manifest["goal_id"]) == [
                    {"operation_id": op_id, "status": "executing"}
                ]
                registered = call(
                    port, "agent", "door_operation_status", operation_id=op_id
                )["data"]["found"]
                assert registered == (mode == "after")
            recovery = _worker("recover", mode, data, port)
            assert recovery.returncode == 0, (
                f"M2 {mode} recovery: {recovery.stdout[-1200:]}; "
                f"{recovery.stderr[-4000:]}"
            )
            verified = json.loads((data / "recovery.json").read_text(encoding="utf-8"))
            assert verified["status"] == "M2_CASE_PASS"
            assert len(effect_events(port)) == expected
            assert effect_events(port) == effect_before
            assert call(port, "agent", "hello")["data"]["world_instance_id"] == (
                hello["world_instance_id"]
            )
            sense = call(port, "agent", "observe")["data"]
            door = [
                x["typed_value"]["value"] for x in sense["readings"]
                if x["subject_ref"] == "lab.door.01"
            ]
            assert door == (["open"] if mode == "before" else ["closed"])
            assert verified["expected_effects"] == expected
            return {"case": mode, **verified, "world_instance_unchanged": True,
                    "no_duplicate_effect": True}
        except BaseException:
            log.flush()
            print(
                f"Godot {mode} log tail:\n"
                + log_file.read_text(encoding="utf-8", errors="replace")[-3500:],
                file=sys.stderr,
            )
            raise
        finally:
            stop_child(lab)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", type=Path, default=(
        Path.home() / ".local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
    ))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--phase", choices=("main", "seed", "recover"),
                        default="main")
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    if args.phase != "main":
        if args.mode is None or args.data_dir is None or args.port is None:
            parser.error("worker requires --mode --data-dir --port")
        if args.report is not None:
            parser.error("worker cannot write external reports")
        if args.phase == "seed":
            seed(args.mode, args.data_dir, args.port)
        else:
            recover(args.mode, args.data_dir, args.port)
        return 0

    if args.mode is not None or args.data_dir is not None or args.port is not None:
        parser.error("Worker arguments are not available to main gate")
    godot = args.godot.expanduser().resolve()
    if not godot.is_file():
        parser.error(f"Godot executable not found: {godot}")
    if args.report is not None:
        target = args.report.expanduser().resolve()
        if target.exists() or target.is_relative_to(ROOT):
            parser.error("Report must be new and outside ANIMA repository")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        git_sha = "unknown"
    with tempfile.TemporaryDirectory(prefix="anima-m2-live-godot-") as scratch:
        rows = [
            run_case(mode, godot, Path(scratch)) for mode in MODES
        ]
    result = {
        "schema": SCHEMA, "status": "M2_INTEGRATED_GODOT_PASS",
        "commit": git_sha,
        "python": platform.python_version(), "platform": platform.platform(),
        "machine": platform.machine(), "godot_version": "4.7.2",
        "cases": rows, "source_authority": "registered VAL sensor only",
        "model_used": False, "pi_tested": False, "sigkill_tested": False,
        "production_code_changed": False,
    }
    output = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.report is not None:
        with args.report.expanduser().resolve().open("x", encoding="utf-8") as fp:
            fp.write(output)
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
