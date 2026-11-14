"""v0.1 smoke acceptance is not an automatic release tag."""
from scripts.run_release_v01_gate import run_gate


def test_release_v01_integrated_tiny_gate_and_metrics():
    result = run_gate(events=24)
    assert result["test_status"] == "FUNCTIONAL_GATE_PASS"
    assert result["performance_status"] == "MEASURED_NOT_SLO_GATED"
    assert result["identity_reopen"] is True
    assert result["source_links"] == "ALL_ACCOUNTED"
    assert result["event_index_complete"] is True
    assert result["sandbox_goal_status"] == "completed"
    assert result["sandbox_effects"] == 1
    assert result["events"] == 24
    assert result["memories"] >= 1
    assert result["model_calls"] == 0
    assert result["real_godot_used"] is False
    assert result["pi_tested"] is False
    assert result["report_latency_ms"]["p95"] > 0
