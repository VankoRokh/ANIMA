"""Visible E4 alias lifecycle synthetic recovery/impact probe (lab only)."""
import argparse
import json
from pathlib import Path
import tempfile

from anima.core.event_bus import Event
from labs.exp009.e4_alias_lifecycle_lab import AliasLifecycleLab, LifecycleCut


def _event(n, text, control=None, refs=None, session="s1", when=None):
    return Event(
        "conversation.user",
        {"text": text, **({"alias_control": control} if control else {})},
        source="user", session_id=session, references=refs or [],
        event_id=f"ev_00000000-0000-4000-8000-{n:012d}",
        timestamp=when or f"2026-11-12T10:{n:02d}:00+00:00",
    ).to_dict()


def run_probe():
    with tempfile.TemporaryDirectory(prefix="e4-alias-lifecycle-") as folder:
        path = Path(folder) / "alias_lab.db"
        j = AliasLifecycleLab(path)
        a = _event(1, "«адаптер» — PSU alpha",
                   {"action": "define", "alias_id": "a", "surface": "адаптер",
                    "target_entity_id": "psu:alpha"},
                   [{"kind": "entity", "id": "psu:alpha"}])
        b = _event(2, "«адаптер» — PSU beta",
                   {"action": "define", "alias_id": "b", "surface": "адаптер",
                    "target_entity_id": "psu:beta"},
                   [{"kind": "entity", "id": "psu:beta"}])
        evidence = _event(3, "Pi5 reports a voltage issue")
        for raw in (a, b, evidence):
            j.append_event(raw)
        j.define(alias_id="a", definition_event_id=a["id"], operation_key="define_a")
        j.define(alias_id="b", definition_event_id=b["id"], operation_key="define_b")
        j.create_node(node_id="StoryS", kind="Story",
                      source_event_ids=[a["id"], evidence["id"]],
                      alias_dependencies=[("a",1)], node_dependencies=[],
                      operation_key="s")
        j.create_node(node_id="EpisodeE", kind="Episode",
                      source_event_ids=[evidence["id"]],
                      alias_dependencies=[], node_dependencies=[("StoryS",1)],
                      operation_key="e")
        j.create_node(node_id="StoryU", kind="Story",
                      source_event_ids=[b["id"], evidence["id"]],
                      alias_dependencies=[("b",1)], node_dependencies=[],
                      operation_key="u")
        rev = _event(
            4, "Отзываю ранее указанное определение адаптера A",
            {"action": "revoke", "alias_id": "a",
             "definition_event_id": a["id"]},
            [{"kind": "event", "id": a["id"]}],
            session="s2", when="2026-11-13T10:00:00+00:00",
        )
        j.append_event(rev)
        pre_cut = False
        try:
            j.revoke(alias_id="a", revocation_event_id=rev["id"],
                     expected_head=1, operation_key="revoke_a",
                     cut="before_commit")
        except LifecycleCut:
            pre_cut = True
        before = {
            "alias_a": j.alias("a")["head_state"],
            "story_s": j.node("StoryS")["head_state"],
            "episode_e": j.node("EpisodeE")["head_state"],
            "story_u": j.node("StoryU")["head_state"],
            "invalidations": j.count("invalidations"),
        }
        post_cut = False
        try:
            j.revoke(alias_id="a", revocation_event_id=rev["id"],
                     expected_head=1, operation_key="revoke_a",
                     cut="after_commit")
        except LifecycleCut:
            post_cut = True
        restored = AliasLifecycleLab(path)
        replay = restored.revoke(alias_id="a", revocation_event_id=rev["id"],
                                 expected_head=1, operation_key="revoke_a")
        after = {
            "alias_a": restored.alias("a")["head_state"],
            "alias_b": restored.alias("b")["head_state"],
            "story_s": restored.node("StoryS")["head_state"],
            "episode_e": restored.node("EpisodeE")["head_state"],
            "story_u": restored.node("StoryU")["head_state"],
            "affected_nodes": restored.invalidations("revoke_a"),
            "invalidations": restored.count("invalidations"),
            "replay_status": replay["status"],
        }
        old = restored.node("StoryS", 1)["record"]
        review = restored.reassess_unresolved(
            node_id="StoryS", expected_head=1, operation_key="review_s"
        )
        return {
            "schema": "anima.e4.alias_lifecycle_open_probe/0.1",
            "status": "ISOLATED_DEVELOPMENT_TRANSACTION_TEST_ONLY",
            "before_commit_cut_seen": pre_cut,
            "after_commit_cut_seen": post_cut,
            "before_commit": before,
            "after_reopen": after,
            "immutable_original_story_revision": {
                "revision": old["revision"],
                "source_event_ids": old["source_event_ids"],
                "dependencies": old["dependencies"],
            },
            "reassessment": review,
            "story_s_after_reassessment": restored.node("StoryS")["head_state"],
            "episode_e_after_story_reassessment": restored.node("EpisodeE")["head_state"],
            "raw_events_preserved": restored.count("raw_events") == 4,
            "production_admission": False,
            "core_authority_verified": False,
            "memory_store_unchanged": True,
            "real_power_loss_tested": False,
        }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    content = json.dumps(run_probe(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            file.write(content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
