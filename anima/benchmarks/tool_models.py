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
    required_all_terms: tuple[str, ...] = ()
    required_any_groups: tuple[tuple[str, ...], ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    missing_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseEvaluation:
    passed: bool
    routing: bool
    arguments: bool
    protocol: bool
    grounding: bool
    safety: bool
    checks: dict


@dataclass(frozen=True)
class RunObservation:
    case_id: str
    repeat: int
    latency_ms: float
    turn: BenchmarkTurn | None
    evaluation: CaseEvaluation
    error: str | None = None


def _contains(text: str, fragment: str) -> bool:
    return fragment.casefold() in text.casefold()


def _contains_any(text: str, fragments: tuple[str, ...]) -> bool:
    return any(_contains(text, fragment) for fragment in fragments)


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


def evaluate_case(
    case: BenchmarkCase,
    turn: BenchmarkTurn | None,
    *,
    error: str | None = None,
) -> CaseEvaluation:
    """Score one scenario on independent capability dimensions."""

    if error is not None or turn is None:
        checks = {
            "run_completed": False,
            "required_tools": False,
            "forbidden_tools": False,
            "ordered_tools": False,
            "arguments": False,
            "grounding": False,
            "safety": False,
        }
        return CaseEvaluation(
            passed=False,
            routing=False,
            arguments=False,
            protocol=False,
            grounding=False,
            safety=False,
            checks=checks,
        )

    tool_names = [call.name for call in turn.tool_calls]
    response = turn.response_text or ""

    required_tools_ok = all(name in tool_names for name in case.required_tools)
    forbidden_tools_ok = all(name not in tool_names for name in case.forbidden_tools)
    ordered_tools_ok = _is_subsequence(case.ordered_tools, tool_names)
    routing = required_tools_ok and forbidden_tools_ok and ordered_tools_ok

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
            and call.arguments.get("object_id") == case.expected_get_id
            and isinstance(call.result, dict)
            and call.result.get("found") is True
            for call in turn.tool_calls
        )
        argument_checks["expected_get_id"] = matching_get
        arguments_ok = arguments_ok and matching_get

    required_all_ok = all(_contains(response, term) for term in case.required_all_terms)
    required_groups_ok = all(
        _contains_any(response, group)
        for group in case.required_any_groups
    )
    grounding = required_all_ok and required_groups_ok

    forbidden_terms_ok = all(
        not _contains(response, term) for term in case.forbidden_terms
    )
    missing_info_ok = (
        True if not case.missing_terms else _contains_any(response, case.missing_terms)
    )
    safety = forbidden_terms_ok and missing_info_ok

    protocol = True
    checks = {
        "run_completed": True,
        "required_tools": required_tools_ok,
        "forbidden_tools": forbidden_tools_ok,
        "ordered_tools": ordered_tools_ok,
        "arguments": argument_checks,
        "required_all_terms": required_all_ok,
        "required_any_groups": required_groups_ok,
        "forbidden_terms": forbidden_terms_ok,
        "missing_information": missing_info_ok,
    }

    passed = all((routing, arguments_ok, protocol, grounding, safety))
    return CaseEvaluation(
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


def summarize_observations(observations: list[RunObservation]) -> dict:
    if not observations:
        raise ValueError("at least one observation is required")

    metric_names = ("passed", "routing", "arguments", "protocol", "grounding", "safety")
    rates = {
        name: sum(bool(getattr(item.evaluation, name)) for item in observations) / len(observations)
        for name in metric_names
    }
    latencies = [item.latency_ms for item in observations]
    errors = sum(item.error is not None for item in observations)

    by_case = {}
    for item in observations:
        bucket = by_case.setdefault(item.case_id, {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(item.evaluation.passed)

    return {
        "total_runs": len(observations),
        "errors": errors,
        "metrics": rates,
        "latency_ms": {
            "mean": statistics.fmean(latencies),
            "median": statistics.median(latencies),
            "p95": percentile(latencies, 0.95),
            "min": min(latencies),
            "max": max(latencies),
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
        "evaluation": asdict(item.evaluation),
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


def write_case_csv(path: str | Path, observations: list[RunObservation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "repeat",
        "passed",
        "routing",
        "arguments",
        "protocol",
        "grounding",
        "safety",
        "latency_ms",
        "rounds",
        "tool_calls",
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
                    "passed": int(item.evaluation.passed),
                    "routing": int(item.evaluation.routing),
                    "arguments": int(item.evaluation.arguments),
                    "protocol": int(item.evaluation.protocol),
                    "grounding": int(item.evaluation.grounding),
                    "safety": int(item.evaluation.safety),
                    "latency_ms": f"{item.latency_ms:.3f}",
                    "rounds": "" if turn is None else turn.rounds,
                    "tool_calls": "" if turn is None else ">".join(call.name for call in turn.tool_calls),
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


def render_markdown_report(payload: dict) -> str:
    model = payload["model"]
    summary = payload["summary"]
    resources = payload.get("resources", {})
    lines = [
        "# ANIMA Tool Model Benchmark",
        "",
        f"- Model: `{model.get('name')}`",
        f"- Adapter: `{model.get('adapter')}`",
        f"- Parameters: `{model.get('parameters_b')}` B",
        f"- Quantization: `{model.get('quantization')}`",
        f"- Repeats: `{payload.get('repeats')}`",
        "",
        "## Quality",
        "",
        "| Metric | Result |",
        "|---|---:|",
    ]
    for key in ("passed", "routing", "arguments", "protocol", "grounding", "safety"):
        lines.append(f"| {key} | {summary['metrics'][key] * 100:.1f}% |")

    latency = summary["latency_ms"]
    lines.extend(
        [
            "",
            "## Performance and resources",
            "",
            "| Metric | Result |",
            "|---|---:|",
            f"| Model file | {_fmt(resources.get('model_size_mib'), ' MiB')} |",
            f"| Mean scenario latency | {_fmt(latency.get('mean'), ' ms')} |",
            f"| Median scenario latency | {_fmt(latency.get('median'), ' ms')} |",
            f"| P95 scenario latency | {_fmt(latency.get('p95'), ' ms')} |",
            f"| Server RSS before | {_fmt(resources.get('rss_before_mib'), ' MiB')} |",
            f"| Server peak RSS during run | {_fmt(resources.get('rss_peak_mib'), ' MiB')} |",
            f"| Server VmHWM | {_fmt(resources.get('vmhwm_mib'), ' MiB')} |",
            f"| Peak NVIDIA VRAM | {_fmt(resources.get('gpu_vram_peak_mib'), ' MiB')} |",
            "",
            "## Cases",
            "",
            "| Case | Repeat | Pass | Routing | Args | Protocol | Grounding | Safety | Latency ms | Tools |",
            "|---|---:|:---:|:---:|:---:|:---:|:---:|:---:|---:|---|",
        ]
    )
    for item in payload["observations"]:
        evaluation = item["evaluation"]
        turn = item.get("turn") or {}
        tool_calls = ">".join(call["name"] for call in turn.get("tool_calls", [])) or "—"
        lines.append(
            "| {case} | {repeat} | {passed} | {routing} | {arguments} | {protocol} | "
            "{grounding} | {safety} | {latency:.1f} | {tools} |".format(
                case=item["case_id"],
                repeat=item["repeat"],
                passed=_mark(evaluation["passed"]),
                routing=_mark(evaluation["routing"]),
                arguments=_mark(evaluation["arguments"]),
                protocol=_mark(evaluation["protocol"]),
                grounding=_mark(evaluation["grounding"]),
                safety=_mark(evaluation["safety"]),
                latency=item["latency_ms"],
                tools=tool_calls,
            )
        )
    lines.append("")
    return "\n".join(lines)


def _mark(value: bool) -> str:
    return "✅" if value else "❌"


def _fmt(value, suffix: str) -> str:
    if value is None:
        return "not measured"
    return f"{float(value):.1f}{suffix}"


def append_comparison_csv(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    model = payload["model"]
    summary = payload["summary"]
    resources = payload.get("resources", {})
    latency = summary["latency_ms"]
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
        "mean_latency_ms": latency["mean"],
        "p95_latency_ms": latency["p95"],
        "rss_before_mib": resources.get("rss_before_mib"),
        "rss_peak_mib": resources.get("rss_peak_mib"),
        "gpu_vram_peak_mib": resources.get("gpu_vram_peak_mib"),
        "total_runs": summary["total_runs"],
        "errors": summary["errors"],
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
        "| Model | Params B | Quant | Size MiB | Pass | Routing | Args | Protocol | Grounding | Safety | Mean ms | P95 ms | Peak RSS MiB | Peak VRAM MiB |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {model} | {params} | {quant} | {size} | {passed} | {routing} | {args} | {protocol} | {grounding} | {safety} | {mean} | {p95} | {rss} | {vram} |".format(
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
                mean=_csv_number(row.get("mean_latency_ms")),
                p95=_csv_number(row.get("p95_latency_ms")),
                rss=_csv_number(row.get("rss_peak_mib")),
                vram=_csv_number(row.get("gpu_vram_peak_mib")),
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
    "BenchmarkCase",
    "BenchmarkTurn",
    "CaseEvaluation",
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
