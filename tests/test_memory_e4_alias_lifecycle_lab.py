"""Negative E4 alias lifecycle tests; isolated SQLite, no production Memory."""
from copy import deepcopy
import sqlite3

import pytest

from anima.core.event_bus import Event
from labs.exp009.e4_alias_lifecycle_lab import (
    AliasLifecycleLab, LifecycleConflict, LifecycleIntegrity, LifecycleCut,
)


def _event(n, text, *, control=None, refs=None, session="s1",
           source="user", timestamp=None, event_type="conversation.user"):
    payload = {"text": text}
    if control is not None:
        payload["alias_control"] = control
    return Event(
        event_type, payload,
        source=source, session_id=session,
        references=refs if refs is not None else [],
        event_id=f"ev_00000000-0000-4000-8000-{n:012d}",
        timestamp=timestamp or f"2026-11-12T10:{n%60:02d}:00+00:00",
    ).to_dict()


def _definition(n, alias_id, target, surface="адаптер", session="s1",
                source="user"):
    return _event(
        n, f"Под «{surface}» я имел в виду {target}.",
        session=session, source=source,
        control={"action": "define", "alias_id": alias_id,
                 "surface": surface, "target_entity_id": target},
        refs=[{"kind": "entity", "id": target}],
    )


def _revocation(n, alias_id, definition, *, session="s2", source="user",
                refs=None, control=None, timestamp="2026-11-13T10:00:00+00:00"):
    return _event(
        n, "Отзываю прежнее определение алиаса, не используй его.",
        source=source, session=session, timestamp=timestamp,
        control=control if control is not None else {
            "action": "revoke", "alias_id": alias_id,
            "definition_event_id": definition["id"],
        },
        refs=refs if refs is not None else [
            {"kind": "event", "id": definition["id"]}
        ],
    )


def _setup(tmp_path):
    path = tmp_path / "isolated_alias_lifecycle.db"
    j = AliasLifecycleLab(path)
    # SAME surface / distinct targets — both candidate definitions survive.
    a = _definition(1, "a", "psu:alpha")
    b = _definition(2, "b", "psu:beta")
    observation = _event(3, "Pi5 испытывает проблемы с питанием.")
    for raw in (a, b, observation):
        assert j.append_event(raw)["status"] == "appended"
    j.define(alias_id="a", definition_event_id=a["id"], operation_key="define_a")
    j.define(alias_id="b", definition_event_id=b["id"], operation_key="define_b")
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


def _revoke(j, a, *, cut=None, operation_key="revoke_a"):
    rev = _revocation(4, "a", a)
    j.append_event(rev)
    return j.revoke(alias_id="a", revocation_event_id=rev["id"],
                    expected_head=1, operation_key=operation_key, cut=cut)


def test_selective_transitive_invalidation_not_entire_source_stream(tmp_path):
    j, _, a, b, observation = _setup(tmp_path)
    r = _revoke(j, a)
    assert r["status"] == "revoked"
    assert r["affected_nodes"] == ["episode_e", "story_s"]
    assert r["invalidation_count"] == 2
    assert j.node("story_s")["head_state"] == "stale"
    assert j.node("episode_e")["head_state"] == "stale"
    assert j.node("story_u")["head_state"] == "current"
    assert j.node("story_u")["eligible_for_lab_preflight"]
    assert j.alias("a")["head_state"] == "revoked"
    assert j.alias("b")["head_state"] == "active"
    assert j.invalidations("revoke_a") == ["episode_e", "story_s"]


def test_immutable_alias_versions_and_competing_definition_survives(tmp_path):
    j, _, a, b, observation = _setup(tmp_path)
    _revoke(j, a)
    old = j.alias("a", 1)
    current = j.alias("a")
    assert old["record"]["target_entity_id"] == "psu:alpha"
    assert old["record"]["state"] == "active"
    assert old["is_head"] is False
    assert current["record"]["state"] == "revoked"
    assert current["record"]["previous_revision"] == 1
    assert j.alias("b")["record"]["target_entity_id"] == "psu:beta"
    assert j.alias("b")["head_state"] == "active"
    assert j.count("raw_events") == 4
    assert j.count("alias_versions") == 3
    assert j.count("derived_versions") == 3


