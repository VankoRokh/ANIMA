"""M1 laptop gate: historical Memory advisory + Core-owned verified door action.

All production modules are reused unchanged. One isolated headless virtual door
per scenario, two fresh Python processes per scenario. FAST is a non-LLM
recording backend and cannot authorize the registered tool or update Belief.
"""
import argparse
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from anima.cognition.fast import FastCognition, FastResult
from anima.core.assembly import build_core
from anima.core.belief import PropertyRule
from anima.core.door_world import (
    DOOR_PREDICATE, DOOR_PRODUCER, DOOR_SOURCE, DOOR_SUBJECT,
    DOOR_TOOL, DOOR_VERSION, VirtualDoorWorld,
)
from anima.core.goal_decision import GoalCriterion
from anima.core.ingress import SourceRegistration
from anima.execution.contracts import ActionSpec
from anima.memory.context_builder import ContextBuilder
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine

SCHEMA = "anima.memory_v1.integrated_decision_m1/0.1"
SCENARIOS = ("false_closed", "false_open", "sensor_unavailable")
QUERY = "What did the earlier report claim about the virtual door state?"
MANIFEST = "m1_manifest.json"
EXPECTED = {"type": "symbol", "value": "closed"}
HISTORY = {
    "false_closed": "Unverified earlier report claims that the virtual door is closed.",
    "false_open": "Unverified earlier report claims that the virtual door is open.",
    "sensor_unavailable": "Unverified earlier report claims that the virtual door is closed.",
}


def _world(root):
    return VirtualDoorWorld(root / "world")


def _effect_count(world):
    with sqlite3.connect(world.path) as connection:
        return connection.execute("SELECT COUNT(*) FROM door_effects").fetchone()[0]


def _core(root):
    key = (
        DOOR_SUBJECT, DOOR_PREDICATE,
        json.dumps(EXPECTED, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    )
    return build_core(
        root / "runtime",
        sources={DOOR_SOURCE: SourceRegistration(
            source_ref=DOOR_SOURCE, producer_ref=DOOR_PRODUCER,
            allowed_kinds=("state.property",),
        )},
        properties={(DOOR_SUBJECT, DOOR_PREDICATE): PropertyRule(
            subject_ref=DOOR_SUBJECT, predicate_ref=DOOR_PREDICATE,
            value_type="symbol", clock_domain="lab_tick",
            allowed_sources=(DOOR_SOURCE,), freshness_ticks=2,
            allowed_symbols=("open", "closed"),
        )},
        goal_actions={key: ActionSpec(
            candidate_id="door_close_01", tool=DOOR_TOOL,
            tool_version=DOOR_VERSION, arguments={"subject_ref": DOOR_SUBJECT},
        )},
        virtual_door_root=root / "world",
        auto_core=False,  # Explicit operator Goal and explicit bounded execution.
        enable_event_retrieval=True,
    )


def _sync(index):
    for _ in range(24):
        status = index.sync(max_events=32)
        if status["status"] == "complete":
            return status
    raise AssertionError("M1 Event index failed to complete within sync bound")


def _knowledge_count(core):
    with sqlite3.connect(core.memory_store.database_file) as connection:
        return connection.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]


def _source_memories(core, event_id):
    return [
        m["id"] for m in core.memory_store.list_memories()
        if event_id in core.memory_store.source_events(m["id"])
    ]


class _SnapshotContext:
    """Test-only frozen read view of history before the current request write."""

    def __init__(self, query, captured):
        self.query = query
        self.captured = captured

    def build(self, query, *, consumer="FAST"):
        if query != self.query or consumer != "FAST":
            raise ValueError("Snapshot belongs only to this FAST input")
        return self.captured


class _NonAuthoritativeBackend:
    def __init__(self):
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return FastResult(
            response_text="Historical user report received as advisory, not world truth."
        )


def _goal(core, *, description):
    return core.internal_state.goals.create_goal(
        source="test.operator.m1", priority=5, description=description,
        success_criterion="independent registered door sensor confirms closed",
        reason="explicit isolated M1 typed Core acceptance",
    )["id"]


def _binding(goal_id):
    return GoalCriterion(
        goal_id=goal_id, subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE, expected=dict(EXPECTED),
    )


