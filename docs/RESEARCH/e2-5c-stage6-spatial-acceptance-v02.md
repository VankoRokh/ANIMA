# ANIMA v0.2 — E2.5c: Stage2 Goal/Task + Stage6 World Actions в Visual Lab

**Вердикт:** `PASS_LAB_STAGE2_STAGE6_SPATIAL`. Это **исследовательская частичная интеграция**, не готовность production Core, не нативная поддержка пространственных планов в `CoreGoalDecision` и не FAST/DEEP.  
**Проверенный snapshot кода:** `a60cf73666eac0e5b1cfe8ca659b3341c48a4353`.  
**Первичные доказательства:** [CI #45281261375](https://github.com/VankoRokh/ANIMA/actions/runs/45281261375) — **4/4 SUCCESS**, Python 3.12/3.13/3.14 по **2496 PASS**; настоящий Godot 4.7.2 на seed 7 и 8; полный E1.2–E2.5b live regression **PASS**.  
**Дата:** 24 ноября 2026. **Основа:** [E2.5b Visual Decision](e2-5b-visual-decision-lab-acceptance-v02.md), [E2.5a Cognitive Initiative](e2-5a-cognitive-initiative-acceptance-v02.md).  
**Репозиторий:** `VankoRokh/ANIMA`, ветка `work/v02-e25c-core-spatial-execution`. **PR №26 — DRAFT**, без merge/release/data changes.

## 1. Задача

Заменить прямое лабораторное исполнение `LabClient.act` в визуальном режиме E2.5b на проверяемую связь действительного Core Goal, Stage6 Task, ExecutionAction, VerificationSpec и SandboxExecutor. Сохранить исходную детерминированную политику как контрольный эксперимент; не расширять полномочия FAST или Godot operator truth.

```text
Godot sensor-only observe_view / E2.4 full Raw
  → CoreIngress view_digest event, forwarded EventLog, current Core Belief
  → deterministic Proposal from agent-only observations / bounded memory
  → CoreSpatialActionGateway.prepare
     ✓ registered Stage2 Goal: lab.visual, active
     ✓ exact Core source/producer, hash pointer and fresh Belief
     ✓ exact permitted world.turn/step registry, bounded direction
     ✓ no incomplete Task/Operation from same Goal
  → canonical TaskStore (new Task active)
  → canonical Stage6 ExecutionStore
     typed ExecutionAction + VerificationSpec in ONE DB commit
  → CoreSpatialActionGateway.before_effect checks Goal/Task/Raw/operation
  → Stage6 SandboxExecutor executes exact keyed Godot tool
  → E2.4b separate operation_status readback
  → new E2.4 Core-backed Raw observation and verified relative transition
  → CoreSpatialActionGateway.finish_verified corroborates Stage6 receipt,
     readback, before/after Core Raw and canonical stored intent
  → Stage6 Task completed; next bounded decision / Stage2 GoalProgress success
```

## 2. Реализованные компоненты

**`anima/core/spatial_action_gate.py`** — новый *опциональный* `CoreSpatialActionGateway`; не подменяет `CoreDoorExecution`. Использует существующие `GoalStore`, `TaskStore` и `ExecutionStore` как владельцев lifecycle, `CoreIngress` для идентичности источника/актуальности view digest. Создаёт `VerificationSpec(world.egocentric_transition)` и `ExecutionAction` атомарно в Stage6 DB. Отказ при отменённой цели, незарегистрированной операции, повреждённом Raw, отсутствии forwarded receipt, старом Belief, несовпадении Task/Stage6 intent или предыдущей незавершённой операции. Не выполняет world effects напрямую.

**`labs/virtual_anima_lab/python/lifecycle/stage6_world.py`** — строго ограниченные `ToolDescriptor` и `SandboxHandler` для `world.turn(left/right)` и `world.step(forward)`, точная схема аргументов, keyed Stage6 operation ID. Внешний секрет Godot доступен только доверенному процессу runtime, включая сам Stage6 handler и лабораторный `E24PoseTrail` для readback, **не** политике, LLM или внешнему HUD. На неоднозначном эффекте read-only reconcile **не разрешает `retry`**: возврат `unknown` останавливает `SandboxExecutor`.

**`visual_runner.py --core-stage6`** — опциональное включение новой схемы для существующего GUI. Реально создаёт Stage2 Goal через `InternalStateRuntime.create_goal`, затем внутри последовательного STEP выбирает действие по наблюдениям, запрашивает Core Admission, исполняет Stage6 Action и только после следующего Core-backed Raw завершает Task. Успех ограниченной визуальной цели оформляет через `GoalObservation(CONFIRMED_RESULT)` и Stage2 `GoalProgressEngine`. При провале эффекта/проверки — `BLOCKED_UNVERIFIED`, дальнейшая работа без произвольного replay запрещена.

**`scripts/run_visual_stage6_lab.sh`** — одна команда для графического Godot + Stage2/Stage6. Предыдущий `scripts/run_visual_decision_lab.sh` без `--core-stage6` остаётся контрольным E2.5b **LAB_ADMISSION**, схемы исходных сенсорных DTO не изменены.

**Godot HUD** отображает фактический статус `action_admission=CORE_STAGE2_TASK_STAGE6`, статус Stage2 Goal, текущий Raw/Memory/Decision/Verification. Операторские глобальные координаты остаются только у человека; FAST/DEEP всегда `NOT CONNECTED`.

## 3. Проверенная серия

| Gate | Результат |
| --- | --- |
| Python 3.12 / 3.13 / 3.14 | **2496 PASS** на каждой версии, полный набор |
| Новые отрицательные unit | **10 PASS**: точный Raw/Core pointer, Stage6 spec, несовпадения, Goal cancellation, stale Raw, forged readback, duplicate verification |
| Real Godot seed 7 и 8 | **`E2_5C_CORE_STAGE6_VISUAL_PASS`** |
| На каждый seed | 3 agent-only Core-backed Raw, 2 самостоятельно выбранные операции, 2 подтверждённых перехода |
| Реальная Stage2/Stage6 запись | **2 Task completed + 2 Stage6 operations succeeded**, обе с сохранёнными `ExecutionAction/VerificationSpec` |
| Статус Goal после шага | **`completed`** в каноническом GoalStore |
| Контроль отсутствия lab-bypass | У нового Stage6 режима **0 записей** в старой таблице `visual_decisions` |
| Control API | Неправильные bearer tokens и произвольные тела запросов отклоняются, UI polling не вызывает Raw |
| Старый E2.5b + E1.2–E2.5a | **PASS**, отдельная детерминированная контрольная ветка поведения сохранена |
| Python syntax/docs до этого отчёта | 199 страниц, 1379 локальных ссылок PASS |

Смысл теста: алгоритм выбора действий **не изменён**, но право исполнять и регистрировать действие передано штатным владельцам Stage2/Stage6. Разница между старой и новой схемой — в границе полномочий, persistence и fail-closed, **не** в улучшении навигации.

### Устранённые тестовые ошибки

Первый запуск [CI #45281152548](https://github.com/VankoRokh/ANIMA/actions/runs/45281152548) выявил **две ошибки нового unit-набора**: тест обращался к отсутствующему `VerificationSpec.to_dict()` и ожидал отличающуюся формулировку отказа на повторную финализацию. Это исправлено в [CI #45281261375](https://github.com/VankoRokh/ANIMA/actions/runs/45281261375); все новые negative tests и реальная Godot цепочка PASS. Ошибки не следует интерпретировать как отказ базового Stage6 механизма.

## 4. Открытые риски и ограничения

**E25C-R1 HIGH / CoreGoalDecision не универсализирован.** Исходный `CoreGoalDecision` поддерживает `ensure_once/world.property_equals`, а `CoreDoorExecution` — именно дверь. Новый `CoreSpatialActionGateway` использует **канонические GoalStore/TaskStore/ExecutionStore/SandboxExecutor** и Stage2 GoalProgress, но не интегрирован в единую систему generic GoalDecision или `CoreAssembly.core_execution`. Нельзя писать «универсальный Core Action» или «поддержка любых мировых действий».

**E25C-R2 HIGH / Verification пока лабораторная.** `operation_status` и последующий Core Raw согласуют exact world revision/tick; E24PoseTrail сверяет эффект. **Не доказано независимым физическим датчиком**, что цель достигнута в реальном пространстве. Stage6 `VerificationSpec` сохранён атомарно с Action, но standalone `VerificationResult` и формальная проверка семантического достижения цели не образуют полностью автономный производственный путь. Контракт успешно выполненного приближающего шага строго ограничен данным сценарием.

**E25C-R3 HIGH / Прерывания и рестарт.** При аварии после Stage6 admission, но до сохранения результата внешний эффект может оставаться `executing/uncertain`. Reconcile только read-only и **не ретраит** при недоказанном эффекте, что безопаснее автоматического повтора, но **восстановление и продолжение того же Goal после процесса/epoch не реализованы**. Консистентного backup между Core SQLite, Stage6 DB, E24 sidecar и Godot ledger нет.

**E25C-R4 / Конкурентные эффекты.** В GUI один сериализованный worker; полноценный multi-process locking/арбитраж, races между несколькими внешними эффекторами не испытаны. Один process с той же учётной записью ОС может получить ключи из среды/памяти: bearer keys на loopback **не** OS sandbox.

**E25C-R5 / Реальный FAST не подключён.** Действия выбирает ограниченная `CrateInvestigationPolicy`; нет свободного планирования LLM, DEEP, самостоятельной постановки целей или доказательства обучения. Поле `mode=DETERMINISTIC` честно отражает эксперимент.

**E25C-R6 / Недостаточность выборки.** Реальные seed 7 и 8 и маленькая комната — smoke/recovery gates, не статистическое обобщение. Нет перемещённого ящика, неправильных сенсорных воспоминаний, длинных периодов непрерывной работы или stress на десятки тысяч записей.

**Независимый архитектурный аудит не проводился.** [Техническое задание для независимой проверки E2.5c](../TESTING/ANIMA_E25C_Independent_Spatial_Stage6_Audit_Brief.md). Публикацию в release и открытие любых пользовательских/физических эффекторов отложить.

## 5. Решение и следующая работа

`PASS_LAB_STAGE2_STAGE6_SPATIAL` принимается **только в исследовательском контуре**. Перед настоящей FAST приоритет — независимый аудит и отрицательные испытания в точках `prepare → before_effect → SandboxExecutor → readback → new Raw → Task/Goal transition`, включая исчезновение Godot ledger, смену epoch, отмену Goal и попытки прямого обхода Gateway.

Затем — первый **FAST adapter** к `CognitiveStepProposal/ActionProposal`, со строгим бюджетом, регистрацией причин и сравнением `DETERMINISTIC / STUB / FAST` при одинаковых сенсорных потоках. Первыми метриками должны быть валидность решений, достижение простого Goal, необоснованные предположения, потребление токенов/латентность, а не движение по клеткам ради движения.

## 6. Запуск на ноутбуке

```bash
cd ~/Projects/ANIMA
git fetch origin work/v02-e25c-core-spatial-execution
git worktree add --detach ../ANIMA-visual-stage6 origin/work/v02-e25c-core-spatial-execution
cd ~/Projects/ANIMA-visual-stage6
PYTHON_BIN=~/Projects/ANIMA/.venv/bin/python bash scripts/run_visual_stage6_lab.sh
```

Перед запуском закрыть другие `LifecycleWorld`. В Godot нажать **STEP**, затем **RUN**. Ожидается `Admission: CORE_STAGE2_TASK_STAGE6`, после первого шага `Core Goal: active`, после второго `Core Goal: completed`. Эффект и причина выбора отображаются через реальный контроллер, никакие operator `x/y` не поступают в Cognitive Context.

Для независимого повторения на Godot 4.7.2: `bash scripts/run_stage6_visual_gate.sh "$GODOT_BIN"`. Данные создаются только во временной директории, путь выводится в консоли.
