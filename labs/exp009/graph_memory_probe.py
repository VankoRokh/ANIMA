"""EXP-009 G1: lab-only SQLite graph projection over real ANIMA stores.

Nodes: raw Events and current Memory records. Typed edges reproduce the
existing Memory->Event provenance links. This is an *index*, not a new
production Memory, learned knowledge graph, or LLM-generated ontology.
"""

from collections import deque
from contextlib import closing
import re
import sqlite3
from pathlib import Path


TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
MAX_DEPTH = 3
MAX_VISITS = 100
MAX_SEEDS = 25


class GraphMemoryProbe:
    def __init__(self, database_file):
        self.database_file = Path(database_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('event', 'memory')),
                    content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    source_id TEXT NOT NULL REFERENCES nodes(id),
                    relation TEXT NOT NULL CHECK (
                        relation IN ('has_source', 'member_of')
                    ),
                    target_id TEXT NOT NULL REFERENCES nodes(id),
                    PRIMARY KEY (source_id, relation, target_id)
                );
                CREATE INDEX IF NOT EXISTS edges_source
                    ON edges(source_id, relation);
                CREATE VIRTUAL TABLE IF NOT EXISTS node_fts
                    USING fts5(node_id UNINDEXED, content);
                """
            )

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _event_content(event):
        payload = event.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            return payload["text"]
        # System events are retained in the graph as provenance nodes, but
        # only text-bearing records can match the fixture's text queries.
        return event["type"]

    @staticmethod
    def _add_node(connection, public_id, kind, content):
        previous = connection.execute(
            "SELECT kind, content FROM nodes WHERE id = ?", (public_id,)
        ).fetchone()
        if previous is not None:
            if previous["kind"] != kind or previous["content"] != content:
                raise ValueError(
                    "Graph index snapshot changed for existing node "
                    + public_id
                )
            return False
        connection.execute(
            "INSERT INTO nodes(id, kind, content) VALUES (?, ?, ?)",
            (public_id, kind, content),
        )
        connection.execute(
            "INSERT INTO node_fts(node_id, content) VALUES (?, ?)",
            (public_id, content),
        )
        return True

    def ingest_snapshot(self, event_log, memory_store):
        """Index an immutable snapshot; idempotent for identical inputs.

        This experiment does not attempt live graph synchronization.
        """
        events = event_log.load_events()
        memories = memory_store.list_memories()
        known_event_ids = {event["id"] for event in events}
        if len(known_event_ids) != len(events):
            raise AssertionError("Duplicated raw event in input snapshot")
        with closing(self._connect()) as connection, connection:
            for event in events:
                self._add_node(
                    connection, event["id"], "event",
                    self._event_content(event),
                )
            for memory in memories:
                self._add_node(
                    connection, memory["id"], "memory", memory["content"]
                )
            for memory in memories:
                for event_id in memory_store.source_events(memory["id"]):
                    if event_id not in known_event_ids:
                        raise ValueError(
                            "Memory provenance is missing raw event " + event_id
                        )
                    connection.execute(
                        "INSERT OR IGNORE INTO edges("
                        "source_id, relation, target_id) VALUES (?, ?, ?)",
                        (memory["id"], "has_source", event_id),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO edges("
                        "source_id, relation, target_id) VALUES (?, ?, ?)",
                        (event_id, "member_of", memory["id"]),
                    )
        return self.snapshot()

    def snapshot(self):
        with closing(self._connect()) as connection:
            nodes = [
                dict(row) for row in connection.execute(
                    "SELECT id, kind, content FROM nodes ORDER BY id"
                )
            ]
            edges = [
                dict(row) for row in connection.execute(
                    "SELECT source_id, relation, target_id FROM edges "
                    "ORDER BY source_id, relation, target_id"
                )
            ]
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _fts_query(query):
        if not isinstance(query, str):
            raise ValueError("Graph query must be a string")
        tokens = sorted({
            token.casefold() for token in TOKEN_PATTERN.findall(query)
            if len(token) >= 2
        })[:8]
        if not tokens:
            return None
        return " OR ".join('"' + token + '"' for token in tokens)

    @staticmethod
    def _validate_limits(max_depth, max_items, max_chars, max_visits):
        if type(max_depth) is not int or not 0 <= max_depth <= MAX_DEPTH:
            raise ValueError("max_depth must be an integer in [0, 3]")
        if type(max_items) is not int or not 1 <= max_items <= 100:
            raise ValueError("max_items must be an integer in [1, 100]")
        if type(max_chars) is not int or not 1 <= max_chars <= 100_000:
            raise ValueError("max_chars must be an integer in [1, 100000]")
        if type(max_visits) is not int or not 1 <= max_visits <= MAX_VISITS:
            raise ValueError("max_visits must be an integer in [1, 100]")

    def search(
        self, query, *, max_depth=0, max_items=5, max_chars=1200,
        max_visits=40,
    ):
        """Bounded breadth-first traversal from lexical seeds.

        Seed rank comes from SQLite FTS5, not gold labels. The queue contains
        all FTS seeds first. A deeper search does not guarantee better context.
        """
        self._validate_limits(max_depth, max_items, max_chars, max_visits)
        fts_query = self._fts_query(query)
        if fts_query is None:
            return {
                "query": query, "depth_limit": max_depth,
                "budget": {"items": max_items, "chars": max_chars,
                           "visits": max_visits},
                "fts_seeds": [], "visited": [], "selected": [],
                "stats": {"items_used": 0, "chars_used": 0,
                          "visited": 0, "omitted": 0, "truncated": False},
            }
        with closing(self._connect()) as connection:
            seeds = [
                row["node_id"] for row in connection.execute(
                    "SELECT node_id FROM node_fts "
                    "WHERE node_fts MATCH ? "
                    "ORDER BY bm25(node_fts), node_id LIMIT ?",
                    (fts_query, MAX_SEEDS),
                )
            ]
            queue = deque((node_id, 0, None, "fts_seed") for node_id in seeds)
            enqueued = set(seeds)
            visited = []
            while queue and len(visited) < max_visits:
                node_id, depth, parent, relation = queue.popleft()
                node = connection.execute(
                    "SELECT id, kind, content FROM nodes WHERE id = ?",
                    (node_id,),
                ).fetchone()
                if node is None:
                    raise AssertionError("Graph edge points to missing node")
                visited.append({
                    **dict(node), "depth": depth,
                    "via_id": parent, "via_relation": relation,
                })
                if depth >= max_depth:
                    continue
                for edge in connection.execute(
                    "SELECT relation, target_id FROM edges "
                    "WHERE source_id = ? ORDER BY relation, target_id",
                    (node_id,),
                ):
                    target = edge["target_id"]
                    if target not in enqueued:
                        enqueued.add(target)
                        queue.append(
                            (target, depth + 1, node_id, edge["relation"])
                        )
            limit_hit = bool(queue)

        selected = []
        chars_used = 0
        omitted = 0
        for node in visited:
            cost = len(node["content"])
            if len(selected) >= max_items or chars_used + cost > max_chars:
                omitted += 1
                continue
            selected.append(node)
            chars_used += cost
        return {
            "query": query,
            "depth_limit": max_depth,
            "budget": {
                "items": max_items, "chars": max_chars, "visits": max_visits,
            },
            "fts_seeds": seeds,
            "visited": visited,
            "selected": selected,
            "stats": {
                "items_used": len(selected),
                "chars_used": chars_used,
                "visited": len(visited),
                "omitted": omitted,
                "truncated": bool(omitted or limit_hit),
                "visit_limit_hit": limit_hit,
            },
        }
