"""EXP-009 Stage 1: paired A/B/C/D retrieval from ONE immutable Runtime snapshot.

Lab-only projection. This does not mutate Core, Memory, EventLog or Knowledge.
All methods use the same SQLite FTS5 table, tokenizer, renderer and budgets.
A: Memory-only, B: Event-only, C: combined, D: combined + one provenance hop.
"""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter

from anima.core.assembly import build_core
from anima.memory.context_builder import ContextBuilder
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine
from labs.exp009.c2_graph_compare import QUERIES as G1_QUERIES
from labs.exp009.c2_memory_observe import MATCHED, corpus
from labs.exp009.graph_memory_probe import TOKEN_PATTERN


METHODS = ("A", "B", "C", "D")
BUDGETS = ((3, 256), (3, 1200), (10, 256), (10, 1200))
MAX_SEEDS = 40
MAX_VISITS = 40
MAX_EDGES_PER_NODE = 12
PARSER_VERSION = "exp009.common-fts/0.1"
RENDERER_VERSION = "exp009.typed-json/0.1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def lexical_query(query):
    if not isinstance(query, str):
        raise ValueError("Query must be text")
    tokens = sorted({token.casefold() for token in TOKEN_PATTERN.findall(query)
                     if len(token) >= 2})[:8]
    return " OR ".join('"' + token + '"' for token in tokens) if tokens else None


def freeze_runtime(root):
    core = build_core(Path(root) / "runtime")
    core.runtime.wake()
    inputs = []
    for row in corpus(MATCHED):
        processed = core.runtime.user_input(row["text"])
        messages = [event for event in processed
                    if event.event_type == "conversation.user"]
        if len(messages) != 1:
            raise AssertionError("Exactly one user Event per input required")
        inputs.append({**row, "event_id": messages[0].event_id})
    events = [
        {"id": event["id"], "content": event["payload"]["text"]}
        for event in core.event_log.load_events()
        if event["type"] == "conversation.user"
    ]
    memories = [
        {"id": memory["id"], "content": memory["content"]}
        for memory in core.memory_store.list_memories()
    ]
    links = {
        item["id"]: sorted(core.memory_store.source_events(item["id"]))
        for item in memories
    }
    event_ids = {item["id"] for item in events}
    if len(inputs) != 20 or len(events) != 20 or len(event_ids) != 20:
        raise AssertionError("Frozen corpus must have 20 distinct user Events")
    if {row["event_id"] for row in inputs} != event_ids:
        raise AssertionError("Runtime user Events do not match frozen inputs")
    if set(links) != {item["id"] for item in memories}:
        raise AssertionError("Memory source manifest is incomplete")
    if any(set(ids) - event_ids for ids in links.values()):
        raise AssertionError("Dangling source Event reference")
    snapshot = {
        "events": sorted(events, key=lambda row: row["id"]),
        "memories": sorted(memories, key=lambda row: row["id"]),
        "links": links,
    }
    return core, inputs, snapshot


def query_cases(inputs):
    by_marker = {item["marker"]: item["event_id"] for item in inputs}
    rows = []
    for query_id, query, markers in G1_QUERIES:
        rows.append({
            "query_id": query_id, "query": query, "category": "G1",
            "markers": list(markers),
            "target_event_ids": sorted({by_marker[marker] for marker in markers}),
        })
    for item in inputs:
        marker = item["marker"]
        rows.append({
            "query_id": "exact_" + marker, "query": marker,
            "category": "exact_marker", "markers": [marker],
            "target_event_ids": [item["event_id"]],
        })
    for query_id, query, markers in (
        ("paraphrase_fan_stopped", "ventilation motor ceased spinning",
         ("exp009case001",)),
        ("paraphrase_fan_repaired", "airflow device fixed",
         ("exp009case003",)),
        ("numeric_91", "temperature 91", ("exp009case001",)),
        ("negative_unseen", "unrecorded comet telemetry", ()),
    ):
        rows.append({
            "query_id": query_id, "query": query,
            "category": ("paraphrase" if query_id.startswith("paraphrase")
                         else "negative" if not markers else "lexical"),
            "markers": list(markers),
            "target_event_ids": sorted({by_marker[m] for m in markers}),
        })
    assert len({row["query_id"] for row in rows}) == len(rows)
    return rows


