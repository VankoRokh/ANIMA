"""Independent logical graph oracle + authority-spoof characterization.

All tests use the isolated E4 SQLite lab. A characterization of a known
security gap is NOT a production acceptance test.
"""
from collections import defaultdict
from random import Random

from tests.test_memory_e4_alias_lifecycle_lab import (_setup, _revocation, _definition, _event)


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


def test_twelve_competing_source_definitions_revoke_incremental_closure(tmp_path):
    """Many conflicting Event claims, multiple revocations and mixed DAG paths.

    This tests structural scoping, not truth or actual source independence.
    """
    from labs.exp009.e4_alias_lifecycle_lab import AliasLifecycleLab

    j = AliasLifecycleLab(tmp_path / "multi_conflict_lab.db")
    definitions = {}
    aliases = [f"conflict_{i:02d}" for i in range(12)]
    for i, alias_id in enumerate(aliases):
        definition = _definition(
            100 + i, alias_id, f"psu:alternative:{i:02d}",
            surface="адаптер", session=f"report_{i:02d}")
        j.append_event(definition)
        j.define(alias_id=alias_id,
                 definition_event_id=definition["id"],
                 operation_key=f"define_{alias_id}")
        definitions[alias_id] = definition
    observation = _event(1000, "Синтетическое наблюдение общего устройства.")
    j.append_event(observation)

    rng = Random(99173)
    graph = {}
    created = []
    for i in range(90):
        node = f"mixed_{i:03d}"
        primary = aliases[i % 12]
        alias_deps = [primary]
        if i % 7 == 0:
            secondary = aliases[(i + 5) % 12]
            if secondary != primary:
                alias_deps.append(secondary)
        n_parents = rng.randrange(min(3, len(created)) + 1)
        parent_deps = rng.sample(created, k=n_parents)
        j.create_node(
            node_id=node,
            kind="Story" if i % 3 else "Episode",
            source_event_ids=[observation["id"]],
            alias_dependencies=[(name, 1) for name in alias_deps],
            node_dependencies=[(name, 1) for name in parent_deps],
            operation_key=f"seed_{node}",
        )
        graph[node] = ([("alias", name) for name in alias_deps] +
                       [("node", name) for name in parent_deps])
        created.append(node)

    already_stale = set()
    revoked_aliases = set()
    for revocation_number, alias_id in enumerate((aliases[0], aliases[5], aliases[9])):
        revocation = _revocation(
            2000 + revocation_number, alias_id,
            definitions[alias_id], session="revisit_s2",
            timestamp="2026-11-14T12:00:00+00:00")
        j.append_event(revocation)
        result = j.revoke(
            alias_id=alias_id, revocation_event_id=revocation["id"],
            expected_head=1, operation_key=f"revoke_{alias_id}")

        revoked_aliases.add(alias_id)
        expected_now = set().union(*(
            _logical_closure(graph, name) for name in revoked_aliases
        ))
        newly_stale = expected_now - already_stale
        assert set(result["affected_nodes"]) == newly_stale
        assert result["invalidation_count"] == len(newly_stale)
        assert set(j.invalidations(f"revoke_{alias_id}")) == newly_stale
        for node in graph:
            assert j.node(node)["head_state"] == (
                "stale" if node in expected_now else "current"
            )
        already_stale = expected_now

    assert 12 < len(already_stale) < 90
    assert j.count("raw_events") == 16
    for alias_id in aliases:
        state = "revoked" if alias_id in revoked_aliases else "active"
        assert j.alias(alias_id)["head_state"] == state
        assert j.alias(alias_id, 1)["record"]["state"] == "active"
