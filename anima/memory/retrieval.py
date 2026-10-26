import re
import sqlite3

from anima.memory.link_store import (
    KNOWLEDGE_ID_PREFIX,
    KNOWLEDGE_STATUSES,
)
from anima.memory.memory_store import (
    MEMORY_DOMAINS,
    MEMORY_ID_PREFIX,
    MEMORY_STATUSES,
    MEMORY_TYPES,
)


TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
DEFAULT_TOP_K = 10
MAX_TOP_K = 100
FTS_SEED_LIMIT = 25

DEFAULT_MEMORY_STATUSES = {"open", "closed"}
DEFAULT_KNOWLEDGE_STATUSES = {
    "provisional",
    "confirmed",
    "challenged",
}

STATUS_BONUS = {
    ("memory", "open"): 2,
    ("memory", "closed"): 3,
    ("memory", "merged"): 0,
    ("knowledge", "provisional"): 2,
    ("knowledge", "confirmed"): 6,
    ("knowledge", "challenged"): 4,
    ("knowledge", "superseded"): 0,
    ("knowledge", "rejected"): 0,
}


class RetrievalEngine:
    """Deterministic Stage 1.8 retrieval over Memory/Knowledge and 1-hop links."""

    def __init__(self, *, memory_store, link_store, trace=None):
        self.memory_store = memory_store
        self.link_store = link_store
        self.trace = trace

    def retrieve(
        self,
        query=None,
        *,
        object_ids=None,
        kinds=("knowledge", "memory"),
        domain=None,
        memory_types=None,
        memory_statuses=None,
        knowledge_statuses=None,
        entity_ids=None,
        entity_names=None,
        relation_hops=1,
        top_k=DEFAULT_TOP_K,
    ):
        kinds = self._validate_kinds(kinds)
        top_k = self._validate_top_k(top_k)
        relation_hops = self._validate_relation_hops(relation_hops)
        domain = self._validate_domain(domain)
        memory_types = self._validate_set(
            memory_types,
            MEMORY_TYPES,
            "memory type",
        )
        memory_statuses = self._validate_set(
            memory_statuses,
            MEMORY_STATUSES,
            "memory status",
        )
        knowledge_statuses = self._validate_set(
            knowledge_statuses,
            KNOWLEDGE_STATUSES,
            "knowledge status",
        )
        object_ids = self._clean_ids(object_ids)
        entity_ids = self._clean_ids(entity_ids)
        entity_names = self._clean_names(entity_names)

        if query is not None:
            if not isinstance(query, str):
                raise ValueError("Retrieval query must be a string or null")
            query = query.strip()
            if not query:
                query = None

        if query is not None and self._looks_like_object_id(query):
            object_ids = [query] + [
                public_id
                for public_id in object_ids
                if public_id != query
            ]
            text_query = None
        else:
            text_query = query

        resolved_entities = self._resolve_entities(
            entity_ids,
            entity_names,
        )

        has_structured_filter = any(
            value is not None
            for value in (
                domain,
                memory_types,
                memory_statuses,
                knowledge_statuses,
            )
        )
        if not (
            object_ids
            or resolved_entities
            or text_query
            or has_structured_filter
        ):
            raise ValueError(
                "Retrieval requires query, object_ids, entity filter or structured filter"
            )

        candidates = {}
        stats = {
            "exact": 0,
            "filters": 0,
            "entities": 0,
            "fts": 0,
            "relations": 0,
        }

        for public_id in object_ids:
            result = self._exact(public_id, kinds)
            if result is None:
                continue
            kind, record = result
            if not self._allowed(
                kind,
                record,
                memory_types=memory_types,
                memory_statuses=memory_statuses,
                knowledge_statuses=knowledge_statuses,
                domain=domain,
                explicit=True,
            ):
                continue
            self._add_candidate(
                candidates,
                kind,
                record,
                score=100,
                reason="exact_id:+100",
            )
            stats["exact"] += 1

        filter_records = self._filter_records(
            kinds,
            domain=domain,
            memory_types=memory_types,
            memory_statuses=memory_statuses,
            knowledge_statuses=knowledge_statuses,
        )
        for kind, record in filter_records:
            if not self._allowed(
                kind,
                record,
                memory_types=memory_types,
                memory_statuses=memory_statuses,
                knowledge_statuses=knowledge_statuses,
                domain=domain,
            ):
                continue
            self._add_candidate(
                candidates,
                kind,
                record,
                score=20,
                reason="structured_filter:+20",
            )
            stats["filters"] += 1

        for entity in resolved_entities:
            relations = self.link_store.relations_for(
                "entity",
                entity["id"],
                direction="incoming",
                relation_types={"about"},
            )
            for relation in relations:
                kind = relation["source_kind"]
                if kind not in kinds or kind not in {"memory", "knowledge"}:
                    continue
                record = self._get_record(kind, relation["source_id"])
                if record is None or not self._allowed(
                    kind,
                    record,
                    memory_types=memory_types,
                    memory_statuses=memory_statuses,
                    knowledge_statuses=knowledge_statuses,
                    domain=domain,
                ):
                    continue
                self._add_candidate(
                    candidates,
                    kind,
                    record,
                    score=35,
                    reason=f"entity:{entity['id']}:+35",
                )
                stats["entities"] += 1

        if text_query is not None:
            fts_query = self._fts_query(text_query)
            if fts_query is not None:
                for kind, record, rank_index in self._fts_records(
                    fts_query,
                    kinds,
                ):
                    if not self._allowed(
                        kind,
                        record,
                        memory_types=memory_types,
                        memory_statuses=memory_statuses,
                        knowledge_statuses=knowledge_statuses,
                        domain=domain,
                    ):
                        continue
                    score = max(10, 30 - rank_index)
                    self._add_candidate(
                        candidates,
                        kind,
                        record,
                        score=score,
                        reason=f"fts_rank:{rank_index + 1}:+{score}",
                    )
                    stats["fts"] += 1

        if relation_hops == 1 and candidates:
            seed_keys = list(candidates)
            for kind, public_id in seed_keys:
                relations = self.link_store.relations_for(
                    kind,
                    public_id,
                    direction="both",
                )
                for relation in relations:
                    neighbor = self._relation_neighbor(
                        relation,
                        kind,
                        public_id,
                    )
                    if neighbor is None:
                        continue
                    neighbor_kind, neighbor_id = neighbor
                    if (
                        neighbor_kind not in kinds
                        or neighbor_kind not in {"memory", "knowledge"}
                    ):
                        continue
                    record = self._get_record(
                        neighbor_kind,
                        neighbor_id,
                    )
                    if record is None or not self._allowed(
                        neighbor_kind,
                        record,
                        memory_types=memory_types,
                        memory_statuses=memory_statuses,
                        knowledge_statuses=knowledge_statuses,
                        domain=domain,
                    ):
                        continue
                    self._add_candidate(
                        candidates,
                        neighbor_kind,
                        record,
                        score=8,
                        reason=f"relation:{relation['type']}:1hop:+8",
                    )
                    stats["relations"] += 1

        results = []
        for candidate in candidates.values():
            kind = candidate["kind"]
            record = candidate["record"]
            bonus = STATUS_BONUS.get(
                (kind, record["status"]),
                0,
            )
            candidate["score"] += bonus
            if bonus:
                candidate["reasons"].add(
                    f"status:{record['status']}:+{bonus}"
                )
            if kind == "memory" and record.get("importance"):
                importance = record["importance"]
                candidate["score"] += importance
                candidate["reasons"].add(
                    f"importance:{importance}:+{importance}"
                )

            results.append(
                {
                    "kind": kind,
                    "id": record["id"],
                    "score": candidate["score"],
                    "reasons": sorted(candidate["reasons"]),
                    "record": record,
                }
            )

        results.sort(
            key=lambda item: (
                -item["score"],
                0 if item["kind"] == "knowledge" else 1,
                item["id"],
            )
        )
        total_candidates = len(results)
        results = results[:top_k]

        response = {
            "query": query,
            "top_k": top_k,
            "results": results,
            "stats": {
                **stats,
                "candidates": total_candidates,
                "returned": len(results),
            },
        }
        self._trace_result(response)
        return response

    @staticmethod
    def _validate_kinds(kinds):
        if isinstance(kinds, str):
            kinds = {kinds}
        else:
            try:
                kinds = set(kinds)
            except TypeError as error:
                raise ValueError("Retrieval kinds must be a collection") from error
        unknown = kinds - {"memory", "knowledge"}
        if unknown or not kinds:
            raise ValueError(
                "Retrieval kinds must contain memory and/or knowledge"
            )
        return kinds

    @staticmethod
    def _validate_top_k(top_k):
        if (
            not isinstance(top_k, int)
            or isinstance(top_k, bool)
            or not 1 <= top_k <= MAX_TOP_K
        ):
            raise ValueError(
                f"Retrieval top_k must be an integer from 1 to {MAX_TOP_K}"
            )
        return top_k

    @staticmethod
    def _validate_relation_hops(value):
        if value not in {0, 1}:
            raise ValueError("Stage 1 retrieval relation_hops must be 0 or 1")
        return value

    @staticmethod
    def _validate_domain(domain):
        if domain is not None and domain not in MEMORY_DOMAINS:
            raise ValueError(f"Unknown retrieval domain: {domain!r}")
        return domain

    @staticmethod
    def _validate_set(value, allowed, label):
        if value is None:
            return None
        if isinstance(value, str):
            value = {value}
        else:
            try:
                value = set(value)
            except TypeError as error:
                raise ValueError(f"Retrieval {label}s must be a collection") from error
        unknown = value - allowed
        if unknown:
            raise ValueError(
                f"Unknown retrieval {label}(s): "
                + ", ".join(sorted(unknown))
            )
        if not value:
            raise ValueError(f"Retrieval {label}s cannot be empty")
        return value

    @staticmethod
    def _clean_ids(values):
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]
        cleaned = []
        seen = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Retrieval IDs must be non-empty strings")
            value = value.strip()
            if value not in seen:
                seen.add(value)
                cleaned.append(value)
        return cleaned

    @staticmethod
    def _clean_names(values):
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]
        cleaned = []
        seen = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Entity names must be non-empty strings")
            value = " ".join(value.split())
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                cleaned.append(value)
        return cleaned

    @staticmethod
    def _looks_like_object_id(value):
        return value.startswith(MEMORY_ID_PREFIX) or value.startswith(
            KNOWLEDGE_ID_PREFIX
        )

    def _resolve_entities(self, entity_ids, entity_names):
        resolved = []
        seen = set()
        for entity_id in entity_ids:
            entity = self.link_store.get_entity(entity_id)
            if entity is None:
                raise ValueError(f"Unknown entity: {entity_id}")
            if entity["id"] not in seen:
                seen.add(entity["id"])
                resolved.append(entity)
        for name in entity_names:
            entity = self.link_store.resolve_entity(name)
            if entity is None:
                raise ValueError(f"Unknown entity name: {name!r}")
            if entity["id"] not in seen:
                seen.add(entity["id"])
                resolved.append(entity)
        return resolved

    def _exact(self, public_id, kinds):
        if public_id.startswith(MEMORY_ID_PREFIX):
            if "memory" not in kinds:
                return None
            try:
                record = self.memory_store.get_memory(public_id)
            except ValueError as error:
                raise ValueError(f"Invalid retrieval object ID: {public_id}") from error
            return None if record is None else ("memory", record)
        if public_id.startswith(KNOWLEDGE_ID_PREFIX):
            if "knowledge" not in kinds:
                return None
            try:
                record = self.link_store.get_knowledge(public_id)
            except ValueError as error:
                raise ValueError(f"Invalid retrieval object ID: {public_id}") from error
            return None if record is None else ("knowledge", record)
        raise ValueError(
            "Retrieval object ID must use mem_ or kn_ prefix"
        )

    def _filter_records(
        self,
        kinds,
        *,
        domain,
        memory_types,
        memory_statuses,
        knowledge_statuses,
    ):
        records = []
        with self.memory_store.transaction() as connection:
            if "memory" in kinds and any(
                value is not None
                for value in (domain, memory_types, memory_statuses)
            ):
                clauses = []
                values = []
                if domain is not None:
                    clauses.append("domain = ?")
                    values.append(domain)
                if memory_types is not None:
                    placeholders = ",".join("?" for _ in memory_types)
                    clauses.append(f"type IN ({placeholders})")
                    values.extend(sorted(memory_types))
                if memory_statuses is not None:
                    placeholders = ",".join("?" for _ in memory_statuses)
                    clauses.append(f"status IN ({placeholders})")
                    values.extend(sorted(memory_statuses))
                rows = connection.execute(
                    "SELECT * FROM memories WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY updated_at DESC, row_id DESC LIMIT ?",
                    values + [FTS_SEED_LIMIT],
                ).fetchall()
                records.extend(
                    ("memory", self.memory_store._row_to_memory(row))
                    for row in rows
                )

            if "knowledge" in kinds and any(
                value is not None
                for value in (domain, knowledge_statuses)
            ):
                clauses = []
                values = []
                if domain is not None:
                    clauses.append("domain = ?")
                    values.append(domain)
                if knowledge_statuses is not None:
                    placeholders = ",".join("?" for _ in knowledge_statuses)
                    clauses.append(f"status IN ({placeholders})")
                    values.extend(sorted(knowledge_statuses))
                rows = connection.execute(
                    "SELECT * FROM knowledge WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY updated_at DESC, row_id DESC LIMIT ?",
                    values + [FTS_SEED_LIMIT],
                ).fetchall()
                records.extend(
                    ("knowledge", self.link_store._row_to_knowledge(row))
                    for row in rows
                )
        return records

    def _fts_records(self, fts_query, kinds):
        records = []
        try:
            with self.memory_store.transaction() as connection:
                if "memory" in kinds:
                    rows = connection.execute(
                        """
                        SELECT m.*, bm25(memory_fts) AS fts_rank
                        FROM memory_fts
                        JOIN memories m ON m.row_id = memory_fts.rowid
                        WHERE memory_fts MATCH ?
                        ORDER BY fts_rank, m.row_id
                        LIMIT ?
                        """,
                        (fts_query, FTS_SEED_LIMIT),
                    ).fetchall()
                    records.extend(
                        (
                            "memory",
                            self.memory_store._row_to_memory(row),
                            index,
                        )
                        for index, row in enumerate(rows)
                    )

                if "knowledge" in kinds:
                    rows = connection.execute(
                        """
                        SELECT k.*, bm25(knowledge_fts) AS fts_rank
                        FROM knowledge_fts
                        JOIN knowledge k ON k.row_id = knowledge_fts.rowid
                        WHERE knowledge_fts MATCH ?
                        ORDER BY fts_rank, k.row_id
                        LIMIT ?
                        """,
                        (fts_query, FTS_SEED_LIMIT),
                    ).fetchall()
                    records.extend(
                        (
                            "knowledge",
                            self.link_store._row_to_knowledge(row),
                            index,
                        )
                        for index, row in enumerate(rows)
                    )
        except sqlite3.OperationalError as error:
            raise ValueError(
                f"FTS retrieval failed for query {fts_query!r}: {error}"
            ) from error
        return records

    @staticmethod
    def _tokens(text):
        return {
            token.casefold()
            for token in TOKEN_PATTERN.findall(text)
            if len(token) >= 2
        }

    @classmethod
    def _fts_query(cls, text):
        tokens = sorted(cls._tokens(text))[:8]
        if not tokens:
            return None
        return " OR ".join(f'"{token}"' for token in tokens)

    def _get_record(self, kind, public_id):
        if kind == "memory":
            return self.memory_store.get_memory(public_id)
        if kind == "knowledge":
            return self.link_store.get_knowledge(public_id)
        return None

    @staticmethod
    def _relation_neighbor(relation, kind, public_id):
        if (
            relation["source_kind"] == kind
            and relation["source_id"] == public_id
        ):
            return relation["target_kind"], relation["target_id"]
        if (
            relation["target_kind"] == kind
            and relation["target_id"] == public_id
        ):
            return relation["source_kind"], relation["source_id"]
        return None

    @staticmethod
    def _allowed(
        kind,
        record,
        *,
        memory_types,
        memory_statuses,
        knowledge_statuses,
        domain,
        explicit=False,
    ):
        if domain is not None and record["domain"] != domain:
            return False

        if kind == "memory":
            if memory_types is not None and record["type"] not in memory_types:
                return False
            allowed_statuses = (
                memory_statuses
                if memory_statuses is not None
                else (MEMORY_STATUSES if explicit else DEFAULT_MEMORY_STATUSES)
            )
            return record["status"] in allowed_statuses

        allowed_statuses = (
            knowledge_statuses
            if knowledge_statuses is not None
            else (
                KNOWLEDGE_STATUSES
                if explicit
                else DEFAULT_KNOWLEDGE_STATUSES
            )
        )
        return record["status"] in allowed_statuses

    @staticmethod
    def _add_candidate(
        candidates,
        kind,
        record,
        *,
        score,
        reason,
    ):
        key = (kind, record["id"])
        candidate = candidates.setdefault(
            key,
            {
                "kind": kind,
                "record": record,
                "score": 0,
                "reasons": set(),
            },
        )
        if reason not in candidate["reasons"]:
            candidate["score"] += score
            candidate["reasons"].add(reason)

    def _trace_result(self, response):
        if self.trace is None:
            return
        ids = ",".join(item["id"] for item in response["results"])
        self.trace.record(
            "retrieval: "
            f"query={response['query']!r} "
            f"returned={response['stats']['returned']} "
            f"candidates={response['stats']['candidates']} "
            f"ids={ids or 'none'}"
        )
