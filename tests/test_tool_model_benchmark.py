import json

import pytest

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


def test_reasoning_case_requires_exact_body_control_and_retrieval():
    case = _case("T08_retrieval_plus_reasoning")
    search = _call(
        "memory_search", {"query": "предпочтение кофе"},
        {"results": [{"id": M_COFFEE}]},
    )
    control = {
        "choice": "эспрессо", "basis": "memory_preference",
        "remembered_preference": "эспрессо",
    }
    good = BenchmarkTurn(_response(control, "Выбор: Эспрессо."), (search,), 2)
    assert evaluate_case(case, good).status == RUN_PASS
    wrong_cases = [
        (_response({**control, "choice": "чай"}, "Выбор: Чай."), (search,)),
        (_response(control, "Выбор: Эспрессо. На самом деле выбираю чай."), (search,)),
        (_response({**control, "basis": "guess"}, "Выбор: Эспрессо."), (search,)),
        (_response({**control, "remembered_preference": "чай"}, "Выбор: Эспрессо."), (search,)),
        (_response(control, "Выбор: Эспрессо."), ()),
        (_response(control, "Выбор: Эспрессо."), (
            _call("memory_search", {"query": "погода"}, {"results": []}),
        )),
    ]
    for response, calls in wrong_cases:
        assert evaluate_case(case, BenchmarkTurn(response, calls, 2)).status == RUN_FAIL


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


@pytest.mark.parametrize("number", ["9" * 400, "NaN", "Infinity", "-Infinity", "1e999"])
def test_hostile_numeric_control_fails_without_crashing(number):
    case = _case("T01_no_tool_arithmetic")
    result = evaluate_case(case, BenchmarkTurn(
        'CONTROL: {"answer":' + number + '}', (), 1,
    ))
    assert result.status == RUN_FAIL
    assert result.grounding is False


def test_scalar_comparison_rejects_nonfinite_and_overflow():
    from anima.benchmarks.tool_models import _scalar_equal

    for value in (10 ** 400, float("nan"), float("inf"), -float("inf")):
        assert _scalar_equal(value, 102) is False
    assert _scalar_equal(float("inf"), float("inf")) is False
    assert _scalar_equal(float("nan"), float("nan")) is False
    assert _scalar_equal(102, 102.0) is True
    assert _scalar_equal(True, 1) is False


@pytest.mark.parametrize("case_id, raw, body", [
    ("T01_no_tool_arithmetic", '{"answer":999,"answer":102}', ""),
    ("T05_missing_personal_fact", '{"dog_name":"Рекс","dog_name":null}', "Имя собаки неизвестно."),
])
def test_duplicate_control_keys_fail(case_id, raw, body):
    case = _case(case_id)
    calls = () if not case.required_tools else (
        _call("memory_search", {"query": "собака"}, {"results": []}),
    )
    result = evaluate_case(case, BenchmarkTurn(body + "\nCONTROL: " + raw, calls, 2))
    assert result.status == RUN_FAIL
    assert result.checks["control_parse"] is False
    assert "duplicate JSON key" in result.checks["control_error"]
    if case.safety_control_keys:
        assert result.safety is False


def test_nested_duplicate_keys_are_rejected_during_json_decode():
    from anima.benchmarks.tool_models import _split_control

    _, control, error = _split_control(
        'CONTROL: {"answer":102,"extra":[{"nested":{"key":1,"key":2}}]}'
    )
    assert control is None
    assert "duplicate JSON key" in error


def test_protocol_failure_is_excluded_from_completed_latency():
    case = _case("T01_no_tool_arithmetic")
    turn = BenchmarkTurn(_response({"answer": 102}), (), 1)
    summary = summarize_observations([
        RunObservation(case.id, 1, 100, turn, evaluate_case(case, turn)),
        RunObservation(case.id, 2, 1, None, evaluate_case(
            case, None, error="bad protocol", error_kind="model_protocol",
        )),
        RunObservation(case.id, 3, 2, None, evaluate_case(
            case, None, error="offline", error_kind="infrastructure",
        )),
    ])
    assert summary["latency_ms"]["pass"]["mean"] == 100
    assert summary["latency_ms"]["completed"]["mean"] == 100
    assert summary["latency_ms"]["completed"]["count"] == 1
    assert summary["latency_ms"]["error"]["mean"] == 2
    assert summary["metric_counts"]["passed"] == 2
    assert summary["metric_counts"]["routing"] == 1


