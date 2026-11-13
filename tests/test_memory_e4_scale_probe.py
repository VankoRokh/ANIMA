"""Small E4 scale smoke: full workload remains opt-in and cross-device."""
import pytest

from labs.exp009.e4_scale_probe import run_one


def test_100_node_selective_oracle_preserves_unaffected_and_receipts():
    outcome = run_one(100)
    assert outcome["status"] == "ISOLATED_SCALE_PASS"
    assert outcome["node_count"] == 100
    assert outcome["affected"] == 8
    assert outcome["unaffected"] == 92
    assert outcome["coarse_avoided_count"] == 92
    assert outcome["replay_status"] == "idempotent_replay"
    assert outcome["production_admission"] is False
    assert outcome["db_bytes_after"] > 0


@pytest.mark.parametrize("size", [2, 10001])
def test_invalid_unbounded_scale_rejected(size):
    with pytest.raises(ValueError):
        run_one(size)