class PairedIndex:
    """Read-only experimental FTS5 projection with typed direct source edges."""

    def __init__(self, db_path, snapshot):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.links = {key: tuple(ids) for key, ids in snapshot["links"].items()}
        reverse = {}
        for memory_id, event_ids in self.links.items():
            for event_id in event_ids:
                reverse.setdefault(event_id, []).append(memory_id)
        self.reverse = {key: tuple(sorted(ids)) for key, ids in reverse.items()}
        self.nodes = {
            **{item["id"]: {"kind": "event", **item}
               for item in snapshot["events"]},
            **{item["id"]: {"kind": "memory", **item}
               for item in snapshot["memories"]},
        }
        if len(self.nodes) != len(snapshot["events"]) + len(snapshot["memories"]):
            raise AssertionError("Duplicate Event/Memory identifier in snapshot")
        self.snapshot_hash = sha256(canonical(snapshot).encode("utf-8")).hexdigest()
        with closing(self._connect()) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('event', 'memory')),
                    content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS index_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS node_fts
                    USING fts5(node_id UNINDEXED, kind UNINDEXED, content);
            """)
            previous_hash = connection.execute(
                "SELECT value FROM index_meta WHERE key='snapshot_hash'"
            ).fetchone()
            if previous_hash and previous_hash["value"] != self.snapshot_hash:
                raise ValueError("Cannot mix different frozen snapshots in one index")
            connection.execute(
                "INSERT OR IGNORE INTO index_meta VALUES ('snapshot_hash', ?)",
                (self.snapshot_hash,),
            )
            for node_id in sorted(self.nodes):
                node = self.nodes[node_id]
                existing = connection.execute(
                    "SELECT kind, content FROM nodes WHERE node_id=?",
                    (node_id,),
                ).fetchone()
                if existing:
                    if (existing["kind"], existing["content"]) != (
                            node["kind"], node["content"]):
                        raise ValueError("Snapshot drift for " + node_id)
                    continue
                connection.execute(
                    "INSERT INTO nodes VALUES (?, ?, ?)",
                    (node_id, node["kind"], node["content"]),
                )
                connection.execute(
                    "INSERT INTO node_fts VALUES (?, ?, ?)",
                    (node_id, node["kind"], node["content"]),
                )
            count = connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            if count != len(self.nodes):
                raise ValueError("Index contains foreign snapshot entries")

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def lookup_event(self, event_id):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT node_id, kind, content FROM nodes "
                "WHERE node_id=? AND kind='event'", (event_id,),
            ).fetchone()
        return None if row is None else {
            "id": row["node_id"], "kind": row["kind"],
            "content": row["content"],
        }

    def _seeds(self, query, method):
        match = lexical_query(query)
        if match is None:
            return []
        with closing(self._connect()) as connection:
            if method == "A":
                kind_filter = "AND kind='memory'"
            elif method == "B":
                kind_filter = "AND kind='event'"
            else:
                kind_filter = ""
            return [
                {"id": row["node_id"], "score": row["rank"]}
                for row in connection.execute(
                    "SELECT node_id, bm25(node_fts) AS rank "
                    "FROM node_fts WHERE node_fts MATCH ? " + kind_filter
                    + " ORDER BY rank, node_id LIMIT ?",
                    (match, MAX_SEEDS),
                )
            ]

    def _neighbors(self, node_id):
        node = self.nodes[node_id]
        if node["kind"] == "memory":
            return self.links.get(node_id, ())
        return self.reverse.get(node_id, ())

    def search(self, query, *, method, max_items, max_chars):
        if method not in METHODS:
            raise ValueError("Unknown comparison method")
        if type(max_items) is not int or not 1 <= max_items <= 100:
            raise ValueError("Invalid item budget")
        if type(max_chars) is not int or not 2 <= max_chars <= 100000:
            raise ValueError("Invalid character budget")
        started = perf_counter()
        seeds = self._seeds(query, method)
        candidates = []
        seen = set()
        capped_edges = False

        for row in seeds:
            if len(candidates) >= MAX_VISITS:
                break
            node_id = row["id"]
            if node_id not in seen:
                candidates.append((node_id, "fts", row["score"]))
                seen.add(node_id)
            if method != "D":
                continue
            neighbors = self._neighbors(node_id)
            if len(neighbors) > MAX_EDGES_PER_NODE:
                capped_edges = True
            for linked_id in neighbors[:MAX_EDGES_PER_NODE]:
                if len(candidates) >= MAX_VISITS:
                    break
                if linked_id not in seen:
                    candidates.append((linked_id, "source:" + node_id, None))
                    seen.add(linked_id)

        selected = []
        entries = []
        exhausted = False
        for node_id, via, score in candidates:
            node = self.nodes[node_id]
            rendered = {
                "content": node["content"], "id": node_id,
                "kind": node["kind"], "via": via,
            }
            blob = canonical(rendered)
            if len(selected) >= max_items:
                exhausted = True
                break
            # Charge the exact serialized context including [] and commas.
            if len("[" + ",".join([*entries, blob]) + "]") > max_chars:
                exhausted = True
                continue
            selected.append({**rendered, "score": score})
            entries.append(blob)
        rendered_context = "[" + ",".join(entries) + "]"
        if len(rendered_context) > max_chars:
            raise AssertionError("Rendered output exceeded common budget")
        if len(selected) > max_items:
            raise AssertionError("Items exceeded common budget")
        return {
            "method": method, "query": query, "max_items": max_items,
            "max_chars": max_chars, "parser_version": PARSER_VERSION,
            "renderer_version": RENDERER_VERSION,
            "seeds": seeds, "candidates_visited": len(candidates),
            "source_edge_cap_hit": capped_edges,
            "selected": selected, "rendered_context": rendered_context,
            "items_used": len(selected), "chars_used": len(rendered_context),
            "truncated": exhausted or len(candidates) == MAX_VISITS,
            "latency_ms": (perf_counter() - started) * 1000,
        }


def score(case, result, index):
    gold = set(case["target_event_ids"])
    events = [node["id"] for node in result["selected"]
              if node["kind"] == "event"]
    memories = [node["id"] for node in result["selected"]
                if node["kind"] == "memory"]
    hits = sorted(set(events) & gold)
    sourced = {event_id for memory_id in memories
               for event_id in index.links[memory_id]}
    linked_hits = sorted(sourced & gold)
    return {
        "type": "comparison", "query_id": case["query_id"],
        "category": case["category"], "query": case["query"],
        "target_event_ids": sorted(gold), "markers": case["markers"],
        "selected_event_ids": events, "selected_memory_ids": memories,
        "hits": hits, "false_positives": sorted(set(events) - gold),
        "misses": sorted(gold - set(events)),
        "precision_at_k": len(hits) / len(events) if events else None,
        "recall_at_k": len(hits) / len(gold) if gold else None,
        "linked_source_coverage": len(linked_hits) / len(gold) if gold else None,
        "no_match_pass": not result["selected"] if not gold else None,
        "false_positive_count": len(result["selected"]) if not gold else None,
        "snapshot_hash": index.snapshot_hash,
        **result,
    }


def run_abcd(root, *, report_path=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    core, inputs, snapshot = freeze_runtime(root)
    index = PairedIndex(root / "lab_fts.db", snapshot)
    before_events = core.event_log.load_events()
    before_memories = core.memory_store.list_memories()
    queries = query_cases(inputs)
    marker_ids = {row["marker"]: row["event_id"] for row in inputs}
    for event_id in marker_ids.values():
        if index.lookup_event(event_id) is None:
            raise AssertionError("Indexed Event ID unavailable")

    records = [{
        "type": "experiment",
        "format": "exp009.abcd.raw-jsonl/0.1",
        "snapshot_hash": index.snapshot_hash,
        "events": len(snapshot["events"]),
        "memories": len(snapshot["memories"]),
        "links": sum(map(len, snapshot["links"].values())),
        "queries": len(queries), "methods": list(METHODS),
        "budgets": [list(b) for b in BUDGETS],
        "max_seeds": MAX_SEEDS, "max_visits": MAX_VISITS,
        "max_edges_per_node": MAX_EDGES_PER_NODE,
        "parser_version": PARSER_VERSION,
        "renderer_version": RENDERER_VERSION,
        "note": "Source ID recall; no semantic truth or graph superiority implied.",
    }]
    records.extend({"type": "input", **item} for item in inputs)
    records.append({"type": "snapshot", "snapshot": snapshot})
    for case in queries:
        for max_items, max_chars in BUDGETS:
            for method in METHODS:
                result = index.search(
                    case["query"], method=method,
                    max_items=max_items, max_chars=max_chars,
                )
                records.append(score(case, result, index))

    # Historical baseline is a separate reference, never relabeled as A.
    retrieval = RetrievalEngine(
        memory_store=core.memory_store, link_store=core.link_store
    )
    context = ContextBuilder(
        retrieval=retrieval,
        provenance=ProvenanceResolver(
            core.memory_store, core.link_store, core.event_log,
        ),
    )
    for case in queries[:len(G1_QUERIES)]:
        records.append({
            "type": "production_reference", "query_id": case["query_id"],
            "max_items": 10, "max_chars": 1200,
            "retrieval": retrieval.retrieve(
                case["query"], kinds={"memory"}, relation_hops=0, top_k=10,
            ),
            "contexts": {
                role: context.build(
                    case["query"], consumer=role,
                    max_items=10, max_chars=1200,
                    retrieval_options={"kinds": {"memory"}},
                )
                for role in ("FAST", "DEEP")
            },
        })
    if (core.event_log.load_events() != before_events or
            core.memory_store.list_memories() != before_memories):
        raise AssertionError("Lab retrieval mutated production source stores")
    records.append({
        "type": "final", "snapshot_hash": index.snapshot_hash,
        "query_count": len(queries), "comparison_count": sum(
            item["type"] == "comparison" for item in records),
        "direct_id_lookups": len(marker_ids),
        "raw_events_unchanged": True, "memories_unchanged": True,
    })
    if report_path is not None:
        report = Path(report_path)
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("x", encoding="utf-8") as handle:
            for record in records:
                handle.write(canonical(record) + "\n")
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anima-exp009-abcd-") as folder:
        report = args.report_dir / "retrieval_abcd.jsonl"
        records = run_abcd(Path(folder), report_path=report)
    final = records[-1]
    print(
        f"EXP-009 A/B/C/D: queries={final['query_count']} "
        f"comparisons={final['comparison_count']} "
        f"direct_ids={final['direct_id_lookups']} report={report}"
    )
    if args.print_summary:
        for method in METHODS:
            items = [r for r in records if r["type"] == "comparison"
                     and r["method"] == method and r["max_items"] == 10
                     and r["max_chars"] == 1200 and r["target_event_ids"]]
            total = sum(len(r["target_event_ids"]) for r in items)
            hits = sum(len(r["hits"]) for r in items)
            print(f"  {method}: direct_event_recall={hits}/{total}")


if __name__ == "__main__":
    main()
