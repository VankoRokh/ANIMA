from scripts.benchmark_stage1 import run_dataset


LATENCY_METRICS = {
    "memory_create",
    "memory_update",
    "entity_lookup",
    "knowledge_lookup",
    "fts_memory",
    "relation_1hop",
    "retrieval",
    "context_fast",
    "context_deep",
}


def test_stage1_performance_benchmark_smoke(tmp_path):
    result = run_dataset(
        50,
        samples=2,
        batch_count=1,
        workdir=tmp_path / "benchmark",
    )

    assert result["size"] == 50
    assert result["event_append"]["events"] == 50
    assert result["event_append"]["events_per_s"] > 0

    seed = result["synthetic_seed"]
    assert seed["memories"] == 50
    assert seed["knowledge"] == 2
    assert seed["entities"] == 50
    assert seed["relations"] > 50
    assert seed["rows_per_s"] > 0

    assert set(result["latency"]) == LATENCY_METRICS
    for metric in result["latency"].values():
        assert metric["samples"] >= 1
        assert metric["p50_ms"] >= 0
        assert metric["p95_ms"] >= metric["p50_ms"]

    batch = result["batch_processing"]
    assert batch["events"] == 1
    assert len(batch["actions"]) == 1
    assert batch["events_per_s"] > 0

    storage = result["storage_after_seed"]
    assert storage["memory_db_mb"] > 0
    assert storage["events_jsonl_mb"] > 0
    assert storage["data_total_mb"] >= storage["memory_db_mb"]

    assert result["storage_final"]["data_total_mb"] >= storage["data_total_mb"]
    assert result["total"]["wall_s"] > 0
    assert result["total"]["cpu_s"] > 0
    assert result["total"]["peak_rss_mb"] > 0
