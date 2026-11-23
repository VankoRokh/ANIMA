"""E2.5a bounded read-only cognitive initiation in an isolated lab.

This is a *laboratory admission policy*, not Stage6/Core native admission.
The existing CoreAssembly remains source-of-truth for Raw pointers/Belief;
CognitiveStepProposal is untrusted. No LLM access to SQLite, OS, Godot,
executors, MemoryStore writes, confirmed Knowledge, Goal or world actions.

Adapter may initiate ANOTHER registered read-only step after inspecting prior
verified outcomes. The trusted coordinator admits each proposed step and
writes pre-execution decision evidence before invoking a handler.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from typing import Any

from labs.virtual_anima_lab.python.cognition.contracts import (
    CognitiveStepProposal, CognitiveProposalError, SCHEMA,
)
from labs.virtual_anima_lab.python.lifecycle.e24_working_memory import (
    E24WorkingMemory, E24MemoryError, SUBJECT, PREDICATE,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS e25_cognitive_trace (
 turn_id TEXT NOT NULL,
 step_index INTEGER NOT NULL CHECK(step_index BETWEEN 0 AND 7),
 proposal_id TEXT,
 operation_kind TEXT,
 context_json TEXT NOT NULL,
 context_sha256 TEXT NOT NULL,
 proposal_json TEXT,
 admission TEXT NOT NULL CHECK(admission IN ('ADMITTED','REJECTED')),
 reason_code TEXT NOT NULL,
 outcome_json TEXT,
 outcome_sha256 TEXT,
 PRIMARY KEY(turn_id, step_index),
 UNIQUE(proposal_id)
);
"""
_TURN_ID = re.compile(r"[A-Za-z][A-Za-z0-9._:/@-]{0,71}\Z")
MAX_STEPS = 6
MAX_RESULT_BYTES = 16384
MAX_CONTEXT_BYTES = 32768


