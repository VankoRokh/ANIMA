# ANIMA Core v0.1 — P1 Standalone Bootstrap (implementation slice)

**Статус:** P1 bootstrap **PASS** по предоставленным owner результатам локального прогона (2026-11-05). Проверена только сборка/жизненный цикл, **не** автономная работа. P0 / P2–P4 остаются отдельными контрольными точками.  
**Дата:** 2026-11-05.  
**Ветка:** `work/core-v0-1-p1-bootstrap` (происходит из `work/core-v0-1-planning`).  
**План:** [Core v0.1 + Virtual Lab](Core_v0_1_VAL_v0_1_Plan_Draft.md).  
**P0:** [Boundary & reuse audit](Core_v0_1_P0_Boundary_Draft.md).  
**Контракт Belief:** [Event/Observation/Belief](Core_v0_1_Event_Belief_Contract_Draft.md).  
**Контракт действий:** [Goal/Task/Decision/Execution/Verification](Core_v0_1_Goal_Decision_Execution_Contract_Draft.md).

## 1. P1 boundary

Цель P1 — одна и та же сборка проверенных компонентов Runtime в интерактивном CLI и headless smoke без LLM/GUI/Godot. Это **не** реализация `Observation→Belief→Decision→Action`; P2–P4 ещё не начаты.

## 2. Реализовано

- [`anima/core/assembly.py`](../../anima/core/assembly.py): `build_core(data_dir)` строит существующие Identity, AnimaState, EventBus, EventLog, Memory, InternalState и Runtime. `CoreAssembly` явно перечисляет components; создание объекта **не вызывает** `wake()`.
- [`main.py`](../../main.py): интерактивный CLI теперь использует ту же фабрику вместо собственного дублирующего composition root. Семантика `run_cli`, `wake/user_input/sleep` не меняется.
- [`anima/core/__main__.py`](../../anima/core/__main__.py): отдельный явный `--once` smoke с machine-readable JSON. В отчёте всегда `phase=P1_BOOTSTRAP_ONLY` и `autonomous_loop=false`.
- [`tests/test_core_p1_bootstrap.py`](../../tests/test_core_p1_bootstrap.py): no implicit wake, persistence, два запуска subprocess с общей Identity, отказ от запуска без `--once`.

**Не реализовано:** SQLite Core ingestion, BeliefStore, типизированные World Goals, autonomous scheduler, action adapter, verifier for world, automatic fault injection. Они остаются запланированными P2–P4. P1 намеренно использует существующие legacy EventLog/Memory semantics.

## 3. Прогоны (в корне репозитория)

Сначала посмотреть рабочее дерево:

```bash
git status --short
```

Проверка синтаксиса и документированной структуры:

```bash
bash scripts/check.sh
```

Прицельные тесты для P1 и сохранения прежнего поведения CLI:

```bash
.venv/bin/python -m pytest -q tests/test_core_p1_bootstrap.py tests/test_runtime.py tests/test_cli_session.py tests/test_d1_validation.py
```

Полная регрессия (обязательна до gate PASS):

```bash
.venv/bin/python -m pytest -q
```

Если `.venv` отсутствует, использовать установленный Python окружения проекта по [Operations](../OPERATIONS/README.md). Не подменять результаты запусков текстом документации.

Изолированный ручной smoke (не затрагивает `./data`; команда создаёт файлы только в заданной директории):

```bash
tmp_dir="$(mktemp -d)"
.venv/bin/python -m anima.core --once --data-dir "$tmp_dir"
.venv/bin/python -m anima.core --once --data-dir "$tmp_dir"
```

Ожидаемые структурные признаки:
- один `instance_id` в двух запусках;
- `status=sleeping` после каждого;
- `session` увеличивается с 1 до 2;
- `events_processed` с 2 до 4;
- `memories=0`;
- `autonomous_loop=false` (не замаскирована как готовая автономия).

**Предупреждение:** запуск без `--data-dir` пишет в `ANIMA_DATA_DIR` или каталог данных проекта; для демонстрации всегда задавать изолированную директорию.

## 4. P1 acceptance matrix

Сводная матрица P1-A…P1-G и доказательства её прохождения приведены в разделе 5 ниже.

**P1 bootstrap gate:** PASS по результатам локальных проверок владельца проекта; точный `git rev-parse HEAD` пользователь не приложил. Ветка в момент получения результатов указывала на commit `64e774bd561d41211f4e8666a1be004e326b4f44`, но его нельзя без дополнительного подтверждения объявлять точным исполненным snapshot. Статусы Stage и `docs/project.json` не изменяются. P0 replay/authority design и P2–P4 остаются открытыми.

## 5. Evidence — owner-reported local execution, 2026-11-05

Пользователь выполнил проверки локально и предоставил терминальный вывод. Ассистент **не** запускал тесты на своём окружении и не выдаёт эти результаты за CI.

- `bash scripts/check.sh`: PASS. Documentation: **87 pages**, **493 local links**; generated blocks current, architecture references valid; Python syntax **291 files**, VS Code JSON **3 files**, Bash syntax **3 files**; no instance/private data in tracked paths. Python **3.14.4**.
- Targeted `pytest` (P1/Runtime/CLI/D1): **9 passed in 0.57s**.
- Full `pytest -q`: **1252 passed in 18.48s**.
- Isolated smoke run 1: `phase=P1_BOOTSTRAP_ONLY`, `autonomous_loop=false`, `events_processed=2`, `session=1`, `status=sleeping`, `memories=0`.
- Isolated smoke run 2 (same data directory): same `instance_id`, `events_processed=4`, `session=2`, `status=sleeping`, `memories=0`.
- Identity (instance UUID) совпадает между двумя smoke-прогонами. Полный UUID намеренно не дублируется в отчёте: проверяется равенство, а не персональный ID.

| P1 gate | Verdict | Evidence |
|---|---|---|
| P1-A | PASS (targeted smoke + code review) | headless CLI запускается без обязательной модели/GUI |
| P1-B | PASS (targeted pytest) | `build_core` не вызывает wake автоматически |
| P1-C | PASS (smoke + pytest) | два события за wake→sleep |
| P1-D | PASS (smoke + pytest) | instance identity и жизненный цикл переживают рестарт |
| P1-E | PASS (targeted + full pytest) | CLI и D1 regression |
| P1-F | PASS (smoke + code review) | Sleep processor не required в bootstrap |
| P1-G | PASS (owner-local execution) | scripts/check.sh и full pytest |

**Границы доказательства:** не тестировались здесь ни real-world sensor inputs, ни Belief State, ни автономный Goal/Task→Action, ни cross-database crash recovery, ни долгосрочный soak-test. Точный коммит локального исполнения можно закрепить отдельно через `git rev-parse HEAD`.

## 6. Дальше

После P1 gate: P2 typed CoreIngress/Observation/Belief в единой SQLite transaction, с одобренным D1 journal + replay; затем P3 Goal/Decision/Action/Verification. Нельзя смешивать «запустился без модели» с «принял автономное решение».
