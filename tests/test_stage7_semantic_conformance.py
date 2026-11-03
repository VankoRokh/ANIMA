import json
from pathlib import Path

import pytest

from anima.semantic import (
    EvaluationPlan,
    evaluate_document,
    parse_and_validate_request,
    validate_assessment,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "stage7" / "classify_relation_0_1"


def _manifest():
    return json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))


def _root_cases():
    manifest = _manifest()
    for block_name, block in manifest["blocks"].items():
        block_dir = FIXTURE_ROOT / block["path"]
        block_manifest = json.loads((block_dir / "manifest.json").read_text(encoding="utf-8"))
        assert len(block_manifest["root_cases"]) == block["cases"]
        for item in block_manifest["root_cases"]:
            yield block_name, block_dir / item["path"], item["id"]


CASES = tuple(_root_cases())


@pytest.mark.parametrize(("block", "case_dir", "root_id"), CASES, ids=[case[2] for case in CASES])
def test_stage7_root_fixture_contract(block, case_dir, root_id):
    del block
    metadata = json.loads((case_dir / "metadata.json").read_text(encoding="utf-8"))
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    raw_request = (case_dir / "request.json").read_text(encoding="utf-8")

    assert metadata["root_case"] == root_id
    assert metadata["training_use"] == "forbidden"

    result = evaluate_document(raw_request)

    if expected.get("kind") == "process_error":
        assert isinstance(result, dict)
        assert result == expected
        assert metadata["backend_calls_expected"] == 0
        return

    request = parse_and_validate_request(raw_request)
    validate_assessment(expected, request)
    assert isinstance(result, EvaluationPlan)
    assert result.backend_calls_required == metadata["backend_calls_expected"]

    if result.complete:
        assert result.assessment() == expected
    else:
        for facet, value in result.determined_facets().items():
            assert value == expected[facet]


def test_stage7_root_manifest_matches_measured_residual():
    manifest = _manifest()
    measured_residual = []
    measured_zero_backend = 0
    measured_process_errors = []

    for _, case_dir, root_id in CASES:
        raw_request = (case_dir / "request.json").read_text(encoding="utf-8")
        result = evaluate_document(raw_request)
        if isinstance(result, dict):
            measured_process_errors.append(root_id)
            assert result["backend_calls_expected"] == 0
            measured_zero_backend += 1
            continue
        if result.residual_facets:
            measured_residual.append(root_id)
        else:
            measured_zero_backend += 1

    assert len(CASES) == manifest["root_case_count"] == 50
    assert measured_residual == manifest["execution_summary"]["model_residual_roots"]
    assert measured_process_errors == manifest["execution_summary"]["process_error_roots"]
    assert measured_zero_backend == manifest["execution_summary"]["deterministic_or_preflight_zero_backend_roots"]
