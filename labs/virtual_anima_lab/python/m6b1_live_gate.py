#!/usr/bin/env python3
"""M6-B1 real Godot 4.7.2 migration *preflight*: no action is executed.

Seven independent live Godot worlds; each is inspected by separate Python
processes before and after source mapping decision. No P2 target registration
change, WorldPort-in-Core, Task, Tool or action execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile

from anima.core.door_world import DOOR_SOURCE, DOOR_PRODUCER
from labs.virtual_anima_lab.python.core_port import VALDoorPort
from labs.virtual_anima_lab.python.m6b1_godot_migration import (
    M6B1Migration, OperatorMigrationDecision, OPERATOR, SCHEMA,
)
from labs.virtual_anima_lab.python.p6_core_crash_recovery_gate import (
    ROOT, call, effect_events, free_port, start_godot, stop_child,
)
from labs.virtual_anima_lab.python.m5_binding_admission import restricted_core
from scripts.run_memory_v1_binding_gate import _m5, seed as m5_seed

CASES = (
    "normal", "unapproved", "rejected", "stale",
    "mapping_changed", "source_modified", "sample_corrupt",
    "world_restarted",
)
MANIFEST = "m6b1_manifest.json"


def _bridge(root, port_num):
    core = restricted_core(root)
    m5 = _m5(core, root)
    port = VALDoorPort(root / "p6_port", port=port_num)
    return M6B1Migration(root=root, m5=m5, port=port)


def _decision(row, case, action="APPROVE"):
    return OperatorMigrationDecision(
        ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
        decision_id="m6b1-mapping-" + case,
        operator_ref=OPERATOR, action=action,
    )


def _invariants(bridge, goal_id):
    core = bridge.m5.core
    assert core.core_execution is None and core.core_autonomy is None
    assert core.core_events.ingress.sources[DOOR_SOURCE].producer_ref == DOOR_PRODUCER
    assert core.core_decision._binding(goal_id) is not None
    assert core.internal_state.goals.goal_count() == 1
    assert core.internal_state.goals.get_goal(goal_id)["status"] == "active"
    assert core.core_decision.tasks.list_tasks() == []
    # No ExecutionStore is ever opened by the preflight.
    with sqlite3.connect(core.memory_store.database_file) as db:
        assert db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
    assert not (bridge.root / "runtime" / "execution.db").exists()


def seed(root, case, port_num):
    if not root.is_dir() or any(root.iterdir()):
        raise ValueError("M6-B1 requires fresh empty synthetic case directory")
    assert m5_seed(root, "normal")["status"] == "M5_SEED_PASS"
    m5manifest = json.loads((root / "m5_manifest.json").read_text(encoding="utf-8"))
    bridge = _bridge(root, port_num)
    row = bridge.stage(m5manifest["m5_ticket_id"])
    assert row["status"] == "staged"
    saved = json.loads(row["snapshot_json"])
    assert saved["goal_id"] == m5manifest["goal_id"]
    assert saved["mapping"]["same_source_authority"] is False
    assert saved["mapping"]["clock_conversion_authorized"] is False
    assert saved["mapping"]["execution_permission"] is False
    _invariants(bridge, saved["goal_id"])

    with (root / MANIFEST).open("x", encoding="utf-8") as f:
        json.dump({
            "schema": SCHEMA, "case": case,
            "m5_ticket_id": m5manifest["m5_ticket_id"],
            "m4_ticket_id": m5manifest["m4_ticket_id"],
            "goal_id": saved["goal_id"],
            "ticket_id": row["ticket_id"],
            "fingerprint": row["fingerprint"],
            "initial_target": saved["target"],
        }, f, indent=2, sort_keys=True)
        f.write("\n")
    if case == "unapproved":
        return {"phase": "seed", "status": "M6B1_SEED_PASS"}
    assert bridge.decide(_decision(
        row, case, action="REJECT" if case == "rejected" else "APPROVE",
    ))["status"] == ("rejected" if case == "rejected" else "approved")

    if case == "source_modified":
        original = bridge.m5.m4.get_ticket(m5manifest["m4_ticket_id"])
        mid = json.loads(original["draft_json"])["memory_id"]
        bridge.m5.core.memory_store.update_memory(
            mid, content="M6B1_MUTATED_HISTORICAL_MEMORY_AFTER_APPROVAL",
        )
    elif case == "mapping_changed":
        modified = json.loads(row["snapshot_json"])
        modified["mapping"]["godot_adapter"]["producer_ref"] = DOOR_PRODUCER
        with sqlite3.connect(bridge.path) as db:
            db.execute("UPDATE m6b1_mappings SET snapshot_json=? WHERE ticket_id=?",
                       (json.dumps(modified, sort_keys=True), row["ticket_id"]))
    elif case == "sample_corrupt":
        seq = saved["target"]["lab_sample"]
        with sqlite3.connect(bridge.port.database_file) as db:
            db.execute(
                "UPDATE sample_log SET world_revision=world_revision+1 "
                "WHERE sample_seq=?", (seq,),
            )
    _invariants(bridge, saved["goal_id"])
    return {"phase": "seed", "status": "M6B1_SEED_PASS"}


def verify(root, case, port_num):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema"] == SCHEMA and manifest["case"] == case
    bridge = _bridge(root, port_num)
    row = bridge.get(manifest["ticket_id"])
    assert row and row["fingerprint"] == manifest["fingerprint"]
    assert row["goal_id"] == manifest["goal_id"]
    _invariants(bridge, row["goal_id"])
    if case == "normal":
        assert row["status"] == "approved"
        proof = bridge.revalidate(row["ticket_id"])
        assert proof["status"] == "M6B1_SOURCE_MAPPING_REVALIDATED"
        assert proof["fresh_lab_sample"] > proof["initial_lab_sample"]
        assert proof["world_instance_id"] == manifest["initial_target"]["world_instance_id"]
        assert proof["epoch"] == manifest["initial_target"]["epoch"]
        assert proof["world_revision"] == manifest["initial_target"]["world_revision"]
        assert proof["executor_installed"] is False
        assert proof["action_authorized"] is False
        # Same immutable receipt is repeatable; changed approval is denied.
        assert bridge.decide(_decision(row, case))["status"] == "approved"
        try:
            bridge.decide(OperatorMigrationDecision(
                ticket_id=row["ticket_id"], fingerprint=row["fingerprint"],
                decision_id="modified", operator_ref=OPERATOR, action="APPROVE",
            ))
        except ValueError as exc:
            assert "conflicting" in str(exc)
        else:
            raise AssertionError("M6-B1 accepted changed approval")
        status = proof["status"]
        newer = proof["fresh_lab_sample"]
    else:
        if case == "stale":
            bridge._live_sample = lambda: manifest["initial_target"]
        try:
            bridge.revalidate(row["ticket_id"])
        except (ValueError, RuntimeError) as exc:
            if case in ("unapproved", "rejected"):
                assert "APPROVE required" in str(exc)
            elif case == "stale":
                assert "stale" in str(exc)
            elif case == "source_modified":
                assert "not fresh" in str(exc) or "changed" in str(exc)
            elif case == "world_restarted":
                assert "changed" in str(exc) or "epoch" in str(exc)
            else:
                assert "changed" in str(exc) or "mutated" in str(exc)
        else:
            raise AssertionError(f"M6-B1 {case} incorrectly accepted source migration")
        status = "M6B1_MIGRATION_DENIED"
        newer = None
    _invariants(bridge, row["goal_id"])
    return {
        "phase": "verify", "status": "M6B1_CASE_PASS", "case": case,
        "disposition": status, "ticket_id": row["ticket_id"],
        "goal_id": row["goal_id"], "m5_ticket_id": manifest["m5_ticket_id"],
        "original_world_instance": manifest["initial_target"]["world_instance_id"],
        "initial_lab_sample": manifest["initial_target"]["lab_sample"],
        "fresh_lab_sample": newer,
        "source_migration_executable": False,
        "m5_origin_remains_virtual": True,
        "target_p2_registered": False,
        "world_effect_count": 0, "task_count": 0, "knowledge_count": 0,
        "operator_authenticated": False,
    }


def _worker(phase, root, case, port):
    return subprocess.run([
        sys.executable, "-m", "labs.virtual_anima_lab.python.m6b1_live_gate",
        "--phase", phase, "--root", str(root), "--case", case, "--port", str(port),
    ],capture_output=True,text=True,timeout=85)


def run_case(godot, scratch, case):
    port = free_port()
    root = scratch / ("case_" + case)
    root.mkdir()
    logfile = scratch / ("godot_" + case + ".log")
    proc = None
    with logfile.open("wb") as log:
        try:
            proc = start_godot(godot, port, log)
            hello = call(port, "agent", "hello")["data"]
            assert hello["scenario"] == "p6_door"
            assert effect_events(port) == []
            a = _worker("seed", root, case, port)
            assert a.returncode == 0, (
                f"M6B1 {case} seed rc={a.returncode}: "
                + a.stderr[-3600:] + a.stdout[-800:]
            )
            assert effect_events(port) == [], "M6-B1 seed triggered Godot action"
            if case == "world_restarted":
                stop_child(proc)
                proc = None
                proc = start_godot(godot, port, log)
                changed = call(port, "agent", "hello")["data"]
                assert changed["world_instance_id"] != hello["world_instance_id"], (
                    "Godot restart did not alter world identity"
                )
            b = _worker("verify", root, case, port)
            assert b.returncode == 0, (
                f"M6B1 {case} verify rc={b.returncode}: "
                + b.stderr[-3600:] + b.stdout[-800:]
            )
            result = json.loads(b.stdout)
            assert result["status"] == "M6B1_CASE_PASS"
            assert effect_events(port) == []
            return result
        except BaseException:
            log.flush()
            print(f"M6B1 {case} Godot log tail:\n" +
                  logfile.read_text(errors="replace")[-3200:], file=sys.stderr)
            raise
        finally:
            stop_child(proc)


def run_all(godot):
    with tempfile.TemporaryDirectory(prefix="anima-m6b1-godot-") as temp:
        results = [run_case(godot, Path(temp), case) for case in CASES]
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    return {
        "schema": SCHEMA, "status": "M6B1_GODOT_SOURCE_PREFLIGHT_PASS",
        "commit": sha, "python": platform.python_version(),
        "machine": platform.machine(), "godot_version": "4.7.2",
        "cases": results, "world_effect_total": 0,
        "existing_goal_count_per_case": 1, "tasks_created": 0,
        "migration_executable": False, "target_p2_registered": False,
        "operator_authenticated": False, "godot_tested": True,
        "production_code_changed": False, "pi_tested": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=("main", "seed", "verify"), default="main")
    ap.add_argument("--case", choices=CASES)
    ap.add_argument("--port", type=int)
    ap.add_argument("--root", type=Path)
    ap.add_argument("--godot", type=Path, default=(
        Path.home()/".local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
    ))
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)
    if args.phase != "main":
        if args.root is None or args.case is None or args.port is None or args.report:
            ap.error("M6-B1 child requires --root --case --port and no report")
        value = seed(args.root, args.case, args.port) if args.phase == "seed" else verify(
            args.root, args.case, args.port,
        )
    else:
        if args.root is not None or args.case is not None or args.port is not None:
            ap.error("M6-B1 worker options are internal")
        binary = args.godot.expanduser().resolve()
        if not binary.is_file():
            ap.error(f"Godot executable not found: {binary}")
        detected = subprocess.run(
            [str(binary), "--headless", "--version"],capture_output=True,
            text=True, timeout=12,
        )
        if detected.returncode != 0 or not detected.stdout.strip().startswith("4.7.2"):
            ap.error("M6-B1 requires Godot 4.7.2")
        if args.report is not None:
            dest = args.report.expanduser().resolve()
            if dest.exists() or dest.is_relative_to(ROOT):
                ap.error("M6-B1 report must be new and outside repository")
        value = run_all(binary)
    output = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.report is not None:
        with args.report.expanduser().resolve().open("x", encoding="utf-8") as fp:
            fp.write(output)
    print(output, end="")


if __name__ == "__main__":
    main()
