"""Subprocess helper for P4-D: terminate inside a real SQLite transaction.

Launched only by pytest, with a disposable test directory. Deliberately uses
os._exit(73): no finally/connection close, reproducing process-cut semantics.
"""

import os
import sys
from pathlib import Path

from tests.test_core_p4_acceptance import _core, _goal


def main():
    root = Path(sys.argv[1])
    core = _core(root)
    goal_id = _goal(core, priority=9, title="atomic mid-transaction cut", notify=False)
    (root / "audit_goal.txt").write_text(goal_id, encoding="utf-8")
    original = core.core_execution.store.create_operation

    def terminate_after_operation_insert(action, **kwargs):
        def cut(stage):
            if stage == "after_action_insert":
                os._exit(73)
        return original(action, **kwargs, fault_hook=cut)

    core.core_execution.store.create_operation = terminate_after_operation_insert
    core.runtime.run_core_autonomous()
    raise AssertionError("Atomic preparation cut was not reached")


if __name__ == "__main__":
    main()
