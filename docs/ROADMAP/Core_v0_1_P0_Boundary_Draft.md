# ANIMA Core v0.1 — P0 Boundary & Reuse Audit

**Статус:** P0 architecture review / proposed baseline. Требует owner acceptance перед P1.  
**Дата:** 2026-11-05.  
**Исходный code snapshot:** `e2a1e6bfdb6126b82ac36873dce92e7c6876aa4b` на `work/stage7-semantic-boundary-v0`.  
**Рабочая ветка:** `work/core-v0-1-planning` (только документация).  
**Общий план:** [Core v0.1 + VAL](Core_v0_1_VAL_v0_1_Plan_Draft.md).
**Первый технический контракт (на согласование):** [Event / Observation / Belief](Core_v0_1_Event_Belief_Contract_Draft.md).
**Второй технический контракт (на согласование):** [Belief → Goal / Task → Decision → Execution / Verification](Core_v0_1_Goal_Decision_Execution_Contract_Draft.md).
**P1 standalone bootstrap:** [P1 — owner-verified bootstrap PASS](Core_v0_1_P1_Bootstrap_Draft.md).
**P2-A owner-verified PASS:** [SQLite Core Event Ingress](Core_v0_1_P2A_Ingress_Draft.md).
**P2-B owner-verified PASS:** [Typed Observation / Belief Projection](Core_v0_1_P2B_Belief_Draft.md).
**P2-C implementation (tests pending):** [Runtime / Durable Dispatch Integration](Core_v0_1_P2C_Runtime_Integration_Draft.md).  
**Референс реализованной архитектуры:** [Architecture](../ARCHITECTURE/README.md).  
**Актуальные статусы:** [project.json](../project.json); никакой Stage не объявляется закрытым этим документом.

## 1. Executive decision proposal

**Первая сборка Core v0.1 должна стать самостоятельным headless event-driven runtime.** Она не должна зависеть от LLM, Godot, сети, GUI, навигации, Sleep processing и произвольного model-generated Planner.

Минимальная доказуемая способность:

> На основе доступного типизированного наблюдения ANIMA обновляет свой Belief, сопоставляет его с внешне заданной проверяемой целью, выбирает разрешённое действие или abstain/observe/defer, регистрирует и выполняет действие через trusted adapter, независимо наблюдает результат, обновляет Task/Goal и продолжает после перезапуска.

**Это НЕ новая реализация всей ANIMA.** Переподключаем proven компоненты Stage 0–3, 5–6; создаём только отсутствующие boundaries и адаптеры. Отдельный 2D World Engine не входит в P0–P4.

## 2. Что реально подключено сейчас

### 2.1. Ordinary CLI assembly

[`main.py`](../../main.py) создаёт `AnimaState`, `Identity`, `EventBus`, `EventLog`, `MemoryStore`, `LinkStore`, `EpisodicMemory`, `MemoryProcessor`, `EventProcessingCoordinator`, `DiagnosticTrace`, `InternalStateRuntime` и передаёт их в [`Runtime`](../../anima/runtime.py), затем вызывает CLI.

[`Runtime._process_events`](../../anima/runtime.py) обрабатывает queued события через EventLog → EventProcessingCoordinator/MemoryProcessor; `wake/user_input/sleep` — активный путь. `create_goal/choose/observe_goal` доступны, если подключён Internal State, но это ещё не автономный цикл.

**В ordinary `main.py` не собираются** `TaskStore`, `CognitiveCoordinator`, `CognitiveRouter`, `ActionChoiceCoordinator`, `ExecutionCoordinator`, `ExecutionStore`, `UnifiedTrace` или независимый GoalVerifier. Наличие этих реализаций и успешных Stage 6 integration tests **не означает** их участие в обычном CLI runtime.

### 2.2. Existing integration substrate

