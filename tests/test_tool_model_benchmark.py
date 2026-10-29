import json

from anima.benchmarks.tool_model_corpus import (
    BENCHMARK_STATE_CONFIG,
    M_COFFEE,
    M_FAST_BOUNDARY,
    benchmark_cases,
)
from anima.benchmarks.tool_models import (
    BenchmarkTurn,
    RUN_ERROR,
    RUN_FAIL,
    RUN_PASS,
    RunObservation,
    ToolCallObservation,
    append_comparison_csv,
    evaluate_case,
    observation_to_dict,
    render_markdown_report,
    summarize_observations,
    write_comparison_markdown,
)
from scripts.benchmark_tool_models import build_gateway


def _case(case_id):
    return next(item for item in benchmark_cases() if item.id == case_id)


def _call(name, arguments, result, round_index=1):
    return ToolCallObservation(
        round_index=round_index,
        name=name,
        arguments=arguments,
        result=result,
    )


def _response(control, body=""):
    control_line = "CONTROL: " + json.dumps(control, ensure_ascii=False)
    return control_line if not body else body + "\n" + control_line


def test_corpus_has_ten_fixed_cases_across_three_levels():
    cases = benchmark_cases()

    assert len(cases) == 10
    assert len({case.id for case in cases}) == 10
    assert [case.level for case in cases].count(1) == 3
    assert [case.level for case in cases].count(2) == 3
    assert [case.level for case in cases].count(3) == 4


def test_no_tool_control_case_passes_only_with_exact_control_contract():
    case = _case("T01_no_tool_arithmetic")
    good = BenchmarkTurn(
        response_text=_response({"answer": 102}),
        tool_calls=(),
        rounds=1,
    )
    wrong_value = BenchmarkTurn(
        response_text=_response({"answer": 999}),
        tool_calls=(),
        rounds=1,
    )
    contradictory_body = BenchmarkTurn(
        response_text=_response({"answer": 102}, body="Не 102, а 999."),
        tool_calls=(),
        rounds=1,
    )

    result = evaluate_case(case, good)
    assert result.status == RUN_PASS
    assert result.passed is True
    assert result.routing is True
    assert result.arguments is True
    assert result.grounding is True

    assert evaluate_case(case, wrong_value).grounding is False
    assert evaluate_case(case, contradictory_body).grounding is False


