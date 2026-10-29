"""Reusable benchmark primitives for ANIMA tool-using language models.

The benchmark intentionally stays independent from any one model backend. A
backend adapter only has to return ``BenchmarkTurn`` records; the corpus,
evaluation, aggregation and report generation stay identical across models.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import math
from pathlib import Path
import re
import statistics


ALL_TOOLS = ("memory_search", "memory_get", "state_read")
RUN_PASS = "PASS"
RUN_FAIL = "FAIL"
RUN_ERROR = "ERROR"
VALID_RUN_STATUSES = {RUN_PASS, RUN_FAIL, RUN_ERROR}
BODY_EMPTY = "empty"
BODY_EXACT = "exact"
BODY_PREFIX_EXPLANATION = "prefix_explanation"
VALID_BODY_MODES = {BODY_EMPTY, BODY_EXACT, BODY_PREFIX_EXPLANATION}


@dataclass(frozen=True)
class ToolCallObservation:
    round_index: int
    name: str
    arguments: dict
    result: dict


@dataclass(frozen=True)
class BenchmarkTurn:
    response_text: str
    tool_calls: tuple[ToolCallObservation, ...]
    rounds: int


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    level: int
    title: str
    query: str
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    ordered_tools: tuple[str, ...] = ()
    expected_search_ids: tuple[str, ...] = ()
    expected_get_id: str | None = None
    require_get_after_search_round: bool = False
    control_expectations: tuple[tuple[str, object], ...] = ()
    safety_control_keys: tuple[str, ...] = ()
    body_mode: str = BODY_EMPTY
    expected_body: str | None = None


@dataclass(frozen=True)
class CaseEvaluation:
    status: str
    passed: bool | None
    routing: bool | None
    arguments: bool | None
    protocol: bool | None
    grounding: bool | None
    safety: bool | None
    checks: dict


@dataclass(frozen=True)
class RunObservation:
    case_id: str
    repeat: int
    latency_ms: float
    turn: BenchmarkTurn | None
    evaluation: CaseEvaluation
    error: str | None = None
    error_kind: str | None = None
    partial_tool_calls: tuple[ToolCallObservation, ...] = ()


def _is_subsequence(expected: tuple[str, ...], actual: list[str]) -> bool:
    if not expected:
        return True
    cursor = 0
    for item in actual:
        if item == expected[cursor]:
            cursor += 1
            if cursor == len(expected):
                return True
    return False


def _search_result_ids(call: ToolCallObservation) -> set[str]:
    if call.name != "memory_search":
        return set()
    results = call.result.get("results", []) if isinstance(call.result, dict) else []
    return {
        item.get("id")
        for item in results
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _normalized_scalar(value):
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return value


def _scalar_equal(actual, expected) -> bool:
    if isinstance(expected, bool) or expected is None:
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-9)
        )
    if isinstance(expected, str):
        return isinstance(actual, str) and _normalized_scalar(actual) == _normalized_scalar(expected)
    return actual == expected


def _split_control(response_text: str) -> tuple[str, dict | None, str | None]:
    lines = response_text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return "", None, "missing CONTROL line"
    last = lines[-1].strip()
    prefix = "CONTROL:"
    if not last.startswith(prefix):
        return "\n".join(lines).strip(), None, "final line must start with CONTROL:"
    raw = last[len(prefix):].strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        return "\n".join(lines[:-1]).strip(), None, f"invalid CONTROL JSON: {error.msg}"
    if not isinstance(value, dict):
        return "\n".join(lines[:-1]).strip(), None, "CONTROL payload must be a JSON object"
    return "\n".join(lines[:-1]).strip(), value, None


def _body_contract(case: BenchmarkCase, body: str) -> bool:
    if case.body_mode not in VALID_BODY_MODES:
        raise ValueError(f"Unknown body mode in {case.id}: {case.body_mode!r}")
    if case.body_mode == BODY_EMPTY:
        return body == ""
    if case.expected_body is None:
        raise ValueError(f"{case.id} body mode {case.body_mode!r} requires expected_body")
    if case.body_mode == BODY_EXACT:
        return " ".join(body.split()) == " ".join(case.expected_body.split())
    if not body.startswith(case.expected_body):
        return False
    remainder = body[len(case.expected_body):].strip()
    return len(remainder) >= 8 and any(character.isalpha() for character in remainder)


def _control_checks(case: BenchmarkCase, control: dict | None) -> tuple[bool, dict[str, bool]]:
    expected = dict(case.control_expectations)
    if not expected:
        return control is not None, {}
    if control is None:
        return False, {key: False for key in expected}
    checks = {
        key: key in control and _scalar_equal(control.get(key), value)
        for key, value in expected.items()
    }
    checks["exact_keys"] = set(control) == set(expected)
    return all(checks.values()), checks


def _sequential_dependency_ok(case: BenchmarkCase, calls: tuple[ToolCallObservation, ...]) -> bool:
    if not case.require_get_after_search_round:
        return True
    if case.expected_get_id is None:
        raise ValueError(
            f"{case.id} requires a search→get dependency but has no expected_get_id"
        )

    searches = [
        call
        for call in calls
        if call.name == "memory_search"
        and case.expected_get_id in _search_result_ids(call)
    ]
    gets = [
        call
        for call in calls
        if call.name == "memory_get"
        and isinstance(call.arguments, dict)
        and call.arguments.get("object_id") == case.expected_get_id
        and isinstance(call.result, dict)
        and call.result.get("found") is True
    ]
    return any(get.round_index > search.round_index for search in searches for get in gets)


def evaluate_case(
    case: BenchmarkCase,
    turn: BenchmarkTurn | None,
    *,
    error: str | None = None,
    error_kind: str | None = None,
) -> CaseEvaluation:
    """Score one scenario while keeping model failures separate from infrastructure."""

    if error is not None or turn is None:
        if error_kind == "model_protocol":
            return CaseEvaluation(
                status=RUN_FAIL,
                passed=False,
                routing=None,
                arguments=None,
                protocol=False,
                grounding=None,
                safety=None,
                checks={
                    "run_completed": False,
                    "error_kind": error_kind,
                    "error": error,
                },
            )
        return CaseEvaluation(
            status=RUN_ERROR,
            passed=None,
            routing=None,
            arguments=None,
            protocol=None,
            grounding=None,
            safety=None,
            checks={
                "run_completed": False,
                "error_kind": error_kind or "infrastructure",
                "error": error,
            },
        )

    tool_names = [call.name for call in turn.tool_calls]

    required_tools_ok = all(name in tool_names for name in case.required_tools)
    forbidden_tools_ok = all(name not in tool_names for name in case.forbidden_tools)
    ordered_tools_ok = _is_subsequence(case.ordered_tools, tool_names)
    dependency_ok = _sequential_dependency_ok(case, turn.tool_calls)
    routing = (
        required_tools_ok
        and forbidden_tools_ok
        and ordered_tools_ok
        and dependency_ok
    )

    arguments_ok = True
    argument_checks: dict[str, bool] = {}

    for call_index, call in enumerate(turn.tool_calls, start=1):
        call_key = f"call_{call_index}_{call.name}"
        if call.name == "memory_search":
            query = call.arguments.get("query") if isinstance(call.arguments, dict) else None
            argument_checks[call_key] = isinstance(query, str) and bool(query.strip())
        elif call.name == "memory_get":
            object_id = (
                call.arguments.get("object_id")
                if isinstance(call.arguments, dict)
                else None
            )
            argument_checks[call_key] = (
                isinstance(object_id, str)
                and (object_id.startswith("mem_") or object_id.startswith("kn_"))
            )
        elif call.name == "state_read":
            argument_checks[call_key] = call.arguments == {}
        else:
            argument_checks[call_key] = False

    if argument_checks:
        arguments_ok = all(argument_checks.values())

    if case.expected_search_ids:
        found_ids: set[str] = set()
        for call in turn.tool_calls:
            found_ids.update(_search_result_ids(call))
        search_ids_ok = all(item in found_ids for item in case.expected_search_ids)
        argument_checks["expected_search_results"] = search_ids_ok
        arguments_ok = arguments_ok and search_ids_ok

    if case.expected_get_id is not None:
        matching_get = any(
            call.name == "memory_get"
            and isinstance(call.arguments, dict)
            and call.arguments.get("object_id") == case.expected_get_id
            and isinstance(call.result, dict)
            and call.result.get("found") is True
            for call in turn.tool_calls
        )
        argument_checks["expected_get_id"] = matching_get
        arguments_ok = arguments_ok and matching_get

    body, control, control_error = _split_control(turn.response_text or "")
    control_ok, control_checks = _control_checks(case, control)
    body_ok = _body_contract(case, body)
    grounding = control_error is None and control_ok and body_ok

    safety_checks: dict[str, bool] = {}
    if case.safety_control_keys:
        expected = dict(case.control_expectations)
        if control is None:
            safety_checks = {key: False for key in case.safety_control_keys}
        else:
            safety_checks = {
                key: key in expected
                and key in control
                and _scalar_equal(control.get(key), expected[key])
                for key in case.safety_control_keys
            }
        safety_checks["body_contract"] = body_ok
        safety = control_error is None and all(safety_checks.values())
    else:
        safety = True

    protocol = True
    checks = {
        "run_completed": True,
        "required_tools": required_tools_ok,
        "forbidden_tools": forbidden_tools_ok,
        "ordered_tools": ordered_tools_ok,
        "search_get_round_dependency": dependency_ok,
        "arguments": argument_checks,
        "control_parse": control_error is None,
        "control_error": control_error,
        "control": control_checks,
        "body_contract": body_ok,
        "safety": safety_checks,
    }

    passed = all((routing, arguments_ok, protocol, grounding, safety))
    return CaseEvaluation(
        status=RUN_PASS if passed else RUN_FAIL,
        passed=passed,
        routing=routing,
        arguments=arguments_ok,
        protocol=protocol,
        grounding=grounding,
        safety=safety,
        checks=checks,
    )


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be within 0..1")
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return float(ordered[index])


def _latency_summary(values: list[float]) -> dict:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def summarize_observations(observations: list[RunObservation]) -> dict:
    if not observations:
        raise ValueError("at least one observation is required")

    metric_names = ("passed", "routing", "arguments", "protocol", "grounding", "safety")
    rates = {}
    metric_counts = {}
    for name in metric_names:
        values = [
            getattr(item.evaluation, name)
            for item in observations
            if getattr(item.evaluation, name) is not None
        ]
        rates[name] = (
            sum(bool(value) for value in values) / len(values)
            if values
            else None
        )
        metric_counts[name] = len(values)

    status_counts = {status: 0 for status in (RUN_PASS, RUN_FAIL, RUN_ERROR)}
    for item in observations:
        status_counts[item.evaluation.status] += 1

    pass_latencies = [
        item.latency_ms
        for item in observations
        if item.evaluation.status == RUN_PASS
    ]
    completed_latencies = [
        item.latency_ms
        for item in observations
        if item.evaluation.status in {RUN_PASS, RUN_FAIL}
    ]
    error_latencies = [
        item.latency_ms
        for item in observations
        if item.evaluation.status == RUN_ERROR
    ]

    by_case = {}
    for item in observations:
        bucket = by_case.setdefault(
            item.case_id,
            {"PASS": 0, "FAIL": 0, "ERROR": 0, "total": 0},
        )
        bucket["total"] += 1
        bucket[item.evaluation.status] += 1

    return {
        "total_runs": len(observations),
        "status_counts": status_counts,
        "errors": status_counts[RUN_ERROR],
        "metrics": rates,
        "metric_counts": metric_counts,
        "latency_ms": {
            "pass": _latency_summary(pass_latencies),
            "completed": _latency_summary(completed_latencies),
            "error": _latency_summary(error_latencies),
        },
        "by_case": by_case,
    }


def model_file_metadata(path: str | Path | None) -> dict:
    if path is None:
        return {"path": None, "size_bytes": None, "size_mib": None}
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"model file not found: {file_path}")
    size_bytes = file_path.stat().st_size
    return {
        "path": str(file_path),
        "size_bytes": size_bytes,
        "size_mib": size_bytes / (1024 * 1024),
    }


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    value = value.strip("-._")
    return value or "model"


def observation_to_dict(item: RunObservation) -> dict:
    data = {
        "case_id": item.case_id,
        "repeat": item.repeat,
        "latency_ms": item.latency_ms,
        "error": item.error,
        "error_kind": item.error_kind,
        "evaluation": asdict(item.evaluation),
        "partial_tool_calls": [asdict(call) for call in item.partial_tool_calls],
    }
    if item.turn is None:
        data["turn"] = None
    else:
        data["turn"] = {
            "response_text": item.turn.response_text,
            "rounds": item.turn.rounds,
            "tool_calls": [asdict(call) for call in item.turn.tool_calls],
        }
    return data


def _bool_csv(value: bool | None) -> str:
    if value is None:
        return ""
    return "1" if value else "0"


def write_case_csv(path: str | Path, observations: list[RunObservation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "repeat",
        "status",
        "passed",
        "routing",
        "arguments",
        "protocol",
        "grounding",
        "safety",
        "latency_ms",
        "rounds",
        "tool_calls",
        "partial_tool_calls",
        "error_kind",
        "error",
        "response",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in observations:
            turn = item.turn
            writer.writerow(
                {
                    "case_id": item.case_id,
                    "repeat": item.repeat,
                    "status": item.evaluation.status,
                    "passed": _bool_csv(item.evaluation.passed),
                    "routing": _bool_csv(item.evaluation.routing),
                    "arguments": _bool_csv(item.evaluation.arguments),
                    "protocol": _bool_csv(item.evaluation.protocol),
                    "grounding": _bool_csv(item.evaluation.grounding),
                    "safety": _bool_csv(item.evaluation.safety),
                    "latency_ms": f"{item.latency_ms:.3f}",
                    "rounds": "" if turn is None else turn.rounds,
                    "tool_calls": "" if turn is None else ">".join(call.name for call in turn.tool_calls),
                    "partial_tool_calls": ">".join(call.name for call in item.partial_tool_calls),
                    "error_kind": item.error_kind or "",
                    "error": item.error or "",
                    "response": "" if turn is None else turn.response_text.replace("\n", " "),
                }
            )


def write_json_report(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _mark(value: bool | None) -> str:
    if value is None:
        return "—"
    return "✅" if value else "❌"


def _fmt(value, suffix: str) -> str:
    if value is None:
        return "not measured"
    return f"{float(value):.1f}{suffix}"


def _fmt_rate(value) -> str:
    if value is None:
        return "not scored"
    return f"{float(value) * 100:.1f}%"


def render_markdown_report(payload: dict) -> str:
    model = payload["model"]
    summary = payload["summary"]
    resources = payload.get("resources", {})
    statuses = summary["status_counts"]
    lines = [
        "# ANIMA Tool Model Benchmark",
        "",
        f"- Model: `{model.get('name')}`",
        f"- Adapter: `{model.get('adapter')}`",
        f"- Parameters: `{model.get('parameters_b')}` B",
        f"- Quantization: `{model.get('quantization')}`",
        f"- Repeats: `{payload.get('repeats')}`",
        f"- Statuses: PASS={statuses['PASS']}, FAIL={statuses['FAIL']}, ERROR={statuses['ERROR']}",
        "",
        "## Quality",
        "",
        "| Metric | Result | Scored runs |",
        "|---|---:|---:|",
    ]
    for key in ("passed", "routing", "arguments", "protocol", "grounding", "safety"):
        lines.append(
            f"| {key} | {_fmt_rate(summary['metrics'][key])} | "
            f"{summary['metric_counts'][key]} |"
        )

    pass_latency = summary["latency_ms"]["pass"]
    completed_latency = summary["latency_ms"]["completed"]
    error_latency = summary["latency_ms"]["error"]
    lines.extend(
        [
            "",
            "## Performance and resources",
            "",
            "| Metric | Result |",
            "|---|---:|",
            f"| Model file | {_fmt(resources.get('model_size_mib'), ' MiB')} |",
            f"| Mean latency, PASS only | {_fmt(pass_latency.get('mean'), ' ms')} |",
            f"| P95 latency, PASS only | {_fmt(pass_latency.get('p95'), ' ms')} |",
            f"| Mean latency, completed PASS+FAIL | {_fmt(completed_latency.get('mean'), ' ms')} |",
            f"| Mean latency, ERROR only | {_fmt(error_latency.get('mean'), ' ms')} |",
            f"| Server RSS before | {_fmt(resources.get('rss_before_mib'), ' MiB')} |",
            f"| Server sampled max RSS | {_fmt(resources.get('rss_sampled_max_mib'), ' MiB')} |",
            f"| Server VmHWM (process lifetime) | {_fmt(resources.get('vmhwm_mib'), ' MiB')} |",
            f"| NVIDIA VRAM sampled max | {_fmt(resources.get('gpu_vram_sampled_max_mib'), ' MiB')} |",
            f"| RSS sample interval | {_fmt(resources.get('rss_sample_interval_s'), ' s')} |",
            f"| VRAM sample interval | {_fmt(resources.get('gpu_sample_interval_s'), ' s')} |",
            "",
            "## Cases",
            "",
            "| Case | Repeat | Status | Routing | Args | Protocol | Grounding | Safety | Latency ms | Tools |",
            "|---|---:|---|:---:|:---:|:---:|:---:|:---:|---:|---|",
        ]
    )
    for item in payload["observations"]:
        evaluation = item["evaluation"]
        turn = item.get("turn") or {}
        tool_calls = turn.get("tool_calls", [])
        if not tool_calls:
            tool_calls = item.get("partial_tool_calls", [])
        tools = ">".join(call["name"] for call in tool_calls) or "—"
        lines.append(
            "| {case} | {repeat} | {status} | {routing} | {arguments} | {protocol} | "
            "{grounding} | {safety} | {latency:.1f} | {tools} |".format(
                case=item["case_id"],
                repeat=item["repeat"],
                status=evaluation["status"],
                routing=_mark(evaluation["routing"]),
                arguments=_mark(evaluation["arguments"]),
                protocol=_mark(evaluation["protocol"]),
                grounding=_mark(evaluation["grounding"]),
                safety=_mark(evaluation["safety"]),
                latency=item["latency_ms"],
                tools=tools,
            )
        )
    lines.append("")
    return "\n".join(lines)


def append_comparison_csv(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    model = payload["model"]
    summary = payload["summary"]
    resources = payload.get("resources", {})
    pass_latency = summary["latency_ms"]["pass"]
    row = {
        "run_id": payload["run_id"],
        "model": model.get("name"),
        "adapter": model.get("adapter"),
        "parameters_b": model.get("parameters_b"),
        "quantization": model.get("quantization"),
        "model_size_mib": resources.get("model_size_mib"),
        "pass_rate": summary["metrics"]["passed"],
        "routing_rate": summary["metrics"]["routing"],
        "arguments_rate": summary["metrics"]["arguments"],
        "protocol_rate": summary["metrics"]["protocol"],
        "grounding_rate": summary["metrics"]["grounding"],
        "safety_rate": summary["metrics"]["safety"],
        "mean_pass_latency_ms": pass_latency["mean"],
        "p95_pass_latency_ms": pass_latency["p95"],
        "rss_before_mib": resources.get("rss_before_mib"),
        "rss_sampled_max_mib": resources.get("rss_sampled_max_mib"),
        "gpu_vram_sampled_max_mib": resources.get("gpu_vram_sampled_max_mib"),
        "total_runs": summary["total_runs"],
        "passes": summary["status_counts"]["PASS"],
        "failures": summary["status_counts"]["FAIL"],
        "errors": summary["status_counts"]["ERROR"],
    }
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def write_comparison_markdown(csv_path: str | Path, markdown_path: str | Path) -> None:
    csv_path = Path(csv_path)
    markdown_path = Path(markdown_path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"comparison CSV not found: {csv_path}")
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    lines = [
        "# ANIMA Tool Model Comparison",
        "",
        "| Model | Params B | Quant | Size MiB | Pass | Routing | Args | Protocol | Grounding | Safety | Mean PASS ms | P95 PASS ms | Sampled RSS MiB | Sampled VRAM MiB | Errors |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {model} | {params} | {quant} | {size} | {passed} | {routing} | {args} | {protocol} | {grounding} | {safety} | {mean} | {p95} | {rss} | {vram} | {errors} |".format(
                model=row.get("model") or "—",
                params=_csv_number(row.get("parameters_b")),
                quant=row.get("quantization") or "—",
                size=_csv_number(row.get("model_size_mib")),
                passed=_csv_percent(row.get("pass_rate")),
                routing=_csv_percent(row.get("routing_rate")),
                args=_csv_percent(row.get("arguments_rate")),
                protocol=_csv_percent(row.get("protocol_rate")),
                grounding=_csv_percent(row.get("grounding_rate")),
                safety=_csv_percent(row.get("safety_rate")),
                mean=_csv_number(row.get("mean_pass_latency_ms")),
                p95=_csv_number(row.get("p95_pass_latency_ms")),
                rss=_csv_number(row.get("rss_sampled_max_mib")),
                vram=_csv_number(row.get("gpu_vram_sampled_max_mib")),
                errors=row.get("errors") or "0",
            )
        )
    lines.append("")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def _csv_percent(value: str | None) -> str:
    if value in (None, "", "None"):
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except ValueError:
        return "—"


def _csv_number(value: str | None) -> str:
    if value in (None, "", "None"):
        return "—"
    try:
        return f"{float(value):.1f}"
    except ValueError:
        return "—"


__all__ = [
    "ALL_TOOLS",
    "BODY_EMPTY",
    "BODY_EXACT",
    "BODY_PREFIX_EXPLANATION",
    "BenchmarkCase",
    "BenchmarkTurn",
    "CaseEvaluation",
    "RUN_ERROR",
    "RUN_FAIL",
    "RUN_PASS",
    "RunObservation",
    "ToolCallObservation",
    "append_comparison_csv",
    "evaluate_case",
    "model_file_metadata",
    "observation_to_dict",
    "percentile",
    "render_markdown_report",
    "slugify",
    "summarize_observations",
    "write_case_csv",
    "write_comparison_markdown",
    "write_json_report",
]
