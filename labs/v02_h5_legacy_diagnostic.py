"""ANIMA v0.2 H5: non-mutating legacy memory integrity diagnostic.

For an OFFLINE SNAPSHOT, not for a running instance. No MemoryStore,
EventLog, schema bootstrap, rebuild, migrations, or write transactions.
SQLite opens an existing snapshot in mode=ro + query_only; WAL snapshots
must be made consistently before calling this tool. Never use immutable=1
on a potentially live WAL store (it would ignore uncheckpointed changes).

Usage:
    PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_legacy_diagnostic \
        --memory-db /path/to/OFFLINE_SNAPSHOT/memory.db \
        --events /path/to/OFFLINE_SNAPSHOT/events.jsonl

Output is JSON containing counts and bounded ID samples, not Memory texts.
This diagnoses known invariants; it is NOT a migration/repair tool and does
not assert that other hazards, semantic errors or source tampering are absent.
"""

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from anima.core.event_bus import Event

REQUIRED = {
    "schema_meta", "memories", "memory_sources", "knowledge",
    "knowledge_sources", "relations", "history", "entities",
    "event_processing",
}
KINDS = {
    "memory": "memories",
    "knowledge": "knowledge",
    "entity": "entities",
}
SAMPLE_LIMIT = 8
REPORT_SCHEMA = "anima.v02.h5.legacy_diagnostic/0.1"


def _raw_ids(path, issue):
    """Read terminated JSONL and validate every Event; no file writes."""
    if path is None:
        return None, None
    if not path.is_file():
        issue("raw_file_missing", str(path))
        return None, 0
    ids = set()
    invalid = False
    n = 0
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            if not raw.endswith(b"\n"):
                invalid = True
                issue("invalid_raw_eventlog", f"line:{line_number}:unterminated")
                continue
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
                Event.validate_record(record)
            except (UnicodeError, ValueError, TypeError) as error:
                invalid = True
                issue(
                    "invalid_raw_eventlog",
                    f"line:{line_number}:{type(error).__name__}",
                )
                continue
            if record["id"] in ids:
                invalid = True
                issue("invalid_raw_eventlog", f"line:{line_number}:duplicate")
                continue
            ids.add(record["id"])
            n += 1
    return (None if invalid else ids), n


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp missing UTC offset")
    return parsed


