"""EXP-009 E2: ambiguous suggestions do not become facts or merges."""

import json

from labs.exp009.memory_encoding_e2 import run_e2


def test_e2_reports_true_and_false_entity_candidates_without_merge(tmp_path):
    result = run_e2(tmp_path / "run", report_path=tmp_path / "e2.json")
    assert result["type"] == "exp009.shadow-encoding.e2/0.1"
    assert result["memory_unchanged"]
    assert result["episode_count"] == 7
    assert result["gold_related"] == [["decision", "baseline"]]
    assert result["suggested_pairs"] == [
        ["decision", "baseline"],
        ["distractor", "baseline"],
        ["distractor", "decision"],
    ]
    assert result["hits"] == [["decision", "baseline"]]
    assert result["false_candidates"] == [
        ["distractor", "baseline"],
        ["distractor", "decision"],
    ]
    assert result["missed"] == []
    assert result["candidate_precision"] == 1 / 3
    assert result["candidate_recall"] == 1.0
    assert json.loads((tmp_path / "e2.json").read_text()) == result


def test_e2_possible_links_are_unverified_and_replay_safe(tmp_path):
    result = run_e2(tmp_path / "run")
    decisions = result["decisions"]
    for item in decisions.values():
        row = item["decision"]
        assert row["action"] == "new_episode"
        assert len(row["source_event_ids"]) == 1
        for possible in row["possible_related"]:
            assert possible["status"] == "unverified"
            assert possible["reason"] == "shared_entity_without_raw_overlap"
            assert possible["source_event_ids"]
            assert possible["shared_entity_ids"]
    assert len(decisions["decision"]["decision"]["possible_related"]) == 1
    assert len(decisions["distractor"]["decision"]["possible_related"]) == 2
    # Hard boundaries must not even produce weak suggestions.
    for name in (
        "baseline", "different_entity", "different_session",
        "time_boundary", "no_entity_paraphrase",
    ):
        assert decisions[name]["decision"]["possible_related"] == []


def test_e2_does_not_mutate_parent_episode_sources_on_weak_link(tmp_path):
    result = run_e2(tmp_path / "run")
    baseline = result["decisions"]["baseline"]["decision"]
    decision = result["decisions"]["decision"]["decision"]
    distractor = result["decisions"]["distractor"]["decision"]
    assert baseline["episode_id"] != decision["episode_id"]
    assert decision["episode_id"] != distractor["episode_id"]
    assert baseline["source_event_ids"] == [
        result["decisions"]["baseline"]["event_id"]
    ]
    assert decision["source_event_ids"] == [
        result["decisions"]["decision"]["event_id"]
    ]


def test_e2_replay_cannot_add_second_provisional_edge(tmp_path):
    from anima.memory.memory_store import MemoryStore
    from anima.memory.link_store import LinkStore
    from anima.memory.shadow_encoding import ShadowEpisodeEncoder
    from labs.exp009.memory_encoding_e2 import CASES, make_event, ENT_CPU_A

    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    links.create_entity(
        entity_type="technology", canonical_name="CPU A",
        public_id=ENT_CPU_A,
    )
    encoder = ShadowEpisodeEncoder(link_store=links)
    encoder.accept(make_event(0, CASES[0]))
    original = encoder.accept(make_event(1, CASES[1]))
    replay = encoder.accept(make_event(1, CASES[1]))
    assert replay["action"] == "replay"
    assert replay["possible_related"] == original["possible_related"]
    assert len(encoder.episodes()) == 2
    assert store.list_memories() == []


def test_e2_candidate_cap_and_stable_recent_order(tmp_path):
    from anima.core.event_bus import Event
    from anima.memory.memory_store import MemoryStore
    from anima.memory.link_store import LinkStore
    from anima.memory.shadow_encoding import ShadowEpisodeEncoder
    from labs.exp009.memory_encoding_e2 import ENT_CPU_A, S1, event_id

    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    links.create_entity(
        entity_type="technology", canonical_name="CPU A",
        public_id=ENT_CPU_A,
    )
    encoder = ShadowEpisodeEncoder(link_store=links)
    labels = ("alpha", "bravo", "charlie", "delta", "echo",
              "foxtrot", "golf", "hotel")
    for i, label in enumerate(labels):
        item = Event(
            "conversation.user", {"text": label}, source="user",
            timestamp=f"2026-11-12T12:0{i}:00+00:00",
            session_id=S1, event_id=event_id(i + 310),
            references=[{"kind": "entity", "id": ENT_CPU_A}],
        )
        outcome = encoder.accept(item)
        assert outcome["action"] == "new_episode"
    assert len(outcome["possible_related"]) == 5
    assert [x["episode_id"] for x in outcome["possible_related"]] == [
        "shadow_ep_" + event_id(i + 310) for i in range(6, 1, -1)
    ]
    assert store.list_memories() == []