def seed(root, scenario):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown M1 scenario")
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("M1 seed directory must be absent or completely empty")
    state = "closed" if scenario == "false_open" else "open"
    world = _world(root)
    world.seed(state=state, tick=40)
    core = _core(root)
    assert core.core_autonomy is None
    core.runtime.wake()

    history = core.runtime.user_input(HISTORY[scenario])
    assert len(history) == 1
    history_id = history[0].event_id
    assert _source_memories(core, history_id), "No real processed source Memory"
    _sync(core.event_retrieval)

    provenance = ProvenanceResolver(
        core.memory_store, core.link_store, core.event_log,
        event_retrieval=core.event_retrieval,
    )
    builder = ContextBuilder(
        retrieval=RetrievalEngine(
            memory_store=core.memory_store, link_store=core.link_store,
        ),
        provenance=provenance,
    )
    # Read historical source BEFORE the current query is written to Memory.
    captured = builder.build(
        QUERY, consumer="FAST",
        retrieval_options={"kinds": ("memory",)},
    )
    assert captured["consumer"] == "FAST"
    assert captured["events"] == [] and captured["knowledge"] == []
    assert captured["budget"] == {"max_items": 6, "max_chars": 1200}
    assert len(captured["memories"]) >= 1
    source_memories = set(_source_memories(core, history_id))
    selected = {m["record"]["id"] for m in captured["memories"]}
    assert source_memories & selected, "History must be present in FAST snapshot"
    source_ids_at_capture = {
        event_id
        for item in captured["memories"]
        for event_id in core.memory_store.source_events(item["record"]["id"])
    }
    assert history_id in source_ids_at_capture

    query_turns = core.runtime.user_input(QUERY)
    assert len(query_turns) == 1
    query_event = query_turns[0]
    assert query_event.event_id not in source_ids_at_capture, (
        "Current request was included as its own earlier testimony"
    )
    backend = _NonAuthoritativeBackend()
    fast = FastCognition(
        context_builder=_SnapshotContext(QUERY, captured), backend=backend,
    )
    turn = fast.process(query_event)
    assert turn.request.input_event_id == query_event.event_id
    assert turn.request.context_bundle is captured
    assert len(backend.requests) == 1
    assert _knowledge_count(core) == 0
    assert _effect_count(world) == 0

    # Memory report and FAST do not create or bind executable Goals.
    unbound = _goal(core, description="Unbound Goal must never execute")
    attempted = core.runtime.run_core_door_goal(unbound)
    assert attempted.outcome == "DEFERRED"
    assert attempted.reason_code == "UNBOUND_GOAL"
    assert core.core_execution.store.list_operations(goal_id=unbound) == []
    assert _effect_count(world) == 0

    goal_id = _goal(core, description="Close the real virtual door once")
    assert core.runtime.bind_core_goal(_binding(goal_id)) is True
    assert _effect_count(world) == 0

    blocked = False
    if scenario == "sensor_unavailable":
        observer = core.core_execution.world
        original_sense = observer.sense

        def no_sensor():
            raise RuntimeError("M1 simulated registered sensor outage")

        observer.sense = no_sensor
        try:
            try:
                core.runtime.run_core_door_goal(goal_id)
            except RuntimeError as exc:
                assert "sensor outage" in str(exc)
            else:
                raise AssertionError("Missing trusted sensor was silently accepted")
            assert _effect_count(world) == 0
            assert core.internal_state.goals.get_goal(goal_id)["status"] == "active"
            assert core.core_execution._proof(goal_id) is None
            blocked = True
        finally:
            observer.sense = original_sense

    outcome = core.runtime.run_core_door_goal(goal_id)
    assert outcome.outcome == "VERIFIED_SUCCESS", outcome
    expected_effects = 0 if scenario == "false_open" else 1
    assert _effect_count(world) == expected_effects
    assert world.current()["state"] == "closed"  # test oracle, never a Belief input
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert [t.status for t in core.core_decision.tasks.list_tasks(goal_id=goal_id)] == [
        "completed"
    ]

    proof = core.core_execution._proof(goal_id)
    assert proof is not None
    source = core.core_events.ingress.get_event(proof["event_id"])
    assert source["kind"] == "state.property"
    assert source["source_ref"] == DOOR_SOURCE
    assert source["producer_ref"] == DOOR_PRODUCER
    assert core.core_execution._verified(  # independent sensor evidence + Belief
        goal_id, proof["event_id"],
        core.core_events.ingress.get_event(proof["event_id"])["payload"]["observed_at"]["value"],
        core.runtime.read_core_belief(
            DOOR_SUBJECT, DOOR_PREDICATE,
            as_of_tick=core.core_events.ingress.get_event(proof["event_id"])["payload"]["observed_at"]["value"],
        ),
    )
    assert _knowledge_count(core) == 0
    assert core.core_autonomy is None  # No unattended trigger of world effects.

    manifest = {
        "schema": SCHEMA,
        "scenario": scenario,
        "goal_id": goal_id,
        "unbound_goal_id": unbound,
        "history_id": history_id,
        "query_id": query_event.event_id,
        "historical_memory_ids": sorted(source_memories),
        "fast_memory_ids": sorted(selected),
        "fast_chars": captured["selection_stats"]["chars_used"],
        "fast_items": captured["selection_stats"]["items_used"],
        "historical_source_ids_at_read": sorted(source_ids_at_capture),
        "expected_effects": expected_effects,
        "sensor_failure_blocked": blocked,
        "proof_event_id": proof["event_id"],
    }
    with (root / MANIFEST).open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    return {"phase": "seed", "scenario": scenario, "status": "M1_SEED_PASS",
            "effects": expected_effects, "sensor_failure_blocked": blocked}


