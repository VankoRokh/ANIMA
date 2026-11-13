"""Opt-in E4 isolated SQLite dependency invalidation scale study.

Bulk synthetic DB seeding is ONE transaction and not the public create_node
write path. Measures revoke() only; does not benchmark production Memory.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import tempfile
from time import perf_counter

from labs.exp009.e4_alias_lifecycle_lab import _json, _digest
from labs.exp009.e4_process_kill_probe import _events, _registry, TOKEN_A, TOKEN_B
from labs.exp009.e4_source_authority_gate import AuthorizedAliasLifecycleLab


def _make_lab(path):
    j = AuthorizedAliasLifecycleLab(path, adapters=_registry())
    a, b, obs, rev = _events()
    j.admit_event(a, adapter_ref="adapter.a", token=TOKEN_A)
    j.admit_event(b, adapter_ref="adapter.b", token=TOKEN_B)
    j.append_event(obs)
    j.admit_event(rev, adapter_ref="adapter.a", token=TOKEN_A)
    j.define(alias_id="a", definition_event_id=a["id"], operation_key="define_a")
    j.define(alias_id="b", definition_event_id=b["id"], operation_key="define_b")
    j.create_node(node_id="S", kind="Story", source_event_ids=[obs["id"]],
                  alias_dependencies=[("a", 1)], node_dependencies=[],
                  operation_key="seed_S")
    j.create_node(node_id="E", kind="Episode", source_event_ids=[obs["id"]],
                  alias_dependencies=[], node_dependencies=[("S", 1)],
                  operation_key="seed_E")
    j.create_node(node_id="U", kind="Story", source_event_ids=[obs["id"]],
                  alias_dependencies=[("b", 1)], node_dependencies=[],
                  operation_key="seed_U")
    return j, obs, rev


def _expected_closure(graph, origin):
    # Independent pure-graph oracle (no SQL / no AliasLifecycleLab._downstream).
    touched = {name for name, deps in graph.items()
               if ("alias", origin) in deps}
    while True:
        next_touched = touched | {
            name for name, deps in graph.items()
            if any(kind == "node" and parent in touched
                   for kind, parent in deps)
        }
        if touched == next_touched:
            return touched
        touched = next_touched


def _seed_bulk(j, observation, size, affected_target):
    if size < 3 or not 2 <= affected_target <= min(128, size - 1):
        raise ValueError("Invalid seed size or affected target")
    graph = {
        "S": [("alias", "a")],
        "E": [("node", "S")],
        "U": [("alias", "b")],
    }
    with j._tx() as db:
        _source, fingerprint, _seq = j._raw(db, observation["id"])
        for i in range(3, size):
            node_id = f"N{i:06d}"
            if i <= affected_target:
                if i == 3 or (i - 3) % 4 == 0:
                    deps = [("alias", "a", 1)]
                else:
                    deps = [("node", f"N{i - 1:06d}", 1)]
            elif i == affected_target + 1 or i % 4 == 0:
                deps = [("alias", "b", 1)]
            else:
                deps = [("node", f"N{i - 1:06d}", 1)]
            graph[node_id] = [(kind, upstream) for kind, upstream, _ in deps]
            record = {
                "node_id": node_id, "revision": 1, "kind": "Story",
                "state": "current",
                "source_event_ids": [observation["id"]],
                "source_sha256": {observation["id"]: fingerprint},
                "dependencies": deps,
                "authority": "LAB_ONLY",
            }
            body = _json(record)
            db.execute(
                "INSERT INTO derived_heads VALUES(?,?,?,?)",
                (node_id, "Story", 1, "current"),
            )
            db.execute(
                "INSERT INTO derived_versions VALUES(?,?,?,?)",
                (node_id, 1, body, _digest(body)),
            )
            for kind, upstream, revision in deps:
                db.execute(
                    "INSERT INTO edges VALUES(?,?,?,?,?)",
                    (node_id, 1, kind, upstream, revision),
                )
    oracle = _expected_closure(graph, "a")
    assert len(graph) == size
    assert len(oracle) == affected_target
    return oracle


def _file_bytes(path):
    return sum(p.stat().st_size for p in
               (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
               if p.exists())


def run_one(size, *, affected=None, location=None):
    """For fixed size measure ONE successful selective revocation."""
    if type(size) is not int or not 3 <= size <= 10000:
        raise ValueError("3 <= size <= 10000")
    target = affected if affected is not None else min(64, max(8, size // 20))
    if target > 128 or target >= size:
        raise ValueError("Affected set exceeds the current bounded lab")
    with tempfile.TemporaryDirectory(prefix="anima-e4-scale-", dir=location) as folder:
        path = Path(folder) / "isolated_e4_scale.db"
        j, obs, rev = _make_lab(path)
        started_seed = perf_counter()
        oracle = _seed_bulk(j, obs, size, target)
        seed_s = perf_counter() - started_seed

        db_pre = _file_bytes(path)
        started = perf_counter()
        receipt = j.revoke(alias_id="a", revocation_event_id=rev["id"],
                           expected_head=1, operation_key="scale_revoke")
        revoke_s = perf_counter() - started
        db_post = _file_bytes(path)

        assert receipt["status"] == "revoked"
        assert receipt["affected_nodes"] == sorted(oracle)
        assert j.invalidations("scale_revoke") == sorted(oracle)
        assert j.allowed_decision("scale_revoke")["admitted_principal_id"] == "principal.a"
        with j._connection() as db:
            states = dict(db.execute(
                "SELECT state,COUNT(*) FROM derived_heads GROUP BY state").fetchall())
            count = db.execute("SELECT COUNT(*) FROM derived_heads").fetchone()[0]
        assert states == {"current": size - target, "stale": target}
        assert count == size
        assert j.alias("b")["head_state"] == "active"
        assert j.node("U")["head_state"] == "current"
        for node_id in oracle:
            assert j.node(node_id)["head_state"] == "stale"
            assert j.node(node_id, 1)["record"]["state"] == "current"
        replay = j.revoke(alias_id="a", revocation_event_id=rev["id"],
                          expected_head=1, operation_key="scale_revoke")
        assert replay["status"] == "idempotent_replay"
        assert j.count("invalidations") == target
        assert j.authority_counts()["allowed_revocations"] == 1

        # ru_maxrss is a process-wide high-water mark, not operation-only RSS.
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "status": "ISOLATED_SCALE_PASS",
            "node_count": size,
            "affected": target,
            "unaffected": size - target,
            "affected_fraction": round(target / size, 6),
            "coarse_would_touch": size,
            "coarse_avoided_count": size - target,
            "seed_method": "single_tx_direct_synthetic_sql_not_public_API",
            "seed_s": round(seed_s, 6),
            "revoke_s": round(revoke_s, 6),
            "db_bytes_before": db_pre,
            "db_bytes_after": db_post,
            "peak_rss_kib_linux_process": rss if sys.platform.startswith("linux") else None,
            "replay_status": replay["status"],
            "production_admission": False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.repeat <= 7:
        parser.error("repeat must be 1..7")
    if any(size not in (100, 1000, 10000) for size in args.sizes):
        parser.error("supported sizes: 100, 1000, 10000")
    result = {
        "schema": "anima.e4.isolated_scale/0.1",
        "status": "LAB_BENCHMARK_ONLY",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "runs": [],
        "actual_power_loss_tested": False,
        "production_memory_changed": False,
        "note": "Synthetic direct SQL seeding; not a public Memory API benchmark. "
                "Coarse count is theoretical, not separately timed.",
    }
    for size in args.sizes:
        samples = [run_one(size) for _ in range(args.repeat)]
        times = [item["revoke_s"] for item in samples]
        result["runs"].append({
            "size": size, "median_revoke_s": round(statistics.median(times), 6),
            "min_revoke_s": min(times), "max_revoke_s": max(times),
            "samples": samples,
        })
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
