"""Memory Encoding Stage 3: deterministic *shadow-only* episode association.

Only primary conversation.user Events and validated typed Entity references influence
episode identity. The resulting clusters never write MemoryStore or change the
production MemoryProcessor. Content summarization is deliberately absent.
"""

from datetime import datetime
import re

from anima.core.event_bus import Event


TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
# Bounded, explicit lexical-noise list, not an NLP semantic ontology.
STOPWORDS = frozenset({
    "a", "an", "and", "are", "at", "by", "for", "from", "in", "is",
    "of", "on", "or", "the", "to", "was", "were", "with", "after",
    "before", "then", "it", "this", "that", "и", "в", "во", "на",
    "по", "для", "от", "из", "это", "был", "была", "были", "с",
    "со", "у", "о", "об", "как",
})
MAX_GAP_SECONDS = 30 * 60
MAX_ACTIVE_EPISODES = 64
MAX_SOURCES_PER_EPISODE = 128
MAX_POSSIBLE_RELATED = 5
MIN_PAIR_OVERLAP = 2
MIN_PAIR_RATIO = 0.4


def _tokens(text):
    return frozenset(
        t.casefold() for t in TOKEN_PATTERN.findall(text)
        if len(t) >= 2 and not t.isdecimal() and t.casefold() not in STOPWORDS
    )