def test_unrelated_later_event_does_not_coarsely_invalidate_any_view(tmp_path):
    j, _, a, b, _ = _setup(tmp_path)
    late = _event(9, "Потепление сегодня, к питанию Pi5 не относится.",
                  session="s3", timestamp="2026-11-14T10:00:00+00:00")
    j.append_event(late)
    assert all(j.node(x)["head_state"] == "current"
               for x in ("story_s", "episode_e", "story_u"))


@pytest.mark.parametrize("bad_refs", [
    [], [{"kind":"event","id":"ev_00000000-0000-4000-8000-000000099999"}],
    [{"kind":"event","id":"placeholder"}],
])
def test_wrong_missing_or_foreign_definition_reference_fails_closed(tmp_path, bad_refs):
    j, _, a, _, _ = _setup(tmp_path)
    rev = _revocation(4, "a", a, refs=bad_refs)
    j.append_event(rev)
    with pytest.raises(LifecycleConflict, match="Revocation source"):
        j.revoke(alias_id="a", revocation_event_id=rev["id"],
                 expected_head=1, operation_key="revoke_a")
    assert j.alias("a")["head_state"] == "active"
    assert j.count("invalidations") == 0


def test_duplicate_and_extra_typed_event_refs_fail_closed(tmp_path):
    j, _, a, _, _ = _setup(tmp_path)
    dup = [{"kind":"event","id":a["id"]}]*2
    rev = _revocation(4, "a", a, refs=dup)
    j.append_event(rev)
    with pytest.raises(LifecycleConflict):
        j.revoke(alias_id="a", revocation_event_id=rev["id"],
                 expected_head=1, operation_key="revoke_a")
    assert j.node("story_s")["head_state"] == "current"


@pytest.mark.parametrize("variant", ["relay","wrong_alias","wrong_source","old_time"])
def test_foreign_or_stale_revocation_rejected(variant, tmp_path):
    j, _, a, _, _ = _setup(tmp_path)
    kwargs = {}
    if variant == "relay":
        kwargs["source"] = "unknown.relay"
    if variant == "wrong_alias":
        kwargs["control"] = {"action":"revoke","alias_id":"b",
                             "definition_event_id":a["id"]}
    if variant == "wrong_source":
        kwargs["control"] = {"action":"revoke","alias_id":"a",
                             "definition_event_id":"ev_00000000-0000-4000-8000-000000099999"}
    if variant == "old_time":
        kwargs["timestamp"] = "2026-11-11T10:00:00+00:00"
    rev = _revocation(4, "a", a, **kwargs)
    j.append_event(rev)
    with pytest.raises(LifecycleConflict):
        j.revoke(alias_id="a", revocation_event_id=rev["id"],
                 expected_head=1, operation_key="revoke_a")
    assert j.alias("a")["head_state"] == "active"


def test_crash_before_commit_rolls_back_alias_and_derived_invalidation(tmp_path):
    j, path, a, b, obs = _setup(tmp_path)
    with pytest.raises(LifecycleCut, match="before commit"):
        _revoke(j, a, cut="before_commit")
    restored = AliasLifecycleLab(path)
    assert restored.alias("a")["head_revision"] == 1
    assert restored.alias("a")["head_state"] == "active"
    assert restored.node("story_s")["head_state"] == "current"
    assert restored.node("episode_e")["head_state"] == "current"
    assert restored.count("invalidations") == 0
    assert restored.count("alias_versions") == 2
    assert _revoke(restored, a)["invalidation_count"] == 2


