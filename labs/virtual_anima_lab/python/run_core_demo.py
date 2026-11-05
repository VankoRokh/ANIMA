#!/usr/bin/env python3
"""P6 experimental single-Goal Core↔VAL demo; plug-in lives outside Core.

Run with python -m labs.virtual_anima_lab.python.run_core_demo.
Requires a separate Godot instance in scenario p6_door, and NEW data-dir.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from anima.core.assembly import build_core
from anima.core.belief import PropertyRule
from anima.core.door_world import (
    DOOR_PREDICATE, DOOR_SOURCE, DOOR_SUBJECT,
    DOOR_TOOL, DOOR_VERSION,
)
from anima.core.goal_decision import GoalCriterion
from anima.core.ingress import SourceRegistration
from anima.execution.contracts import ActionSpec

from .core_port import VALDoorPort


def make_core(data_dir: Path, *, port: int = 46019):
    """Composition root registers the external port as exactly one narrow source.

    No Godot-specific class is imported anywhere by the Core implementation.
    The Lab connection remains a local demo boundary, not transport auth.
    """
    value = {"type": "symbol", "value": "closed"}
    key = (
        DOOR_SUBJECT, DOOR_PREDICATE,
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    )
    root = Path(data_dir).expanduser().resolve()
    world = VALDoorPort(root / "p6_port", port=port)
    return build_core(
        root / "core",
        sources={DOOR_SOURCE: SourceRegistration(
            source_ref=DOOR_SOURCE,
            producer_ref="adapter.val_door_port/0.1",
            allowed_kinds=("state.property", "sensor.unavailable"),
        )},
        properties={(DOOR_SUBJECT, DOOR_PREDICATE): PropertyRule(
            subject_ref=DOOR_SUBJECT,
            predicate_ref=DOOR_PREDICATE,
            value_type="symbol",
            clock_domain="lab_sample",
            allowed_sources=(DOOR_SOURCE,),
            freshness_ticks=2,
            allowed_symbols=("open", "closed"),
        )},
        goal_actions={key: ActionSpec(
            candidate_id="door_close", tool=DOOR_TOOL,
            tool_version=DOOR_VERSION,
            arguments={"subject_ref": DOOR_SUBJECT},
        )},
        world_port=world,
        world_handlers=world.handlers(),
        auto_core=True,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=46019)
    parser.add_argument(
        "--data-dir", required=True, type=Path,
        help="P6-only Core and adapter data; never point to production ANIMA data",
    )
    args = parser.parse_args(argv)
    core = make_core(args.data_dir, port=args.port)
    core.runtime.wake()
    try:
        goal = core.internal_state.goals.create_goal(
            source="test.operator.p6", priority=5,
            description="Close the observed door in P6 Lab",
            success_criterion="Independent door-state readback is closed",
            reason="Explicit local P6 integration acceptance",
        )
        goal_id = goal["id"]
        criterion = GoalCriterion(
            goal_id=goal_id, subject_ref=DOOR_SUBJECT,
            predicate_ref=DOOR_PREDICATE,
            expected={"type": "symbol", "value": "closed"},
        )
        core.runtime.bind_core_goal(criterion)
        final = core.internal_state.goals.get_goal(goal_id)
        ops = core.core_execution.store.list_operations(goal_id=goal_id)
        proof = core.core_execution._proof(goal_id)
        print(json.dumps({
            "goal_id": goal_id, "goal_status": final["status"],
            "operations": [op["status"] for op in ops],
            "has_independent_proof": proof is not None,
            "attempts": list(core.core_autonomy.attempts()),
        }, indent=2, ensure_ascii=False))
        if (
            final["status"] == "completed"
            and proof is not None
            and len(ops) == 1
            and ops[0]["status"] == "succeeded"
        ):
            print("P6_CORE_VAL_DOOR_PASS")
            return 0
        print("P6_CORE_VAL_DOOR_INCOMPLETE")
        return 1
    finally:
        core.runtime.sleep()


if __name__ == "__main__":
    raise SystemExit(main())
