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
CREATE TABLE IF NOT EXISTS visual_hypotheses(
 prior_sample_id TEXT PRIMARY KEY REFERENCES e24_raw(sample_id),
 suspected_sample_id TEXT NOT NULL REFERENCES e24_raw(sample_id),
 prior_event_id TEXT NOT NULL,
 suspected_event_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('SUSPECTED_STALE','REOBSERVED_AFTER_CONFLICT')),
 revised_sample_id TEXT REFERENCES e24_raw(sample_id),
 revised_event_id TEXT
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
    suspect_prior_sample: str | None = None


class CrateInvestigationPolicy:
    """Explicit baseline. Sensor and memory ONLY, no Godot designer truth.

    Historical bearing is projected through readback-confirmed *local* pose.
    A missing target where it was expected creates only a SUSPECTED stale
    hypothesis, never knowledge of the object's true new position.
    """

    @staticmethod
    def _projection(remembered: dict, pose: dict) -> tuple[float, float, float] | None:
        poses = {entry["sample_id"]: entry for entry in pose["poses"]}
        past = poses.get(remembered["last_seen_sample"])
        if past is None:
            return None
        current = pose["poses"][-1]
        angle = math.radians(remembered["last_seen_view"]["bearing_mdeg"] / 1000)
        distance = remembered["last_seen_view"]["range_milli_cells"] / 1000
        h = past["relative_heading_quadrants"]
        forward_axes = ((0, 1), (1, 0), (0, -1), (-1, 0))
        right_axes = ((1, 0), (0, -1), (-1, 0), (0, 1))
        fx, fy = forward_axes[h]
        rx, ry = right_axes[h]
        target_x = (past["local_right_steps"] +
                    distance * (fx * math.cos(angle) + rx * math.sin(angle)))
        target_y = (past["local_forward_steps"] +
                    distance * (fy * math.cos(angle) + ry * math.sin(angle)))
        dx = target_x - current["local_right_steps"]
        dy = target_y - current["local_forward_steps"]
        heading = current["relative_heading_quadrants"]
        cf, cr = forward_axes[heading], right_axes[heading]
        return (
            dx * cf[0] + dy * cf[1],
            dx * cr[0] + dy * cr[1],
            math.hypot(dx, dy),
        )

    @staticmethod
    def _possibly_occluded(view: dict, distance: float) -> bool:
        # If another reported opaque cell is in front, NOT observing the
        # old target is not evidence against its recorded position.
        for row in view["readings"]:
            if (row["category"] in ("surface", "obstacle")
                    and abs(row["bearing_mdeg"]) <= 16_000
                    and row["range_milli_cells"] < int((distance - 0.20) * 1000)):
                return True
        return False

    @classmethod
    def propose(cls, view: dict, memory: dict, pose: dict,
                *, stale_sample_ids: frozenset[str] = frozenset()) -> PolicyChoice:
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
            return PolicyChoice("world.step", "forward",
                                "APPROACH_VISIBLE_CRATE", "current_raw", near)

        if memory["memory_enabled"]:
            remembered = next((
                entry for entry in memory["entities"]
                if entry["entity_ref"] == "lab.item.crate"
            ), None)
            if remembered is not None:
                if remembered["last_seen_sample"] in stale_sample_ids:
                    # Keep the original Raw, but stop trusting its geometry.
                    return PolicyChoice(
                        "world.turn", "right", "SEARCH_AFTER_MEMORY_CONFLICT",
                        "suspected_stale_hypothesis",
                    )
                result = cls._projection(remembered, pose)
                if result is not None:
                    forward, right, distance = result
                    if (forward > 0.7 and abs(right) <= 0.25
                            and distance <= 2.0
                            and not cls._possibly_occluded(view, distance)):
                        # Looked where earlier evidence predicted a crate,
                        # now not observed. This weakens the location
                        # hypothesis, it does not prove the crate absent.
                        return PolicyChoice(
                            "world.turn", "right",
                            "PRIOR_LOCATION_NOT_REOBSERVED",
                            "suspected_stale_hypothesis", False,
                            remembered["last_seen_sample"],
                        )
                    if distance > 0.6:
                        if right > 0.25:
                            return PolicyChoice(
                                "world.turn", "right",
                                "CHECK_REMEMBERED_TARGET", "memory_hypothesis",
                            )
                        if right < -0.25:
                            return PolicyChoice(
                                "world.turn", "left",
                                "CHECK_REMEMBERED_TARGET", "memory_hypothesis",
                            )
                        if forward < -0.25:
                            return PolicyChoice(
                                "world.turn", "right",
                                "REORIENT_REMEMBERED_TARGET", "memory_hypothesis",
                            )
                    # Never step toward a historical target that is not
                    # directly visible in a verified *current* view.
        return PolicyChoice("world.turn", "right",
                            "SEARCH_NEW_VIEW", "current_uncertainty")