- [`tests/test_stage6_acceptance.py`](../../tests/test_stage6_acceptance.py) вручную собирает Stage 6 components в acceptance fixture, проверяет routing, controlled execution, restart и no-model deterministic paths.
- [`tests/test_stage6_execution_verification.py`](../../tests/test_stage6_execution_verification.py) отдельно проверяет operation ledger, stale Task/Goal, receipt != verified success, uncertain replay/reconciliation.
- [`tests/test_stage6_unified_trace_recovery.py`](../../tests/test_stage6_unified_trace_recovery.py) проверяет сохранение causal trace и нормализацию незавершённых операций при восстановлении.
- [`tests/test_event_processing.py`](../../tests/test_event_processing.py) проверяет idempotent memory processing и recovery в существующей границе.
- [`tests/test_runtime.py`](../../tests/test_runtime.py) проверяет headless lifecycle, но не автономное действие в динамической среде.

**Вывод:** объединять механизмы предстоит в новой **composition/run mode**, а не добавлять новый LLM Planner или считать старый CLI доказательством автономности.

## 3. Матрица переиспользования

| Область | Код/путь | Решение для Core v0.1 | Непокрытая функция / риск |
|---|---|---|---|
| Identity | [`core/identity.py`](../../anima/core/identity.py) | **REUSE + HARDEN** | `get()` возвращает изменяемый словарь; load без проверки схемы, первичная запись неатомарна |
| Lifecycle/state | [`core/state.py`](../../anima/core/state.py) | **REUSE** | отделить lifecycle от Belief; не путать состояние режима с мировыми фактами |
| Event/Bus | [`core/event_bus.py`](../../anima/core/event_bus.py) | **REUSE + ADAPT** | очередь RAM, нет bounded backpressure; payload/references не полностью иммутабельны |
| Raw events | [`memory/event_log.py`](../../anima/memory/event_log.py) | **REUSE + HARDEN** | JSONL append отдельно от SQLite; повтор same ID сейчас приводит к exception, `load_events()` читает весь журнал |
| Memory processor | [`memory/event_processing.py`](../../anima/memory/event_processing.py) | **REUSE memory path; DO NOT make Belief depend on text composer** | exactly-once касается конкретного memory processor в SQLite transaction, а не произвольного world side effect |
| SQLite | [`memory/memory_store.py`](../../anima/memory/memory_store.py) | **REUSE storage conventions** | выбрать чёткий transaction/commit boundary для observation→belief; не обещать глобальную атомарность по нескольким БД |
| Episode/Knowledge | [`memory/episodic.py`](../../anima/memory/episodic.py), [`memory/knowledge.py`](../../anima/memory/knowledge.py) | **KEEP OPTIONAL** | Knowledge `confirmed` ещё не является доказанной world truth; не использовать `confirm()` вместо belief policy |
| Provenance | [`memory/provenance.py`](../../anima/memory/provenance.py) | **REUSE concepts** | ссылки на источники нужны всегда; full JSONL indexing нежелателен на каждом turn |
| Semantic | [`semantic/`](../../anima/semantic/), [Stage 7](Stage_7_Semantic_Boundary_v0.md) | **PRESERVE BOUNDARY; no production semantic write** | DP-08/09/10b/11 остаются открытыми; Core v0.1 поддерживает узкие typed observations |
| Task | [`tasks/contracts.py`](../../anima/tasks/contracts.py), [`tasks/store.py`](../../anima/tasks/store.py) | **REUSE** | lifecycle `queued→active→completed/failed/...`; нет автоматической генерации/планирования |
| Goal | [`internal_state/goals.py`](../../anima/internal_state/goals.py) | **REUSE + ADAPT** | `success_criterion` сейчас текст, нужен типизированный проверяемый criterion для limited Core |
| Progress | [`internal_state/goal_progress.py`](../../anima/internal_state/goal_progress.py) | **REUSE verified transition** | `criterion_satisfied` не должен задаваться как слепое утверждение decision-модуля |
| Choice | [`internal_state/choice_engine.py`](../../anima/internal_state/choice_engine.py), [`cognition/action_choice.py`](../../anima/cognition/action_choice.py) | **REUSE WHEN APPLICABLE; SIMPLIFY at v0.1** | ActionChoiceCoordinator жёстко привязан к `CHOOSE_ACTION` + `multiple_actions_without_policy` и state-scoring, не general rule engine |
| Deterministic resolution | [`resolution/resolver.py`](../../anima/resolution/resolver.py) | **REUSE narrow operation cases** | `CALCULATE/COMPARE/POWER_COMPATIBILITY/CHOOSE_ACTION/QUERY_FACT` — не универсальная world action policy |
| CognitiveCoordinator | [`cognition/coordinator.py`](../../anima/cognition/coordinator.py) | **REUSE boundary for supported CanonicalTask** | возвращает directive, не исполняет автономный turn; не заменять им event loop |
| Execution contracts | [`execution/contracts.py`](../../anima/execution/contracts.py), [`execution/store.py`](../../anima/execution/store.py) | **REUSE** | persisted operation/idempotency/status, typed action/receipt/observation/verification |
| ExecutionCoordinator | [`execution/coordinator.py`](../../anima/execution/coordinator.py) | **ADAPT, preserving guards** | `prepare()` требует `ActionChoiceTurn`, `SandboxExecutor` и `ToolRegistry`; нельзя выдавать за generic world executor |
| SandboxExecutor | [`execution/sandbox.py`](../../anima/execution/sandbox.py) | **KEEP trusted-tool path; abstract world adapter** | отдельный process и filesystem sandbox не должны быть обязательной обвязкой локального/внешнего world bridge |
| Goal verifier | [`execution/verification.py`](../../anima/execution/verification.py) | **REUSE principle + contracts, ADD structured observer/verifier** | текущий `DeterministicGoalVerifier` поддерживает `file.content_equals`, но не `world.property_equals` |
| Recovery | [`cognition/recovery.py`](../../anima/cognition/recovery.py) | **REUSE operation-reconciliation semantics, ADAPT composition** | `Stage6RecoveryCoordinator` жёстко требует `TaskSleepCoordinator`; базовый Core не должен требовать подключение Sleep |
| Trace | [`diagnostics/unified_trace.py`](../../anima/diagnostics/unified_trace.py) | **REUSE** | привязать event/observation/belief/decision/action/verification к одному причинному пути |
| ScenarioRunner | [`scenario.py`](../../anima/scenario.py) | **OPTIONAL harness helper** | исполняет известные операции Runtime, не подменяет полный тестовый мир |
| FAST/DEEP, Sleep processing, navigation, CV | соответствующие модули | **OUT OF CORE v0.1** | подключаемые способности, не обязательный bootstrap |