def verify(root, scenario):
    with (root / MANIFEST).open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    assert manifest["schema"] == SCHEMA
    assert manifest["scenario"] == scenario
    core = _core(root)  # Independent interpreter, same stores, same adapter.
    core.runtime.wake()
    _sync(core.event_retrieval)
    history_id, query_id = manifest["history_id"], manifest["query_id"]
    assert core.event_retrieval.get(history_id)["payload"]["text"] == HISTORY[scenario]
    assert core.event_retrieval.get(query_id)["payload"]["text"] == QUERY
    assert _source_memories(core, history_id) == manifest["historical_memory_ids"]
    assert query_id not in manifest["historical_source_ids_at_read"]

    goal_id = manifest["goal_id"]
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "completed"
    assert [t.status for t in core.core_decision.tasks.list_tasks(goal_id=goal_id)] == [
        "completed"
    ]
    assert core.core_execution._proof(goal_id)["event_id"] == manifest["proof_event_id"]
    operations_before = core.core_execution.store.list_operations(goal_id=goal_id)
    effect_before = _effect_count(core.core_execution.world)
    assert effect_before == manifest["expected_effects"]
    replay = core.runtime.run_core_door_goal(goal_id)
    assert replay.outcome == "RECOVERED_VERIFIED_SUCCESS", replay
    assert replay.reason_code == "PERSISTED_VERIFICATION_PROOF"
    assert replay.evidence_event_id == manifest["proof_event_id"]
    operations_after = core.core_execution.store.list_operations(goal_id=goal_id)
    assert [op["id"] for op in operations_after] == [
        op["id"] for op in operations_before
    ]
    assert _effect_count(core.core_execution.world) == effect_before
    assert core.core_execution.world.current()["state"] == "closed"

    unbound = manifest["unbound_goal_id"]
    assert core.runtime.run_core_door_goal(unbound).reason_code == "UNBOUND_GOAL"
    assert _effect_count(core.core_execution.world) == effect_before
    assert _knowledge_count(core) == 0
    return {
        "phase": "verify", "scenario": scenario, "status": "M1_SCENARIO_PASS",
        "python": platform.python_version(), "machine": platform.machine(),
        "platform": platform.platform(),
        "history_id": history_id, "query_id": query_id,
        "history_memory_ids": manifest["historical_memory_ids"],
        "fast_memory_ids": manifest["fast_memory_ids"],
        "fast_items": manifest["fast_items"],
        "fast_chars": manifest["fast_chars"],
        "query_excluded_from_historical_snapshot": True,
        "memory_used_as_sensor_authority": False,
        "typed_goal_explicitly_operator_bound": True,
        "independent_sensor_proof": True,
        "goal_status": "completed",
        "registered_sensor": DOOR_SOURCE,
        "effect_count": effect_before,
        "effect_replayed": False,
        "sensor_failure_blocked": manifest["sensor_failure_blocked"],
        "knowledge_count": 0,
        "core_autonomy_enabled": False,
        "real_sigkill_tested": False,
        "godot_val_tested": False,
    }


def _child(phase, root, scenario):
    cmd = [
        sys.executable, "-m", "scripts.run_memory_v1_integrated_decision_gate",
        "--internal-phase", phase, "--scenario", scenario, "--root", str(root),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
    if proc.returncode != 0:
        raise AssertionError(
            f"M1 {scenario}/{phase} failed code={proc.returncode}; "
            f"stdout={proc.stdout[-3000:]!r}; stderr={proc.stderr[-6000:]!r}"
        )
    return json.loads(proc.stdout)


def run_gate():
    results = []
    for scenario in SCENARIOS:
        with tempfile.TemporaryDirectory(prefix=f"anima-m1-{scenario}-") as temp:
            root = Path(temp)
            seeded = _child("seed", root, scenario)
            verified = _child("verify", root, scenario)
            assert seeded["status"] == "M1_SEED_PASS"
            assert verified["status"] == "M1_SCENARIO_PASS"
            assert seeded["effects"] == verified["effect_count"]
            results.append(verified)
    return {
        "schema": SCHEMA, "status": "M1_INTEGRATED_DECISION_PASS",
        "machine": platform.machine(), "python": platform.python_version(),
        "scenarios": results, "production_code_changed": False,
        "pi_tested": False, "model_used": False,
        "godot_val_tested": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-phase", choices=("seed", "verify"))
    parser.add_argument("--scenario", choices=SCENARIOS)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.internal_phase:
        if args.scenario is None or args.root is None or args.report is not None:
            parser.error("Internal phase requires --scenario and --root only")
        result = (
            seed(args.root, args.scenario)
            if args.internal_phase == "seed"
            else verify(args.root, args.scenario)
        )
    else:
        if args.scenario is not None or args.root is not None:
            parser.error("--scenario and --root are for internal processes")
        result = run_gate()
    output = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as stream:
            stream.write(output)
    print(output, end="")


if __name__ == "__main__":
    main()
