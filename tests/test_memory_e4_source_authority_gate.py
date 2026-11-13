"""Synthetic source-authority tests: NO production authentication or integration."""
import sqlite3

import pytest

from tests.test_memory_e4_alias_lifecycle_lab import (
    _definition, _event, _revocation,
)
from labs.exp009.e4_alias_lifecycle_lab import LifecycleConflict, LifecycleIntegrity, LifecycleCut
from labs.exp009.e4_source_authority_gate import (
    AuthorizedAliasLifecycleLab, AuthorityDenied, LabAdapterRegistration,
    POLICY_REVISION,
)

ALICE_TOKEN = b"A" * 32  # deterministic synthetic fixture ONLY
BOB_TOKEN = b"B" * 32
MALLORY_TOKEN = b"M" * 32


def _adapters():
    return {
        "adapter.alice": LabAdapterRegistration(
            "adapter.alice", "principal.alice", ALICE_TOKEN),
        "adapter.bob": LabAdapterRegistration(
            "adapter.bob", "principal.bob", BOB_TOKEN),
        "adapter.mallory": LabAdapterRegistration(
            "adapter.mallory", "principal.mallory", MALLORY_TOKEN),
    }


def _admit(j, raw, who="alice"):
    return j.admit_event(raw, adapter_ref=f"adapter.{who}",
                         token={"alice": ALICE_TOKEN, "bob": BOB_TOKEN,
                                "mallory": MALLORY_TOKEN}[who])


def _setup(tmp_path):
    path = tmp_path / "guarded_alias_lab.db"
    j = AuthorizedAliasLifecycleLab(path, adapters=_adapters())
    a = _definition(1, "a", "psu:alpha", session="s1")
    b = _definition(2, "b", "psu:beta", session="s1")
    observation = _event(3, "Pi5 has a power issue")
    assert _admit(j, a, "alice")["status"] == "admitted"
    assert _admit(j, b, "bob")["status"] == "admitted"
    j.append_event(observation)
    j.define(alias_id="a", definition_event_id=a["id"],
             operation_key="define_a")
    j.define(alias_id="b", definition_event_id=b["id"],
             operation_key="define_b")
    j.create_node(node_id="story_s", kind="Story",
                  source_event_ids=[a["id"], observation["id"]],
                  alias_dependencies=[("a", 1)], node_dependencies=[],
                  operation_key="seed_s")
    j.create_node(node_id="episode_e", kind="Episode",
                  source_event_ids=[observation["id"]],
                  alias_dependencies=[], node_dependencies=[("story_s", 1)],
                  operation_key="seed_e")
    j.create_node(node_id="story_u", kind="Story",
                  source_event_ids=[b["id"], observation["id"]],
                  alias_dependencies=[("b", 1)], node_dependencies=[],
                  operation_key="seed_u")
    return j, path, a, b, observation


def _call_revoke(j, raw, *, op="revoke_a", cut=None):
    return j.revoke(alias_id="a", revocation_event_id=raw["id"],
                    expected_head=1, operation_key=op, cut=cut)


def _unchanged(j):
    assert j.alias("a")["head_state"] == "active"
    assert j.alias("b")["head_state"] == "active"
    assert j.node("story_s")["head_state"] == "current"
    assert j.node("episode_e")["head_state"] == "current"
    assert j.node("story_u")["head_state"] == "current"
    assert j.count("invalidations") == 0
    assert j.authority_counts()["allowed_revocations"] == 0