Все `REUSE` означают проверку совместимости с новой сборкой, а не объявление компонент готовым для нового world contract.

## 4. Предлагаемый минимальный runtime flow

```text
external structured input / timer / task activation
    ↓
Ingress validator → durable Event record / dedupe
    ↓
Observation adapter (source, observed_at, received_at, identity, scope)
    ↓
Belief policy → versioned belief revision + evidence ref
    ↓
Scheduler (bounded active Goals / Tasks)
    ↓
Deterministic decision:
    already satisfied → no-op / verify
    known actionable → propose registered Action
    missing or stale → request observation / defer
    conflicting → abstain / dispute / bounded follow-up
    ↓
Policy: permissions, capability, current Goal/Task, belief revision,
        fresh preconditions, action quota, idempotency class
    ↓
Execution ledger → trusted adapter → Receipt
    ↓
Independent Observer → VerificationResult
    ↓
Goal/Task transitions + causal trace + next event
```

**Обязательное разделение:**
- `World ground truth` известен тестовому adapter/harness, **не Core**.
- `Belief` — system-owned versioned projection, а не `Knowledge.confirm()` или текстовое резюме.
- `Decision` выбирает кандидат; `Policy` разрешает или запрещает; `Executor` применяет действие; `Observer/Verifier` подтверждают или опровергают результат.
- Время симуляции/поступления фиксируется отдельно. Решение связывается с `belief_revision`; перед эффектом проверяются критические preconditions.
- При отсутствии work Core ждёт; он не обязан крутить busy loop.

