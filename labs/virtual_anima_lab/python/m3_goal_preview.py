"""M3 experimental read-only historical-Memory -> Goal suggestion review boundary.

Not production Core, not Stage 6 CognitiveDispatcher or ProposalValidator.
There is deliberately NO method for creating/binding Goals or executing tools.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from anima.memory.context_builder import ContextBuilder
from anima.memory.event_retrieval import EventRetrieval
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine

SCHEMA = "anima.memory_v1.goal_suggestion_m3/0.1"
TEMPLATE = "suggest.ensure_virtual_door_closed/0.1"
REQUEST = "M3_REQUEST_DOOR_CLOSE"
REVOKE = "M3_REVOKE_DOOR_CLOSE"
STATE = "M3_REPORT_DOOR_CLOSED"
MAX_VISIBLE_SOURCES = 32
MAX_RATIONALE = 256
_TOKEN = re.compile(r"\bM3_(?:REQUEST_DOOR_CLOSE|REVOKE_DOOR_CLOSE|REPORT_DOOR_CLOSED)\b")
_FIELDS = frozenset({
    "schema", "template", "memory_id", "source_event_id",
    "current_event_id", "rationale",
})


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value):
    return sha256(_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceExcerpt:
    memory_id: str
    event_id: str
    text: str


@dataclass(frozen=True, slots=True)
class PreviewWindow:
    """Immutable historical bounded view built before the current input event."""

    current_event_id: str
    query: str
    selected: tuple[tuple[str, str], ...]  # memory ID + exact row digest
    sources: tuple[SourceExcerpt, ...]
    items_used: int
    chars_used: int
    truncated: bool

    def to_dict(self):
        return {
            "current_event_id": self.current_event_id,
            "query": self.query,
            "selected_memory_ids": [m for m, _ in self.selected],
            "source_event_ids": [s.event_id for s in self.sources],
            "items_used": self.items_used,
            "chars_used": self.chars_used,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class PreviewReview:
    disposition: str  # REVIEW_REQUIRED | CONFLICT_REVIEW | REJECTED
    reason: str
    template: str | None
    memory_id: str | None
    source_event_id: str | None

    def to_dict(self):
        return {
            "disposition": self.disposition,
            "reason": self.reason,
            "template": self.template,
            "memory_id": self.memory_id,
            "source_event_id": self.source_event_id,
            "goal_created": False,
            "tool_authorized": False,
        }


class FixtureSuggestionBackend:
    """A deterministic synthetic marker matcher, NOT an LLM or NLP evaluator."""

    def propose(self, view: PreviewWindow):
        for item in view.sources:
            if REQUEST in _TOKEN.findall(item.text):
                return {
                    "schema": SCHEMA,
                    "template": TEMPLATE,
                    "memory_id": item.memory_id,
                    "source_event_id": item.event_id,
                    "current_event_id": view.current_event_id,
                    "rationale": "Recorded maintenance request warrants operator review.",
                }
        return None


class MemoryGoalPreviewGate:
    """Source-backed non-authorizing draft reviewer.

    Gate can read but holds no GoalStore, TaskStore, WorldPort or Executor.
    A provenance PASS results only in REVIEW_REQUIRED, never authorization.
    """

    def __init__(self, *, memory_store, link_store, event_log, event_retrieval):
        if not isinstance(memory_store, MemoryStore):
            raise TypeError("M3 requires MemoryStore")
        if not isinstance(event_retrieval, EventRetrieval):
            raise TypeError("M3 requires EventRetrieval")
        if event_retrieval.event_log is not event_log:
            raise ValueError("M3 requires the canonical EventLog")
        if event_retrieval.memory_store is not memory_store:
            raise ValueError("M3 Event Retrieval must share MemoryStore")
        self.memory_store = memory_store
        self.index = event_retrieval
        self.provenance = ProvenanceResolver(
            memory_store, link_store, event_log, event_retrieval=event_retrieval,
        )
        self.context = ContextBuilder(
            retrieval=RetrievalEngine(
                memory_store=memory_store, link_store=link_store,
            ),
            provenance=self.provenance,
        )

    def capture(self, *, query, current_event_id):
        """Capture strictly source-backed memory context before current input."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("M3 requires a non-empty query")
        if not isinstance(current_event_id, str) or not current_event_id.startswith("ev_"):
            raise ValueError("M3 requires an independently assigned current Event ID")
        if self.index.status()["status"] != "complete":
            raise ValueError("M3 cannot capture incomplete Event index")

        context = self.context.build(
            query, consumer="FAST", retrieval_options={"kinds": ("memory",)},
        )
        if context["knowledge"] or context["events"]:
            raise ValueError("M3 context must be Memory-only")
        if context["budget"] != {"max_items": 6, "max_chars": 1200}:
            raise ValueError("M3 requires frozen FAST budget")
        selected = []
        sources = []
        seen = set()
        for entry in context["memories"]:
            memory = entry["record"]
            mid = memory["id"]
            selected.append((mid, _digest(memory)))
            resolved = self.provenance.memory(mid)
            for event in resolved["events"]:
                if event["id"] == current_event_id:
                    raise ValueError("Current input cannot be its own historical source")
                if event["type"] != "conversation.user" or event["source"] != "user":
                    # The fixture only analyzes user-reported historical notes.
                    continue
                text = event["payload"].get("text")
                if not isinstance(text, str):
                    continue
                key = (mid, event["id"])
                if key not in seen:
                    sources.append(SourceExcerpt(mid, event["id"], text))
                    seen.add(key)
                if len(sources) > MAX_VISIBLE_SOURCES:
                    raise ValueError("M3 visible source budget exceeded")
        return PreviewWindow(
            current_event_id=current_event_id, query=query,
            selected=tuple(selected), sources=tuple(sources),
            items_used=context["selection_stats"]["items_used"],
            chars_used=context["selection_stats"]["chars_used"],
            truncated=bool(context["truncated"]
                           or context["selection_stats"]["omitted_budget"]),
        )

    @staticmethod
    def _reject(reason):
        return PreviewReview("REJECTED", reason, None, None, None)

    def review(self, view, draft):
        if not isinstance(view, PreviewWindow):
            raise TypeError("M3 requires its immutable PreviewWindow")
        if view.truncated:
            return self._reject("bounded_context_incomplete")
        if draft is None:
            return self._reject("no_proposal")
        if type(draft) is not dict or set(draft) != _FIELDS:
            return self._reject("invalid_or_privileged_draft_shape")
        if draft["schema"] != SCHEMA or draft["template"] != TEMPLATE:
            return self._reject("unsupported_template")
        for field in ("memory_id", "source_event_id", "current_event_id", "rationale"):
            if type(draft[field]) is not str or not draft[field].strip():
                return self._reject("invalid_draft_field")
        if len(draft["rationale"]) > MAX_RATIONALE:
            return self._reject("unbounded_rationale")
        if draft["current_event_id"] != view.current_event_id:
            return self._reject("wrong_current_input")
        if draft["source_event_id"] == view.current_event_id:
            return self._reject("current_input_self_citation")
        chosen = (draft["memory_id"], draft["source_event_id"])
        if chosen not in {(s.memory_id, s.event_id) for s in view.sources}:
            return self._reject("unselected_or_hallucinated_source")
        if self.index.status()["status"] != "complete":
            return self._reject("index_incomplete_or_changed")

        # Every selected memory/source must still match the frozen historical view.
        # Re-read exact raw bytes through Event Retrieval (sha256 verified).
        try:
            for mid, digest in view.selected:
                record = self.memory_store.get_memory(mid)
                if record is None or _digest(record) != digest:
                    return self._reject("memory_changed_after_capture")
                current_events = {
                    event["id"]: event
                    for event in self.provenance.memory(mid)["events"]
                }
                recorded_ids = {
                    s.event_id for s in view.sources if s.memory_id == mid
                }
                visible_ids = {
                    event_id for event_id, event in current_events.items()
                    if event["type"] == "conversation.user"
                    and event["source"] == "user"
                    and isinstance(event["payload"].get("text"), str)
                }
                if visible_ids != recorded_ids:
                    return self._reject("source_set_changed_after_capture")
                for item in view.sources:
                    if item.memory_id == mid:
                        event = current_events.get(item.event_id)
                        if (event is None or event["payload"]["text"] != item.text):
                            return self._reject("raw_source_changed_after_capture")
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            return self._reject("raw_provenance_unavailable")

        selected_text = next(
            s.text for s in view.sources
            if (s.memory_id, s.event_id) == chosen
        )
        if REQUEST not in _TOKEN.findall(selected_text):
            return self._reject("source_does_not_request_target")
        if any(REVOKE in _TOKEN.findall(s.text) for s in view.sources):
            return PreviewReview(
                "CONFLICT_REVIEW", "visible_revocation_requires_independent_review",
                TEMPLATE, draft["memory_id"], draft["source_event_id"],
            )
        return PreviewReview(
            "REVIEW_REQUIRED", "historical_report_only_not_authorization",
            TEMPLATE, draft["memory_id"], draft["source_event_id"],
        )


__all__ = [
    "MemoryGoalPreviewGate", "FixtureSuggestionBackend", "PreviewWindow",
    "PreviewReview", "SourceExcerpt", "SCHEMA", "TEMPLATE", "REQUEST",
    "REVOKE", "STATE",
]