def audit_snapshot(memory_db, events_jsonl=None, *, at=None):
    """Read an existing, quiescent snapshot and return a structured report.

    The caller is responsible for making a consistent SQLite backup or
    stopping the producer before copying DB + WAL files. This function
    never attempts to repair a historical state.
    """
    memory_db = Path(memory_db)
    events = Path(events_jsonl) if events_jsonl is not None else None
    if not memory_db.is_file():
        raise FileNotFoundError(f"Memory database not found: {memory_db}")
    now = _instant(at) if at is not None else datetime.now(timezone.utc)
    findings = defaultdict(lambda: {"count": 0, "ids": []})

    def issue(code, public_id):
        item = findings[code]
        item["count"] += 1
        if len(item["ids"]) < SAMPLE_LIMIT:
            item["ids"].append(str(public_id))

    raw_ids, raw_count = _raw_ids(events, issue)
    uri = "file:" + quote(str(memory_db.resolve()), safe="/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing_tables = sorted(REQUIRED - tables)
        for name in missing_tables:
            issue("missing_table", name)
        counts = {
            "raw_events": raw_count,
            "memories": None,
            "knowledge": None,
            "relations": None,
            "finalized_events": None,
        }
        if missing_tables:
            return {
                "schema": REPORT_SCHEMA, "status": "degraded",
                "as_of": now.isoformat(), "counts": counts,
                "findings": dict(sorted(findings.items())),
                "limits": ["Incomplete schema; detailed checks not executed."],
            }

        quick_check = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
        if quick_check != "ok":
            issue("sqlite_quick_check_failed", quick_check)

        memories = {
            row["public_id"]: row["status"]
            for row in conn.execute("SELECT public_id, status FROM memories")
        }
        knowledge = {
            row["public_id"]: row["status"]
            for row in conn.execute("SELECT public_id, status FROM knowledge")
        }
        entities = {
            row["public_id"]
            for row in conn.execute("SELECT public_id FROM entities")
        }
        objects = {
            "memory": memories,
            "knowledge": knowledge,
            "entity": entities,
        }
        counts["memories"] = len(memories)
        counts["knowledge"] = len(knowledge)

        supports = set()
        relation_count = 0
        for row in conn.execute(
            "SELECT public_id, source_kind, source_id, relation_type, "
            "target_kind, target_id, created_at, valid_until, "
            "source_memory_id FROM relations ORDER BY row_id"
        ):
            relation_count += 1
            rel_id = row["public_id"]
            source_kind = row["source_kind"]
            target_kind = row["target_kind"]
            source_id = row["source_id"]
            target_id = row["target_id"]
            provenance_id = row["source_memory_id"]

            if (
                source_kind not in objects
                or source_id not in objects[source_kind]
            ):
                issue("orphan_relation_source", rel_id)
            if (
                target_kind not in objects
                or target_id not in objects[target_kind]
            ):
                issue("orphan_relation_target", rel_id)
            if provenance_id not in memories:
                issue("orphan_relation_provenance", rel_id)

            try:
                started = _instant(row["created_at"])
                ended = (
                    None if row["valid_until"] is None
                    else _instant(row["valid_until"])
                )
            except ValueError:
                issue("invalid_relation_timestamp", rel_id)
                continue
            if ended is not None and ended <= started:
                issue("invalid_relation_interval", rel_id)

            active = started <= now and (ended is None or now < ended)
            if not active or (
                row["relation_type"] not in {"supports", "contradicts"}
            ) or target_kind != "knowledge":
                continue

            valid = (
                source_kind == "memory"
                and source_id == provenance_id
                and memories.get(source_id) == "closed"
            )
            if not valid:
                issue("invalid_active_knowledge_evidence", rel_id)
            elif row["relation_type"] == "supports":
                supports.add(target_id)

        counts["relations"] = relation_count

        # Historical import may contain confirmed rows that predate H2.1.
        confirmation_history = {
            row["object_id"]
            for row in conn.execute(
                "SELECT object_id FROM history WHERE object_kind='knowledge' "
                "AND operation IN ('confirm', 'create_superseding')"
            )
        }
        for kn_id, status in knowledge.items():
            if status != "confirmed":
                continue
            if kn_id not in supports:
                issue("confirmed_without_live_closed_support", kn_id)
            if kn_id not in confirmation_history:
                issue("confirmed_without_confirmation_history", kn_id)

        for row in conn.execute(
            "SELECT public_id, merged_into FROM memories "
            "WHERE merged_into IS NOT NULL"
        ):
            if row["merged_into"] not in memories:
                issue("orphan_memory_merge_target", row["public_id"])

        for row in conn.execute(
            "SELECT memory_id, event_id FROM memory_sources"
        ):
            if row["memory_id"] not in memories:
                issue("orphan_memory_source_owner", row["memory_id"])
            if raw_ids is not None and row["event_id"] not in raw_ids:
                issue("memory_source_missing_raw", row["event_id"])

        # Counts include the actual processor-version-specific ledger rows,
        # not a guessed one-to-one mapping to Memory sources.
        for row in conn.execute(
            "SELECT event_id, processor, processor_version, status "
            "FROM event_processing"
        ):
            if row["status"] in {"done", "skipped"}:
                counts["finalized_events"] = (
                    1 if counts["finalized_events"] is None
                    else counts["finalized_events"] + 1
                )
                if raw_ids is not None and row["event_id"] not in raw_ids:
                    issue("finalized_event_missing_raw", row["event_id"])
        if counts["finalized_events"] is None:
            counts["finalized_events"] = 0

        for row in conn.execute("PRAGMA foreign_key_check"):
            issue("sqlite_foreign_key_violation", (
                f"{row[0]}:{row[1]}:{row[2]}"
            ))

        # A complete raw-log validation is required before saying healthy.
        if findings:
            status = "degraded"
        elif events is None:
            status = "unverified"
        else:
            status = "healthy"

        return {
            "schema": REPORT_SCHEMA,
            "status": status,
            "as_of": now.isoformat(),
            "counts": counts,
            "findings": dict(sorted(findings.items())),
            "limits": [
                "No automatic repair, retention or lifecycle mutation.",
                "Memory text semantics and Entity authority are not verified.",
                "Raw/source hashes are not externally attested.",
                "Run on a consistent offline snapshot; live WAL is not safe.",
            ],
        }
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-db", required=True, type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--as-of", type=str)
    args = parser.parse_args(argv)
    report = audit_snapshot(
        args.memory_db, args.events, at=args.as_of,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "healthy" else 2


if __name__ == "__main__":
    raise SystemExit(main())