def test_crash_after_commit_reopen_replay_is_idempotent(tmp_path):
    j, path, a, b, obs = _setup(tmp_path)
    with pytest.raises(LifecycleCut, match="after commit"):
        _revoke(j, a, cut="after_commit")
    restored = AliasLifecycleLab(path)
    assert restored.alias("a")["head_revision"] == 2
    assert restored.node("episode_e")["head_state"] == "stale"
    count = restored.count("invalidations")
    receipt = _revoke(restored, a)
    assert receipt["status"] == "idempotent_replay"
    assert receipt["affected_nodes"] == ["episode_e", "story_s"]
    assert restored.count("invalidations") == count
    assert restored.count("alias_versions") == 3


def test_operation_collision_and_stale_head_do_not_change_state(tmp_path):
    j, _, a, b, obs = _setup(tmp_path)
    _revoke(j, a)
    rev = _revocation(11, "a", a, timestamp="2026-11-14T10:00:00+00:00")
    j.append_event(rev)
    with pytest.raises(LifecycleIntegrity, match="collision"):
        j.revoke(alias_id="a", revocation_event_id=rev["id"],
                 expected_head=1, operation_key="revoke_a")
    with pytest.raises(LifecycleConflict, match="already changed"):
        j.revoke(alias_id="a", revocation_event_id=rev["id"],
                 expected_head=1, operation_key="new_revoke")
    assert j.count("invalidations") == 2


def test_manual_reassessment_preserves_history_and_stale_downstream(tmp_path):
    j, path, a, b, obs = _setup(tmp_path)
    _revoke(j, a)
    new = j.reassess_unresolved(node_id="story_s", expected_head=1,
                                operation_key="review_s")
    assert new["status"] == "unresolved"
    assert new["revision"] == 2
    restored = AliasLifecycleLab(path)
    old = restored.node("story_s", 1)
    assert old["record"]["state"] == "current"
    assert old["record"]["dependencies"] == [["alias", "a", 1]]
    now = restored.node("story_s")
    assert now["record"]["state"] == "unresolved"
    assert now["record"]["dependencies"] == []
    assert not now["eligible_for_lab_preflight"]
    assert restored.node("episode_e")["head_state"] == "stale"
    assert restored.node("story_u")["head_state"] == "current"
    assert restored.reassess_unresolved(node_id="story_s", expected_head=1,
                                        operation_key="review_s")["status"] == "idempotent_replay"
    with pytest.raises(LifecycleConflict):
        restored.reassess_unresolved(node_id="story_s", expected_head=1,
                                     operation_key="another_review")


def test_source_event_replay_altered_body_or_direct_sql_tampering_detected(tmp_path):
    j, path, a, b, obs = _setup(tmp_path)
    assert j.append_event(a)["status"] == "idempotent_replay"
    changed = deepcopy(a)
    changed["payload"]["text"] = "Changed source"
    with pytest.raises(LifecycleIntegrity, match="altered"):
        j.append_event(changed)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE raw_events SET body='{}' WHERE event_id=?", (a["id"],))
    with pytest.raises(LifecycleIntegrity, match="Raw Event"):
        AliasLifecycleLab(path).alias("a")


