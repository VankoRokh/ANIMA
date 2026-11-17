"""H5.4b — read-only compatibility review of an OFFLINE Memory/Raw snapshot.

No schema migration, event replay, backup/restore, or write connections.
The event-processing key (event_id, processor, processor_version) is an
idempotence namespace; changing its version without a projection migration
would make previously finalized events look unprocessed. H4 changed how
new events are associated but did NOT authorize replay of old done/skipped.

This report distinguishes:
  NO_ISSUES_DETECTED: checked conditions have no flags, NOT RC approval;
  REVIEW_REQUIRED: old/unattested claims or other ledger namespaces exist;
  BLOCKED: inconsistent ledger, missing Raw, or existing H5.0 failures.

Historical memory->entity "about" may be legitimate: there is no stored
authorization token in the legacy schema, so it is queued for review, NOT
automatically declared false or deleted. Reports include bounded IDs only,
not Memory texts.

Usage:
    PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_compatibility \
        --memory-db /path/to/OFFLINE-COPY/memory.db \
        --events /path/to/OFFLINE-COPY/events.jsonl
"""

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

from anima.memory.event_processing import (
    PROCESSOR_NAME, PROCESSOR_VERSION, FINAL_STATUSES,
)
from anima.memory.memory_store import SCHEMA_VERSION
from anima.release_v01 import PROTOCOL
from labs.v02_h5_legacy_diagnostic import audit_snapshot

SCHEMA = "anima.v02.h5.compatibility/0.1"
SAMPLE_LIMIT = 8


def analyze_snapshot(memory_db, events_jsonl, *, at=None):
    """Inspect an existing consistent snapshot; never open production writers."""
    memory_db = Path(memory_db)
    events_jsonl = Path(events_jsonl)
    base = audit_snapshot(memory_db, events_jsonl, at=at)
    findings = defaultdict(lambda: {"count": 0, "ids": []})

    def mark(code, item):
        finding = findings[code]
        finding["count"] += 1
        if len(finding["ids"]) < SAMPLE_LIMIT:
            finding["ids"].append(str(item))

    raw_ids = None
    if (
        events_jsonl.is_file()
        and "invalid_raw_eventlog" not in base["findings"]
        and "raw_file_missing" not in base["findings"]
    ):
        with events_jsonl.open("r", encoding="utf-8", newline="\n") as stream:
            raw_ids = {
                json.loads(line)["id"]
                for line in stream if line.strip()
            }

    uri = "file:" + quote(str(memory_db.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")

        expected_tables = {"event_processing", "memory_sources", "relations"}
        available = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not expected_tables <= available:
            for name in sorted(expected_tables - available):
                mark("missing_compatibility_table", name)
            return {
                "schema": SCHEMA, "status": "BLOCKED",
                "base_diagnostic": base["status"],
                "base_findings": base["findings"],
                "compatibility_findings": dict(sorted(findings.items())),
                "processor_ledger": {"name": PROCESSOR_NAME,
                                     "version": PROCESSOR_VERSION},
                "memory_schema": SCHEMA_VERSION,
                "release_protocol": PROTOCOL,
                "limits": ["Schema incomplete; no write or repair attempted."],
            }

        rows = conn.execute(
            "SELECT event_id, processor, processor_version, status, attempts "
            "FROM event_processing ORDER BY event_id, processor, "
            "processor_version"
        ).fetchall()
        sources = defaultdict(set)
        for row in conn.execute(
            "SELECT event_id, memory_id FROM memory_sources"
        ):
            sources[row["event_id"]].add(row["memory_id"])

        counts = Counter()
        versions = defaultdict(set)
        all_ids = defaultdict(set)
        current = {}
        for row in rows:
            event_id = row["event_id"]
            processor = row["processor"]
            version = row["processor_version"]
            counts[(processor, version, row["status"])] += 1
            if processor != PROCESSOR_NAME:
                # Other processors are outside this contract.
                continue
            versions[version].add(event_id)
            all_ids[event_id].add(version)
            if raw_ids is not None and event_id not in raw_ids:
                mark("processor_row_missing_raw", event_id)
            if version != PROCESSOR_VERSION:
                mark("other_memory_processor_version", event_id)
                continue
            current[event_id] = row
            if row["status"] == "done" and not sources[event_id]:
                mark("done_without_source", event_id)
            if row["status"] == "skipped" and sources[event_id]:
                mark("skipped_with_source", event_id)
            if row["status"] not in FINAL_STATUSES and sources[event_id]:
                mark("unfinished_with_committed_source", event_id)

        for event_id, observed in all_ids.items():
            if len(observed) > 1:
                mark("event_processed_under_multiple_versions", event_id)

        # An untracked source may be safely adopted by recovery if Raw exists,
        # but adoption is a migration action and requires separate validation.
        for event_id in sources:
            if event_id not in current:
                mark("source_without_current_processing_row", event_id)

        # The old schema cannot say whether these links came from a trusted
        # explicit review or a formerly auto-generated unverified claim.
        # Treat as queue for authority review, NEVER delete/auto-confirm.
        for row in conn.execute(
            "SELECT public_id FROM relations "
            "WHERE source_kind='memory' AND target_kind='entity' "
            "AND relation_type='about' AND valid_until IS NULL "
            "ORDER BY public_id"
        ):
            mark("legacy_about_authority_unverifiable", row["public_id"])

    blocker_keys = {
        "missing_compatibility_table",
        "processor_row_missing_raw",
        "done_without_source",
        "skipped_with_source",
        "unfinished_with_committed_source",
        "event_processed_under_multiple_versions",
    }
    has_blocker = any(findings.get(k) for k in blocker_keys)
    if base["status"] != "healthy" or has_blocker:
        status = "BLOCKED"
    elif findings:
        status = "REVIEW_REQUIRED"
    else:
        status = "NO_ISSUES_DETECTED"

    return {
        "schema": SCHEMA,
        "status": status,
        "base_diagnostic": base["status"],
        "base_findings": base["findings"],
        "compatibility_findings": dict(sorted(findings.items())),
        "processor_ledger": {
            "name": PROCESSOR_NAME,
            "version": PROCESSOR_VERSION,
            "version_policy": (
                "PIN: ledger idempotence namespace, not the semantic "
                "version of association rules"
            ),
            "rows_by_version_status": [
                {"processor": processor, "version": version,
                 "status": state, "count": count}
                for (processor, version, state), count
                in sorted(counts.items())
            ],
            "distinct_memory_processor_versions": sorted(versions),
        },
        "memory_schema": SCHEMA_VERSION,
        "release_protocol": PROTOCOL,
        "limits": [
            "Status never authorizes replay, migration, or RC by itself.",
            "Old done/skipped entries must remain finalized, no backfill.",
            "Legacy about links need authority review, not automatic deletion.",
            "All files MUST be a consistent OFFLINE snapshot.",
            "SHA-256 inventory and operator approval belong to H5.4a.",
            "No modification, reclassification, or side-effect permitted.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-db", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--output", type=Path,
                        help="Write a NEW JSON report without overwriting.")
    args = parser.parse_args(argv)
    result = analyze_snapshot(
        args.memory_db, args.events, at=args.as_of,
    )
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    print(payload)
    return 0 if result["status"] == "NO_ISSUES_DETECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