class ShadowEpisodeEncoder:
    """In-memory, idempotent lab comparison only; no Memory writes.

    Candidates: bounded to 64 newest episodes. Text signal: overlap against
    the first and last two *raw* Events, not any composed Memory.content.
    Temporal and session boundaries are conservative and explicit.
    """

    def __init__(self, *, link_store=None):
        self.link_store = link_store
        self._episodes = []
        self._by_event = {}

    def _entities(self, event):
        # Without an authority registry, do NOT treat supplied Entity IDs as
        # validated evidence. Only text/session/time may then associate.
        if self.link_store is None:
            return frozenset()
        result = set()
        for reference in event.references:
            if reference["kind"] != "entity":
                continue
            entity_id = reference["id"]
            if self.link_store.get_entity(entity_id) is None:
                raise ValueError("Unknown Entity reference: " + entity_id)
            result.add(entity_id)
        return frozenset(result)

    @staticmethod
    def _score(episode, *, text_tokens, entities, event, now):
        last = episode["_last_at"]
        delta = (now - last).total_seconds()
        if delta < 0:
            return None, ["late_event:cannot_append"]
        if delta > MAX_GAP_SECONDS:
            return None, ["time_gap:new_episode"]
        if episode["session_id"] is None or event.session_id is None or (
            episode["session_id"] != event.session_id
        ):
            return None, ["session_boundary:new_episode"]
        if episode["source"] != event.source:
            return None, ["source_boundary:new_episode"]
        if entities and episode["_entities"] and (
            entities.isdisjoint(episode["_entities"])
        ):
            return None, ["different_entities:new_episode"]
        if len(episode["source_event_ids"]) >= MAX_SOURCES_PER_EPISODE:
            return None, ["episode_source_limit:new_episode"]

        best_overlap, best_ratio = 0, 0.0
        # Compare *individual* raw-source token sets to prevent weak
        # transitive token unions from merging unrelated topics.
        for source_tokens in (
            episode["_first_tokens"], *episode["_recent_tokens"]
        ):
            common = len(source_tokens & text_tokens)
            denominator = min(len(source_tokens), len(text_tokens))
            ratio = common / denominator if denominator else 0.0
            if (common, ratio) > (best_overlap, best_ratio):
                best_overlap, best_ratio = common, ratio

        if best_overlap < MIN_PAIR_OVERLAP or best_ratio < MIN_PAIR_RATIO:
            return None, ["raw_overlap:insufficient"]
        shared_entity = bool(episode["_entities"] & entities)
        score = best_overlap * 2 + int(best_ratio * 10) + (
            2 if shared_entity else 0
        )
        return score, [
            f"raw_pair_overlap:{best_overlap}",
            f"raw_pair_ratio:{best_ratio:.3f}",
            f"entity_overlap:{int(shared_entity)}",
            f"time_gap_seconds:{int(delta)}",
        ]

    def accept(self, event):
        if not isinstance(event, Event):
            raise TypeError("ShadowEpisodeEncoder requires Event")
        original = event.to_dict()
        prior = self._by_event.get(event.event_id)
        if prior is not None:
            if prior["raw_event"] != original:
                raise ValueError("Conflicting replay for Event ID " + event.event_id)
            episode_id = prior["episode_id"]
            sources = (
                []
                if episode_id is None
                else list(next(
                    e["source_event_ids"] for e in self._episodes
                    if e["episode_id"] == episode_id
                ))
            )
            return {
                "event_id": event.event_id, "action": "replay",
                "episode_id": episode_id, "source_event_ids": sources,
                "reasons": ["already_seen:verified"],
                "score": prior["score"],
                "possible_related": list(prior["possible_related"]),
            }

        if event.event_type != "conversation.user":
            return self._remember_skip(original, "selection:event_type")
        text = event.payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return self._remember_skip(original, "selection:empty_text")

        entities = self._entities(event)
        now = datetime.fromisoformat(event.timestamp)
        text_tokens = _tokens(text)
        scored = []
        possible = []
        for episode in self._episodes[-MAX_ACTIVE_EPISODES:]:
            score, reasons = self._score(
                episode, text_tokens=text_tokens, entities=entities,
                event=event, now=now,
            )
            if score is not None:
                scored.append((score, episode["_last_at"],
                               episode["_ordinal"], episode, reasons))
            elif reasons == ["raw_overlap:insufficient"] and entities:
                # An Entity is a possible link, NOT enough for episode merge.
                shared = sorted(entities & episode["_entities"])
                if shared:
                    possible.append({
                        "episode_id": episode["episode_id"],
                        "source_event_ids": list(episode["source_event_ids"][-3:]),
                        "shared_entity_ids": shared,
                        "reason": "shared_entity_without_raw_overlap",
                        "status": "unverified",
                    })
        if scored:
            score, _, _, chosen, reasons = max(
                scored, key=lambda row: (row[0], row[1], row[2])
            )
            chosen["source_event_ids"].append(event.event_id)
            chosen["_last_at"] = now
            chosen["_recent_tokens"].append(text_tokens)
            chosen["_recent_tokens"] = chosen["_recent_tokens"][-2:]
            chosen["_entities"] = chosen["_entities"] | entities
            action, episode_id = "append", chosen["episode_id"]
            sources = list(chosen["source_event_ids"])
            possible_related = []
        else:
            score = 0
            reasons = ["no_qualified_raw_candidate"]
            episode_id = "shadow_ep_" + event.event_id
            chosen = {
                "episode_id": episode_id, "source": event.source,
                "session_id": event.session_id,
                "source_event_ids": [event.event_id],
                "_first_tokens": text_tokens,
                "_recent_tokens": [text_tokens],
                "_entities": entities,
                "_last_at": now,
                "_ordinal": len(self._episodes),
            }
            self._episodes.append(chosen)
            action, sources = "new_episode", [event.event_id]
            # Recent first; no ranking pretense beyond recency, hard caps
            # and only source-validated, within-session Entity coincidences.
            possible_related = list(reversed(possible[-MAX_POSSIBLE_RELATED:]))
        self._by_event[event.event_id] = {
            "raw_event": original, "episode_id": episode_id, "score": score,
            "possible_related": possible_related,
        }
        return {
            "event_id": event.event_id, "action": action,
            "episode_id": episode_id, "source_event_ids": sources,
            "score": score, "reasons": reasons,
            "possible_related": possible_related,
        }

    def _remember_skip(self, original, reason):
        event_id = original["id"]
        self._by_event[event_id] = {
            "raw_event": original, "episode_id": None, "score": 0,
            "possible_related": [],
        }
        return {
            "event_id": event_id, "action": "skip", "episode_id": None,
            "source_event_ids": [], "score": 0, "reasons": [reason],
            "possible_related": [],
        }

    def episodes(self):
        return [
            {
                "episode_id": e["episode_id"], "source": e["source"],
                "session_id": e["session_id"],
                "source_event_ids": list(e["source_event_ids"]),
                "entity_ids": sorted(e["_entities"]),
            }
            for e in self._episodes
        ]

    def event_assignments(self):
        return {
            event_id: row["episode_id"]
            for event_id, row in self._by_event.items()
            if row["episode_id"] is not None
        }
