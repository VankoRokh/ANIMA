"""Visual Lab E2.5b: REAL observations and a bounded deterministic agent loop.

Human UI issues STEP/RUN/PAUSE on an authenticated loopback control port.
Only this trusted lab runner holds the Godot executor key. The policy receives
E2.3 agent-only readings + provenance-backed E2.4 memory, never Godot inspect
or absolute coordinates. All proposed world actions are lab admitted and
recorded BEFORE effects, then checked against readback and next Core Raw.

IMPORTANT: 'LAB_ADMISSION' is not native Stage6 or CoreGoalDecision action
authority. No actual FAST/DEEP connection; this is a deterministic baseline.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import secrets
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from anima.core.assembly import build_core
from labs.virtual_anima_lab.python.lab_client import LabClient, PROTOCOL_V2
from .e24_working_memory import (
    E24WorkingMemory, SOURCE, SUBJECT, PREDICATE,
    vision_source_registration, vision_digest_rule,
)
from .e24_pose import E24PoseTrail
from .egocentric import E23ObserverPort, EgocentricAction, VIEW_ACTION_SCHEMA
from .world_smoke import PROJECT, _port, _wait

CONTROL_SCHEMA = "anima.lab.visual_runner_state/0.1"
MAX_STEPS = 32
EVENT_LIMIT = 16
_DECISION_SQL = """
CREATE TABLE IF NOT EXISTS visual_decisions (
 sequence INTEGER PRIMARY KEY CHECK(sequence > 0),
 pre_sample_id TEXT NOT NULL,
 source_event_id TEXT NOT NULL,
 memory_context_sha256 TEXT NOT NULL,
 proposal_json TEXT NOT NULL,
 admission TEXT NOT NULL CHECK(admission='LAB_ADMITTED'),
 reason TEXT NOT NULL,
 receipt_json TEXT,
 after_sample_id TEXT,
 outcome TEXT
);
"""


class VisualRunnerError(RuntimeError):
    pass


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _sha(data: Any) -> str:
    import hashlib
    return hashlib.sha256(_json(data).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PolicyChoice:
    kind: str
    direction: str
    reason: str
    basis: str
    approach_finishes: bool = False


class CrateInvestigationPolicy:
    """Minimal deterministic policy; rules depend on real observation, not seed.

    Goal: obtain direct sight of the crate, then perform a verified forward
    approach step while aligned. This is NOT a learned navigation strategy.
    """

    @staticmethod
    def propose(view: dict, memory: dict, pose: dict) -> PolicyChoice:
        crate = next((
            row for row in view["readings"]
            if row["entity_ref"] == "lab.item.crate"
        ), None)
        if crate is not None:
            bearing = crate["bearing_mdeg"]
            if bearing > 16_000:
                return PolicyChoice("world.turn", "right",
                                    "CRATE_VISIBLE_RIGHT", "current_raw")
            if bearing < -16_000:
                return PolicyChoice("world.turn", "left",
                                    "CRATE_VISIBLE_LEFT", "current_raw")
            near = crate["range_milli_cells"] <= 1550
            return PolicyChoice(
                "world.step", "forward",
                "APPROACH_VISIBLE_CRATE", "current_raw", near,
            )

        if memory["memory_enabled"]:
            remembered = next((
                entry for entry in memory["entities"]
                if entry["entity_ref"] == "lab.item.crate"
            ), None)
            if remembered is not None:
                # Last-seen bearing is in a PREVIOUS viewpoint, not current.
                # Project the remembered location through the locally
                # reconstructed, readback-proven egocentric pose history.
                poses = {p["sample_id"]: p for p in pose["poses"]}
                old = poses.get(remembered["last_seen_sample"])
                current = pose["poses"][-1]
                if old is not None:
                    angle = math.radians(
                        remembered["last_seen_view"]["bearing_mdeg"] / 1000
                    )
                    distance = remembered["last_seen_view"]["range_milli_cells"] / 1000
                    heading = old["relative_heading_quadrants"]
                    forward_axes = ((0, 1), (1, 0), (0, -1), (-1, 0))
                    right_axes = ((1, 0), (0, -1), (-1, 0), (0, 1))
                    fx, fy = forward_axes[heading]
                    rx, ry = right_axes[heading]
                    target_x = (old["local_right_steps"] +
                                distance * (fx * math.cos(angle) + rx * math.sin(angle)))
                    target_y = (old["local_forward_steps"] +
                                distance * (fy * math.cos(angle) + ry * math.sin(angle)))
                    dx = target_x - current["local_right_steps"]
                    dy = target_y - current["local_forward_steps"]
                    if math.hypot(dx, dy) > 0.6:
                        h = current["relative_heading_quadrants"]
                        cf, cr = forward_axes[h], right_axes[h]
                        fwd = dx * cf[0] + dy * cf[1]
                        right = dx * cr[0] + dy * cr[1]
                        if right > 0.25:
                            return PolicyChoice("world.turn", "right",
                                                "CHECK_REMEMBERED_TARGET", "memory_hypothesis")
                        if right < -0.25:
                            return PolicyChoice("world.turn", "left",
                                                "CHECK_REMEMBERED_TARGET", "memory_hypothesis")
                        if fwd < -0.25:
                            return PolicyChoice("world.turn", "right",
                                                "REORIENT_REMEMBERED_TARGET", "memory_hypothesis")
                        # Don't walk blindly toward a target absent in current
                        # sensor. Rotate and seek new direct evidence first.
        return PolicyChoice("world.turn", "right",
                            "SEARCH_NEW_VIEW", "current_uncertainty")


class VisualDecisionSession:
    """One-actor step engine. All external actions live in this trusted object."""

    def __init__(self, *, memory: E24WorkingMemory, pose: E24PoseTrail,
                 world_port: int, executor_key: str, max_steps: int = MAX_STEPS):
        if type(memory) is not E24WorkingMemory or type(pose) is not E24PoseTrail:
            raise TypeError("visual engine requires verified E24 Core and pose")
        if type(world_port) is not int or not 1024 <= world_port <= 65535:
            raise ValueError("invalid world port")
        if type(executor_key) is not str or len(executor_key) < 32:
            raise ValueError("invalid executor capability")
        if type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS:
            raise ValueError("bounded max_steps 1..32")
        self.memory = memory
        self.pose = pose
        self.world_port = world_port
        self.executor_key = executor_key
        self.max_steps = max_steps
        self.memory_enabled = True
        self.goal_status = "ACTIVE"
        self.sequence = 0
        self.last_sample_id: str | None = None
        self.events: list[dict] = []
        self.last_choice: dict | None = None
        self.last_outcome: dict | None = None
        self.run_enabled = False
        self.busy = False
        self.error: str | None = None
        self.lock = threading.RLock()
        with closing(memory._connect()) as db:
            db.executescript(_DECISION_SQL)

    def _event(self, stage: str, value: str, *, evidence: str | None = None):
        self.events.append({
            "stage": stage, "text": value,
            "source_event_id": evidence,
            "sequence": self.sequence,
        })
        del self.events[:-EVENT_LIMIT]

    def snapshot(self) -> dict:
        with self.lock:
            try:
                model = self.memory.world_model(memory_enabled=self.memory_enabled) if self.last_sample_id else None
                viewpoint = self.pose.reconstruct() if self.last_sample_id else None
                current = self.memory.raw_evidence(self.last_sample_id).as_dict() if self.last_sample_id else None
                recalled = [] if model is None else [
                    {"entity_ref": x["entity_ref"],
                     "status": x["current_observation"],
                     "evidence_count": x["evidence_count"],
                     "source_event_id": x["last_seen_event_id"]}
                    for x in model["entities"]
                    if x["category"] != "surface"
                ][:8]
                visible = [] if current is None else [
                    {"entity_ref": x["entity_ref"],
                     "bearing_mdeg": x["bearing_mdeg"],
                     "range_milli_cells": x["range_milli_cells"]}
                    for x in current["readings"] if x["category"] != "surface"
                ][:8]
                last_pose = None if viewpoint is None else viewpoint["poses"][-1]
                return {
                    "schema": CONTROL_SCHEMA,
                    "runner_connected": True,
                    "mode": "DETERMINISTIC",
                    "model_connected": False,
                    "action_admission": "LAB_ONLY_NOT_STAGE6",
                    "goal": "observe_crate_then_verified_approach_step",
                    "goal_status": self.goal_status,
                    "run_enabled": self.run_enabled,
                    "busy": self.busy,
                    "memory_enabled": self.memory_enabled,
                    "max_steps": self.max_steps,
                    "steps": self.sequence,
                    "latest_sample": self.last_sample_id,
                    "agent_view": visible,
                    "memory": recalled,
                    "relative_pose": last_pose,
                    "last_choice": self.last_choice,
                    "last_outcome": self.last_outcome,
                    "trace": self.events[-8:],
                    "error": self.error,
                }
            except Exception as exc:
                # Fail-closed telemetry: corrupted Core evidence is not displayed.
                return {"schema": CONTROL_SCHEMA, "runner_connected": True,
                        "goal_status": "ERROR", "error": type(exc).__name__}

    def step(self):
        """One full read→proposal→lab admission→effect→verification cycle."""
        with self.lock:
            if self.goal_status != "ACTIVE":
                return
            if self.sequence >= self.max_steps:
                self.goal_status = "BOUNDED_STOP"
                self.run_enabled = False
                self._event("BUDGET", "Reached bounded action budget")
                return
            self.busy = True
            try:
                if self.last_sample_id is None:
                    first = self.memory.observe_and_record()
                    self.last_sample_id = first.sample_id
                    self._event("OBSERVE", "Captured initial agent-only view",
                                evidence=first.core_event_id)
                view = self.memory.raw_evidence(self.last_sample_id).as_dict()
                model = self.memory.world_model(memory_enabled=self.memory_enabled)
                pose = self.pose.reconstruct()
                choice = CrateInvestigationPolicy.propose(view, model, pose)
                self.sequence += 1
                self.last_choice = {
                    "operation": choice.kind, "direction": choice.direction,
                    "reason_code": choice.reason, "basis": choice.basis,
                    "source_sample_id": view["sample_id"],
                }
                self._event("DECIDE", f"{choice.kind}({choice.direction}): {choice.reason}")
                operation = f"visual_step_{self.sequence}"
                action = EgocentricAction({
                    "schema": VIEW_ACTION_SCHEMA,
                    "world_instance_id": view["world_instance_id"],
                    "epoch": view["epoch"],
                    "expected_revision": view["revision"],
                    "observation_id": view["sample_id"],
                    "operation_id": operation,
                    "action_type": choice.kind,
                    "arguments": {"direction": choice.direction},
                })
                # Explicit LAB-only admission: admissible kinds/directions are
                # constrained by EgocentricAction. Core event provenance is
                # checked by E24 before signing decision; NOT native Stage6.
                proof = self.memory.raw_evidence(view["sample_id"])
                with closing(self.memory._connect()) as db:
                    raw = db.execute(
                        "SELECT core_event_id FROM e24_raw WHERE sample_id=?",
                        (view["sample_id"],),
                    ).fetchone()
                    if raw is None or not raw["core_event_id"]:
                        raise VisualRunnerError("unproven source event")
                    db.execute(
                        "INSERT INTO visual_decisions(sequence,pre_sample_id,"
                        "source_event_id,memory_context_sha256,proposal_json,"
                        "admission,reason) VALUES(?,?,?,?,?,?,?)",
                        (self.sequence, view["sample_id"], raw["core_event_id"],
                         _sha(self.memory.context_for_cognition(
                             memory_enabled=self.memory_enabled
                         )), action.canonical_json, "LAB_ADMITTED", choice.reason),
                    )
                self._event("ADMIT", "LAB_ADMITTED (not Stage6)",
                            evidence=raw["core_event_id"])
                with LabClient(self.world_port, role="agent",
                               protocol=PROTOCOL_V2) as client:
                    receipt = client.call(
                        "act", auth=self.executor_key, action=action.as_dict()
                    )["data"]
                # Independently read back the exact action from the world ledger.
                confirmed = self.pose.record_verified_external_action(action)
                if (confirmed["operation_id"] != receipt["operation_id"]
                        or confirmed["revision"] != receipt["revision"]
                        or confirmed["tick"] != receipt["tick"]
                        or confirmed["effect_applied"] != receipt["effect_applied"]):
                    raise VisualRunnerError("world effect receipt/readback mismatch")
                observed = self.memory.observe_and_record()
                self.last_sample_id = observed.sample_id
                trail = self.pose.reconstruct()
                trans = trail["verified_transitions"]
                if not trans or trans[-1]["operation_id"] != operation:
                    raise VisualRunnerError("new Raw does not verify world transition")
                with closing(self.memory._connect()) as db:
                    db.execute(
                        "UPDATE visual_decisions SET receipt_json=?,"
                        "after_sample_id=?,outcome=? WHERE sequence=?",
                        (_json(confirmed), observed.sample_id,
                         "VERIFIED_EFFECT" if receipt["effect_applied"]
                         else "VERIFIED_BLOCKED", self.sequence),
                    )
                self.last_outcome = {
                    "status": "VERIFIED_EFFECT" if receipt["effect_applied"] else "VERIFIED_BLOCKED",
                    "operation_id": operation, "after_sample_id": observed.sample_id,
                    "source_event_id": observed.core_event_id,
                }
                self._event("VERIFY", self.last_outcome["status"],
                            evidence=observed.core_event_id)
                if (receipt["effect_applied"] and choice.approach_finishes
                        and choice.kind == "world.step"
                        and choice.basis == "current_raw"):
                    self.goal_status = "COMPLETED_LAB_CONDITION"
                    self.run_enabled = False
                    self._event("GOAL", "Observed crate; verified approach step completed")
            except Exception as exc:
                self.goal_status = "BLOCKED_UNVERIFIED"
                self.run_enabled = False
                self.error = f"{type(exc).__name__}: {exc}"
                self._event("ERROR", "Stopped: uncertain world/Core state; no blind replay")
            finally:
                self.busy = False


class VisualControlService:
    """Loopback JSON control API, one serialized worker for all effects."""

    def __init__(self, session: VisualDecisionSession, *, port: int, token: str,
                 interval: float = 1.2):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("bad control port")
        if type(token) is not str or len(token) < 32:
            raise ValueError("invalid control token")
        if not 0.2 <= interval <= 10:
            raise ValueError("interval out of range")
        self.session = session
        self.token = token
        self.interval = interval
        self.commands: queue.Queue[str] = queue.Queue(maxsize=4)
        self.halt = threading.Event()
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _response(self, status, payload):
                encoded = _json(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)

            def _authorized(self):
                return self.headers.get("X-ANIMA-Control-Key", "") == service.token

            def do_GET(self):
                if not self._authorized():
                    self._response(403, {"error": "FORBIDDEN"})
                    return
                if urlsplit(self.path).path != "/state":
                    self._response(404, {"error": "NOT_FOUND"})
                    return
                self._response(200, service.session.snapshot())

            def do_POST(self):
                if not self._authorized():
                    self._response(403, {"error": "FORBIDDEN"})
                    return
                cmd = urlsplit(self.path).path
                if cmd not in ("/step", "/run", "/pause", "/memory"):
                    self._response(404, {"error": "NOT_FOUND"})
                    return
                length = self.headers.get("Content-Length", "0")
                if length not in ("0", ""):
                    self._response(400, {"error": "NONEMPTY_BODY"})
                    return
                try:
                    service.commands.put_nowait(cmd[1:])
                except queue.Full:
                    self._response(429, {"error": "COMMAND_QUEUE_FULL"})
                    return
                self._response(202, {"queued": cmd[1:]})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.http_worker = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.http_worker.start()
        self.worker.start()

    def _work(self):
        next_run = time.monotonic()
        while not self.halt.is_set():
            try:
                command = self.commands.get(timeout=0.1)
            except queue.Empty:
                command = None
            if command is not None:
                with self.session.lock:
                    if command == "pause":
                        self.session.run_enabled = False
                    elif command == "run" and self.session.goal_status == "ACTIVE":
                        self.session.run_enabled = True
                    elif command == "memory" and not self.session.busy:
                        self.session.memory_enabled = not self.session.memory_enabled
                    elif command == "step" and self.session.goal_status == "ACTIVE":
                        self.session.run_enabled = False
                        self.session.step()
                next_run = time.monotonic() + self.interval
            if (self.session.run_enabled
                    and time.monotonic() >= next_run
                    and not self.halt.is_set()):
                self.session.step()
                next_run = time.monotonic() + self.interval

    def stop(self):
        self.halt.set()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.http_worker.join(timeout=3)


def launch(*, godot: str, seed: int, headless: bool,
           report_dir: Path | None = None, step_interval: float = 1.2):
    root = report_dir or Path(tempfile.mkdtemp(prefix="anima-visual-runner-"))
    root.mkdir(parents=True, exist_ok=True)
    world_port, control_port = _port(), _port()
    while control_port == world_port:
        control_port = _port()
    observer_key, executor_key, operator_key, control_key = (
        secrets.token_urlsafe(32) for _ in range(4)
    )
    env = {
        **os.environ,
        "ANIMA_LIFECYCLE_OBSERVER_KEY": observer_key,
        "ANIMA_LIFECYCLE_EXECUTOR_KEY": executor_key,
        "ANIMA_LIFECYCLE_OPERATOR_KEY": operator_key,
        "ANIMA_VISUAL_CONTROL_KEY": control_key,
    }
    args = [godot]
    if headless:
        args.append("--headless")
    args += [
        "--path", str(PROJECT), "res://LifecycleWorld.tscn", "--",
        "--lifecycle-port", str(world_port), "--lifecycle-seed", str(seed),
        "--lifecycle-guarded", "--lifecycle-effects", "--lifecycle-ledger",
        "--lifecycle-egocentric", "--lifecycle-debug-ui",
        "--lifecycle-visual-control-port", str(control_port),
    ]
    logfile = (root / "godot-visual.log").open("w", encoding="utf-8")
    process = subprocess.Popen(args, cwd=PROJECT, env=env,
                               stdout=logfile, stderr=subprocess.STDOUT)
    service = None
    try:
        ready = _wait(process, world_port)
        ready.close()
        instance = build_core(
            root / "core",
            sources={SOURCE: vision_source_registration()},
            properties={(SUBJECT, PREDICATE): vision_digest_rule()},
        )
        memory = E24WorkingMemory(
            instance, E23ObserverPort(port=world_port, observer_key=observer_key),
        )
        pose = E24PoseTrail(memory, port=world_port, executor_key=executor_key)
        session = VisualDecisionSession(
            memory=memory, pose=pose,
            world_port=world_port, executor_key=executor_key,
        )
        service = VisualControlService(
            session, port=control_port, token=control_key, interval=step_interval,
        )
        service.start()
        print("ANIMA_VISUAL_RUNNER_READY", flush=True)
        print(f"Godot world: {world_port}, diagnostics/control: {control_port}", flush=True)
        print("Mode: deterministic / LAB_ADMISSION / Core-backed Raw", flush=True)
        print(f"Evidence directory: {root}", flush=True)
        print("Use STEP/RUN/PAUSE in Godot; Ctrl+C exits.", flush=True)
        return session, service, process, logfile
    except BaseException as exc:
        if service:
            service.stop()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        logfile.close()
        try:
            text = (root / "godot-visual.log").read_text(
                encoding="utf-8", errors="replace"
            )[-6000:]
        except OSError:
            text = "Godot log unavailable"
        raise VisualRunnerError(
            f"Godot/control startup failed ({type(exc).__name__}): {exc}\\n"
            f"Godot log:\\n{text}"
        ) from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", default=os.environ.get("GODOT_BIN"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--step-interval", type=float, default=1.2)
    args = parser.parse_args()
    godot = (args.godot or shutil.which("godot") or shutil.which("godot4")
             or str(Path.home() / ".local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"))
    if not Path(godot).is_file():
        raise SystemExit(f"Godot binary not found: {godot}")
    if not 0 <= args.seed <= 2147483647:
        raise SystemExit("--seed out of range")
    session, service, proc, logfile = launch(
        godot=godot, seed=args.seed, headless=args.headless,
        report_dir=args.report_dir, step_interval=args.step_interval,
    )
    try:
        while proc.poll() is None:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        logfile.close()
        print("ANIMA_VISUAL_RUNNER_STOPPED", flush=True)


if __name__ == "__main__":
    main()
