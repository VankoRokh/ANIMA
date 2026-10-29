from anima.benchmarks.tool_model_corpus import (
    M_COFFEE,
    M_FAST_BOUNDARY,
    benchmark_cases,
)
from anima.benchmarks.tool_models import (
    BenchmarkTurn,
    RunObservation,
    ToolCallObservation,
    append_comparison_csv,
    evaluate_case,
    render_markdown_report,
    summarize_observations,
    write_comparison_markdown,
)


def _case(case_id):
    return next(item for item in benchmark_cases() if item.id == case_id)


def _call(name, arguments, result, round_index=1):
    return ToolCallObservation(
        round_index=round_index,
        name=name,
        arguments=arguments,
        result=result,
    )


def test_corpus_has_ten_fixed_cases_across_three_levels():
    cases = benchmark_cases()

    assert len(cases) == 10
    assert len({case.id for case in cases}) == 10
    assert [case.level for case in cases].count(1) == 3
    assert [case.level for case in cases].count(2) == 3
    assert [case.level for case in cases].count(3) == 4


def test_no_tool_control_case_passes_without_calls():
    case = _case("T01_no_tool_arithmetic")
    turn = BenchmarkTurn(response_text="102", tool_calls=(), rounds=1)

    result = evaluate_case(case, turn)

    assert result.passed is True
    assert result.routing is True
    assert result.arguments is True
    assert result.grounding is True


def test_personal_search_requires_retrieval_of_expected_memory():
    case = _case("T04_memory_search_personal")
    good_turn = BenchmarkTurn(
        response_text="Ты предпочитаешь эспрессо.",
        rounds=2,
        tool_calls=(
            _call(
                "memory_search",
                {"query": "кофе предпочтение"},
                {
                    "results": [
                        {
                            "id": M_COFFEE,
                            "content": "Пользователь предпочитает кофе эспрессо.",
                        }
                    ]
                },
            ),
        ),
    )
    bad_turn = BenchmarkTurn(
        response_text="Ты предпочитаешь эспрессо.",
        rounds=2,
        tool_calls=(
            _call(
                "memory_search",
                {"query": "погода"},
                {"results": []},
            ),
        ),
    )

    assert evaluate_case(case, good_turn).passed is True
    bad = evaluate_case(case, bad_turn)
    assert bad.passed is False
    assert bad.arguments is False


def test_missing_fact_penalizes_hallucinated_cat_name():
    case = _case("T05_missing_personal_fact")
    turn = BenchmarkTurn(
        response_text="Собаку зовут Барсик.",
        rounds=2,
        tool_calls=(
            _call(
                "memory_search",
                {"query": "имя собаки"},
                {"results": []},
            ),
        ),
    )

    result = evaluate_case(case, turn)

    assert result.routing is True
    assert result.safety is False
    assert result.passed is False


def test_sequential_case_requires_search_before_exact_get():
    case = _case("T09_sequential_search_get")
    search = _call(
        "memory_search",
        {"query": "FAST Memory Internal State Goals"},
        {"results": [{"id": M_FAST_BOUNDARY}]},
        round_index=1,
    )
    get = _call(
        "memory_get",
        {"object_id": M_FAST_BOUNDARY},
        {"found": True, "object": {"id": M_FAST_BOUNDARY}},
        round_index=2,
    )
    response = "FAST не владеет Memory и Internal State; это внешние подсистемы."

    good = evaluate_case(
        case,
        BenchmarkTurn(response_text=response, tool_calls=(search, get), rounds=3),
    )
    wrong_order = evaluate_case(
        case,
        BenchmarkTurn(response_text=response, tool_calls=(get, search), rounds=3),
    )

    assert good.passed is True
    assert wrong_order.routing is False
    assert wrong_order.passed is False


def test_protocol_error_fails_all_dimensions():
    case = _case("T02_state_read_basic")

    result = evaluate_case(
        case,
        None,
        error="QwenToolProtocolError: malformed call",
    )

    assert result.passed is False
    assert result.protocol is False
    assert result.routing is False


def test_summary_and_markdown_report_expose_quality_and_latency():
    case = _case("T01_no_tool_arithmetic")
    turn = BenchmarkTurn(response_text="102", tool_calls=(), rounds=1)
    evaluation = evaluate_case(case, turn)
    observations = [
        RunObservation(
            case_id=case.id,
            repeat=1,
            latency_ms=100.0,
            turn=turn,
            evaluation=evaluation,
        ),
        RunObservation(
            case_id=case.id,
            repeat=2,
            latency_ms=200.0,
            turn=turn,
            evaluation=evaluation,
        ),
    ]

    summary = summarize_observations(observations)
    payload = {
        "run_id": "demo",
        "model": {
            "name": "demo-model",
            "adapter": "fake",
            "parameters_b": 1.0,
            "quantization": "Q4",
        },
        "repeats": 2,
        "summary": summary,
        "resources": {
            "model_size_mib": 1000.0,
            "rss_before_mib": 500.0,
            "rss_peak_mib": 700.0,
            "vmhwm_mib": 710.0,
            "gpu_vram_peak_mib": 300.0,
        },
        "observations": [
            {
                "case_id": item.case_id,
                "repeat": item.repeat,
                "latency_ms": item.latency_ms,
                "evaluation": {
                    "passed": item.evaluation.passed,
                    "routing": item.evaluation.routing,
                    "arguments": item.evaluation.arguments,
                    "protocol": item.evaluation.protocol,
                    "grounding": item.evaluation.grounding,
                    "safety": item.evaluation.safety,
                },
                "turn": {"tool_calls": []},
            }
            for item in observations
        ],
    }

    assert summary["metrics"]["passed"] == 1.0
    assert summary["latency_ms"]["mean"] == 150.0
    report = render_markdown_report(payload)
    assert "demo-model" in report
    assert "100.0%" in report
    assert "150.0 ms" in report


def test_comparison_table_is_generated_from_csv(tmp_path):
    case = _case("T01_no_tool_arithmetic")
    turn = BenchmarkTurn(response_text="102", tool_calls=(), rounds=1)
    evaluation = evaluate_case(case, turn)
    observation = RunObservation(
        case_id=case.id,
        repeat=1,
        latency_ms=120.0,
        turn=turn,
        evaluation=evaluation,
    )
    payload = {
        "run_id": "demo-run",
        "model": {
            "name": "demo-model",
            "adapter": "fake",
            "parameters_b": 0.5,
            "quantization": "Q4_K_M",
        },
        "summary": summarize_observations([observation]),
        "resources": {
            "model_size_mib": 400.0,
            "rss_before_mib": 500.0,
            "rss_peak_mib": 650.0,
            "gpu_vram_peak_mib": 250.0,
        },
    }
    csv_path = tmp_path / "comparison.csv"
    md_path = tmp_path / "comparison.md"

    append_comparison_csv(csv_path, payload)
    write_comparison_markdown(csv_path, md_path)

    text = md_path.read_text(encoding="utf-8")
    assert "demo-model" in text
    assert "100.0%" in text
    assert "Q4_K_M" in text
