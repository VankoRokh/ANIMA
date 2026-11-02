from scripts.analyze_deep_baseline import (
    analyze_arm,
    extract_semantic_label,
)


def test_extract_semantic_label_accepts_one_label_inside_explanation():
    assert extract_semantic_label("The case is UNRESOLVED because evidence conflicts.") == "UNRESOLVED"
    assert extract_semantic_label("result: temporal_change") == "TEMPORAL_CHANGE"


def test_extract_semantic_label_rejects_multiple_distinct_labels():
    assert extract_semantic_label("Could be SUPPORT or CONTRADICTION.") is None


def test_analyzer_separates_semantic_correctness_from_exact_contract():
    arm = {
        "arm": "SmolLM3-3B-Q8_0:DEEP",
        "model": "SmolLM3-3B-Q8_0",
        "role": "DEEP",
        "cases": [
            {
                "case_id": "S01",
                "difficulty": "simple",
                "category": "support",
                "expected": "SUPPORT",
                "response": "SUPPORT because both sources agree.",
                "correct": False,
                "format_valid": False,
            },
            {
                "case_id": "S05",
                "difficulty": "simple",
                "category": "uncertain",
                "expected": "UNRESOLVED",
                "response": "UNRESOLVED",
                "correct": True,
                "format_valid": True,
            },
        ],
    }

    result = analyze_arm(arm)

    assert result["strict_passes"] == 1
    assert result["semantic_passes"] == 2
    assert result["format_valid"] == 1
    assert result["abstention_strict"] == 1
    assert result["abstention_semantic"] == 1
    assert result["abstention_total"] == 1
