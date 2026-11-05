"""Standalone P3-C acceptance demonstration. Explicit isolated data directory.

Run: python -m anima.core.demo_p3c --data-dir /tmp/anima-auto-demo-unique
The directory must be empty. This is a narrow fixed-door test, not a GUI lab.
"""

import argparse
import json
from pathlib import Path

from anima.core.assembly import build_core
from anima.core.belief import PropertyRule
from anima.core.door_world import (
    DOOR_SUBJECT, DOOR_PREDICATE, DOOR_SOURCE, DOOR_PRODUCER,
    DOOR_TOOL, DOOR_VERSION, VirtualDoorWorld,
)
from anima.core.goal_decision import GoalCriterion
from anima.core.ingress import SourceRegistration
from anima.execution.contracts import ActionSpec


def _emit(stage, data):
    print(json.dumps({"stage": stage, **data}, sort_keys=True, ensure_ascii=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="P3-C bounded autonomous door demo (no LLM, no Godot)"
    )
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--initial-state", choices=("open", "closed"), default="open")
    args = parser.parse_args(argv)

    root = args.data_dir.expanduser().resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        parser.error("Demo data-dir must be absent or empty; existing instance data is protected")
    world = VirtualDoorWorld(root / "world")
    world.seed(state=args.initial_state, tick=40)

    typed_target = {"type": "symbol", "value": "closed"}
    key = (
        DOOR_SUBJECT, DOOR_PREDICATE,
        json.dumps(typed_target, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    )
    core = build_core(
        root / "runtime",
        sources={
            DOOR_SOURCE: SourceRegistration(
                source_ref=DOOR_SOURCE,
                producer_ref=DOOR_PRODUCER,
                allowed_kinds=("state.property",),
            ),
        },
        properties={
            (DOOR_SUBJECT, DOOR_PREDICATE): PropertyRule(
                subject_ref=DOOR_SUBJECT, predicate_ref=DOOR_PREDICATE,
                value_type="symbol", clock_domain="lab_tick",
                allowed_sources=(DOOR_SOURCE,), freshness_ticks=2,
                allowed_symbols=("open", "closed"),
            ),
        },
        goal_actions={
            key: ActionSpec(
                candidate_id="door_close_01", tool=DOOR_TOOL,
                tool_version=DOOR_VERSION,
                arguments={"subject_ref": DOOR_SUBJECT},
            )
        },
        virtual_door_root=root / "world", auto_core=True,
    )
    core.runtime.wake()
    _emit("bootstrap", {
        "phase": "P3C_ONE_DOOR_ONLY", "autonomous": True,
        "model_required": False, "initial_state": args.initial_state,
    })
    goal = core.internal_state.goals.create_goal(
        source="demo.operator", priority=5,
        description="Ensure registered door is closed once",
        success_criterion="world.door_state equals closed",
        reason="P3-C isolated acceptance demo",
    )
    _emit("goal_registered", {"goal_id": goal["id"]})
    core.runtime.bind_core_goal(GoalCriterion(
        goal_id=goal["id"], subject_ref=DOOR_SUBJECT,
        predicate_ref=DOOR_PREDICATE, expected=typed_target,
    ))
    for entry in core.core_decision.history(goal["id"]):
        _emit("decision", entry)
    for attempt in core.core_autonomy.attempts():
        _emit("scheduler_attempt", attempt)
    for operation in core.core_execution.store.list_operations(goal_id=goal["id"]):
        _emit("execution_ledger", {
            "operation_id": operation["id"], "status": operation["status"],
            "idempotency_class": operation["idempotency_class"],
        })
    current = world.current()  # privileged test operator; not fed to Core.
    belief = core.runtime.read_core_belief(
        DOOR_SUBJECT, DOOR_PREDICATE, as_of_tick=current["tick"]
    )
    tasks = core.core_decision.tasks.list_tasks(goal_id=goal["id"])
    _emit("result", {
        "goal_status": core.internal_state.goals.get_goal(goal["id"])["status"],
        "task_statuses": [task.status for task in tasks],
        "belief_status": belief["status"],
        "belief_value": belief["value"],
        "belief_evidence_events": list(belief["evidence_event_ids"]),
        "operator_ground_truth": current["state"],  # external privileged context
        "pending_auto_triggers": core.core_autonomy.pending_count(),
    })
    core.runtime.sleep()


if __name__ == "__main__":
    main()