def test_tampered_derived_revision_or_dependency_edge_detected(tmp_path):
    j, path, a, b, obs = _setup(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM edges WHERE node_id='story_s'")
    with pytest.raises(LifecycleIntegrity, match="dependency links"):
        AliasLifecycleLab(path).node("story_s")
    j2, path2, a2, b2, obs2 = _setup(tmp_path / "another")
    with sqlite3.connect(path2) as db:
        db.execute("UPDATE derived_versions SET body='{}' WHERE node_id='story_s'")
    with pytest.raises(LifecycleIntegrity, match="Derived revision"):
        AliasLifecycleLab(path2).node("story_s")


def test_stale_alias_or_node_dependency_prevents_new_derived_claim(tmp_path):
    j, _, a, b, obs = _setup(tmp_path)
    _revoke(j, a)
    with pytest.raises(LifecycleConflict, match="Stale alias"):
        j.create_node(node_id="story_new", kind="Story",
                      source_event_ids=[obs["id"]], alias_dependencies=[("a",1)],
                      node_dependencies=[], operation_key="late_s")
    with pytest.raises(LifecycleConflict, match="stale upstream"):
        j.create_node(node_id="episode_new", kind="Episode",
                      source_event_ids=[obs["id"]], alias_dependencies=[],
                      node_dependencies=[("story_s",1)], operation_key="late_e")
    assert j.count("derived_versions") == 3


def test_self_dependency_and_nonexistent_upstream_rejected(tmp_path):
    j, _, a, b, obs = _setup(tmp_path)
    for upstream in ["unknown", "story_self"]:
        with pytest.raises(LifecycleConflict, match="Missing or stale"):
            j.create_node(node_id="story_self", kind="Story",
                          source_event_ids=[obs["id"]], alias_dependencies=[],
                          node_dependencies=[(upstream,1)], operation_key=f"bad_{upstream}")


def test_bounded_invalidation_rolls_back_whole_transaction(tmp_path):
    j, _, a, b, obs = _setup(tmp_path)
    for n in range(130):
        j.create_node(node_id=f"independent_{n}", kind="Story",
                      source_event_ids=[obs["id"]],
                      alias_dependencies=[("a",1)], node_dependencies=[],
                      operation_key=f"seed_extra_{n}")
    assert j.count("derived_versions") == 133
    with pytest.raises(LifecycleConflict, match="budget"):
        _revoke(j, a)
    assert j.alias("a")["head_state"] == "active"
    assert j.count("invalidations") == 0
    assert j.node("story_s")["head_state"] == "current"
    assert j.node("independent_129")["head_state"] == "current"


def test_definition_cannot_overwrite_existing_alias_even_same_surface(tmp_path):
    j, _, a, b, obs = _setup(tmp_path)
    new_definition = _definition(15, "a", "psu:new", session="s2")
    j.append_event(new_definition)
    with pytest.raises(LifecycleConflict, match="already exists"):
        j.define(alias_id="a", definition_event_id=new_definition["id"],
                 operation_key="rewrite_a")
    assert j.alias("a")["record"]["target_entity_id"] == "psu:alpha"
    assert j.alias("b")["record"]["target_entity_id"] == "psu:beta"


def test_untrusted_definition_rejected_and_idempotent_seeding(tmp_path):
    j, _, a, b, obs = _setup(tmp_path)
    untrusted = _definition(20, "evil", "psu:evil", source="unknown.relay")
    j.append_event(untrusted)
    with pytest.raises(LifecycleConflict, match="Unverified"):
        j.define(alias_id="evil", definition_event_id=untrusted["id"],
                 operation_key="evil")
    receipt = j.define(alias_id="a", definition_event_id=a["id"],
                       operation_key="define_a")
    assert receipt["status"] == "idempotent_replay"
    again = j.create_node(node_id="story_s", kind="Story",
                          source_event_ids=[a["id"], obs["id"]],
                          alias_dependencies=[("a",1)], node_dependencies=[],
                          operation_key="seed_s")
    assert again["status"] == "idempotent_replay"


def test_open_lifecycle_probe_records_exact_scope_and_replay():
    from labs.exp009.e4_alias_lifecycle_probe import run_probe
    outcome = run_probe()
    assert outcome["before_commit_cut_seen"]
    assert outcome["after_commit_cut_seen"]
    assert outcome["before_commit"] == {
        "alias_a": "active", "story_s": "current",
        "episode_e": "current", "story_u": "current",
        "invalidations": 0,
    }
    after = outcome["after_reopen"]
    assert after["affected_nodes"] == ["EpisodeE", "StoryS"]
    assert after["story_u"] == "current"
    assert after["alias_b"] == "active"
    assert after["invalidations"] == 2
    assert after["replay_status"] == "idempotent_replay"
    assert outcome["story_s_after_reassessment"] == "unresolved"
    assert outcome["episode_e_after_story_reassessment"] == "stale"
    assert outcome["raw_events_preserved"]
    assert outcome["core_authority_verified"] is False
    assert outcome["production_admission"] is False
    assert outcome["memory_store_unchanged"] is True