OLD_COMPARISON_HEADER = (
    "run_id,model,adapter,parameters_b,quantization,model_size_mib,"
    "pass_rate,routing_rate,arguments_rate,protocol_rate,grounding_rate,safety_rate,"
    "mean_latency_ms,p95_latency_ms,rss_before_mib,rss_peak_mib,gpu_vram_peak_mib,"
    "total_runs,errors\r\n"
)


def test_old_comparison_schema_is_rejected_without_changing_bytes(tmp_path):
    from anima.benchmarks.tool_models import ComparisonSchemaMismatchError

    dest = tmp_path / "comparison.csv"
    original = OLD_COMPARISON_HEADER.encode() + b"old,evidence,untouched\r\n"
    dest.write_bytes(original)
    case = _case("T01_no_tool_arithmetic")
    turn = BenchmarkTurn(_response({"answer": 102}), (), 1)
    observation = RunObservation(case.id, 1, 100, turn, evaluate_case(case, turn))
    payload = {"run_id": "new", "model": {}, "summary": summarize_observations([observation])}
    with pytest.raises(ComparisonSchemaMismatchError, match="schema mismatch"):
        append_comparison_csv(dest, payload)
    assert dest.read_bytes() == original


def test_live_runner_preserves_runs_on_evaluator_error_and_schema_mismatch(
    tmp_path, monkeypatch, capsys,
):
    import scripts.benchmark_tool_models as runner

    case = _case("T01_no_tool_arithmetic")
    original_csv = OLD_COMPARISON_HEADER.encode()
    (tmp_path / "comparison.csv").write_bytes(original_csv)
    (tmp_path / "comparison.md").write_bytes(b"existing comparison")
    monkeypatch.setattr(runner, "check_server", lambda *args: None)
    monkeypatch.setattr(runner, "discover_llama_server_pid", lambda: None)
    monkeypatch.setattr(runner, "build_qwen_agent_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(runner, "benchmark_cases", lambda: (case,))

    class FakeLoop:
        def __init__(self, **kwargs):
            pass

        def run(self, query):
            return BenchmarkTurn(_response({"answer": 102}), (), 1)

    monkeypatch.setattr(runner, "QwenAgentToolLoop", FakeLoop)
    evaluations = 0

    def broken_once(*args, **kwargs):
        nonlocal evaluations
        evaluations += 1
        if evaluations == 2:
            raise RuntimeError("synthetic evaluator defect")
        return evaluate_case(*args, **kwargs)

    monkeypatch.setattr(runner, "evaluate_case", broken_once)
    monkeypatch.setattr("sys.argv", [
        "benchmark_tool_models.py", "--output-dir", str(tmp_path), "--repeats", "3",
    ])
    runner.main()
    results = list(tmp_path.glob("*/results.json"))
    assert len(results) == 1
    payload = json.loads(results[0].read_text())
    observations = payload["observations"]
    assert [item["evaluation"]["status"] for item in observations] == [RUN_PASS, RUN_ERROR, RUN_PASS]
    error = observations[1]
    assert error["error_kind"] == "benchmark_evaluator"
    assert "Benchmark evaluator failed" in error["error"]
    assert "synthetic evaluator defect" in error["error"]
    assert error["turn"]["response_text"] == _response({"answer": 102})
    assert error["evaluation"]["grounding"] is None
    assert payload["summary"]["metric_counts"]["passed"] == 2
    assert payload["summary"]["latency_ms"]["completed"]["count"] == 3
    assert (results[0].parent / "cases.csv").is_file()
    assert (results[0].parent / "report.md").is_file()
    assert (tmp_path / "comparison.csv").read_bytes() == original_csv
    assert (tmp_path / "comparison.md").read_bytes() == b"existing comparison"
    assert "cumulative comparison not updated due to schema mismatch" in capsys.readouterr().out


@pytest.mark.parametrize("name,args", [
    ("memory_search", {"query": "кофе", "ignored": float("nan")}),
    ("memory_search", {"query": "кофе", "ignored": {"x": [float("inf")]}}),
    ("memory_search", {"query": "кофе", "ignored": float("-inf")}),
    ("memory_search", {"query": "кофе", "extra": 1}),
    ("memory_search", {"query": "кофе", "limit": True}),
    ("memory_search", {"query": "кофе", "limit": 0}),
    ("memory_search", {"query": "кофе", "limit": 7}),
    ("memory_search", {"query": "кофе", "limit": 1.0}),
    ("memory_search", {"query": " "}),
    ("memory_search", {}),
    ("memory_search", {"query": None}),
    ("memory_search", {"query": "\ud800"}),
    ("memory_get", {"object_id": "bad"}),
    ("memory_get", {"object_id": M_COFFEE, "extra": 0}),
    ("memory_get", {}),
    ("state_read", {"extra": 0}),
    ("state_read", []),
])
def test_benchmark_rejects_invalid_arguments_before_execution_or_trace(tmp_path, monkeypatch, name, args):
    from anima.cognition.qwen_agent_tools import AnimaReadOnlyToolGateway, QwenToolProtocolError

    gateway = build_gateway(tmp_path)
    def forbidden_execution(*args):
        pytest.fail("invalid arguments reached production gateway")
    monkeypatch.setattr(AnimaReadOnlyToolGateway, "execute", forbidden_execution)
    with pytest.raises(QwenToolProtocolError):
        gateway.execute(name, args)
    assert gateway.executed_calls == []


def _offline_runner(monkeypatch, tmp_path, cases, llm):
    import scripts.benchmark_tool_models as runner
    monkeypatch.setattr(runner, "check_server", lambda *args: None)
    monkeypatch.setattr(runner, "discover_llama_server_pid", lambda: None)
    monkeypatch.setattr(runner, "build_qwen_agent_chat_model", lambda **kwargs: llm)
    monkeypatch.setattr(runner, "benchmark_cases", lambda: cases)
    monkeypatch.setattr("sys.argv", ["benchmark_tool_models.py", "--output-dir", str(tmp_path)])
    return runner


def test_runner_preserves_evidence_and_continues_after_nonfinite_arguments(tmp_path, monkeypatch):
    class FakeLLM:
        def __init__(self):
            self.calls = 0
        def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return [{"function_call": {"name": "memory_search", "arguments":
                    '{"query":"кофе","ignored":NaN}'}}]
            return [{"content": 'CONTROL: {"answer":102}'}]

    llm = FakeLLM()
    runner = _offline_runner(monkeypatch, tmp_path, (
        _case("T04_memory_search_personal"), _case("T01_no_tool_arithmetic")), llm)
    runner.main()
    report = next(tmp_path.glob("*/results.json"))
    payload = json.loads(report.read_text())
    assert [x["evaluation"]["status"] for x in payload["observations"]] == [RUN_FAIL, RUN_PASS]
    failed = payload["observations"][0]
    assert failed["error_kind"] == "model_protocol"
    assert failed["partial_tool_calls"] == []
    assert payload["summary"]["metric_counts"]["grounding"] == 1
    for name in ("results.json", "cases.csv", "report.md"):
        assert (report.parent / name).stat().st_size > 0


def test_csv_append_without_final_newline_preserves_records(tmp_path):
    import csv
    case = _case("T01_no_tool_arithmetic")
    turn = BenchmarkTurn(_response({"answer": 102}), (), 1)
    payload = {"run_id": "first", "model": {}, "summary": summarize_observations([
        RunObservation(case.id, 1, 10, turn, evaluate_case(case, turn))])}
    path = tmp_path / "comparison.csv"
    append_comparison_csv(path, payload)
    original = list(csv.reader(path.open(newline="")))
    path.write_bytes(path.read_bytes().rstrip(b"\r\n"))
    append_comparison_csv(path, {**payload, "run_id": "second"})
    with path.open(newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[:2] == original
    assert len(rows) == 3
    assert all(len(row) == len(rows[0]) for row in rows)
    assert rows[2][0] == "second"


def test_runs_with_identical_datetime_keep_independent_evidence(tmp_path, monkeypatch):
    import csv
    from datetime import datetime, timezone
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    class FakeLLM:
        answer = 102
        def chat(self, **kwargs):
            return [{"content": _response({"answer": self.answer})}]
    llm = FakeLLM()
    runner = _offline_runner(monkeypatch, tmp_path, (_case("T01_no_tool_arithmetic"),), llm)
    monkeypatch.setattr(runner, "datetime", FrozenDatetime)
    runner.main()
    first = next(tmp_path.glob("*/results.json"))
    original = {name: (first.parent / name).read_bytes()
                for name in ("results.json", "cases.csv", "report.md")}
    llm.answer = 0
    runner.main()
    reports = list(tmp_path.glob("*/results.json"))
    assert len(reports) == 2
    payloads = [json.loads(p.read_text()) for p in reports]
    assert len({p["run_id"] for p in payloads}) == 2
    assert {p["observations"][0]["evaluation"]["status"] for p in payloads} == {RUN_PASS, RUN_FAIL}
    for report in reports:
        for name in original:
            assert (report.parent / name).is_file()
    for name, data in original.items():
        assert (first.parent / name).read_bytes() == data
    with (tmp_path / "comparison.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["run_id"] for row in rows} == {p["run_id"] for p in payloads}


def test_t09_rejects_premature_get_even_after_recovery():
    case = _case("T09_sequential_search_get")
    get = _call("memory_get", {"object_id": M_FAST_BOUNDARY},
                {"found": True, "object": {"id": M_FAST_BOUNDARY}}, round_index=1)
    search = _call("memory_search", {"query": "FAST"},
                   {"results": [{"id": M_FAST_BOUNDARY}]}, round_index=2)
    later = _call("memory_get", get.arguments, get.result, round_index=3)
    result = evaluate_case(case, BenchmarkTurn(_response(dict(case.control_expectations)),
                                             (get, search, later), 4))
    assert result.status == RUN_FAIL
    assert result.checks["search_get_round_dependency"] is False


@pytest.mark.parametrize("case_id", ["T03_memory_get_exact", "T09_sequential_search_get"])
def test_get_id_outer_whitespace_matches_gateway_contract(tmp_path, case_id):
    case = _case(case_id)
    gateway = build_gateway(tmp_path)
    target = case.expected_get_id
    calls = []
    if case.require_get_after_search_round:
        calls.append(_call("memory_search", {"query": "FAST"},
                           {"results": [{"id": target}]}, round_index=1))
    args = {"object_id": "  " + target + "  "}
    result = json.loads(gateway.execute("memory_get", args))
    assert result["object"]["id"] == target
    calls.append(_call("memory_get", args, result, round_index=2))
    assert evaluate_case(case, BenchmarkTurn(_response(dict(case.control_expectations)),
                                           tuple(calls), 3)).status == RUN_PASS


def test_t08_query_does_not_supply_the_expected_choice():
    case = _case("T08_retrieval_plus_reasoning")
    assert "Выбор: <вариант>." in case.query
    assert case.expected_body not in case.query
    assert '"choice":"эспрессо"' not in case.query
    assert case.expected_search_ids == (M_COFFEE,)


def test_runner_preserves_evidence_for_unpaired_unicode(tmp_path, monkeypatch):
    class FakeLLM:
        def chat(self, **kwargs):
            return [{"content": '\ud800\nCONTROL: {"answer":102}'}]
    runner = _offline_runner(monkeypatch, tmp_path, (_case("T01_no_tool_arithmetic"),), FakeLLM())
    runner.main()
    report = next(tmp_path.glob("*/results.json"))
    payload = json.loads(report.read_text())
    assert payload["observations"][0]["evaluation"]["status"] == RUN_FAIL
    assert payload["observations"][0]["turn"]["response_text"].startswith('\ud800')
    assert (report.parent / "cases.csv").is_file()
    assert (report.parent / "report.md").is_file()


@pytest.mark.parametrize("variant", ["same_round", "get_before_search", "wrong_id", "id_absent"])
def test_t09_rejects_invalid_dependencies(variant):
    case = _case("T09_sequential_search_get")
    search = _call("memory_search", {"query": "FAST"},
                   {"results": [{"id": M_FAST_BOUNDARY}]}, round_index=1)
    get = _call("memory_get", {"object_id": M_FAST_BOUNDARY},
                {"found": True, "object": {"id": M_FAST_BOUNDARY}}, round_index=2)
    if variant == "same_round":
        get = _call(get.name, get.arguments, get.result, round_index=1)
    elif variant == "get_before_search":
        search = _call(search.name, search.arguments, search.result, round_index=3)
    elif variant == "wrong_id":
        get = _call(get.name, {"object_id": M_COFFEE},
                    {"found": True, "object": {"id": M_COFFEE}}, round_index=2)
    else:
        search = _call(search.name, search.arguments, {"results": [{"id": M_COFFEE}]})
    calls = (get, search) if variant == "get_before_search" else (search, get)
    assert evaluate_case(case, BenchmarkTurn(_response(dict(case.control_expectations)),
                                           calls, 4)).status == RUN_FAIL


@pytest.mark.parametrize("case_id,contradiction", [
    ("T05_missing_personal_fact", "Собаку зовут Рекс."),
    ("T08_retrieval_plus_reasoning", "Выбор: Чай."),
])
def test_runner_scores_and_preserves_all_final_messages(tmp_path, monkeypatch, case_id, contradiction):
    import csv
    case = _case(case_id)
    correct = _response(dict(case.control_expectations), body=case.expected_body)
    class FakeLLM:
        calls = 0
        def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return [{"function_call": {"name": "memory_search", "arguments":
                    '{"query":"кофе собака","limit":6}'}}]
            return [{"role": "assistant", "content": contradiction},
                    {"role": "assistant", "content": correct}]
    runner = _offline_runner(monkeypatch, tmp_path, (case,), FakeLLM())
    runner.main()
    report = next(tmp_path.glob("*/results.json"))
    payload = json.loads(report.read_text())
    item = payload["observations"][0]
    assert item["evaluation"]["status"] == RUN_FAIL
    assert item["evaluation"]["arguments"] is True
    assert item["evaluation"]["routing"] is True
    assert item["evaluation"]["checks"]["body_contract"] is False
    assert item["turn"]["response_text"] == contradiction + "\n" + correct
    with (report.parent / "cases.csv").open(newline="") as handle:
        row = next(csv.DictReader(handle))
    assert contradiction in row["response"]
    assert (report.parent / "report.md").is_file()


@pytest.mark.parametrize("malformed", [[], ["invalid"], True, False, 123, "memory_search",
                                        {}, {"name": None}, {"name": 123}, {"name": ""}])
def test_runner_malformed_function_call_is_scored_fail_and_continues(tmp_path, monkeypatch, malformed):
    class FakeLLM:
        calls = 0
        def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return [{"function_call": malformed}]
            return [{"content": 'CONTROL: {"answer":102}'}]
    case = _case("T01_no_tool_arithmetic")
    runner = _offline_runner(monkeypatch, tmp_path, (case, case), FakeLLM())
    runner.main()
    report = next(tmp_path.glob("*/results.json"))
    payload = json.loads(report.read_text())
    first, second = payload["observations"]
    assert first["evaluation"]["status"] == RUN_FAIL
    assert first["evaluation"]["protocol"] is False
    assert first["error_kind"] == "model_protocol"
    assert first["evaluation"]["checks"]["run_completed"] is False
    assert second["evaluation"]["status"] == RUN_PASS
    assert payload["summary"]["status_counts"] == {"PASS": 1, "FAIL": 1, "ERROR": 0}
    assert payload["summary"]["metric_counts"]["protocol"] == 2
    assert payload["summary"]["metrics"]["protocol"] == 0.5
    assert payload["summary"]["latency_ms"]["completed"]["count"] == 1
    assert payload["summary"]["latency_ms"]["pass"]["count"] == 1
    for name in ("results.json", "cases.csv", "report.md"):
        assert (report.parent / name).is_file()
