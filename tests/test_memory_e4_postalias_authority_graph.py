"""Independent logical graph oracle + authority-spoof characterization.

All tests use the isolated E4 SQLite lab. A characterization of a known
security gap is NOT a production acceptance test.
"""
from collections import defaultdict
from random import Random

from tests.test_memory_e4_alias_lifecycle_lab import _setup, _revocation


def _logical_closure(edges, alias_id):
    """Test-only fixed-point oracle; does NOT query the lab's edge traversal."""
    affected = {
        node for node, parents in edges.items()
        if ("alias", alias_id) in parents
    }
    while True:
        next_affected = affected | {
            node for node, parents in edges.items()
            if any(kind == "node" and upstream in affected
                   for kind, upstream in parents)
        }
        if next_affected == affected:
            return affected
        affected = next_affected


def test_characterization_forged_user_label_can_revoke_without_admission(tmp_path):
    """Known authority gap: Event.source is user-controlled in this lab.

    The test documents a vulnerability; success is evidence of NO-GO.
    """
    j, _, a, _, _ = _setup(tmp_path)
    # An arbitrary caller can prepare this payload without a trusted adapter,
    # authenticated speaker/principal, or Core ingress admission receipt.
    rev = _revocation(40, "a", a, source="user", session="attacker-session")
    j.append_event(rev)
    r = j.revoke(alias_id="a", revocation_event_id=rev["id"],
                 expected_head=1, operation_key="forged_revoke")
    assert r["status"] == "revoked"  # CURRENT VULNERABLE BEHAVIOR
    assert r["affected_nodes"] == ["episode_e", "story_s"]
    assert j.alias("a")["head_state"] == "revoked"
    assert j.node("story_s")["head_state"] == "stale"
    assert j.node("story_u")["head_state"] == "current"
    assert r["production_admission"] is False


def test_independent_dag_oracle_matches_exact_invalidation_and_replay(tmp_path):
    j, _, a, b, observation = _setup(tmp_path)
    rng = Random(271828)
    graph = {
        "story_s": [("alias", "a")],
        "episode_e": [("node", "story_s")],
        "story_u": [("alias", "b")],
    }
    previously_created = list(graph)
    for n in range(96):
        node_id = f"dag_{n:03d}"
        count = rng.randrange(min(3, len(previously_created)) + 1)
        parents = rng.sample(previously_created, k=count)
        marker = rng.randrange(5)
        aliases = (["a", "b"] if n % 13 == 0
                   else ["a"] if marker == 0
                   else ["b"] if marker == 1
                   else [])
        j.create_node(
            node_id=node_id,
            kind="Episode" if n % 4 == 0 else "Story",
            source_event_ids=[observation["id"]],
            alias_dependencies=[(alias, 1) for alias in aliases],
            node_dependencies=[(parent, 1) for parent in parents],
            operation_key=f"dag_seed_{n:03d}",
        )
        graph[node_id] = ([("alias", alias) for alias in aliases] +
                          [("node", parent) for parent in parents])
        previously_created.append(node_id)

    # Independently compute the entire descendant closure, not just direct refs.
    expected = _logical_closure(graph, "a")
    assert len(graph) == 99
    assert 10 < len(expected) < 99
    receipt = _revocation(41, "a", a)
    j.append_event(receipt)
    actual = j.revoke(alias_id="a", revocation_event_id=receipt["id"],
                      expected_head=1, operation_key="oracle_revoke")
    assert actual["affected_nodes"] == sorted(expected)
    assert actual["invalidation_count"] == len(expected)
    assert j.invalidations("oracle_revoke") == sorted(expected)
    for node_id in graph:
        expected_state = "stale" if node_id in expected else "current"
        assert j.node(node_id)["head_state"] == expected_state
    assert j.alias("b")["head_state"] == "active"

    replay = j.revoke(alias_id="a", revocation_event_id=receipt["id"],
                      expected_head=1, operation_key="oracle_revoke")
    assert replay["status"] == "idempotent_replay"
    assert replay["affected_nodes"] == sorted(expected)
    assert j.count("invalidations") == len(expected)


def test_diamond_reaches_shared_descendant_once_and_leaves_neighbor(tmp_path):
    j, _, a, b, obs = _setup(tmp_path)
    additions = [
        ("fork_left", [("story_s", 1)], []),
        ("fork_right", [("story_s", 1)], []),
        ("join", [("fork_left", 1), ("fork_right", 1)], []),
        ("unrelated", [("story_u", 1)], [("b", 1)]),
    ]
    for node, parents, aliases in additions:
        j.create_node(node_id=node, kind="Story",
                      source_event_ids=[obs["id"]],
                      alias_dependencies=aliases,
                      node_dependencies=parents, operation_key=f"seed_{node}")
    rev = _revocation(42, "a", a)
    j.append_event(rev)
    result = j.revoke(alias_id="a", revocation_event_id=rev["id"],
                      expected_head=1, operation_key="diamond_revoke")
    expected = {"story_s", "episode_e", "fork_left", "fork_right", "join"}
    assert set(result["affected_nodes"]) == expected
    assert result["invalidation_count"] == len(expected)
    assert j.count("invalidations") == len(expected)
    assert j.node("unrelated")["head_state"] == "current"


def test_exactly_128_affected_nodes_are_admitted_atomically(tmp_path):
    j, _, a, b, obs = _setup(tmp_path)
    # The original story_s and episode_e are two affected nodes.
    for n in range(126):
        j.create_node(
            node_id=f"boundary_{n:03d}", kind="Story",
            source_event_ids=[obs["id"]],
            alias_dependencies=[("a", 1)], node_dependencies=[],
            operation_key=f"boundary_seed_{n:03d}",
        )
    rev = _revocation(43, "a", a)
    j.append_event(rev)
    result = j.revoke(alias_id="a", revocation_event_id=rev["id"],
                      expected_head=1, operation_key="boundary_revoke")
    assert result["invalidation_count"] == 128
    assert len(set(result["affected_nodes"])) == 128
    assert j.count("invalidations") == 128
    assert j.node("story_u")["head_state"] == "current"
