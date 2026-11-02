from scripts.benchmark_deep_neutral_control import (
    parse_output,
    render_prompts,
    taxonomy_order,
)
from anima.experiments.deep_audit_v02 import default_audit_corpus


def test_neutral_control_has_no_fast_or_deep_identity_and_no_candidates_list():
    case = default_audit_corpus()[0]
    system_prompt, user_prompt = render_prompts(case, 0)

    assert "FAST" not in system_prompt
    assert "DEEP" not in system_prompt
    assert '"candidates"' not in user_prompt
    assert '"evidence"' in user_prompt
    assert case.case_id in user_prompt


def test_taxonomy_order_is_counterbalanced_across_neighbor_cases():
    relations_a, resolutions_a = taxonomy_order(0)
    relations_b, resolutions_b = taxonomy_order(1)

    assert relations_b == tuple(reversed(relations_a))
    assert resolutions_b == tuple(reversed(resolutions_a))


def test_reversed_assignment_swaps_counterbalance():
    assert taxonomy_order(0, reversed_order=True) == taxonomy_order(1)
    assert taxonomy_order(1, reversed_order=True) == taxonomy_order(0)


def test_parse_output_scores_exact_and_semantic_values():
    assert parse_output("RELATION=CORRECTION;RESOLUTION=RESOLVED") == (
        "CORRECTION",
        "RESOLVED",
        True,
    )
    assert parse_output("CORRECTION because old information was wrong; UNRESOLVED") == (
        "CORRECTION",
        "UNRESOLVED",
        False,
    )
