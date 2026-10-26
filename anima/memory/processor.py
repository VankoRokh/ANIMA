import re
from datetime import datetime
from uuid import uuid4

from anima.core.event_bus import Event
from anima.memory.composer import RuleBasedComposer
from anima.memory.link_store import RELATION_ID_PREFIX
from anima.memory.memory_store import MEMORY_ID_PREFIX


TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
HIGH_ASSOCIATION_SCORE = 7
MEDIUM_ASSOCIATION_SCORE = 4
CLOSE_TIME_SECONDS = 30 * 60
UPDATE_MAX_GAP_SECONDS = 2 * 60 * 60
RECENT_CANDIDATE_LIMIT = 20
FTS_CANDIDATE_LIMIT = 10


class MemoryProcessor:
    """Deterministic selection and episodic association baseline."""

    def __init__(
        self,
        *,
        memory_store,
        event_log,
        link_store,
        composer=None,
        trace=None,
    ):
        self.memory_store = memory_store
        self.event_log = event_log
        self.link_store = link_store
        self.composer = composer or RuleBasedComposer()
        self.trace = trace

    def process_event(
        self,
        event,
        *,
        connection=None,
        trace_result=True,
    ):
        if not isinstance(event, Event):
            raise ValueError("MemoryProcessor requires an Event")

        selected, text, selection_reason = self._select(event)
        if not selected:
            result = self._result(
                event,
                action="skip",
                reasons=[selection_reason],
            )
            if trace_result:
                self._trace_result(result)
            return result

        entity_ids = self._event_entity_ids(event)
        candidate = self._best_candidate(event, text, entity_ids)

        if candidate is None:
            result = self._apply_with_connection(
                connection,
                lambda active: self._apply_create(
                    active,
                    event,
                    text,
                    entity_ids,
                    candidate=None,
                ),
            )
            if trace_result:
                self._trace_result(result)
            return result

        semantic_signal = (
            candidate["fts_score"] > 0
            or candidate["entity_overlap"] > 0
        )
        update_allowed = (
            semantic_signal
            and candidate["score"] >= HIGH_ASSOCIATION_SCORE
            and not candidate["large_time_gap"]
        )

        if update_allowed:
            result = self._apply_with_connection(
                connection,
                lambda active: self._apply_update(
                    active,
                    event,
                    text,
                    entity_ids,
                    candidate,
                ),
            )
            if trace_result:
                self._trace_result(result)
            return result

        if (
            semantic_signal
            and candidate["score"] >= MEDIUM_ASSOCIATION_SCORE
        ):
            result = self._apply_with_connection(
                connection,
                lambda active: self._apply_create_related(
                    active,
                    event,
                    text,
                    entity_ids,
                    candidate,
                ),
            )
            if trace_result:
                self._trace_result(result)
            return result

        result = self._apply_with_connection(
            connection,
            lambda active: self._apply_create(
                active,
                event,
                text,
                entity_ids,
                candidate=candidate,
            ),
        )
        if trace_result:
            self._trace_result(result)
        return result

    def _apply_with_connection(self, connection, operation):
        if connection is not None:
            return operation(connection)

        with self.memory_store.transaction() as active:
            return operation(active)

    def _apply_create(
        self,
        connection,
        event,
        text,
        entity_ids,
        *,
        candidate,
    ):
        memory = self._create_memory_tx(connection, event, text)
        self._link_entities_tx(
            connection,
            memory["id"],
            entity_ids,
            event.timestamp,
        )

        reasons = ["association:no_candidate"]
        candidate_id = None
        score = 0
        if candidate is not None:
            candidate_id = candidate["memory"]["id"]
            score = candidate["score"]
            reasons = candidate["reasons"] + [
                "association:insufficient_semantic_signal"
            ]

        return self._result(
            event,
            action="create",
            memory_id=memory["id"],
            candidate_id=candidate_id,
            score=score,
            reasons=reasons,
        )

    def _apply_update(
        self,
        connection,
        event,
        text,
        entity_ids,
        candidate,
    ):
        memory = self._update_memory_tx(
            connection,
            candidate["memory"],
            event,
            text,
        )
        self._link_entities_tx(
            connection,
            memory["id"],
            entity_ids,
            event.timestamp,
        )
        return self._result(
            event,
            action="update",
            memory_id=memory["id"],
            candidate_id=candidate["memory"]["id"],
            score=candidate["score"],
            reasons=candidate["reasons"],
        )

    def _apply_create_related(
        self,
        connection,
        event,
        text,
        entity_ids,
        candidate,
    ):
        memory = self._create_memory_tx(connection, event, text)
        self._link_entities_tx(
            connection,
            memory["id"],
            entity_ids,
            event.timestamp,
        )
        relation = self._insert_relation_tx(
            connection,
            source_kind="memory",
            source_id=memory["id"],
            relation_type="related_to",
            target_kind="memory",
            target_id=candidate["memory"]["id"],
            source_memory_id=memory["id"],
            created_at=event.timestamp,
        )
        return self._result(
            event,
            action="create_related",
            memory_id=memory["id"],
            candidate_id=candidate["memory"]["id"],
            relation_id=relation["id"],
            score=candidate["score"],
            reasons=candidate["reasons"],
        )

    @staticmethod
    def _select(event):
        if event.event_type != "conversation.user":
            return False, None, "selection:event_type"

        payload = event.payload or {}
        text = payload.get("text", "")

        if not isinstance(text, str) or not text.strip():
            return False, None, "selection:empty_text"

        return True, text.strip(), "selection:conversation_user"

    def _best_candidate(self, event, text, entity_ids):
        candidates = self._candidate_memories(text)
        if not candidates:
            return None

        event_index = {
            record["id"]: record
            for record in self.event_log.load_events()
        }
        scored = [
            self._score_candidate(
                memory,
                event,
                text,
                entity_ids,
                event_index,
            )
            for memory in candidates
        ]
        scored.sort(
            key=lambda item: (
                item["score"],
                item["memory"]["updated_at"],
                item["memory"]["id"],
            ),
            reverse=True,
        )
        return scored[0]

    def _candidate_memories(self, text):
        ordered = []
        seen = set()

        with self.memory_store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT public_id
                FROM memories
                WHERE status = 'open'
                  AND type = 'episodic'
                  AND domain = 'user'
                ORDER BY updated_at DESC, row_id DESC
                LIMIT ?
                """,
                (RECENT_CANDIDATE_LIMIT,),
            ).fetchall()

        for row in rows:
            memory = self.memory_store.get_memory(row["public_id"])
            ordered.append(memory)
            seen.add(memory["id"])

        query = self._fts_query(text)
        if query is not None:
            for memory in self.memory_store.search_memories(
                query,
                limit=FTS_CANDIDATE_LIMIT,
            ):
                if (
                    memory["status"] != "open"
                    or memory["type"] != "episodic"
                    or memory["domain"] != "user"
                    or memory["id"] in seen
                ):
                    continue
                ordered.append(memory)
                seen.add(memory["id"])

        return ordered

    def _score_candidate(
        self,
        memory,
        event,
        text,
        entity_ids,
        event_index,
    ):
        score = 0
        reasons = []

        if memory["domain"] == "user":
            score += 2
            reasons.append("same_domain:+2")

        if memory["type"] == "episodic":
            score += 1
            reasons.append("same_type:+1")

        source_events = self._source_events(memory["id"], event_index)
        if any(
            record.get("session_id") == event.session_id
            and event.session_id is not None
            for record in source_events
        ):
            score += 2
            reasons.append("same_session:+2")

        fts_score = self._lexical_score(memory["content"], text)
        if fts_score:
            score += fts_score
            reasons.append(f"fts_overlap:+{fts_score}")

        candidate_entities = self._memory_entities(memory["id"])
        entity_overlap = len(candidate_entities & set(entity_ids))
        if entity_overlap:
            score += entity_overlap
            reasons.append(f"entity_overlap:+{entity_overlap}")

        time_gap = self._time_gap_seconds(source_events, event.timestamp)
        large_time_gap = (
            time_gap is not None
            and time_gap > UPDATE_MAX_GAP_SECONDS
        )

        if time_gap is not None and time_gap <= CLOSE_TIME_SECONDS:
            score += 1
            reasons.append("close_time:+1")
        elif large_time_gap:
            reasons.append("large_time_gap:block_update")

        return {
            "memory": memory,
            "score": score,
            "reasons": reasons,
            "fts_score": fts_score,
            "entity_overlap": entity_overlap,
            "large_time_gap": large_time_gap,
        }

    def _source_events(self, memory_id, event_index):
        records = []
        for event_id in self.memory_store.source_events(memory_id):
            record = event_index.get(event_id)
            if record is None:
                raise ValueError(
                    f"Missing source event {event_id} for memory {memory_id}"
                )
            records.append(record)
        return records

    def _memory_entities(self, memory_id):
        relations = self.link_store.relations_for(
            "memory",
            memory_id,
            direction="outgoing",
            relation_types={"about"},
        )
        return {
            relation["target_id"]
            for relation in relations
            if relation["target_kind"] == "entity"
        }

    def _event_entity_ids(self, event):
        entity_ids = []
        seen = set()

        for reference in event.references:
            if reference["kind"] != "entity":
                continue
            entity_id = reference["id"]
            if entity_id in seen:
                continue
            if self.link_store.get_entity(entity_id) is None:
                raise ValueError(
                    f"Unknown entity reference: {entity_id}"
                )
            seen.add(entity_id)
            entity_ids.append(entity_id)

        return entity_ids

    def _create_memory_tx(self, connection, event, text):
        public_id = f"{MEMORY_ID_PREFIX}{uuid4()}"
        composition = self.composer.compose_create(text)
        connection.execute(
            """
            INSERT INTO memories(
                public_id, type, domain, status, content, importance,
                created_at, updated_at, closed_at, merged_into
            ) VALUES (?, 'episodic', 'user', 'open', ?, 1, ?, ?, NULL, NULL)
            """,
            (
                public_id,
                composition["content"],
                event.timestamp,
                event.timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO memory_sources(memory_id, event_id)
            VALUES (?, ?)
            """,
            (public_id, event.event_id),
        )
        row = connection.execute(
            "SELECT * FROM memories WHERE public_id = ?",
            (public_id,),
        ).fetchone()
        return self.memory_store._row_to_memory(row)

    def _update_memory_tx(self, connection, memory, event, text):
        composition = self.composer.compose_update(
            memory["content"],
            text,
        )
        connection.execute(
            """
            UPDATE memories
            SET content = ?, updated_at = ?
            WHERE public_id = ?
            """,
            (
                composition["content"],
                event.timestamp,
                memory["id"],
            ),
        )
        connection.execute(
            """
            INSERT INTO memory_sources(memory_id, event_id)
            VALUES (?, ?)
            """,
            (memory["id"], event.event_id),
        )
        row = connection.execute(
            "SELECT * FROM memories WHERE public_id = ?",
            (memory["id"],),
        ).fetchone()
        return self.memory_store._row_to_memory(row)

    def _link_entities_tx(
        self,
        connection,
        memory_id,
        entity_ids,
        created_at,
    ):
        if not entity_ids:
            return

        rows = connection.execute(
            """
            SELECT target_id FROM relations
            WHERE source_kind = 'memory' AND source_id = ?
              AND relation_type = 'about' AND target_kind = 'entity'
              AND valid_until IS NULL
            """,
            (memory_id,),
        ).fetchall()
        existing = {row["target_id"] for row in rows}

        for entity_id in entity_ids:
            if entity_id in existing:
                continue
            self._insert_relation_tx(
                connection,
                source_kind="memory",
                source_id=memory_id,
                relation_type="about",
                target_kind="entity",
                target_id=entity_id,
                source_memory_id=memory_id,
                created_at=created_at,
            )
            existing.add(entity_id)

    @staticmethod
    def _insert_relation_tx(
        connection,
        *,
        source_kind,
        source_id,
        relation_type,
        target_kind,
        target_id,
        source_memory_id,
        created_at,
    ):
        duplicate = connection.execute(
            """
            SELECT * FROM relations
            WHERE source_kind = ? AND source_id = ?
              AND relation_type = ?
              AND target_kind = ? AND target_id = ?
              AND source_memory_id = ?
              AND valid_until IS NULL
            """,
            (
                source_kind,
                source_id,
                relation_type,
                target_kind,
                target_id,
                source_memory_id,
            ),
        ).fetchone()
        if duplicate is not None:
            return {
                "id": duplicate["public_id"],
                "source_kind": duplicate["source_kind"],
                "source_id": duplicate["source_id"],
                "type": duplicate["relation_type"],
                "target_kind": duplicate["target_kind"],
                "target_id": duplicate["target_id"],
                "created_at": duplicate["created_at"],
                "valid_until": duplicate["valid_until"],
                "source_memory_id": duplicate["source_memory_id"],
            }

        public_id = f"{RELATION_ID_PREFIX}{uuid4()}"
        connection.execute(
            """
            INSERT INTO relations(
                public_id, source_kind, source_id, relation_type,
                target_kind, target_id, created_at, valid_until,
                source_memory_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                public_id,
                source_kind,
                source_id,
                relation_type,
                target_kind,
                target_id,
                created_at,
                source_memory_id,
            ),
        )
        return {
            "id": public_id,
            "source_kind": source_kind,
            "source_id": source_id,
            "type": relation_type,
            "target_kind": target_kind,
            "target_id": target_id,
            "created_at": created_at,
            "valid_until": None,
            "source_memory_id": source_memory_id,
        }

    @staticmethod
    def _tokens(text):
        return {
            token.casefold()
            for token in TOKEN_PATTERN.findall(text)
            if len(token) >= 2
        }

    @classmethod
    def _lexical_score(cls, left, right):
        left_tokens = cls._tokens(left)
        right_tokens = cls._tokens(right)
        if not left_tokens or not right_tokens:
            return 0

        overlap = len(left_tokens & right_tokens)
        if overlap == 0:
            return 0

        ratio = overlap / min(len(left_tokens), len(right_tokens))
        if ratio >= 0.6:
            return 3
        if ratio >= 0.3:
            return 2
        return 1

    @classmethod
    def _fts_query(cls, text):
        tokens = sorted(cls._tokens(text))[:6]
        if not tokens:
            return None
        return " OR ".join(f'"{token}"' for token in tokens)

    @staticmethod
    def _time_gap_seconds(source_events, current_timestamp):
        if not source_events:
            return None

        current = datetime.fromisoformat(current_timestamp)
        latest = max(
            datetime.fromisoformat(record["timestamp"])
            for record in source_events
        )
        return abs((current - latest).total_seconds())

    @staticmethod
    def _result(
        event,
        *,
        action,
        memory_id=None,
        candidate_id=None,
        relation_id=None,
        score=0,
        reasons=None,
    ):
        return {
            "event_id": event.event_id,
            "action": action,
            "memory_id": memory_id,
            "candidate_id": candidate_id,
            "relation_id": relation_id,
            "score": score,
            "reasons": list(reasons or []),
        }

    def _trace_result(self, result):
        if self.trace is None:
            return

        reasons = ",".join(result["reasons"]) or "none"
        self.trace.record(
            "memory_processor: "
            f"event={result['event_id']} "
            f"action={result['action']} "
            f"memory={result['memory_id']} "
            f"candidate={result['candidate_id']} "
            f"score={result['score']} "
            f"reasons={reasons}"
        )