class E25CognitionError(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_only_result(memory: E24WorkingMemory, *, kind: str,
                      args: dict, memory_enabled: bool) -> dict:
    """Actual trusted service reads, never a model-generated outcome."""
    if kind == "retrieve_memory":
        model = memory.world_model(memory_enabled=memory_enabled)
        # Transparent deterministic string-match baseline, NOT semantic search
        # and not production EpisodicMemory or Knowledge.
        tokens = set(re.findall(r"[a-z0-9]{3,}", args["query"].lower()))
        matches = [
            entity for entity in model["entities"]
            if any(token in entity["entity_ref"].lower() for token in tokens)
        ]
        return {
            "kind": "working_world_memory_search",
            "strategy": "substring_baseline_not_semantic_retrieval",
            "records": matches[:args["top_k"]],
            "returned": min(len(matches), args["top_k"]),
            "possible_matches": len(matches),
            "truncated": len(matches) > args["top_k"],
            "memory_enabled": memory_enabled,
        }
    if kind == "lookup_raw_evidence":
        records = []
        # Explicit IDs; never arbitrary paths, raw SQL, or model-provided raw.
        for event_id in args["event_ids"]:
            with closing(memory._connect()) as db:
                row = db.execute(
                    "SELECT sample_id FROM e24_raw WHERE core_event_id=?",
                    (event_id,),
                ).fetchone()
            if row is None:
                records.append({"event_id": event_id, "status": "not_found"})
                continue
            view = memory.raw_evidence(row["sample_id"])
            observed = view.as_dict()
            records.append({
                "event_id": event_id, "status": "verified_source_view",
                "sample_id": observed["sample_id"],
                "source_ref": observed["source_ref"],
                "sample_seq": observed["sample_seq"],
                "raw_sha256": _sha(view.canonical_json),
                "entities_observed": [r["entity_ref"] for r in observed["readings"]],
                "coverage": observed["coverage"],
            })
        return {"kind": "verified_raw_evidence", "records": records}
    if kind == "inspect_current_belief":
        # Core owns the property registry; no model-selected arbitrary SQL.
        if (args["subject_ref"], args["predicate_ref"]) != (SUBJECT, PREDICATE):
            raise E25CognitionError("UNREGISTERED_PROPERTY")
        read = memory._core.core_events.ingress.read_belief(
            SUBJECT, PREDICATE,
            as_of_tick=memory.world_model()["latest_sample_seq"],
        )
        return {"kind": "core_working_belief", "record": read}
    raise E25CognitionError("OPERATION_UNAVAILABLE")


class E25LabCognitiveCoordinator:
    """Only read-only lab cognition; no independent Core identity or executor."""

    def __init__(self, memory: E24WorkingMemory, *, max_steps: int = 4):
        if type(memory) is not E24WorkingMemory:
            raise TypeError("trusted E24WorkingMemory required")
        if type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS:
            raise ValueError("1..6 cognitive steps budget required")
        if memory._core.core_events is None:
            raise E25CognitionError("no connected CoreIngress")
        self._memory = memory
        self._max_steps = max_steps
        with closing(memory._connect()) as db:
            db.executescript(_SCHEMA)

    def _record(self, *, turn: str, step: int, context: str,
                proposal_id: str | None, op: str | None,
                proposal: str | None, admission: str, reason: str) -> None:
        with closing(self._memory._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "INSERT INTO e25_cognitive_trace("
                    "turn_id,step_index,proposal_id,operation_kind,"
                    "context_json,context_sha256,proposal_json,admission,"
                    "reason_code,outcome_json,outcome_sha256) VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)",
                    (turn, step, proposal_id, op, context, _sha(context),
                     proposal, admission, reason),
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _finalize(self, turn: str, step: int, output: dict) -> None:
        data = _json(output)
        if len(data.encode("utf-8")) > MAX_RESULT_BYTES:
            raise E25CognitionError("OUTCOME_BUDGET_EXCEEDED")
        with closing(self._memory._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cursor = db.execute(
                    "UPDATE e25_cognitive_trace SET outcome_json=?,outcome_sha256=? "
                    "WHERE turn_id=? AND step_index=? AND outcome_json IS NULL",
                    (data, _sha(data), turn, step),
                )
                if cursor.rowcount != 1:
                    raise E25CognitionError("decision result cannot be overwritten")
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def run_turn(self, adapter: Any, *, turn_id: str,
                 memory_enabled: bool = True,
                 focus_refs: tuple[str, ...] = ()) -> dict:
        if type(turn_id) is not str or _TURN_ID.fullmatch(turn_id) is None:
            raise ValueError("bounded safe turn_id required")
        if type(memory_enabled) is not bool:
            raise TypeError("memory_enabled must be boolean")
        if not callable(getattr(adapter, "propose", None)):
            raise TypeError("adapter must expose propose(context,outcomes,turn_id,step_index)")
        with closing(self._memory._connect()) as db:
            if db.execute("SELECT 1 FROM e25_cognitive_trace WHERE turn_id=?",
                          (turn_id,)).fetchone():
                raise E25CognitionError("turn already recorded; no implicit replay")
        view = self._memory.context_for_cognition(
            focus_refs=focus_refs, memory_enabled=memory_enabled,
        )
        base = _json(view)
        if len(base.encode("utf-8")) > MAX_CONTEXT_BYTES:
            raise E25CognitionError("world context exceeds lab budget")
        ctx_id = "ctx_" + _sha(base)
        context = {**view, "context_snapshot_id": ctx_id}
        frozen = _json(context)
        outcomes = []
        for step in range(self._max_steps):
            # Reject races/new observations between generated proposals.
            checked = self._memory.context_for_cognition(
                focus_refs=focus_refs, memory_enabled=memory_enabled,
            )
            if _sha(_json(checked)) != _sha(base):
                raise E25CognitionError("context changed during cognitive turn")
            try:
                raw = adapter.propose(
                    json.loads(frozen), json.loads(_json(outcomes)),
                    turn_id=turn_id, step_index=step,
                )
            except Exception as exc:
                self._record(
                    turn=turn_id, step=step, context=frozen,
                    proposal_id=None, op=None, proposal=None,
                    admission="REJECTED", reason="ADAPTER_FAILURE",
                )
                outcome = {
                    "schema": "anima.lab.cognitive_outcome/0.1",
                    "status": "REJECTED", "reason_code": "ADAPTER_FAILURE",
                    "step_index": step, "proposal_id": None,
                }
                self._finalize(turn_id, step, outcome)
                outcomes.append(outcome)
                break
            # Adapter execution may overlap another sensor process. Never
            # admit a proposal against an observation which changed while the
            # candidate was being prepared.
            fresh = self._memory.context_for_cognition(
                focus_refs=focus_refs, memory_enabled=memory_enabled,
            )
            if _sha(_json(fresh)) != _sha(base):
                self._record(
                    turn=turn_id, step=step, context=frozen,
                    proposal_id=None, op=None, proposal=None,
                    admission="REJECTED", reason="STALE_CONTEXT",
                )
                output = {
                    "schema": "anima.lab.cognitive_outcome/0.1",
                    "status": "REJECTED", "reason_code": "STALE_CONTEXT",
                    "step_index": step, "proposal_id": None,
                }
                self._finalize(turn_id, step, output)
                outcomes.append(output)
                break
            if raw is None:
                # An empty proposal is an explicit stop and is not a cognitive step.
                break
            try:
                proposal = CognitiveStepProposal(raw).as_dict()
                if proposal["turn_id"] != turn_id:
                    raise CognitiveProposalError("turn ID mismatch")
                if proposal["context_snapshot_id"] != ctx_id:
                    raise CognitiveProposalError("stale/forged context snapshot")
                if proposal["proposal_id"] in {
                    x["proposal_id"] for x in outcomes if x.get("proposal_id")
                }:
                    raise CognitiveProposalError("duplicate proposal identity")
            except (CognitiveProposalError, ValueError, TypeError):
                self._record(
                    turn=turn_id, step=step, context=frozen,
                    proposal_id=None, op=None, proposal=None,
                    admission="REJECTED", reason="INVALID_PROPOSAL",
                )
                output = {
                    "schema": "anima.lab.cognitive_outcome/0.1",
                    "status": "REJECTED", "reason_code": "INVALID_PROPOSAL",
                    "step_index": step, "proposal_id": None,
                }
                self._finalize(turn_id, step, output)
                outcomes.append(output)
                break
            kind = proposal["operation_kind"]
            admissible = kind in {
                "retrieve_memory", "lookup_raw_evidence", "inspect_current_belief"
            }
            if kind == "inspect_goal_status":
                # No trusted GoalDecision configured in this lab. Fail closed.
                admissible = False
            reason = "POLICY_READ_ONLY" if admissible else "OPERATION_UNAVAILABLE"
            self._record(
                turn=turn_id, step=step, context=frozen,
                proposal_id=proposal["proposal_id"], op=kind,
                proposal=_json(proposal),
                admission="ADMITTED" if admissible else "REJECTED",
                reason=reason,
            )
            if not admissible:
                output = {
                    "schema": "anima.lab.cognitive_outcome/0.1",
                    "status": "REJECTED", "reason_code": reason,
                    "step_index": step, "proposal_id": proposal["proposal_id"],
                    "operation_kind": kind,
                }
                self._finalize(turn_id, step, output)
                outcomes.append(output)
                break
            try:
                result = _read_only_result(
                    self._memory, kind=kind, args=proposal["arguments"],
                    memory_enabled=memory_enabled,
                )
                output = {
                    "schema": "anima.lab.cognitive_outcome/0.1",
                    "status": "COMPLETED", "reason_code": "VERIFIED_SERVICE_READ",
                    "step_index": step, "proposal_id": proposal["proposal_id"],
                    "operation_kind": kind, "result": result,
                }
                if len(_json(output).encode("utf-8")) > MAX_RESULT_BYTES:
                    raise E25CognitionError("OUTCOME_BUDGET_EXCEEDED")
                verified_context = self._memory.context_for_cognition(
                    focus_refs=focus_refs, memory_enabled=memory_enabled,
                )
                if _sha(_json(verified_context)) != _sha(base):
                    raise E25CognitionError("STALE_CONTEXT")
            except (E24MemoryError, E25CognitionError, ValueError, TypeError):
                output = {
                    "schema": "anima.lab.cognitive_outcome/0.1",
                    "status": "REJECTED", "reason_code": "SERVICE_REJECTED",
                    "step_index": step, "proposal_id": proposal["proposal_id"],
                    "operation_kind": kind,
                }
            self._finalize(turn_id, step, output)
            outcomes.append(output)
            if output["status"] != "COMPLETED":
                break
        else:
            # Explicit budget exhaustion, no free-running cognitive loop.
            return {
                "schema": "anima.lab.cognitive_turn/0.1",
                "turn_id": turn_id, "context_snapshot_id": ctx_id,
                "status": "STEP_BUDGET_EXHAUSTED", "outcomes": outcomes,
                "lab_admission_only": True,
                "model_executive_authority": False,
            }
        return {
            "schema": "anima.lab.cognitive_turn/0.1",
            "turn_id": turn_id, "context_snapshot_id": ctx_id,
            "status": ("STOPPED" if not outcomes or outcomes[-1]["status"] == "COMPLETED"
                       else "REJECTED"),
            "outcomes": outcomes,
            "lab_admission_only": True,
            "model_executive_authority": False,
        }

    def decision_records(self, turn_id: str) -> list[dict]:
        if type(turn_id) is not str or _TURN_ID.fullmatch(turn_id) is None:
            raise ValueError("invalid turn")
        with closing(self._memory._connect()) as db:
            records = db.execute(
                "SELECT * FROM e25_cognitive_trace WHERE turn_id=? "
                "ORDER BY step_index", (turn_id,),
            ).fetchall()
        out = []
        first_context_hash = None
        for row in records:
            if _sha(row["context_json"]) != row["context_sha256"]:
                raise E25CognitionError("decision context was modified after admission")
            if first_context_hash is None:
                first_context_hash = row["context_sha256"]
            elif first_context_hash != row["context_sha256"]:
                raise E25CognitionError("cognitive turn changed Context without renewal")
            if row["outcome_json"] is None or row["outcome_sha256"] is None:
                raise E25CognitionError("interrupted step; outcome unknown")
            if _sha(row["outcome_json"]) != row["outcome_sha256"]:
                raise E25CognitionError("decision result was modified after admission")
            outcome = json.loads(row["outcome_json"])
            if (outcome.get("step_index") != row["step_index"]
                    or outcome.get("proposal_id") != row["proposal_id"]
                    or (row["admission"] == "REJECTED" and outcome.get("status") != "REJECTED")
                    or outcome.get("status") not in ("REJECTED", "COMPLETED")):
                raise E25CognitionError("outcome/admission identity mismatched")
            if row["proposal_json"] is not None:
                candidate = CognitiveStepProposal(json.loads(row["proposal_json"])).as_dict()
                if (candidate["proposal_id"] != row["proposal_id"]
                        or candidate["operation_kind"] != row["operation_kind"]):
                    raise E25CognitionError("proposal identity mismatched")
            elif row["admission"] == "ADMITTED":
                raise E25CognitionError("admitted operation has no typed proposal")
            out.append({
                "turn_id": turn_id, "step_index": row["step_index"],
                "context_snapshot": json.loads(row["context_json"]),
                "proposal": (
                    json.loads(row["proposal_json"])
                    if row["proposal_json"] else None
                ),
                "admission": row["admission"],
                "reason_code": row["reason_code"],
                "outcome": outcome,
            })
        return out


class TwoStepEvidenceStub:
    """Fixed fake cognitive policy, used to prove follow-up initiation.

    It is not FAST, DEEP or a claim of model reasoning.
    """

    def propose(self, context, outcomes, *, turn_id, step_index):
        if step_index == 0:
            return {
                "schema": SCHEMA,
                "proposal_id": f"pr_{turn_id}_1",
                "turn_id": turn_id, "context_snapshot_id": context["context_snapshot_id"],
                "operation_kind": "retrieve_memory",
                "arguments": {"query": "crate", "top_k": 3},
                "expected_information": "Find a previously observed crate",
            }
        if step_index == 1 and outcomes and outcomes[0]["status"] == "COMPLETED":
            rows = outcomes[0]["result"]["records"]
            if not rows:
                return None
            event_id = rows[0]["last_seen_event_id"]
            return {
                "schema": SCHEMA,
                "proposal_id": f"pr_{turn_id}_2",
                "turn_id": turn_id, "context_snapshot_id": context["context_snapshot_id"],
                "operation_kind": "lookup_raw_evidence",
                "arguments": {"event_ids": [event_id]},
                "expected_information": "Check original provenance of remembered crate",
            }
        return None


__all__ = ["E25LabCognitiveCoordinator", "E25CognitionError", "TwoStepEvidenceStub"]