def test_personal_search_requires_retrieval_and_grounded_control():
    case = _case("T04_memory_search_personal")
    search = _call(
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
    )
    good_turn = BenchmarkTurn(
        response_text=_response({"coffee": "эспрессо"}),
        rounds=2,
        tool_calls=(search,),
    )
    wrong_control = BenchmarkTurn(
        response_text=_response({"coffee": "чай"}),
        rounds=2,
        tool_calls=(search,),
    )
    wrong_retrieval = BenchmarkTurn(
        response_text=_response({"coffee": "эспрессо"}),
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
    assert evaluate_case(case, wrong_control).grounding is False
    bad = evaluate_case(case, wrong_retrieval)
    assert bad.passed is False
    assert bad.arguments is False


def test_missing_fact_requires_null_and_safe_refusal_body():
    case = _case("T05_missing_personal_fact")
    search = _call(
        "memory_search",
        {"query": "имя собаки"},
        {"results": []},
    )
    safe = BenchmarkTurn(
        response_text=_response(
            {"dog_name": None},
            body="Имя собаки неизвестно.",
        ),
        rounds=2,
        tool_calls=(search,),
    )
    hallucinated = BenchmarkTurn(
        response_text=_response(
            {"dog_name": "Рекс"},
            body="Собаку зовут Рекс.",
        ),
        rounds=2,
        tool_calls=(search,),
    )
    false_context = BenchmarkTurn(
        response_text=_response(
            {"dog_name": None},
            body="Барсик — кот, имя собаки неизвестно.",
        ),
        rounds=2,
        tool_calls=(search,),
    )

    good = evaluate_case(case, safe)
    assert good.status == RUN_PASS
    assert good.safety is True

    bad = evaluate_case(case, hallucinated)
    assert bad.safety is False
    assert bad.grounding is False
    assert bad.status == RUN_FAIL

    contextual = evaluate_case(case, false_context)
    assert contextual.safety is False
    assert contextual.status == RUN_FAIL


def test_sequential_case_requires_search_result_then_later_round_get():
    case = _case("T09_sequential_search_get")
    search = _call(
        "memory_search",
        {"query": "FAST Memory Internal State Goals"},
        {"results": [{"id": M_FAST_BOUNDARY}]},
        round_index=1,
    )
    get_later = _call(
        "memory_get",
        {"object_id": M_FAST_BOUNDARY},
        {"found": True, "object": {"id": M_FAST_BOUNDARY}},
        round_index=2,
    )
    get_same_round = _call(
        "memory_get",
        {"object_id": M_FAST_BOUNDARY},
        {"found": True, "object": {"id": M_FAST_BOUNDARY}},
        round_index=1,
    )
    response = _response(
        {
            "fast_owns_memory": False,
            "fast_owns_state": False,
            "fast_owns_goals": False,
        }
    )

    good = evaluate_case(
        case,
        BenchmarkTurn(
            response_text=response,
            tool_calls=(search, get_later),
            rounds=3,
        ),
    )
    same_round = evaluate_case(
        case,
        BenchmarkTurn(
            response_text=response,
            tool_calls=(search, get_same_round),
            rounds=2,
        ),
    )

    assert good.passed is True
    assert good.checks["search_get_round_dependency"] is True
    assert same_round.routing is False
    assert same_round.checks["search_get_round_dependency"] is False
    assert same_round.passed is False


def test_reasoning_case_requires_prefix_at_start_and_real_explanation():
    case = _case("T08_retrieval_plus_reasoning")
    search = _call(
        "memory_search",
        {"query": "предпочтение кофе"},
        {"results": [{"id": M_COFFEE}]},
    )
    good = BenchmarkTurn(
        response_text=_response(
            {"choice": "эспрессо", "basis": "memory_preference"},
            body="Выбор: Эспрессо. В Memory сохранено предпочтение эспрессо.",
        ),
        tool_calls=(search,),
        rounds=2,
    )
    wrong_position = BenchmarkTurn(
        response_text=_response(
            {"choice": "эспрессо", "basis": "memory_preference"},
            body="Пояснение. Выбор: Эспрессо.",
        ),
        tool_calls=(search,),
        rounds=2,
    )
    no_explanation = BenchmarkTurn(
        response_text=_response(
            {"choice": "эспрессо", "basis": "memory_preference"},
            body="Выбор: Эспрессо.",
        ),
        tool_calls=(search,),
        rounds=2,
    )

    assert evaluate_case(case, good).passed is True
    assert evaluate_case(case, wrong_position).grounding is False
    assert evaluate_case(case, no_explanation).grounding is False


def test_multi_source_synthesis_has_fixed_body_and_control_fields():
    case = _case("T10_multi_source_synthesis")
    search = _call(
        "memory_search",
        {"query": "текущий приоритет разработки"},
        {"results": [{"id": "mem_66666666-6666-4666-8666-666666666666"}]},
    )
    state = _call(
        "state_read",
        {},
        {
            "available": True,
            "states": {
                "fatigue": 0.0,
                "uncertainty": 0.0,
                "frustration": 0.0,
                "satisfaction": 0.0,
            },
        },
    )
    good = BenchmarkTurn(
        response_text=_response(
            {
                "focus_memory_state_interfaces": True,
                "fatigue": 0.0,
                "uncertainty": 0.0,
                "recommend_continue_focus": True,
            },
            body="Рекомендация: продолжить работу над интерфейсами Memory/Internal State.",
        ),
        tool_calls=(search, state),
        rounds=2,
    )
    opposite = BenchmarkTurn(
        response_text=_response(
            {
                "focus_memory_state_interfaces": False,
                "fatigue": 0.0,
                "uncertainty": 0.0,
                "recommend_continue_focus": False,
            },
            body="Рекомендация: прекратить работу над интерфейсами Memory/Internal State.",
        ),
        tool_calls=(search, state),
        rounds=2,
    )

    assert evaluate_case(case, good).passed is True
    assert evaluate_case(case, opposite).grounding is False


def test_model_protocol_failure_is_fail_not_infrastructure_error():
    case = _case("T02_state_read_basic")

    result = evaluate_case(
        case,
        None,
        error="QwenToolProtocolError: malformed call",
        error_kind="model_protocol",
    )

    assert result.status == RUN_FAIL
    assert result.passed is False
    assert result.protocol is False
    assert result.routing is None
    assert result.arguments is None


def test_infrastructure_failure_is_error_with_unscored_capabilities():
    case = _case("T02_state_read_basic")

    result = evaluate_case(
        case,
        None,
        error="ConnectionError: server disconnected",
        error_kind="infrastructure",
    )

    assert result.status == RUN_ERROR
    assert result.passed is None
    assert result.protocol is None
    assert result.routing is None
    assert result.arguments is None
    assert result.grounding is None
    assert result.safety is None


def test_summary_separates_pass_fail_error_latency_and_metric_denominators():
    case = _case("T01_no_tool_arithmetic")
    pass_turn = BenchmarkTurn(
        response_text=_response({"answer": 102}),
        tool_calls=(),
        rounds=1,
    )
    fail_turn = BenchmarkTurn(
        response_text=_response({"answer": 999}),
        tool_calls=(),
        rounds=1,
    )
    passed = evaluate_case(case, pass_turn)
    failed = evaluate_case(case, fail_turn)
    errored = evaluate_case(
        case,
        None,
        error="ConnectionError",
        error_kind="infrastructure",
    )
    observations = [
        RunObservation(case.id, 1, 100.0, pass_turn, passed),
        RunObservation(case.id, 2, 200.0, fail_turn, failed),
        RunObservation(
            case.id,
            3,
            10.0,
            None,
            errored,
            error="ConnectionError",
            error_kind="infrastructure",
        ),
    ]

    summary = summarize_observations(observations)

    assert summary["status_counts"] == {"PASS": 1, "FAIL": 1, "ERROR": 1}
    assert summary["metrics"]["passed"] == 0.5
    assert summary["metric_counts"]["passed"] == 2
    assert summary["latency_ms"]["pass"]["mean"] == 100.0
    assert summary["latency_ms"]["completed"]["mean"] == 150.0
    assert summary["latency_ms"]["error"]["mean"] == 10.0


def test_partial_tool_calls_are_preserved_in_machine_evidence():
    case = _case("T04_memory_search_personal")
    partial = _call(
        "memory_search",
        {"query": "кофе"},
        {"results": [{"id": M_COFFEE}]},
        round_index=0,
    )
    evaluation = evaluate_case(
        case,
        None,
        error="ConnectionError",
        error_kind="infrastructure",
    )
    observation = RunObservation(
        case_id=case.id,
        repeat=1,
        latency_ms=25.0,
        turn=None,
        evaluation=evaluation,
        error="ConnectionError",
        error_kind="infrastructure",
        partial_tool_calls=(partial,),
    )

    payload = observation_to_dict(observation)

    assert payload["partial_tool_calls"][0]["name"] == "memory_search"
    assert payload["partial_tool_calls"][0]["result"]["results"][0]["id"] == M_COFFEE


def test_gateway_uses_benchmark_owned_internal_state_config(tmp_path):
    gateway = build_gateway(tmp_path)

    assert gateway.internal_state_runtime.store.database_file == tmp_path / "internal_state.db"
    assert gateway.internal_state_runtime.store.config == BENCHMARK_STATE_CONFIG
    assert (tmp_path / "internal_state_config.json").is_file()


def test_summary_and_markdown_report_expose_statuses_and_pass_latency():
    case = _case("T01_no_tool_arithmetic")
    turn = BenchmarkTurn(
        response_text=_response({"answer": 102}),
        tool_calls=(),
        rounds=1,
    )
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
            "rss_sampled_max_mib": 700.0,
            "vmhwm_mib": 710.0,
            "gpu_vram_sampled_max_mib": 300.0,
            "rss_sample_interval_s": 0.25,
            "gpu_sample_interval_s": 1.0,
        },
        "observations": [observation_to_dict(item) for item in observations],
    }

    assert summary["metrics"]["passed"] == 1.0
    assert summary["latency_ms"]["pass"]["mean"] == 150.0
    report = render_markdown_report(payload)
    assert "demo-model" in report
    assert "PASS=2, FAIL=0, ERROR=0" in report
    assert "150.0 ms" in report
    assert "sampled max" in report


def test_comparison_table_is_generated_from_csv(tmp_path):
    case = _case("T01_no_tool_arithmetic")
    turn = BenchmarkTurn(
        response_text=_response({"answer": 102}),
        tool_calls=(),
        rounds=1,
    )
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
            "rss_sampled_max_mib": 650.0,
            "gpu_vram_sampled_max_mib": 250.0,
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
    assert "Errors" in text
