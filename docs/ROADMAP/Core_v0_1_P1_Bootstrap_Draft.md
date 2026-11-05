# ANIMA Core v0.1 — P1 Standalone Bootstrap (implementation slice)

**Статус:** Implementation present; **UNVERIFIED** pending local pytest and documentation checks. Не обозначать P1 Complete или автономность Core.  
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

| Check | Expected | Current evidence |
|---|---|---|
| P1-A | сборка `build_core` без model/GUI/network | code review + pending subprocess |
| P1-B | создание assembly не меняет status/session | pending pytest |
| P1-C | wake→sleep создаёт 2 события и консистентный snapshot | pending pytest |
| P1-D | restart сохраняет instance identity, history и счётчик | pending pytest |
| P1-E | interactive CLI остался совместимым | pending legacy D1/CLI tests |
| P1-F | нет обязательного Sleep processor при запуске | code review + pending tests |
| P1-G | документация/все регрессионные тесты | pending `scripts/check.sh` и full pytest |

**Gate PASS** возможен только после полученных выходных данных проверок. Code-reviewed ✓, executed tests pending. P0 также сохраняет открытый baseline gate, который необходимо закрыть перед объявлением P1 Complete.

## 5. Дальше

После P1 gate: P2 typed CoreIngress/Observation/Belief в единой SQLite transaction, с одобренным D1 journal + replay; затем P3 Goal/Decision/Action/Verification. Нельзя смешивать «запустился без модели» с «принял автономное решение».