## 5. Минимальные новые контракты (проект интерфейса, не утверждённая wire schema)

### 5.1. `ObservationEnvelope`

- `observation_id`, `event_id` / correlation;
- `source_ref` и, где применимо, `producer_ref` (в терминах Stage 7, не слитые в один ID);
- `entity_ref` и `predicate_ref` с версией смысла/типов, `typed_value` или `unknown` (unknown — не поддельный value);
- `observed_at` (known/unknown и clock domain), `received_at`, `valid_scope` при наличии;
- `evidence_ref`, `adapter_version`, `scope/coverage`.

В v0.1 достаточно разрешённых типов наблюдений `object.property` и `sensor.status`. Не принимаются произвольные assertions от непривилегированного клиента как утверждённая truth.

### 5.2. `BeliefSnapshot / BeliefRevision`

- `belief_key` = (canonical entity, predicate, meaning-bearing context), применимость/версия;
- `value` (typed или absent), эпистемический `known / unknown / disputed`;
- **отдельно** `fresh / stale / undetermined`, а не единый enum со статусом истинности;
- `evidence_refs` и `source_refs`, `last_observed_at`/`last_received_at`;
- `revision` / `previous_revision`, причина изменения, проверенная temporal precedence.

Для v0.1 разбирать только зарегистрированные `single-valued exact property` и совпадающий scope, без автоматического именования/слияния сущностей. Запоздалое наблюдение не заменяет текущее лишь по receipt time. Конфликт не порождает произвольный winner.

### 5.3. `BoundedDecision`

Замкнутое множество: `NOOP | REQUEST_OBSERVATION | PROPOSE_ACTION | DEFER`. Обязательны `task_id/goal_id` (если применимо), `belief_revision`, `reason_code`, `capability_ref` и bounded arguments. Никакой универсальной модели/Planner для первой итерации.

### 5.4. `ActionAdmission / Verification`

- `ActionAdmission`: action kind/version, Goal/Task binding, requested/approved/rejected, preconditions, explicit `idempotency_class` и quota.
- World adapter выдаёт receipt, **не `Goal completed`**.
- `Verification`: `world.property_equals` для доступного через независимое наблюдение свойства; результат `satisfied | unsatisfied | unknown` + evidence refs.
- Совместимость со Stage 6 `ExecutionAction`, `ExecutionReceipt`, `Observation`, `VerificationSpec`, `VerificationResult` проверяется до реализации; не дублировать структуры без необходимости.

### 5.5. `CoreRunConfig / CapabilityManifest`

Конфигурация разрешённых источников, зарегистрированных действий, критических preconditions, лимитов и доверенных критериев. Навигация/LLM/GUI/сеть не required. Отказ от неподдерживаемой операции — нормальный исход, не ошибка lifecycle.

## 6. Границы надёжности и конкретные блокеры

**B1 — Event ingress/replay.** `EventLog.write` отвергает повтор event ID, `EventBus` хранит только RAM queue; идемпотентность memory projection не равна idempotent ingress. Нужно определить durable admission + replay contract и учитывать mutable input payload.

**B2 — Belief policy vs Stage 7.** Ввести узкий policy для явных наблюдений и register-owned scalar properties. Не переносить непроверенную `Knowledge.confirm/supersede` семантику в Core. Решить, когда evidence делает belief accepted, disputed, unknown или stale; не считать любой source одинаково достоверным.

**B3 — Typed Goal criterion.** `GoalStore` принимает текстовый `success_criterion`; автоматические проверки требуют зарегистрированного typed criterion, сохранённого и связанного с Goal. В v0.1 предложен criterion sidecar/registry, без обязательной миграции legacy Goal records.

