"""Small deterministic smoke for the separate C3 PC scaling workload."""

import pytest

from labs.exp009.event_retrieval_c3 import run_c3


def test_c3_small_workload_reaches_newly_appended_event(tmp_path):
    result = run_c3(tmp_path / "work", events=64, probe_count=16)
    assert result["type"] == "exp009.c3.event_retrieval/0.1"
    assert result["events"] == 64
    assert result["indexed_after_late"] == 65
    assert result["index_batches"] >= 1
    assert result["get"]["samples"] == 16
    assert result["fts_exact"]["samples"] == 16
    assert result["source_bytes"] > 0
    assert result["index_bytes"] > 0
    assert result["caveat"]
    assert result["get"]["p95_ms"] >= 0


def test_c3_generator_is_replayable_and_bounded(tmp_path):
    first = run_c3(tmp_path / "a", events=20, probe_count=8)
    second = run_c3(tmp_path / "b", events=20, probe_count=8)
    assert first["source_sha256"] == second["source_sha256"]
    for value in (0, 100001, True):
        with pytest.raises(ValueError, match="Events count"):
            run_c3(tmp_path / "bad", events=value)
