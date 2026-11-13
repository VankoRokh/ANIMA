"""M4 isolated operator-decision ledger: reviewed M3 draft -> ONE unbound Core Goal.

Not a production authorization service. OperatorDecision from a trusted test host
is a callback record, not cryptographic authentication against hostile local code.
GoalStore remains canonical; separate ledger has deliberate two-transaction crash
window reconciled using persisted stable UUIDv4-formatted Goal/transition IDs.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import UUID

from anima.internal_state.goals import GoalStore
from anima.memory.event_retrieval import EventRetrieval
from .m3_goal_preview import MemoryGoalPreviewGate, PreviewWindow, TEMPLATE

SCHEMA = "anima.memory_v1.approval_m4/0.1"
OPERATOR = "test.operator.m4"
SOURCE = "m4.approved_operator"
GOAL_DESCRIPTION = "Ensure the virtual door is closed"
GOAL_CRITERION = "Registered door sensor independently verifies closed"
GOAL_PRIORITY = 1.0
GOAL_REASON = "M4 explicit isolated operator approval; no Tool binding"
MAX_TICKET_BYTES = 8192

DDL = """
CREATE TABLE IF NOT EXISTS m4_approval_tickets (
    ticket_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    origin_key TEXT NOT NULL UNIQUE,
    draft_json TEXT NOT NULL,
    view_json TEXT NOT NULL,
    review_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('reviewed','approved','rejected','committed')),
    decision_json TEXT,
    goal_id TEXT NOT NULL UNIQUE,
    transition_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((status='reviewed' AND decision_json IS NULL)
       OR (status!='reviewed' AND decision_json IS NOT NULL))
);
"""


def _canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value):
    return sha256(_canon(value).encode("utf-8")).hexdigest()


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _uuid4_deterministic(seed):
    digest = sha256(seed.encode("ascii")).digest()
    return str(UUID(bytes=digest[:16], version=4))


@dataclass(frozen=True, slots=True)
class OperatorDecision:
    """Host-authorized in the test harness ONLY; never created by FAST/Memory."""

    ticket_id: str
    fingerprint: str
    decision_id: str
    operator_ref: str
    action: str  # APPROVE or REJECT

    def __post_init__(self):
        if self.action not in {"APPROVE", "REJECT"}:
            raise ValueError("M4 requires explicit APPROVE or REJECT")
        if self.operator_ref != OPERATOR:
            raise ValueError("M4 operator is not in the laboratory allowlist")
        for name in ("ticket_id", "fingerprint", "decision_id"):
            value = getattr(self, name)
            if (type(value) is not str or not value.strip() or
                    len(value) > 128):
                raise ValueError("M4 invalid operator decision field " + name)
        if len(self.fingerprint) != 64 or any(
            x not in "0123456789abcdef" for x in self.fingerprint
        ):
            raise ValueError("M4 invalid source fingerprint")


class M4ApprovalBridge:
    """No Core runtime, Tool registry, Goal binding, or world capabilities."""

    def __init__(
        self, *, database_file: Path,
        preview_gate: MemoryGoalPreviewGate, goal_store: GoalStore,
    ):
        if not isinstance(preview_gate, MemoryGoalPreviewGate):
            raise TypeError("M4 requires M3 preview gate")
        if not isinstance(goal_store, GoalStore):
            raise TypeError("M4 requires canonical GoalStore")
        if (not isinstance(preview_gate.index, EventRetrieval) or
                preview_gate.index.status()["status"] != "complete"):
            raise ValueError("M4 source index must be complete at setup")
        self.gate = preview_gate
        self.goals = goal_store
        self.path = Path(database_file)
        if self.path.resolve() == goal_store.database_file.resolve():
            raise ValueError("M4 ticket ledger must be separate from GoalStore")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript(DDL)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        return dict(row)

    def get_ticket(self, ticket_id):
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM m4_approval_tickets WHERE ticket_id=?", (ticket_id,),
            ).fetchone()
        return self._decode(row)

    @staticmethod
    def fingerprint(view: PreviewWindow, draft: dict):
        return _sha({"view": asdict(view), "draft": draft})

    def stage(self, view: PreviewWindow, draft: dict):
        review = self.gate.review(view, draft)
        if review.disposition != "REVIEW_REQUIRED":
            raise ValueError("M4 stage requires unconflicted source-backed REVIEW_REQUIRED")
        if type(draft) is not dict:
            raise ValueError("M4 draft must be the strict M3 dict")
        payload = {"view": asdict(view), "draft": draft}
        raw = _canon(payload)
        if len(raw.encode("utf-8")) > MAX_TICKET_BYTES:
            raise ValueError("M4 preview exceeds durable ticket size")
        digest = _sha(payload)
        origin_key = _sha({
            "template": draft["template"], "memory_id": draft["memory_id"],
            "source_event_id": draft["source_event_id"],
            "current_event_id": draft["current_event_id"],
        })
        ticket_id = "m4_" + digest
        goal_id = "goal_" + _uuid4_deterministic(ticket_id + ":goal")
        transition_id = "gt_" + _uuid4_deterministic(ticket_id + ":start")
        now = _utc()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT OR IGNORE INTO m4_approval_tickets
                    (ticket_id,fingerprint,origin_key,draft_json,view_json,review_json,
                     status,decision_json,goal_id,transition_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,'reviewed',NULL,?,?,?,?)""",
                    (ticket_id, digest, origin_key, _canon(draft), _canon(asdict(view)),
                     _canon(review.to_dict()), goal_id, transition_id, now, now),
                )
                row = db.execute(
                    "SELECT * FROM m4_approval_tickets WHERE origin_key=?",
                    (origin_key,),
                ).fetchone()
                if (row is None or row["ticket_id"] != ticket_id
                        or row["origin_key"] != origin_key
                        or row["fingerprint"] != digest
                        or row["draft_json"] != _canon(draft)
                        or row["view_json"] != _canon(asdict(view))
                        or row["review_json"] != _canon(review.to_dict())):
                    raise ValueError("M4 existing ticket differs from reviewed proposal")
                db.commit()
            except Exception:
                db.rollback()
                raise
        return self.get_ticket(ticket_id)

    def _ensure_fresh(self, row):
        if row is None:
            raise ValueError("Unknown M4 ticket")
        try:
            draft = json.loads(row["draft_json"])
            saved = json.loads(row["view_json"])
            if _sha({"view": saved, "draft": draft}) != row["fingerprint"]:
                raise ValueError("Ticket payload changed")
            if row["ticket_id"] != "m4_" + row["fingerprint"]:
                raise ValueError("Ticket identity changed")
            if row["origin_key"] != _sha({
                "template": draft["template"], "memory_id": draft["memory_id"],
                "source_event_id": draft["source_event_id"],
                "current_event_id": draft["current_event_id"],
            }):
                raise ValueError("Ticket source identity changed")
            if row["goal_id"] != (
                "goal_" + _uuid4_deterministic(row["ticket_id"] + ":goal")
            ) or row["transition_id"] != (
                "gt_" + _uuid4_deterministic(row["ticket_id"] + ":start")
            ):
                raise ValueError("Goal identity reservation changed")
            if self.gate.index.status()["status"] != "complete":
                raise ValueError("Event index incomplete or changed")
            view = self.gate.capture(
                query=saved["query"], current_event_id=saved["current_event_id"],
            )
            if _canon(asdict(view)) != _canon(saved):
                raise ValueError("Historical preview differs from approved snapshot")
            review = self.gate.review(view, draft)
            if (review.disposition != "REVIEW_REQUIRED" or
                    _canon(review.to_dict()) != row["review_json"] or
                    draft["template"] != TEMPLATE):
                raise ValueError("Original proposal no longer passes read-only review")
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            raise ValueError("M4 approved evidence not fresh: " + str(exc)) from exc

    def decide(self, decision: OperatorDecision):
        if not isinstance(decision, OperatorDecision):
            raise TypeError("M4 requires typed operator decision supplied by host")
        row = self.get_ticket(decision.ticket_id)
        if row is None:
            raise ValueError("Cannot decide on an unknown ticket")
        if decision.fingerprint != row["fingerprint"]:
            raise ValueError("M4 approval is bound to exact proposal fingerprint")
        if row["decision_json"] is not None:
            if row["decision_json"] != _canon(asdict(decision)):
                raise ValueError("M4 conflicting decision or replay altered")
            return self.get_ticket(decision.ticket_id)
        self._ensure_fresh(row)
        if row["status"] != "reviewed":
            raise ValueError("M4 reviewed ticket cannot change terminal decision")
        new_status = "approved" if decision.action == "APPROVE" else "rejected"
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cur = db.execute(
                    """UPDATE m4_approval_tickets
                    SET status=?, decision_json=?, updated_at=?
                    WHERE ticket_id=? AND status='reviewed' AND decision_json IS NULL""",
                    (new_status, _canon(asdict(decision)), _utc(), decision.ticket_id),
                )
                if cur.rowcount != 1:
                    concurrent = db.execute(
                        "SELECT decision_json FROM m4_approval_tickets WHERE ticket_id=?",
                        (decision.ticket_id,),
                    ).fetchone()
                    if concurrent is None or concurrent["decision_json"] != _canon(asdict(decision)):
                        raise ValueError("M4 concurrent conflicting decision")
                db.commit()
            except Exception:
                db.rollback()
                raise
        return self.get_ticket(decision.ticket_id)

    @staticmethod
    def _goal_spec(ticket_id):
        return {
            "source": SOURCE, "priority": GOAL_PRIORITY,
            "description": GOAL_DESCRIPTION,
            "success_criterion": GOAL_CRITERION,
            "source_id": ticket_id,
        }

    def _check_created_goal(self, row):
        goal = self.goals.get_goal(row["goal_id"])
        if goal is None:
            return False
        spec = self._goal_spec(row["ticket_id"])
        for field in ("source", "priority", "description", "success_criterion"):
            if goal[field] != spec[field]:
                raise ValueError("M4 reserved Goal ID occupied by unrelated content")
        if goal["status"] != "active":
            raise ValueError("M4 Goal changed lifecycle before unbound acceptance")
        transitions = self.goals.list_goal_transitions(goal_id=row["goal_id"])
        if (len(transitions) != 1
                or transitions[0]["id"] != row["transition_id"]
                or transitions[0]["from_status"] is not None
                or transitions[0]["to_status"] != "active"
                or transitions[0]["source_id"] != row["ticket_id"]):
            raise ValueError("M4 Goal start transition not canonical")
        return True

    def materialize(self, ticket_id, *, cut=None):
        """Create ONE canonical unbound Goal; cut hook is test-only hard exit."""
        if cut not in (None, "before_goal", "after_goal"):
            raise ValueError("Unsupported M4 cut")
        row = self.get_ticket(ticket_id)
        if row is None or row["status"] not in {"approved", "committed"}:
            raise ValueError("M4 Goal creation requires explicit prior APPROVE")
        if row["decision_json"] is None:
            raise ValueError("M4 approval receipt missing")
        stored = OperatorDecision(**json.loads(row["decision_json"]))
        if stored.action != "APPROVE" or stored.fingerprint != row["fingerprint"]:
            raise ValueError("M4 approval receipt does not authorize this exact ticket")

        exists = self._check_created_goal(row)
        if row["status"] == "committed":
            if not exists:
                raise ValueError("M4 committed ticket missing canonical Goal")
            return self.goals.get_goal(row["goal_id"])
        self._ensure_fresh(row)
        if cut == "before_goal":
            import os
            os._exit(74)
        if not exists:
            spec = self._goal_spec(row["ticket_id"])
            try:
                self.goals.create_goal(
                    **{key: spec[key] for key in (
                        "source", "priority", "description", "success_criterion",
                        "source_id",
                    )},
                    reason=GOAL_REASON,
                    public_id=row["goal_id"],
                    transition_id=row["transition_id"],
                )
            except ValueError:
                if not self._check_created_goal(row):
                    raise
        if not self._check_created_goal(row):
            raise AssertionError("M4 creation returned without canonical Goal")
        if cut == "after_goal":
            import os
            os._exit(73)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cur = db.execute(
                    """UPDATE m4_approval_tickets
                    SET status='committed', updated_at=?
                    WHERE ticket_id=? AND status='approved'""",
                    (_utc(), ticket_id),
                )
                if cur.rowcount != 1:
                    status = db.execute(
                        "SELECT status FROM m4_approval_tickets WHERE ticket_id=?",
                        (ticket_id,),
                    ).fetchone()
                    if status is None or status["status"] != "committed":
                        raise ValueError("M4 ticket state changed during commit")
                db.commit()
            except Exception:
                db.rollback()
                raise
        return self.goals.get_goal(row["goal_id"])


__all__ = ["M4ApprovalBridge", "OperatorDecision", "SCHEMA", "OPERATOR"]
