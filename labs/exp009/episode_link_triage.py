"""E3 lab-only re-evaluation of weak links between separate raw Event episodes.

This is a *candidate triage*, never a relation resolver or Memory writer.
An Event whose raw text overlaps both separate episodes can mark a weak
candidate for review, but cannot establish the relation's truth/authority.
"""

from hashlib import sha256
import json

from anima.core.event_bus import Event
from anima.memory.shadow_encoding import _tokens

MAX_CANDIDATES = 256
MAX_BRIDGES = 8
REVIEW_TOKEN_OVERLAP = 2


def _json(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    )


def _eid(value):
    if not isinstance(value, str) or not value.startswith("ev_"):
        raise ValueError("Unrecognized source Event ID")
    return value


def _entity_set(raw, known_entities):
    ids = {
        item["id"] for item in raw["references"]
        if item["kind"] == "entity"
    }
    if ids - known_entities:
        raise ValueError("Unknown Entity in candidate provenance")
    return ids


def _text_tokens(raw):
    return _tokens(raw["payload"]["text"])


class EpisodeLinkTriage:
    """Bounded audit-only triage from frozen E2 shadow outputs.

    The source manifest and events are inputs; gold is never consulted.
    Records are in memory and exportable as a rebuildable projection. The
    queue cannot write to EventLog, MemoryStore, LinkStore or Knowledge.
    """

    def __init__(self, decisions, *, known_entities):
        if not isinstance(known_entities, (set, frozenset)):
            raise ValueError("known_entities must be an explicit set")
        self.known_entities = frozenset(known_entities)
        self.sources = {}
        self.by_episode = {}
        self.candidates = {}
        self.bridges = {}

        for label, row in decisions.items():
            raw = row["raw"]
            Event.validate_record(raw)
            event_id = _eid(raw["id"])
            if row["event_id"] != event_id:
                raise ValueError("Event identity mismatch")
            decision = row["decision"]
            ep_id = decision["episode_id"]
            if decision["action"] != "new_episode" or (
                decision["source_event_ids"] != [event_id]
            ):
                raise ValueError("Triage requires frozen single-source episodes")
            if ep_id != "shadow_ep_" + event_id:
                raise ValueError("Episode ID does not match raw source")
            if ep_id in self.by_episode or event_id in self.sources:
                raise ValueError("Duplicate episode or Event source")
            self.sources[event_id] = raw
            self.by_episode[ep_id] = {
                "event_id": event_id,
                "label": label,
                "raw": raw,
                "candidate_refs": decision["possible_related"],
            }
            _entity_set(raw, self.known_entities)

        for source_ep, source in self.by_episode.items():
            for ref in source["candidate_refs"]:
                target_ep = ref["episode_id"]
                if target_ep not in self.by_episode:
                    raise ValueError("Candidate target not present in snapshot")
                if target_ep == source_ep:
                    raise ValueError("Self-link is not a candidate")
                target = self.by_episode[target_ep]
                target_event_id = target["event_id"]
                if ref["source_event_ids"] != [target_event_id]:
                    raise ValueError("Candidate provenance was forged or truncated")
                if ref["status"] != "unverified" or ref["reason"] != (
                    "shared_entity_without_raw_overlap"
                ):
                    raise ValueError("Unexpected candidate classification")
                observed = set(ref["shared_entity_ids"])
                source_entities = _entity_set(
                    source["raw"], self.known_entities
                )
                target_entities = _entity_set(
                    target["raw"], self.known_entities
                )
                if not observed or observed != (
                    source_entities & target_entities
                ):
                    raise ValueError("Candidate Entity provenance mismatch")

                # 'potentially related' is symmetric. A repeated directional
                # proposal must not create an additional logical relation.
                first, second = sorted((source_ep, target_ep))
                key = (first, second)
                if key not in self.candidates:
                    if len(self.candidates) >= MAX_CANDIDATES:
                        raise ValueError("Candidate review capacity reached")
                    stable_id = "shadow_candidate_" + sha256(
                        _json(key).encode("utf-8")
                    ).hexdigest()[:32]
                    self.candidates[key] = {
                        "candidate_id": stable_id,
                        "episode_ids": [first, second],
                        "source_event_ids": sorted([
                            self.by_episode[first]["event_id"],
                            self.by_episode[second]["event_id"],
                        ]),
                        "entity_ids": sorted(observed),
                        "proposed_by_event_ids": [],
                        "bridge_event_ids": [],
                        "bridge_limit_reached": False,
                    }
                record = self.candidates[key]
                if record["entity_ids"] != sorted(observed):
                    raise ValueError("Contradictory candidate Entity evidence")
                proposal = source["event_id"]
                if proposal not in record["proposed_by_event_ids"]:
                    record["proposed_by_event_ids"].append(proposal)

        self.source_hash = sha256(
            _json({
                "sources": self.sources,
                "candidates": sorted(
                    record["candidate_id"]
                    for record in self.candidates.values()
                ),
            }).encode("utf-8")
        ).hexdigest()

    def _eligible_bridge(self, event, record):
        # Input observations are not independent proof; this is strictly
        # an inexpensive retrigger for human/semantic review downstream.
        raw = event.to_dict()
        candidate = [
            self.by_episode[ep]["raw"]
            for ep in record["episode_ids"]
        ]
        if event.event_type != "conversation.user":
            return False
        if not event.session_id or any(
            item["session_id"] != event.session_id or
            item["source"] != event.source for item in candidate
        ):
            return False
        if not (
            _entity_set(raw, self.known_entities) & set(record["entity_ids"])
        ):
            return False
        # Do not allow old/out-of-window Events to retroactively override the
        # Shadow's conservative temporal episode boundary.
        from datetime import datetime
        at = datetime.fromisoformat(event.timestamp)
        for item in candidate:
            delta = (at - datetime.fromisoformat(item["timestamp"])).total_seconds()
            if delta < 0 or delta > 1800:
                return False
        tokens = _text_tokens(raw)
        return all(
            len(tokens & _text_tokens(item)) >= REVIEW_TOKEN_OVERLAP
            for item in candidate
        )

    def observe(self, event):
        if not isinstance(event, Event):
            raise TypeError("A review trigger must be a typed Event")
        raw = event.to_dict()
        previous = self.bridges.get(event.event_id)
        if previous is not None:
            if previous != raw:
                raise ValueError("Conflicting replay of bridge Event")
            return self.snapshot()
        if event.event_id in self.sources:
            if self.sources[event.event_id] != raw:
                raise ValueError("Conflicting replay of source Event")
            return self.snapshot()

        # Entity refs must be checked prior to any in-memory mutation.
        _entity_set(raw, self.known_entities)
        eligible_keys = [
            key for key, record in self.candidates.items()
            if self._eligible_bridge(event, record)
        ]
        self.bridges[event.event_id] = raw
        for key in eligible_keys:
            record = self.candidates[key]
            if len(record["bridge_event_ids"]) >= MAX_BRIDGES:
                record["bridge_limit_reached"] = True
                continue
            record["bridge_event_ids"].append(event.event_id)
        return self.snapshot()

    def snapshot(self):
        rows = []
        for key in sorted(self.candidates):
            candidate = self.candidates[key]
            # An overlap trigger merely makes the suggestion review-worthy.
            # Neither state grants truth or changes other objects.
            rows.append({
                **{k: (
                    list(v) if isinstance(v, list) else v
                ) for k, v in candidate.items()},
                "status": "unverified",
                "review_state": (
                    "review_ready" if candidate["bridge_event_ids"]
                    else "needs_evidence"
                ),
                "explanation": (
                    "raw_bridge_token_overlap_for_review_only"
                    if candidate["bridge_event_ids"]
                    else "same_entity_only_not_enough_to_link"
                ),
            })
        return {
            "format": "exp009.episode_link_triage/0.1",
            "source_snapshot_sha256": self.source_hash,
            "candidates": rows,
            "bridge_events": [
                self.bridges[key] for key in sorted(self.bridges)
            ],
            "note": (
                "No truth, no independent witness count, no episode merge, "
                "no production relation or Knowledge write."
            ),
        }
