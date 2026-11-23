"""E2.2 live Godot Raw capture/ingress/recovery gate; no FAST or world effects.

Runs on disposable Core databases and guarded Godot-world instances.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import tempfile
from pathlib import Path

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .core_gateway import (
    CoreBoundObservationGateway, SOURCE_REF, lifecycle_source_registration,
    WorldBoundaryError,
)
from .e21_gateway_live_gate import finish, start
from .raw_capture import (
    E22RawCaptureService, lifecycle_snapshot_rule, SUBJECT, PREDICATE,
)
from .world_smoke import _binary, _port, _wait


def check(ok: bool, reason: str):
    if not ok:
        raise AssertionError(reason)


def core(data_dir: Path):
    rule = lifecycle_snapshot_rule()
    return build_core(
        data_dir,
        sources={SOURCE_REF: lifecycle_source_registration()},
        properties={(SUBJECT, PREDICATE): rule},
    )


def service(core_instance, *, port: int, key: str, hook=None):
    gateway = CoreBoundObservationGateway(
        core_instance, port=port, observer_key=key, capture_raw=True,
    )
    return E22RawCaptureService(core_instance, gateway, fault_hook=hook)


def raw_rows(data_dir: Path) -> list[dict]:
    db = sqlite3.connect(data_dir / "e21_world_binding.db")
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(
            "SELECT * FROM e22_raw_capture ORDER BY sample_seq"
        )]
    finally:
        db.close()


def die_at(point: str):
    def hook(stage, _sample):
        if stage == point:
            raise RuntimeError("E22_INJECTED_CRASH:" + point)
    return hook


def run_one(binary: str, seed: int, root: Path) -> dict:
    keys = tuple(secrets.token_urlsafe(32) for _ in range(3))
    port = _port()
    data_dir = root / f"raw-core-{seed}"
    original = core(data_dir)
    process, output = start(binary, port, seed, root / f"e22-world-{seed}.log", keys)
    try:
        ready = _wait(process, port)
        ready.close()

        # First crash after snapshot + cursor were committed, before Core.
        first = service(original, port=port, key=keys[0],
                        hook=die_at("after_snapshot_commit"))
        try:
            first.observe_and_record()
        except RuntimeError as err:
            check("E22_INJECTED_CRASH:after_snapshot_commit" in str(err),
                  "unexpected before-Core failure")
        else:
            raise AssertionError("fault after captured snapshot did not fire")
        check(len(raw_rows(data_dir)) == 1 and
              raw_rows(data_dir)[0]["event_id"] is None,
              "after-capture crash lost raw evidence or invented Core event")
        check(original.core_events.ingress.pending_event_ids(limit=5) == (),
              "Core event was written before snapshot-commit fault")

        # Reopen Core and finish from durable captured bytes, not Godot.
        reopened = core(data_dir)
        ingestor = service(reopened, port=port, key=keys[0])
        linked = ingestor.recover()
        check(len(linked) == 1 and len(reopened.event_log.load_events()) == 1,
              "crash recovery failed to dispatch exact first event")
        original_raw = ingestor.capture_snapshot(raw_rows(data_dir)[0]["sample_id"])
        check(original_raw.as_dict()["sample_seq"] == 1, "recovered snapshot altered")

        # Next sample survives ordinary Core reconnection. Source, event,
        # identity and exact raw digest must all remain correlated.
        saved = ingestor.observe_and_record()
        check(saved.observation.as_dict()["sample_seq"] == 2,
              "Core reopen lost sample cursor")
        check(saved.core_dispatch_receipt == "forwarded",
              "Core dispatcher did not durably process observed sample")

        # Second cut: after Core accepted original sensor pointer, before
        # capture-side acknowledgement. Replaying MUST return ALREADY_SEEN.
        before_event_count = len(reopened.event_log.load_events())
        faulty = service(reopened, port=port, key=keys[0],
                         hook=die_at("after_core_admit"))
        try:
            faulty.observe_and_record()
        except RuntimeError as err:
            check("E22_INJECTED_CRASH:after_core_admit" in str(err),
                  "unexpected after-ingress failure")
        else:
            raise AssertionError("Core admit cut did not fire")
        check(len(raw_rows(data_dir)) == 3 and
              raw_rows(data_dir)[-1]["event_id"] is None,
              "Core admit cut did not preserve pending raw snapshot")
        pending = reopened.core_events.ingress.pending_event_ids(limit=10)
        check(len(pending) == 1,
              "Core commit was not durable before sidecar event-id link")

        final_core = core(data_dir)
        recovered = service(final_core, port=port, key=keys[0])
        recovered_ids = recovered.recover()
        check(len(recovered_ids) == 1 and recovered_ids[0] == pending[0],
              "Core replay generated different event identity")
        check(len(final_core.event_log.load_events()) == before_event_count + 1,
              "Core replay duplicated or lost legacy Raw event")
        check(recovered.recover() == (), "idle recovery admitted new events")
        check(len({x["id"] for x in final_core.event_log.load_events()}) == 3,
              "duplicate legacy Raw after recovery")

        # Trusted fixture action changes world revision but E2.2 does not
        # request any world effect, only the next independent observation.
        with LabClient(port, role="operator", protocol=PROTOCOL_V2) as operator:
            changed = operator.call(
                "set_obstacle", at={"x": 4, "y": 4}, blocked=True,
                auth=keys[2],
            )
        check(changed["data"]["changed"], "fixture did not change virtual world")
        changed_sample = recovered.observe_and_record()
        check(changed_sample.observation.as_dict()["revision"] > saved.observation.as_dict()["revision"],
              "new world revision was not preserved")
        check(len(final_core.event_log.load_events()) == 4,
              "external world change was not captured as a Core Raw pointer")
        check(not final_core.core_events.ingress.pending_event_ids(limit=10),
              "Core dispatcher left pending Raw events without reporting")

        # A reset changes epoch. It must never be auto-rebound or create
        # fabricated Raw evidence in the existing Core identity.
        with LabClient(port, role="operator", protocol=PROTOCOL_V2) as operator:
            operator.call("reset", auth=keys[2])
        before = len(raw_rows(data_dir))
        try:
            recovered.observe_and_record()
        except WorldBoundaryError:
            pass
        else:
            raise AssertionError("new world epoch contaminated old Core Raw")
        check(len(raw_rows(data_dir)) == before,
              "rejected world reset wrote new Raw evidence")
        check(len(final_core.event_log.load_events()) == 4,
              "rejected reset projected a Core event")

        sample_ids = [row["sample_id"] for row in raw_rows(data_dir)]
        check(len(set(sample_ids)) == 4, "duplicate sample provenance")
        return {
            "seed": seed, "captured_snapshots": 4,
            "core_raw_pointer_events": 4,
            "legacy_eventlog": 4,
            "crash_after_capture": "RECOVERED",
            "crash_after_core_admit": "RECOVERED_WITH_SAME_EVENT_ID",
            "core_reopen_same_world": "ACCEPTED",
            "world_reset": "REJECTED",
            "no_world_effects_issued": True,
            "model_used": False,
            "knowledge_published": False,
            "full_snapshot_in_core_eventlog": False,
        }
    finally:
        finish(process, output)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--godot", required=True)
    p.add_argument("--evidence-dir")
    args = p.parse_args(argv)
    try:
        binary = _binary(args.godot)
        if args.evidence_dir:
            work = Path(args.evidence_dir)
            work.mkdir(parents=True, exist_ok=True)
            results = [run_one(binary, seed, work) for seed in (7, 8)]
        else:
            with tempfile.TemporaryDirectory(prefix="anima-e22-") as directory:
                results = [run_one(binary, seed, Path(directory)) for seed in (7, 8)]
        print(json.dumps({
            "schema": "anima.e2_2.raw_capture_gate/0.1",
            "status": "E2_2_LIVE_GATE_PASS",
            "cases": results, "core_goal_action_connected": False,
            "model_used": False, "world_process_restart_durability_tested": False,
        }, sort_keys=True))
        return 0
    except Exception as error:
        print(f"E2_2_LIVE_GATE_FAIL: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