def test_same_admitted_principal_cross_session_changes_only_dependents(tmp_path):
    j, path, a, b, _ = _setup(tmp_path)
    r = _revocation(11, "a", a, session="new-session-from-alice")
    admission = _admit(j, r, "alice")
    assert admission["real_identity_verified"] is False
    result = _call_revoke(j, r)
    assert result["status"] == "revoked"
    assert result["production_admission"] is False
    assert result["affected_nodes"] == ["episode_e", "story_s"]
    assert j.node("story_u")["head_state"] == "current"
    assert j.alias("b")["head_state"] == "active"
    assert j.owner("a")["owner_principal_id"] == "principal.alice"
    decision = j.allowed_decision("revoke_a")
    assert decision["admitted_principal_id"] == "principal.alice"
    assert decision["revocation_event_id"] == r["id"]
    assert decision["definition_event_id"] == a["id"]
    assert decision["from_revision"] == 1
    assert decision["policy_revision"] == POLICY_REVISION
    assert j.alias("a", 1)["record"]["state"] == "active"
    assert j.alias("a")["head_state"] == "revoked"


def test_unbound_but_syntactically_valid_user_revocation_denied_and_audited(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    forged = _revocation(12, "a", a, session="spoofed-session", source="user")
    assert j.append_event(forged)["status"] == "appended"
    with pytest.raises(AuthorityDenied, match="UNADMITTED_REVOCATION"):
        _call_revoke(j, forged, op="spoof")
    _unchanged(j)
    assert j.denial_reasons() == ["UNADMITTED_REVOCATION"]
    restored = AuthorizedAliasLifecycleLab(path, adapters=_adapters())
    assert restored.denial_reasons() == ["UNADMITTED_REVOCATION"]
    _unchanged(restored)


def test_foreign_principal_user_label_correct_refs_never_grants_ownership(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    foreign = _revocation(13, "a", a, source="user", session="foreign-s2")
    _admit(j, foreign, "bob")
    with pytest.raises(AuthorityDenied, match="FOREIGN_OWNER"):
        _call_revoke(j, foreign, op="foreign")
    _unchanged(j)
    assert j.denial_reasons() == ["FOREIGN_OWNER"]


def test_mallory_cannot_define_or_revoke_even_with_same_source_string(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    new = _definition(14, "mallory_alias", "psu:intruder")
    j.append_event(new)
    with pytest.raises(AuthorityDenied, match="UNADMITTED_DEFINITION"):
        j.define(alias_id="mallory_alias",
                 definition_event_id=new["id"], operation_key="unadmitted")
    assert j.owner("mallory_alias") is None
    with pytest.raises(KeyError):
        j.alias("mallory_alias")
    assert j.denial_reasons() == ["UNADMITTED_DEFINITION"]
    foreign = _revocation(15, "a", a, source="user", session="imitation")
    _admit(j, foreign, "mallory")
    with pytest.raises(AuthorityDenied, match="FOREIGN_OWNER"):
        _call_revoke(j, foreign, op="imitation")
    _unchanged(j)


@pytest.mark.parametrize("adapter_ref,token,reason", [
    ("adapter.unknown", ALICE_TOKEN, "UNKNOWN_ADAPTER"),
    ("adapter.alice", BOB_TOKEN, "BAD_ADAPTER_TOKEN"),
    ("adapter.alice", b"garbage", "BAD_ADAPTER_TOKEN"),
])
def test_bad_adapter_credentials_do_not_even_admit_raw_event(
        tmp_path, adapter_ref, token, reason):
    j, path, a, _, _ = _setup(tmp_path)
    rev = _revocation(16, "a", a)
    before = j.count("raw_events")
    with pytest.raises(AuthorityDenied, match=reason):
        j.admit_event(rev, adapter_ref=adapter_ref, token=token)
    assert j.count("raw_events") == before
    assert j.authority_counts()["trusted_admissions"] == 2
    _unchanged(j)


def test_admission_replay_and_owner_identity_conflict_fail_closed(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    assert _admit(j, a, "alice")["status"] == "idempotent_replay"
    with pytest.raises(LifecycleConflict, match="cannot be rebound"):
        _admit(j, a, "bob")
    changed = dict(a)
    changed["payload"] = dict(a["payload"], text="tampered body")
    with pytest.raises(LifecycleIntegrity, match="collision"):
        _admit(j, changed, "alice")
    assert j.owner("a")["owner_principal_id"] == "principal.alice"
    _unchanged(j)


def test_before_commit_rollback_covers_authority_and_invalidation(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    rev = _revocation(17, "a", a)
    _admit(j, rev, "alice")
    with pytest.raises(LifecycleCut, match="before commit"):
        _call_revoke(j, rev, op="same_key", cut="before_commit")
    restored = AuthorizedAliasLifecycleLab(path, adapters=_adapters())
    _unchanged(restored)
    assert restored.allowed_decision("same_key") is None
    assert restored.count("operations") == 5  # 2 definitions, 3 seed nodes
    assert _call_revoke(restored, rev, op="same_key")["invalidation_count"] == 2


def test_after_commit_reopen_replay_is_single_authorized_effect(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    rev = _revocation(18, "a", a)
    _admit(j, rev, "alice")
    with pytest.raises(LifecycleCut, match="after commit"):
        _call_revoke(j, rev, op="persisted", cut="after_commit")
    restored = AuthorizedAliasLifecycleLab(path, adapters=_adapters())
    assert restored.alias("a")["head_state"] == "revoked"
    assert restored.allowed_decision("persisted")["admitted_principal_id"] == "principal.alice"
    before = restored.authority_counts()
    result = _call_revoke(restored, rev, op="persisted")
    assert result["status"] == "idempotent_replay"
    assert result["affected_nodes"] == ["episode_e", "story_s"]
    assert restored.authority_counts() == before
    assert restored.count("invalidations") == 2
    assert restored.count("alias_versions") == 3


def test_authority_decision_rolls_back_when_invalidation_budget_is_exceeded(tmp_path):
    j, path, a, _, obs = _setup(tmp_path)
    for n in range(128):
        j.create_node(
            node_id=f"overflow_{n:03d}", kind="Story",
            source_event_ids=[obs["id"]],
            alias_dependencies=[("a", 1)], node_dependencies=[],
            operation_key=f"overflow_seed_{n:03d}",
        )
    rev = _revocation(19, "a", a)
    _admit(j, rev, "alice")
    with pytest.raises(LifecycleConflict, match="budget"):
        _call_revoke(j, rev, op="overflow")
    assert j.allowed_decision("overflow") is None
    assert j.alias("a")["head_state"] == "active"
    assert j.node("story_s")["head_state"] == "current"
    assert j.node("overflow_127")["head_state"] == "current"
    assert j.count("invalidations") == 0
    assert j.authority_counts()["denied_authority"] == 0


def test_outdated_policy_denied_without_side_effects(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    r = _revocation(20, "a", a)
    _admit(j, r, "alice")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE alias_owners SET policy_revision=999 WHERE alias_id='a'")
    with pytest.raises(AuthorityDenied, match="OUTDATED_AUTHORITY_POLICY"):
        _call_revoke(j, r, op="old_policy")
    _unchanged(j)
    assert j.denial_reasons() == ["OUTDATED_AUTHORITY_POLICY"]


def test_forged_admission_digest_fails_integrity(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    r = _revocation(21, "a", a)
    _admit(j, r, "alice")
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE trusted_admissions SET source_sha256=? WHERE event_id=?",
            ("0" * 64, r["id"]),
        )
    with pytest.raises(LifecycleIntegrity, match="digest"):
        _call_revoke(j, r, op="corrupt_admission")
    _unchanged(j)


def test_trusted_registration_drift_does_not_grant_old_owner_alias(tmp_path):
    j, path, a, _, _ = _setup(tmp_path)
    shifted = _adapters()
    shifted["adapter.alice"] = LabAdapterRegistration(
        "adapter.alice", "principal.mallory", ALICE_TOKEN)
    restarted = AuthorizedAliasLifecycleLab(path, adapters=shifted)
    r = _revocation(22, "a", a)
    restarted.admit_event(r, adapter_ref="adapter.alice", token=ALICE_TOKEN)
    with pytest.raises(AuthorityDenied, match="FOREIGN_OWNER"):
        _call_revoke(restarted, r, op="drift")
    _unchanged(restarted)
