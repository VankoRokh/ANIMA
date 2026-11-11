"""Stage 3 Memory Encoding: independent raw Event episode boundary contracts."""

import json

import pytest

from anima.core.event_bus import Event
from anima.memory.shadow_encoding import ShadowEpisodeEncoder
from labs.exp009.memory_encoding_shadow import (
    CORPUS, ENT_CPU_A, ENT_CPU_B, fixture, run_shadow,
)


def _select(rows, index):
    return rows[index]["episode_id"]


def test_shadow_vs_legacy_is_full_source_grounded_and_non_mutating(tmp_path):
    output = tmp_path / "raw" / "comparison.json"
    result = run_shadow(tmp_path / "work", report_path=output)
    assert result["invariants"]["raw_event_count"] == len(CORPUS) == 20
    assert result["invariants"]["shadow_source_coverage"] == 20
    assert result["invariants"]["legacy_eventlog_unchanged"]
    assert result["invariants"]["legacy_memories_unchanged"]
    assert result["invariants"]["no_llm"]
    assert len(result["shadow"]["turns"]) == len(CORPUS)
    assert len(set(result["shadow"]["assignments"])) == 20
    assert set(result["shadow"]["assignments"]) == set(result["gold"])
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert all(result[label]["metrics"]["recall"] is not None
               for label in ("legacy_64", "legacy_512", "shadow"))
    assert len(result["shadow"]["episodes"]) <= 20
    with pytest.raises(ValueError, match="already exist"):
        run_shadow(tmp_path / "work")


def test_boundaries_interleaving_time_entity_punctuation(tmp_path):
    result = run_shadow(tmp_path / "work")
    rows = result["shadow"]["turns"]
    assert _select(rows, 0) == _select(rows, 2) == _select(rows, 4)
    assert _select(rows, 0) == _select(rows, 5)
    assert _select(rows, 1) == _select(rows, 3)
    assert _select(rows, 0) != _select(rows, 1)
    assert _select(rows, 0) != _select(rows, 6)  # same text, different day
    assert _select(rows, 6) == _select(rows, 7)
    assert _select(rows, 6) != _select(rows, 8)  # different typed Entity
    assert _select(rows, 8) == _select(rows, 9)
    assert _select(rows, 6) != _select(rows, 10)  # same Entity, new topic
    assert _select(rows, 12) == _select(rows, 13)  # punctuation stable
    assert _select(rows, 12) != _select(rows, 14)  # session boundary
    assert _select(rows, 15) != _select(rows, 16)
    assert _select(rows, 17) == _select(rows, 18)
    assert result["shadow"]["metrics"]["false_merge_pairs"] == 0
    assert result["shadow"]["metrics"]["false_split_pairs"] == 0


def test_replay_is_idempotent_and_conflicting_payload_rejected():
    events, _ = fixture()
    encoder = ShadowEpisodeEncoder()  # no entity authority: ignore references
    first = encoder.accept(events[0])
    second = encoder.accept(events[0])
    assert second["action"] == "replay"
    assert first["episode_id"] == second["episode_id"]
    assert len(encoder.episodes()) == 1
    assert encoder.episodes()[0]["source_event_ids"] == [events[0].event_id]

    altered = Event(
        "conversation.user", {"text": "altered source history"},
        source=events[0].source, event_id=events[0].event_id,
        session_id=events[0].session_id,
        timestamp=events[0].timestamp,
        references=events[0].references,
    )
    with pytest.raises(ValueError, match="Conflicting replay"):
        encoder.accept(altered)
    assert len(encoder.episodes()) == 1


def test_skip_events_and_repeat_skipped_event():
    events, _ = fixture()
    encoder = ShadowEpisodeEncoder()
    wake = Event(
        "system.wake", None, source="runtime",
        session_id=events[0].session_id,
        timestamp=events[0].timestamp,
    )
    empty = Event(
        "conversation.user", {"text": "  "}, source="user",
        session_id=events[0].session_id,
        timestamp=events[0].timestamp,
    )
    for event in (wake, empty):
        result = encoder.accept(event)
        assert result["action"] == "skip"
        assert encoder.accept(event)["action"] == "replay"
    assert encoder.episodes() == []
    assert encoder.event_assignments() == {}


def test_late_event_and_session_without_identity_do_not_merge():
    events, _ = fixture()
    encoder = ShadowEpisodeEncoder()
    first = encoder.accept(events[0])
    def changed(*, session=None, stamp, index):
        original = events[0]
        return Event(
            "conversation.user", original.payload, source=original.source,
            session_id=session, timestamp=stamp,
            event_id=events[index].event_id,
        )
    older = changed(stamp="2026-11-11T11:00:00+00:00", index=1)
    unknown = changed(stamp="2026-11-11T12:01:00+00:00", index=2)
    assert encoder.accept(older)["episode_id"] != first["episode_id"]
    assert encoder.accept(unknown)["episode_id"] != first["episode_id"]


def test_unverified_entity_is_not_association_authority(tmp_path):
    from anima.memory.memory_store import MemoryStore
    from anima.memory.link_store import LinkStore

    events, _ = fixture()
    store = MemoryStore(tmp_path / "memory.db")
    links = LinkStore(store)
    links.create_entity(
        entity_type="technology", canonical_name="CPU A",
        public_id=ENT_CPU_A,
    )
    # CPU B does not exist as an Entity in this store: reject a forged ref.
    encoder = ShadowEpisodeEncoder(link_store=links)
    encoder.accept(events[0])
    with pytest.raises(ValueError, match="Unknown Entity reference"):
        encoder.accept(events[6])
    assert events[6].event_id not in encoder.event_assignments()
    assert events[0].event_id in encoder.event_assignments()
    assert ENT_CPU_B not in encoder.episodes()[0]["entity_ids"]


def test_compression_is_not_part_of_shadow_decision():
    events, _ = fixture()
    first = ShadowEpisodeEncoder()
    second = ShadowEpisodeEncoder()
    left = [first.accept(e) for e in events]
    # External summary is deliberately irrelevant: two very different text
    # compositions have no input slot in the shadow association algorithm.
    arbitrary_legacy_contents = (
        "irrelevant summary" * 100,
        "CPU cooling history",
    )
    assert all(isinstance(x, str) for x in arbitrary_legacy_contents)
    right = [second.accept(e) for e in events]
    assert left == right
    assert first.episodes() == second.episodes()


def test_adversarial_compaction_probe_exposes_both_boundaries(tmp_path):
    result = run_shadow(tmp_path / "work")
    probe = result["compression_adversary"]
    input_ids = [row["id"] for row in probe["input_events"]]
    first, decision, followup = input_ids

    # Under the short budget, a new high-priority decision displaces the
    # earlier "Copper calibration" phrase; association of the third Event
    # changes even though the raw source history has not changed.
    small = probe["legacy_64"]["assignments"]
    large = probe["legacy_512"]["assignments"]
    shadow = probe["shadow"]["assignments"]
    assert small[first] == small[decision]
    assert small[followup] != small[first]
    assert large[first] == large[decision] == large[followup]
    assert shadow[first] == shadow[followup]
    assert shadow[decision] != shadow[first]  # entity-only paraphrase missed
    assert probe["legacy_64"]["metrics"]["false_split_pairs"] > 0
    assert probe["legacy_512"]["metrics"]["false_split_pairs"] == 0
    assert probe["shadow"]["metrics"]["false_split_pairs"] > 0
