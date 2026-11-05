"""Human and Markdown views over existing immutable JSONL demo evidence.

Rendering is not an authority: checks are based on the recorded outcomes,
never fed back into Goal decision, Belief admission or tool execution.
"""

from pathlib import Path


_DECISIONS = {
    "PROPOSE_ACTION": "предложить действие",
    "NOOP": "действие не требуется",
    "REQUEST_OBSERVATION": "запросить наблюдение",
    "DEFER": "отложить",
}
_REASONS = {
    "TARGET_DIFFERS": "состояние отличается от цели",
    "TARGET_ALREADY_OBSERVED": "нужное состояние уже наблюдалось",
    "GOAL_SATISFIED": "цель подтверждена новым наблюдением",
    "NO_EFFECT_REQUIRED": "цель подтверждена без изменения мира",
    "BELIEF_NOT_ACTIONABLE": "данных недостаточно для действия",
    "PERSISTED_VERIFICATION_PROOF": "восстановлено ранее сохранённое подтверждение",
}
_TRANSLATIONS = {
    "open": "открыта",
    "closed": "закрыта",
    "completed": "завершена",
    "active": "активна",
    "known": "известно",
}


def _name(value):
    return _TRANSLATIONS.get(value, str(value))


def _short(value):
    if value is None:
        return "—"
    if not isinstance(value, str):
        return str(value)
    # Stable short visual referent; full ID remains in original machine record.
    return value if len(value) <= 24 else value[:17] + "…"


def _sections(records):
    if not isinstance(records, (list, tuple)) or not records:
        raise ValueError("Empty demo trace")
    groups = {}
    for record in records:
        stage = record.get("stage")
        groups.setdefault(stage, []).append(record)
    if (
        len(groups.get("bootstrap", [])) != 1
        or len(groups.get("goal_registered", [])) != 1
        or len(groups.get("result", [])) != 1
    ):
        raise ValueError("Demo trace is missing its required stages")
    return groups


def evaluate(records):
    """Return deterministic acceptance checks for the narrow one-door demo."""
    g = _sections(records)
    bootstrap, result = g["bootstrap"][0], g["result"][0]
    operations = g.get("execution_ledger", [])
    attempts = g.get("scheduler_attempt", [])
    initial = bootstrap["initial_state"]
    checks = {
        "goal_completed": result["goal_status"] == "completed",
        "task_completed": result["task_statuses"] == ["completed"],
        "belief_matches_goal": (
            result["belief_status"] == "known"
            and result["belief_value"] == {"type": "symbol", "value": "closed"}
        ),
        "independent_world_readback": result["operator_ground_truth"] == "closed",
        "verified_scheduler_outcome": (
            len(attempts) == 1
            and attempts[0]["status"] == "finished"
            and attempts[0]["outcome"] == "VERIFIED_SUCCESS"
            and bool(attempts[0]["evidence_event_id"])
        ),
        "expected_effect_count": (
            (initial == "open" and len(operations) == 1
             and operations[0]["status"] == "succeeded")
            or (initial == "closed" and len(operations) == 0)
        ),
        "no_pending_triggers": result["pending_auto_triggers"] == 0,
    }
    return checks


