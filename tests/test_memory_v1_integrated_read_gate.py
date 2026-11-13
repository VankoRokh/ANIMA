"""First Integrated ANIMA M0 gate: real Core and Memory, two Python processes."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from anima.core.assembly import build_core
from scripts.run_memory_v1_integrated_read_gate import (
    ABSENT, EARLY_REPORT, MANIFEST, run_gate,
)


REPO = Path(__file__).resolve().parents[1]


def _phase(name, root):
    return subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_integrated_read_gate",
         "--internal-phase", name, "--root", str(root)],
        cwd=REPO, capture_output=True, text=True, timeout=90,
        check=False,
    )


def test_full_m0_core_memory_event_retrieval_context_fast_with_restart():
    outcome = run_gate()
    assert outcome["status"] == "M0_INTEGRATED_READ_PASS"
    assert outcome["independent_process_reopen"] is True
    assert outcome["memory_count"] >= 1
    assert outcome["raw_event_count"] >= 5
    assert outcome["knowledge_count"] == 0
    assert len(outcome["raw_source_ids"]) == 2
    assert len(outcome["fast_selected_memories"]) >= 1
    assert outcome["fast_items"] <= 6 and outcome["fast_chars"] <= 1200
    assert outcome["index_status"] == "complete"
    assert outcome["absent_marker_results"] == 0
    assert outcome["llm_used"] is False
    assert outcome["actions_executed"] is False


def test_reopen_after_seed_keeps_history_and_link_identity(tmp_path):
    first = _phase("seed", tmp_path)
    assert first.returncode == 0, first.stderr
    created = json.loads(first.stdout)
    assert created["status"] == "M0_SEED_PASS"
    manifest = json.loads((tmp_path / MANIFEST).read_text())
    for event_id in (manifest["early_id"], manifest["late_id"]):
        assert event_id in created["source_memories"]

    second = _phase("verify", tmp_path)
    assert second.returncode == 0, second.stderr
    verified = json.loads(second.stdout)
    assert verified["source_memories"] == created["source_memories"]

    # Source of truth remains the append-only EventLog across actual processes.
    core = build_core(tmp_path, enable_event_retrieval=True)
    assert core.event_retrieval.status()["status"] == "complete"
    assert core.event_retrieval.get(manifest["early_id"])["payload"]["text"] == EARLY_REPORT
    assert core.event_retrieval.search(ABSENT)["results"] == []


def test_changed_authoritative_raw_event_is_not_treated_as_valid_index(tmp_path):
    first = _phase("seed", tmp_path)
    assert first.returncode == 0, first.stderr
    source = tmp_path / "events.jsonl"
    original = source.read_bytes()
    assert b"earlier reading exactly 82 C" in original
    edited = original.replace(
        b"earlier reading exactly 82 C",
        b"earlier reading exactly 92 C",
    )
    assert len(edited) == len(original) and edited != original
    source.write_bytes(edited)

    # The index is derived: silently trusting prior offsets after a source edit
    # would turn a changed report into accepted evidence.
    core = build_core(tmp_path, enable_event_retrieval=True)
    assert core.event_retrieval.status()["status"] == "source_changed"
    with pytest.raises(ValueError, match="rebuild"):
        core.event_retrieval.search("oldheatstamp", require_complete=False)
    with pytest.raises(ValueError, match="rebuild"):
        core.event_retrieval.get(json.loads(
            (tmp_path / MANIFEST).read_text())["early_id"])
    assert core.event_retrieval.status()["status"] != "complete"


def test_missing_manifest_cannot_accidentally_admit_empty_history(tmp_path):
    result = _phase("verify", tmp_path)
    assert result.returncode != 0
    assert not (tmp_path / MANIFEST).exists()
