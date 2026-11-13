"""M3: source-backed untrusted Goal suggestion never becomes executable authority."""
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from anima.cognition.proposals import CognitiveProposal, ProposalKind, ProposalValidator
from labs.virtual_anima_lab.python.m3_goal_preview import (
    FixtureSuggestionBackend, MemoryGoalPreviewGate, REQUEST, REVOKE,
    PreviewWindow, SCHEMA, TEMPLATE,
)
from scripts.run_memory_v1_goal_proposal_gate import (
    CASES, _candidate, _current_id, _gate, _no_effects, _prepare,
    _sync, gate as run_gate, seed, verify,
)

ROOT = Path(__file__).resolve().parents[1]


def test_m3_three_scenarios_and_independent_interpreter_replay():
    report = run_gate()
    assert report["status"] == "M3_GOAL_PREVIEW_PASS"
    assert report["production_code_changed"] is False
    assert [row["case"] for row in report["cases"]] == list(CASES)
    assert [row["disposition"] for row in report["cases"]] == [
        "REVIEW_REQUIRED", "REJECTED", "CONFLICT_REVIEW",
    ]
    for row in report["cases"]:
        assert row["core_goal_count"] == 0
        assert row["task_count"] == 0
        assert row["action_count"] == 0
        assert row["knowledge_count"] == 0
        assert row["review_is_approval"] is False
        assert row["source_backed"] is True
        assert row["current_event_self_cited"] is False


@pytest.mark.parametrize("case", CASES)
def test_m3_seed_then_reopen_same_sources_without_any_goals(tmp_path, case):
    folder = tmp_path / case
    start = seed(folder, case)
    assert start["status"] == "M3_SEED_PASS"
    confirmed = verify(folder, case)
    assert confirmed["status"] == "M3_CASE_PASS"
    assert confirmed["disposition"] == start["disposition"]
    assert confirmed["core_goal_count"] == 0
    saved = json.loads((folder / "manifest.json").read_text())
    assert saved["schema"] == SCHEMA
    assert saved["current_event_id"] not in saved["history_ids"]


def test_m3_rejects_unissued_and_stale_windows(tmp_path):
    core, gate, view, _ = _prepare(tmp_path, "request", current_id=_current_id())
    draft = _candidate(view)
    assert gate.review(view, draft).disposition == "REVIEW_REQUIRED"
    forged = replace(view, truncated=False)
    assert gate.review(forged, draft).reason == "unissued_or_stale_preview_window"
    latest = gate.capture(query=view.query, current_event_id=view.current_event_id)
    assert gate.review(view, draft).reason == "unissued_or_stale_preview_window"
    assert gate.review(latest, _candidate(latest)).disposition == "REVIEW_REQUIRED"
    _no_effects(core)


def test_m3_rejects_memory_changed_after_capture(tmp_path):
    core, gate, view, _ = _prepare(tmp_path, "request", current_id=_current_id())
    draft = _candidate(view)
    mid = view.sources[0].memory_id
    core.memory_store.update_memory(mid, content="rewritten unrelated summary")
    result = gate.review(view, draft)
    assert (result.disposition, result.reason) == (
        "REJECTED", "memory_changed_after_capture"
    )
    _no_effects(core)


def test_m3_rejects_partial_index_and_detects_raw_mutation(tmp_path):
    core, gate, view, _ = _prepare(tmp_path, "request", current_id=_current_id())
    draft = _candidate(view)
    core.runtime.user_input("M3_UNRELATED_TEST_EVENT: new unsynced log entry")
    assert core.event_retrieval.status()["status"] == "partial"
    result = gate.review(view, draft)
    assert result.reason == "index_incomplete_or_changed"
    _sync(core.event_retrieval)
    path = core.event_log.log_file
    source = path.read_bytes()
    needle = REQUEST.encode("ascii")
    assert needle in source
    altered = source.replace(needle, b"M3_REQUESX_DOOR_CLOSE", 1)
    assert len(altered) == len(source)
    path.write_bytes(altered)
    assert core.event_retrieval.status()["status"] == "source_changed"
    result = gate.review(view, draft)
    assert result.reason == "index_incomplete_or_changed"
    _no_effects(core)


def test_m3_rejects_conflict_even_if_backend_selects_only_favorable_source(tmp_path):
    core, gate, view, history = _prepare(tmp_path, "conflict", current_id=_current_id())
    assert set(history).issubset({s.event_id for s in view.sources})
    assert any(REQUEST in s.text for s in view.sources)
    assert any(REVOKE in s.text for s in view.sources)
    draft = _candidate(view)
    assert draft is not None
    review = gate.review(view, draft)
    assert (review.disposition, review.reason) == (
        "CONFLICT_REVIEW", "visible_revocation_requires_independent_review"
    )
    _no_effects(core)


def test_m3_stage6_production_validator_remains_respond_only():
    validator = ProposalValidator()
    for kind in (
        ProposalKind.PROPOSE_ACTION,
        ProposalKind.PROPOSE_TASK,
        ProposalKind.REQUEST_CONTEXT,
    ):
        check = validator.validate(CognitiveProposal(kind, {"candidate": TEMPLATE}))
        assert check.accepted is False
        assert check.reason == "proposal_kind_not_enabled"


def test_m3_cannot_exploit_unknown_privileged_keys(tmp_path):
    core, gate, view, _ = _prepare(tmp_path, "request", current_id=_current_id())
    draft = _candidate(view)
    assert draft is not None
    for field in ("tool", "role", "priority", "goal_id", "action", "approval"):
        review = gate.review(view, {**draft, field: "operator"})
        assert (review.disposition, review.reason) == (
            "REJECTED", "invalid_or_privileged_draft_shape"
        )
    assert gate.review(view, {**draft, "template": "world.door.force_open"}).reason == (
        "unsupported_template"
    )
    _no_effects(core)


def test_m3_refuses_nonempty_seed_directory_and_preserves_data(tmp_path):
    folder = tmp_path / "existing"
    folder.mkdir()
    sentinel = folder / "sentinel.txt"
    sentinel.write_text("PRIVATE DATA", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh empty"):
        seed(folder, "request")
    assert sentinel.read_text(encoding="utf-8") == "PRIVATE DATA"


def test_m3_cli_never_overwrites_existing_report(tmp_path):
    output = tmp_path / "old.json"
    output.write_text("KEEP", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_goal_proposal_gate",
         "--report", str(output)],
        cwd=ROOT, text=True, capture_output=True, timeout=30,
    )
    assert run.returncode != 0
    assert "report must be new" in run.stderr
    assert output.read_text(encoding="utf-8") == "KEEP"
