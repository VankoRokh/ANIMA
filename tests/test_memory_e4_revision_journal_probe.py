"""E4 derived journal raw probe reports simulated effects conservatively."""
from labs.exp009.e4_revision_journal_probe import run_probe


def test_lab_recovery_probe_is_deterministic_and_no_production_claim():
    a = run_probe()
    b = run_probe()
    assert a == b
    assert a["before_commit_cut_injected"]
    assert a["after_commit_cut_injected"]
    assert a["head_after_precommit_cut"] == 1
    assert a["head_after_reopen"] == 2
    assert a["idempotent_replay"] == "idempotent_replay"
    assert a["versions_preserved"] == [1, 2]
    assert a["historical_version1_assignment"] == "shadow_old"
    assert a["current_version2_assignment"] == "derived_split"
    assert a["source_event_digests_preserved"]
    assert a["stale_after_late_event"]
    assert a["preflight_denied_on_stale"]
    assert a["production_memory_modified"] is False
    assert a["core_authority_exercised"] is False
    assert a["physical_power_loss_tested"] is False
