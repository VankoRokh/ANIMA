"""Conservative memory association: no cross-topic update from metadata.

Structured subject labels are only grouping hints, never trusted world facts.
"""
from collections import defaultdict

from anima.release_v01 import open_release
from anima.memory.processor import MemoryProcessor


def _report(instance, text):
    row = instance.handle({"op": "report", "text": text})
    assert row["ok"] and len(row["event_ids"]) == 1
    return row["event_ids"][0]


def test_structured_topics_stay_distinct_with_identical_metadata(tmp_path):
    subjects = ("ambercoil", "beanstock", "doorpanel", "linknode")
    topic_events = defaultdict(list)
    with open_release(tmp_path) as session:
        for cycle in range(3):
            for subject in subjects:
                identifier = _report(
                    session,
                    f"{subject}: independent report {subject} value {cycle}. "
                    f"Номер {cycle:04d}; ref meta{cycle:04d}",
                )
                topic_events[subject].append(identifier)

        store = session.core.memory_store
        rows = store.list_memories()
        assert len(rows) == len(subjects)
        mapped = {}
        for row in rows:
            event_ids = set(store.source_events(row["id"]))
            matching = [
                subject for subject, expected in topic_events.items()
                if event_ids == set(expected)
            ]
            assert len(matching) == 1, "A Memory crossed subjects"
            mapped[matching[0]] = row["id"]
        assert set(mapped) == set(subjects)

        for subject in subjects:
            bundle = session.handle({"op": "context", "query": subject})
            assert bundle["ok"]
            assert bundle["result"]["selection_stats"]["items_used"] >= 1

    with open_release(tmp_path) as reopened:
        assert reopened.core.memory_store.count() == len(subjects)
        assert reopened._index_complete()["status"] == "complete"
        for subject, event_ids in topic_events.items():
            for eid in event_ids:
                assert reopened.core.event_retrieval.get(eid) is not None


def test_unstructured_shared_boilerplate_does_not_merge(tmp_path):
    with open_release(tmp_path) as session:
        first = _report(session, "operator report ref 001 drone airflow stable")
        second = _report(session, "operator report ref 002 coffee beanstock pending")
        followup = _report(session, "operator report ref 003 drone airflow improved")
        store = session.core.memory_store
        rows = store.list_memories()
        assert len(rows) == 2
        source_sets = [set(store.source_events(row["id"])) for row in rows]
        assert {first, followup} in source_sets
        assert {second} in source_sets


def test_generic_status_prefix_not_a_topic_label():
    for generic in ("report:", "Decision:", "номер:", "status:", "NOTE:"):
        assert MemoryProcessor._prefix_anchor(generic + " some words") is None
    assert MemoryProcessor._prefix_anchor("ambercoil: note") == "ambercoil"
    assert MemoryProcessor._prefix_anchor("DEVICE-17: note") == "device-17"


def test_weak_shared_tokens_do_not_form_positive_lexical_score():
    score = MemoryProcessor._lexical_score
    assert score("cooling fan ref номер 0001", "coffee bags ref номер 0002") == 0
    assert score("operator report event 1", "operator report event 2") == 0
    assert score("SQLite storage baseline", "SQLite storage benchmark") > 0