def render_text(records):
    """Terminal-friendly Russian timeline plus explicit checks; no ANSI dependency."""
    g = _sections(records)
    boot, result = g["bootstrap"][0], g["result"][0]
    checks = evaluate(records)
    attempt = g["scheduler_attempt"][0] if g.get("scheduler_attempt") else None
    goal_id = g["goal_registered"][0]["goal_id"]

    lines = [
        "ANIMA  /  CORE v0.1  /  DEMO P3-C",
        "═" * 51,
        f"Начальное состояние двери : {_name(boot['initial_state'])}",
        "Цель                       : закрыть дверь один раз",
        f"Goal ID                    : {_short(goal_id)}",
        "",
        "ХОД ВЫПОЛНЕНИЯ",
    ]
    for index, row in enumerate(g.get("decision", []), start=1):
        kind = row["decision"]
        note = _REASONS.get(row.get("reason_code"), row.get("reason_code", ""))
        lines.append(
            f"  {index}. {_DECISIONS.get(kind, kind)}"
            f"  [Belief rev. {row.get('belief_revision', '—')}]"
        )
        lines.append(f"     Причина: {note}")
    if g.get("execution_ledger"):
        for op in g["execution_ledger"]:
            lines.append(
                f"  → Исполнение: {op['status']}; "
                f"идемпотентность: {op['idempotency_class']}"
            )
    else:
        lines.append("  → Исполнение: операция не потребовалась")
    if attempt:
        lines.append(
            "  → Проверка: "
            + _REASONS.get(attempt["reason_code"], attempt["reason_code"])
        )
        lines.append("    Evidence: " + _short(attempt.get("evidence_event_id")))
    lines.extend([
        "",
        "ИТОГ",
        f"  Goal  : {_name(result['goal_status'])}",
        f"  Task  : {', '.join(map(_name, result['task_statuses']))}",
        f"  Belief: {_name(result['belief_status'])}, "
        f"{_name((result['belief_value'] or {}).get('value'))}",
        f"  Мир*  : {_name(result['operator_ground_truth'])}",
        f"  Эффектов: {len(g.get('execution_ledger', []))} | "
        f"Ожидающих триггеров: {result['pending_auto_triggers']}",
        "",
        "ПРОВЕРКИ",
    ])
    for name, ok in checks.items():
        lines.append(f"  {'✓' if ok else '✗'} {name}")
    lines.append("")
    lines.append("РЕЗУЛЬТАТ: " + ("PASS" if all(checks.values()) else "FAIL"))
    lines.append("* Мир — привилегированная проверка оператора, не вход Belief.")
    return "\n".join(lines) + "\n"


def render_markdown(records, *, snapshot=None):
    """Portable evidence report; machine trace remains the source of raw IDs."""
    g = _sections(records)
    boot, result = g["bootstrap"][0], g["result"][0]
    checks = evaluate(records)
    verdict = "PASS" if all(checks.values()) else "FAIL"
    goal_id = g["goal_registered"][0]["goal_id"]
    lines = [
        "# ANIMA Core v0.1 — Demonstration P3-C",
        "",
        f"**Result:** {verdict}  ",
        f"**Initial door:** `{boot['initial_state']}`  ",
        f"**Goal ID:** `{goal_id}`  ",
        f"**Commit:** `{snapshot or 'not recorded'}`  ",
        "**Scope:** one registered door; no LLM, no background service.",
        "",
        "## Timeline",
        "",
        "| # | Event | Reason / evidence |",
        "|---:|---|---|",
    ]
    i = 0
    for row in g.get("decision", []):
        i += 1
        lines.append(
            f"| {i} | `{row['decision']}` (Belief r{row['belief_revision']}) |"
            f" `{row['reason_code']}` |"
        )
    for op in g.get("execution_ledger", []):
        i += 1
        lines.append(
            f"| {i} | Execution `{op['status']}` |"
            f" `{op['operation_id']}` / `{op['idempotency_class']}` |"
        )
    for row in g.get("scheduler_attempt", []):
        i += 1
        lines.append(
            f"| {i} | `{row['outcome']}` | `{row['reason_code']}`;"
            f" evidence `{row['evidence_event_id']}` |"
        )
    lines.extend([
        "",
        "## Final state",
        "",
        f"- Goal: `{result['goal_status']}`",
        f"- Tasks: `{result['task_statuses']}`",
        f"- Belief: `{result['belief_status']}`, "
        f"`{result['belief_value']}`",
        f"- Operator world ground truth*: `{result['operator_ground_truth']}`",
        f"- Pending triggers: `{result['pending_auto_triggers']}`",
        "",
        "## Acceptance checks",
        "",
    ])
    lines.extend(f"- [{'x' if ok else ' '}] `{name}`" for name, ok in checks.items())
    lines.extend([
        "",
        "*Ground truth is available only to the test operator, "
        "not provided to the ANIMA decision pipeline.*",
        "",
        "Evidence limits: this is a one-case demonstration, not a P4 soak test, "
        "real device validation, or proof of general autonomy.",
        "",
    ])
    return "\n".join(lines)


def save_markdown(records, destination: str | Path, *, snapshot=None):
    """Explicit, non-overwriting report write outside any Core state store."""
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create prevents overwriting even if another process races us.
    with path.open("x", encoding="utf-8") as handle:
        handle.write(render_markdown(records, snapshot=snapshot))
    return path


__all__ = ["evaluate", "render_text", "render_markdown", "save_markdown"]