**B4 — Action adapter / independent verifier.** Stage 6 generic contract хранит operation ledger, но `ExecutionCoordinator` привязан к `ActionChoiceTurn/SandboxExecutor`, а `DeterministicGoalVerifier` реализует `file.content_equals`. Требуется world action/observer adapter с сохранением проверок полномочий и `Receipt ≠ Verified`. Запрещён shortcut: «test-world set_state и есть подтверждение успеха».

**B5 — Recovery composition.** `Stage6RecoveryCoordinator` требует Sleep coordinator. Core требует восстановление persistent Task/Execution/Belief **без обязательной Sleep subsystem**. Разрешить compositional recovery, без второй системы Task ownership. `executing` после reboot → `uncertain`; повтор эффекта только по реальному idempotency/reconcile contract.

**B6 — Cross-store consistency / durability.** Identity JSON, EventLog JSONL, memory SQLite, Goal/Internal State SQLite, TaskStore SQLite, ExecutionStore SQLite и Trace SQLite не образуют общую транзакцию. Выбрать один durable source для Observation/Belief или зафиксировать replay/reconcile sequence. Нельзя обещать atomic multi-store или power-loss resilience без fault-injection.

**B7 — Scheduler.** Сейчас не найдено единого ordinary CLI flow `observe→belief→goal/task→action→verify`. Нужен **один** bounded system-owned driver, который координирует готовые stores и операции. В P1–P3 допускается синхронный один процесс, без потоков и микросервисов.

## 7. Acceptance plan (обязателен до P4; пороги зафиксировать до финального прогона)

| ID | Серия / вариации | Проверяемое поведение | Gate |
|---|---|---|---|
| C0 | startup/restart без LLM и Godot; idle; clean shutdown | identity сохраняется; Core запускается без модели и GUI | P1 |
| C1 | door open → action → independent observation; initially closed | verified Goal success; ноль ненужных действий | P3 |
| C2 | duplicate event ID; same occurrence redelivery; out-of-order observation | event/projection replay не удваивает поддержку/эффекты; Belief не откатывается по received time | P2–P4 |
| C3 | unknown value / sensor unavailable / contradictory sources | ungrounded fact не записывается как known; корректные abstain/observe/defer | P2–P4 |
| C4 | door changes between decision and action | stale precondition → no unintended effect | P3–P4 |
| C5 | action failed; receipt success but world unchanged; delayed verification | Goal остаётся неверифицированной до независимого evidence | P3–P4 |
| C6 | crash before action / during effect / after effect-before-confirmation | operation ledger recovery, no blind replay, no false success | P4 |
| C7 | irrelevant events + critical event + bounded queues | критичное не теряется, нет бесконечного цикла/лишней генерации работы | P4 |
| C8 | attempt unauthorized action, forged model-like proposal | Policy denies; no mutation of stores/authority | P3–P4 |

**Каждое семейство** содержит обычный, отрицательный и крайний/переставленный вариант там, где они применимы. Все перечисленные blocking cases должны пройти; особенно запрещены `unauthorized side effects` и `false verified success` в испытанном fault model.

Численные метрики (`latency`, `queue depth`, `actions per goal`, `recovery delay`) снимаются на baseline. Перечень exact fixtures, поддерживаемый clock model и ограничения тестового адаптера фиксируются до acceptance run. `P4 passed` нельзя объявлять, опираясь только на тесты Stage 6.

### 7.1. Owner-approved validation strategy (2026-11-05)

**Решение:** owner одобрил проверку **всех функций, включённых в Core v0.1**, на трёх уровнях. Решение относится к тестовому подходу, **не** означает утверждения спорных P0 contracts и не делает P0/P1 Complete.

1. **Unit:** инварианты отдельных модулей (Event, Belief, Task, Goal, Policy, Action, Verifier, Recovery) на точных тестовых входах.
2. **Integration:** проверка причинных стыков (Event→Belief→Task; Decision→Policy→Execution→Verification; persistence→restart→reconciliation). Нельзя доказывать систему только моками, всегда успешно отвечающими друг другу.
3. **System / end-to-end:** настоящий собранный headless Core, несколько последовательных, не всегда связанных событий, собственные цели и state transition; никакого внешнего сценарного вызова «заверши цель» вместо автономного loop. Фиксировать условия/версии/детерминизм.

