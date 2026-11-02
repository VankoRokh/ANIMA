from scripts.analyze_deep_baseline_v02 import analyze_report


def test_v02_analysis_builds_confusion_and_case_comparison():
    report = {
        "arms": [
            {
                "arm": "qwen:FAST",
                "summary": {
                    "total": 2,
                    "relation_passes": 1,
                    "resolution_passes": 2,
                    "semantic_pair_passes": 1,
                    "exact_passes": 1,
                },
                "cases": [
                    {
                        "case_id": "S01",
                        "category": "support",
                        "expected_relation": "SUPPORT",
                        "expected_resolution": "RESOLVED",
                        "parsed_relation": "SUPPORT",
                        "parsed_resolution": "RESOLVED",
                        "relation_correct": True,
                        "resolution_correct": True,
                        "semantic_pair_correct": True,
                    },
                    {
                        "case_id": "S02",
                        "category": "temporal",
                        "expected_relation": "TEMPORAL_CHANGE",
                        "expected_resolution": "RESOLVED",
                        "parsed_relation": "INSUFFICIENT",
                        "parsed_resolution": "RESOLVED",
                        "relation_correct": False,
                        "resolution_correct": True,
                        "semantic_pair_correct": False,
                    },
                ],
            },
            {
                "arm": "smol:DEEP",
                "summary": {
                    "total": 2,
                    "relation_passes": 2,
                    "resolution_passes": 1,
                    "semantic_pair_passes": 1,
                    "exact_passes": 0,
                },
                "cases": [
                    {
                        "case_id": "S01",
                        "category": "support",
                        "expected_relation": "SUPPORT",
                        "expected_resolution": "RESOLVED",
                        "parsed_relation": "SUPPORT",
                        "parsed_resolution": "UNRESOLVED",
                        "relation_correct": True,
                        "resolution_correct": False,
                        "semantic_pair_correct": False,
                    },
                    {
                        "case_id": "S02",
                        "category": "temporal",
                        "expected_relation": "TEMPORAL_CHANGE",
                        "expected_resolution": "RESOLVED",
                        "parsed_relation": "TEMPORAL_CHANGE",
                        "parsed_resolution": "RESOLVED",
                        "relation_correct": True,
                        "resolution_correct": True,
                        "semantic_pair_correct": True,
                    },
                ],
            },
        ]
    }

    analysis = analyze_report(report)
    fast = analysis["arms"][0]
    deep = analysis["arms"][1]

    assert fast["relation_confusion"][("TEMPORAL_CHANGE", "INSUFFICIENT")] == 1
    assert fast["category"]["temporal"] == {
        "relation": 0,
        "resolution": 1,
        "pair": 0,
        "total": 1,
    }
    assert deep["resolution_confusion"][("RESOLVED", "UNRESOLVED")] == 1
    assert set(analysis["by_case"]["S01"]) == {"qwen:FAST", "smol:DEEP"}