class VisualDecisionSession:
    """One-actor step engine. All external actions live in this trusted object."""

    def __init__(self, *, memory: E24WorkingMemory, pose: E24PoseTrail,
                 world_port: int, executor_key: str, max_steps: int = MAX_STEPS,
                 scenario: str = "baseline", memory_enabled: bool = True):
        if type(memory) is not E24WorkingMemory or type(pose) is not E24PoseTrail:
            raise TypeError("visual engine requires verified E24 Core and pose")
        if type(world_port) is not int or not 1024 <= world_port <= 65535:
            raise ValueError("invalid world port")
        if type(executor_key) is not str or len(executor_key) < 32:
            raise ValueError("invalid executor capability")
        if type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS:
            raise ValueError("bounded max_steps 1..32")
        if scenario not in ("baseline", "familiar", "relocated"):
            raise ValueError("unsupported E2.5c experiment scenario")
        if type(memory_enabled) is not bool:
            raise ValueError("memory_enabled must be bool")
        self.memory = memory
        self.pose = pose
        self.world_port = world_port
        self.executor_key = executor_key
        self.max_steps = max_steps
        self.scenario = scenario
        self.memory_enabled = memory_enabled
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

    def hypotheses(self) -> list[dict]:
        with closing(self.memory._connect()) as db:
            entries = db.execute(
                "SELECT * FROM visual_hypotheses ORDER BY suspected_sample_id"
            ).fetchall()
        evidence = []
        with closing(self.memory._connect()) as db:
            core_links = {
                row["sample_id"]: row["core_event_id"]
                for row in db.execute("SELECT sample_id,core_event_id FROM e24_raw")
            }
        for entry in entries:
            previous = self.memory.raw_evidence(entry["prior_sample_id"]).as_dict()
            current = self.memory.raw_evidence(entry["suspected_sample_id"]).as_dict()
            if (entry["prior_event_id"] != core_links.get(entry["prior_sample_id"])
                    or entry["suspected_event_id"] != core_links.get(entry["suspected_sample_id"])
                    or not any(x["entity_ref"] == "lab.item.crate"
                               for x in previous["readings"])
                    or any(x["entity_ref"] == "lab.item.crate"
                           for x in current["readings"])):
                raise VisualRunnerError("contradiction hypothesis not bound to source Raw/Core")
            if entry["status"] == "SUSPECTED_STALE":
                if entry["revised_sample_id"] is not None or entry["revised_event_id"] is not None:
                    raise VisualRunnerError("unconfirmed revision attached to stale hypothesis")
            elif entry["status"] == "REOBSERVED_AFTER_CONFLICT":
                if (not entry["revised_sample_id"]
                        or entry["revised_event_id"] != core_links.get(entry["revised_sample_id"])):
                    raise VisualRunnerError("revision not bound to later Core evidence")
                later = self.memory.raw_evidence(entry["revised_sample_id"]).as_dict()
                if (not any(x["entity_ref"] == "lab.item.crate"
                            for x in later["readings"])):
                    raise VisualRunnerError("revised hypothesis is missing re-observation")
            else:
                raise VisualRunnerError("unknown hypothesis state")
            evidence.append({
                "prior_sample_id": entry["prior_sample_id"],
                "suspected_sample_id": entry["suspected_sample_id"],
                "prior_event_id": entry["prior_event_id"],
                "suspected_event_id": entry["suspected_event_id"],
                "status": entry["status"],
                "revised_sample_id": entry["revised_sample_id"],
                "revised_event_id": entry["revised_event_id"],
                "claim": "observation_conflicts_with_old_location_hypothesis"
                         if entry["status"] == "SUSPECTED_STALE"
                         else "new_observation_revises_old_location_hypothesis",
            })
        return evidence

    def _record_suspected_stale(self, prior_id: str, current_id: str) -> None:
        prior = self.memory.raw_evidence(prior_id).as_dict()
        current = self.memory.raw_evidence(current_id).as_dict()
        if (prior["sample_seq"] >= current["sample_seq"]
                or not any(r["entity_ref"] == "lab.item.crate"
                           for r in prior["readings"])
                or any(r["entity_ref"] == "lab.item.crate"
                       for r in current["readings"])):
            raise VisualRunnerError("weak location hypothesis without two source views")
        with closing(self.memory._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                ids = {}
                for sample_id in (prior_id, current_id):
                    row = db.execute(
                        "SELECT core_event_id FROM e24_raw WHERE sample_id=?",
                        (sample_id,),
                    ).fetchone()
                    if row is None or not row["core_event_id"]:
                        raise VisualRunnerError("missing proven Core Raw for hypothesis")
                    ids[sample_id] = row["core_event_id"]
                db.execute(
                    "INSERT OR IGNORE INTO visual_hypotheses VALUES(?,?,?,?,?,NULL,NULL)",
                    (prior_id, current_id, ids[prior_id], ids[current_id],
                     "SUSPECTED_STALE"),
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        self._event(
            "HYPOTHESIS", "Old crate position NOT RE-OBSERVED; investigate elsewhere",
            evidence=ids[current_id],
        )

    def _revise_if_reobserved(self, sample_id: str, event_id: str) -> None:
        view = self.memory.raw_evidence(sample_id).as_dict()
        if not any(r["entity_ref"] == "lab.item.crate" for r in view["readings"]):
            return
        with closing(self.memory._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                changed = db.execute(
                    "UPDATE visual_hypotheses SET status='REOBSERVED_AFTER_CONFLICT',"
                    "revised_sample_id=?,revised_event_id=? "
                    "WHERE status='SUSPECTED_STALE'",
                    (sample_id, event_id),
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        if changed.rowcount:
            self._event(
                "REVISION", "Found new sensor evidence; previous location hypothesis revised",
                evidence=event_id,
            )

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
                    "scenario": self.scenario,
                    "hypotheses": self.hypotheses(),
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
                stale = frozenset(x["prior_sample_id"] for x in self.hypotheses())
                choice = CrateInvestigationPolicy.propose(
                    view, model, pose, stale_sample_ids=stale,
                )
                self.sequence += 1
                if choice.suspect_prior_sample is not None:
                    self._record_suspected_stale(
                        choice.suspect_prior_sample, view["sample_id"],
                    )
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
                self.memory.raw_evidence(view["sample_id"])
                context_digest = _sha(self.memory.context_for_cognition(
                    memory_enabled=self.memory_enabled
                ))
                with closing(self.memory._connect()) as db:
                    db.execute("BEGIN IMMEDIATE")
                    try:
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
                             context_digest, action.canonical_json,
                             "LAB_ADMITTED", choice.reason),
                        )
                        db.commit()  # Durable admission BEFORE world effect.
                    except BaseException:
                        db.rollback()
                        raise
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
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        updated = db.execute(
                            "UPDATE visual_decisions SET receipt_json=?,"
                            "after_sample_id=?,outcome=? "
                            "WHERE sequence=? AND outcome IS NULL",
                            (_json(confirmed), observed.sample_id,
                             "VERIFIED_EFFECT" if receipt["effect_applied"]
                             else "VERIFIED_BLOCKED", self.sequence),
                        )
                        if updated.rowcount != 1:
                            raise VisualRunnerError("missing or already finalized decision")
                        db.commit()  # Durable verified outcome AFTER new Core Raw.
                    except BaseException:
                        db.rollback()
                        raise
                self._revise_if_reobserved(observed.sample_id, observed.core_event_id)
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


def prepare_trial(session: VisualDecisionSession, *, scenario: str,
                  operator_key: str) -> None:
    """Controlled prehistory only. All evaluated actions come from policy.

    Harness sets up the previous experience before user-controlled STEP/RUN.
    For relocated only, it applies one privileged world intervention. Only
    redacted receipt clocks reach E24PoseTrail; target x/y are never added
    to agent Context, Raw, decisions or UI telemetry.
    """
    if scenario == "baseline":
        return
    if scenario not in ("familiar", "relocated"):
        raise ValueError("unsupported scenario")
    first = session.memory.observe_and_record()
    session.last_sample_id = first.sample_id
    session._event("PREP", "Familiarization: initial view", evidence=first.core_event_id)
    for index in (1, 2):
        before = session.memory.raw_evidence(session.last_sample_id).as_dict()
        action = EgocentricAction({
            "schema": VIEW_ACTION_SCHEMA,
            "world_instance_id": before["world_instance_id"],
            "epoch": before["epoch"], "expected_revision": before["revision"],
            "observation_id": before["sample_id"],
            "operation_id": f"prehistory_turn_{index}",
            "action_type": "world.turn", "arguments": {"direction": "right"},
        })
        with LabClient(session.world_port, role="agent", protocol=PROTOCOL_V2) as client:
            receipt = client.call(
                "act", auth=session.executor_key, action=action.as_dict()
            )["data"]
        confirmed = session.pose.record_verified_external_action(action)
        if (confirmed["event_id"] != receipt["event_id"]
                or confirmed["revision"] != receipt["revision"]
                or confirmed["tick"] != receipt["tick"]):
            raise VisualRunnerError("prehistory action receipt not reverified")
        after = session.memory.observe_and_record()
        session.last_sample_id = after.sample_id
        session.pose.reconstruct()
    session._event(
        "PREP", "Previous crate observation is now outside current view",
        evidence=session.memory.world_model()["entities"][0]["last_seen_event_id"]
                 if session.memory.world_model()["entities"] else None,
    )
    if scenario == "relocated":
        before = session.memory.raw_evidence(session.last_sample_id).as_dict()
        fixture_request = {
            "fixture_id": "fixture_move_crate",
            "world_instance_id": before["world_instance_id"],
            "epoch": before["epoch"],
            "expected_revision": before["revision"],
            "expected_sample_id": before["sample_id"],
            "at": {"x": 2, "y": 5},
        }
        with LabClient(session.world_port, role="operator", protocol=PROTOCOL_V2) as op:
            receipt = op.call("relocate_item", auth=operator_key,
                              **fixture_request)["data"]
            replay = op.call("relocate_item", auth=operator_key,
                             **fixture_request)["data"]
        if (receipt["status"] != "APPLIED" or receipt["replayed"] is not False
                or replay["replayed"] is not True
                or replay["event_id"] != receipt["event_id"]
                or replay["revision"] != receipt["revision"]
                or replay["tick"] != receipt["tick"]):
            raise VisualRunnerError("operator fixture isn't idempotent")
        session.pose.record_operator_world_change(receipt)
        after = session.memory.observe_and_record()
        session.last_sample_id = after.sample_id
        changes = session.pose.reconstruct()["verified_external_changes"]
        if len(changes) != 1 or changes[0]["after_sample_id"] != after.sample_id:
            raise VisualRunnerError("unexpected external change not linked to new Raw")
        session._event(
            "PREP", "Operator changed hidden world; agent receives only new vision",
            evidence=after.core_event_id,
        )
    session._event("READY", "Evaluation begins: agent policy chooses all next actions")


def launch(*, godot: str, seed: int, headless: bool,
           report_dir: Path | None = None, step_interval: float = 1.2,
           scenario: str = "baseline", memory_enabled: bool = True):
    if scenario not in ("baseline", "familiar", "relocated"):
        raise ValueError("unsupported visual experiment")
    if type(memory_enabled) is not bool:
        raise ValueError("memory access ablation must be bool")
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
    if scenario == "relocated":
        args.append("--lifecycle-e25c-fixtures")
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
            scenario=scenario, memory_enabled=memory_enabled,
        )
        prepare_trial(session, scenario=scenario, operator_key=operator_key)
        service = VisualControlService(
            session, port=control_port, token=control_key, interval=step_interval,
        )
        service.start()
        print("ANIMA_VISUAL_RUNNER_READY", flush=True)
        print(f"Godot world: {world_port}, diagnostics/control: {control_port}", flush=True)
        print("Mode: deterministic / LAB_ADMISSION / Core-backed Raw", flush=True)
        print(f"Scenario: {scenario}; historical memory: {'ON' if memory_enabled else 'OFF'}", flush=True)
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
    parser.add_argument("--scenario", choices=("baseline", "familiar", "relocated"),
                        default="baseline")
    parser.add_argument("--memory", choices=("on", "off"), default="on")
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
        scenario=args.scenario, memory_enabled=args.memory == "on",
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