Сценарные требования, согласованные owner (соответствия уже существующим блокирующим C0–C8; названия S01–S10 — человекочитаемая группировка, **не** ещё один конкурирующий набор fixtures):

| Семейство | Scenario | Блокирующее свойство |
|---|---|---|
| S01 | открытая дверь → закрыть → независимое наблюдение | C1, C5 |
| S02 | уже закрытая дверь → действие не требуется | C1 |
| S03 | contradictory / stale observations | C2, C3 |
| S04 | выбор из нескольких разрешённых действий | C8, Choice contracts; только если действительно есть несколько валидных кандидатов |
| S05 | исполнение не удалось / receipt не равен goal success | C5 |
| S06 | остановка на нескольких стадиях и restart | C0, C6 |
| S07 | несколько заданных целей/задач; ограниченный арбитраж | C7, Goal/Task contracts |
| S08 | отвлекающие события при сохранении важных | C7 |
| S09 | запрещённая операция / forged proposal | C8 |
| S10 | отсутствующие сведения / недоступный сенсор | C3 |

**Вариативность:** минимум положительный, отрицательный и крайний/переставленный вариант, где применимо; отдельные прогоны с повторными, запоздалыми и противоречивыми событиями; доказательная матрица отображает coverage по **всем включённым механизмам**, а не номинальную численность тестов.

**Live observability также одобрена.** Предусмотреть необязательный терминальный dev monitor без GUI и без прав записи в Core: `mode/goal/task, last event, currently accepted belief + evidence reference/freshness, decision + reason, policy verdict, action/receipt, independent verification, diagnostics`. Любое поле ground truth принадлежит только test operator и явно помечается как external privileged context; в Core оно не передаётся. `confidence` не выводить как калиброванное число без модели и проверки калибровки.

**Run logs:** отдельный machine-readable trace с causal IDs/версией/seed/clock и автоматически сформированный human-readable Markdown report. Монитор показывает поток событий, но не заменяет persistent logs и acceptance assertions.

**Gate P4:** (a) все обязательные unit/integration/system suites PASS на известном snapshot; (b) минимум один длительный многошаговый headless-прогон, не один hardcoded door demo; (c) ноль unauthorized side effects, ноль false-positive goal verification в предусмотренной модели отказов; (d) есть протокол restart/fault injection; (e) regression suite existing modules не ломается. Не объявлять 100% надёжность за пределами испытанных условий.

**Остаётся открыть до P1:** выбрать точные границы persistence/replay, Belief authority, typed criterion, action adapter/observer и независимого Sleep recovery; снять baseline запуск `scripts/check.sh` и `pytest`. Одобрение тестового плана не подменяет эти решения.

## 8. Порядок на следующую сессию разработки

1. Принять/исправить P0 boundary и выбрать один minimal `CoreAssembly` path (не через новый Stage 4 planner).
2. Зафиксировать typed observation + belief + criterion + action ports и authoritative write points.
3. Принять persistence/replay и precondition/uncertain-operation policies, включая случай `EventLog.write` duplicate.
4. Создать P1 headless assembly, проверив cold start, idle, shutdown, отсутствие LLM/Godot.
5. Добавлять P2–P4 только через gate-based vertical slices; P5 Godot не должен блокировать старт P1.

## 9. Проверка этого документа

- Проведён **code-reading audit** целевых файлов и selected tests на указанном commit.
- **Не запускались** `pytest` и `scripts/check.sh`: connected GitHub обеспечивает чтение кода, но локальный checkout/исполняемое окружение в этой сессии недоступны. Показатели исторической ревизии от 2026-11-03 не считаются новым запуском.
- Production code, schemas, Stage status/`project.json` и существующие ADR в рамках P0 не менялись.
- Owner acceptance требуется до реализации P1. Этот документ — рабочая спецификация границы, а не TV acceptance result.
