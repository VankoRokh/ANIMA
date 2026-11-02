# Stage 6 — Cognitive Integration Core

> **Утверждённая спецификация Stage 6.** Этот документ задаёт границы реализации. Динамический статус проекта остаётся в [project.json](../project.json). Реализованные детали после проверки должны переноситься в [Architecture](../ARCHITECTURE/README.md), а исследовательские варианты — в [Research](Research.md).

## 1. Цель

Stage 6 должен объединить уже доказанные подсистемы ANIMA в один наблюдаемый когнитивный цикл, не передавая FAST, DEEP или любой другой LLM владение системным состоянием, памятью, задачами, целями, маршрутизацией или исполнением.

Главный критерий этапа:

> **Модель может предложить следующий когнитивный или исполнительный шаг, но система остаётся владельцем того, что существует, что допустимо, что выполняется и что считается подтверждённым результатом.**

## 2. Архитектурные инварианты

1. FAST и DEEP — сменяемые cognitive consumers, а не владельцы ANIMA.
2. LLM не пишет напрямую в Memory, Task, Goal, Internal State, Sleep или execution stores.
3. Routing принадлежит системному Cognitive Coordinator/Router и должен быть наблюдаемым.
4. `Goal`, persistent `Task`, `CanonicalTask` и `Action` — разные сущности.
5. Internal State влияет только через явные bounded system rules; текстовая самооценка модели не имеет authority.
6. Side effects проходят через system-owned validation/Executor и независимое Observation/Verification.
7. Успешный ExecutionReceipt не равен успешному Goal: результат подтверждает verifier по наблюдаемому evidence.
8. Stage 4 `PlannerAdapter`/LLM Planner не возвращается как cognitive owner и не переименовывается в DEEP.
9. Stage 3 Sleep сохраняет существующие persistent/checkpoint/recovery contracts; Stage 6 только возвращает их в общий lifecycle.
10. Semantic write/update/revision и DEEP-assisted semantic consolidation остаются Stage 7.
11. Любая новая свобода FAST/DEEP добавляется только после отдельного измеримого эксперимента.

## 3. Сущности и ownership

### Goal

Отвечает на вопрос **зачем** выполняется работа и по какому проверяемому критерию она считается успешной. Канонический owner — существующий `InternalStateRuntime/GoalStore`.

### Persistent Task

Отвечает на вопрос **какая единица работы ANIMA сейчас существует во времени**. Task переживает restart и связывает cognitive turns, ожидание внешнего результата, interruption/resume и terminal outcome.

Task не является Goal, prompt, Planner run или модельным chain-of-thought.

### CanonicalTask

Model-independent внутреннее представление одной конкретной когнитивной задачи для deterministic resolution/cognition. Канонический owner — `anima.ir` / resolution pipeline Stage 5.

### Cognitive Proposal

Типизированный результат FAST/DEEP, который система может принять к дальнейшей валидации. Proposal не имеет права самостоятельно менять persistent state.

Baseline proposal kinds Stage 6:

- `RESPOND` — предложить текстовый/структурированный ответ;
- `PROPOSE_ACTION` — предложить один или несколько action candidates;
- `PROPOSE_TASK` — предложить bounded follow-up Task, который система может принять или отклонить;
- `REQUEST_CONTEXT` — экспериментальный запрос дополнительного bounded context, не прямой доступ к Memory.

Поддержка конкретного kind вводится только вместе с validator и тестами. Наличие enum не является разрешением модели пользоваться всеми вариантами.

### Action

Проверенный системный контракт конкретного side effect. Существующие Stage 4 `Action`, Executor, Receipt, Observation и Verification могут быть переиспользованы, если их ownership остаётся system-owned.

## 4. Целевой контур

```text
Event / external request / persistent Task
                ↓
        Cognitive Coordinator
                ↓
            Canonical IR
                ↓
      deterministic resolution
        ├─ deterministic result
        ├─ insufficient data
        └─ cognitive remainder
                ↓
          Cognitive Router
           ├─ FAST
           └─ DEEP
                ↓
        Cognitive Proposal
                ↓
       system-owned validation
          ├─ response
          ├─ Task proposal
          └─ Action candidates
                ↓
       Goal + Internal State
                ↓
             Choice
                ↓
        validated Action
                ↓
            Executor
                ↓
 Receipt → Observation → Verification
                ↓
       Goal / Task transition
```

Ни FAST, ни DEEP не управляют стрелками этого графа.

## 5. Декомпозиция реализации

### 6.0 — Persistent Task Foundation

Создать отдельную system-owned persistent Task abstraction без Planner semantics.

Минимальный baseline:

- отдельный `tasks.db`;
- `task_<UUIDv4>`;
- optional `goal_id` как reference, но без cross-database foreign key;
- `source`, optional `source_id`, `description`;
- lifecycle `queued → active → interrupted/completed/failed/cancelled` с разрешённым resume `interrupted → active`;
- append-only transition history;
- timestamps и terminal reason;
- reopen/restart persistence;
- никакой model/backend/planner информации в Task contract.

TaskStore не заменяет GoalStore и не использует `AgentRun/AgentStep` как persistence layer.

**Acceptance 6.0:** create/read/list/transition/reopen; invalid transitions rejected; terminal Task не возобновляется; restart сохраняет lifecycle/history; Task не мутирует Goal или другие stores.

### 6.1 — Cognitive Coordinator

Добавить системный coordinator над доказанным Stage 5 read/resolution path.

Coordinator обязан:

- принимать persistent Task или внешний Event/request;
- формировать/получать CanonicalTask;
- вызывать deterministic resolution;
- сохранять route/inputs/result в observable trace;
- передавать только `COGNITIVE_REQUIRED` в Cognitive Router;
- не владеть Memory/Goal/Internal State stores напрямую сверх явных adapters;
- не превращаться в новый монолитный AgentLoop.

Существующий `CognitivePipeline` Stage 5 остаётся compatibility/verified path и не ломается ради Stage 6.

### 6.2 — DEEP и FAST/DEEP Router

Ввести первый DEEP role через отдельный model-independent backend contract.

Router принадлежит системе и принимает решение до model call. Baseline routing должен быть простым, bounded и объяснимым; адаптивные эвристики вводятся только через mini experiments.

FAST/DEEP возвращают типизированный `CognitiveProposal`, а не выполняют persistence/execution самостоятельно.

**Запрещено:** использовать Stage 4 LLM Planner как DEEP implementation без нового контракта и независимой проверки ownership.

### 6.3 — Goals + Internal State + Choice

Связать persistent Task с существующим Goal и использовать существующий `ChoiceEngine` для ранжирования уже сформированных action candidates.

Internal State не создаёт candidates и не меняет Goal authority. Влияние state должно быть видно в score trace и сравнимо с baseline без modifiers.

### 6.4 — Execution + Independent Verification

Вернуть только полезный bounded slice Stage 4:

```text
validated proposal
    ↓
Action
    ↓
Executor
    ↓
ExecutionReceipt
    ↓
Observation
    ↓
Verifier
    ↓
GoalObservation
```

Можно переиспользовать существующие sandbox Executor, operation ledger и deterministic verifier/bridge. Старый Agent Planner loop не является частью Stage 6 core.

### 6.5 — Sleep Lifecycle Integration

Связать persistent Task lifecycle с уже реализованным Stage 3 Sleep:

```text
active Task
    ↓
sleep requested
    ↓
Task/system state safely persisted or interrupted
    ↓
existing bounded Sleep work
    ↓
wake
    ↓
Task resumes without duplicate logical effect
```

Stage 6 не добавляет generative dreaming, semantic rewriting или DEEP Memory Composer.

### 6.6 — Recovery + Unified Trace

Один trace должен причинно связывать минимум:

- Task ID;
- Goal ID, если есть;
- CanonicalTask/source;
- resolution route/reason;
- context/provenance summary;
- FAST/DEEP route и backend attempt/completion;
- CognitiveProposal validation;
- Choice/state modifiers;
- Action/operation ID;
- Receipt/Observation/Verification;
- Sleep/restart transitions;
- final Task/Goal outcome.

Recovery должен уметь продолжить незавершённый Task без повторения уже committed side effect.

### 6.7 — Mini Experiments

Эксперименты не блокируют baseline Stage 6, если не доказано обратное.

#### `request_more_context`

```text
FAST/DEEP
    ↓
RequestMoreContext(query/need/budget)
    ↓
System Retrieval
    ↓
new bounded context
    ↓
FAST or DEEP
```

Измерять quality, latency, retrieval count, context growth, provenance и циклы. Модель не получает DB/tool ownership.

#### FAST/DEEP routing

Сравнить простые deterministic правила с более адаптивными вариантами на одинаковом corpus. Измерять quality, latency, DEEP call rate, explainability и failure modes.

#### Internal State effect

Сравнить одинаковые candidate sets при bounded state modifiers и baseline state. Проверить, что влияние measurable и не превращается в шум/скрытую authority.

### 6.8 — Stage Acceptance

Основной end-to-end сценарий:

```text
persistent Goal
    ↓
persistent Task
    ↓
Canonical IR / resolution
    ↓
FAST or DEEP route
    ↓
validated Action candidates
    ↓
Internal State + Choice
    ↓
Executor
    ↓
independent Observation
    ↓
Verification
    ↓
Goal completed
    ↓
Task completed
```

В середине сценария выполняется controlled restart.

Acceptance должен доказать:

1. Task и Goal переживают restart;
2. уже committed Action не выполняется повторно;
3. verification продолжает использовать independent evidence;
4. route FAST/DEEP объясним из trace;
5. замена FAST/DEEP backend не переносит Identity/Memory/Task/Goal state;
6. Internal State влияет только через bounded Choice rules;
7. Sleep interrupt/wake/resume не теряет Task и не дублирует effect;
8. LLM не имеет прямого persistence/execution ownership;
9. Stage 5 deterministic/insufficient paths по-прежнему не делают лишних model calls;
10. полный regression suite остаётся зелёным.

Отдельные acceptance cases должны покрывать FAST route, DEEP route, deterministic no-model route, insufficient-data route, invalid proposal rejection, backend failure и Sleep resume.

## 6. Explicit non-goals

Не входят в Stage 6:

- semantic write/update/revision lifecycle;
- автоматическое создание CONFIRMED Knowledge моделью;
- unrestricted self-generated Goals;
- обучение весов FAST/DEEP;
- generative dreaming;
- Virtual ANIMA / 2D world;
- perception/audio/video pipeline;
- distributed compute;
- hardware-specific routing;
- удалённый tool/network access;
- возврат LLM Planner ownership.

Если реализация требует один из этих пунктов, Stage 6 должен остановиться на интерфейсе/эксперименте и не расширять scope молча.

## 7. Порядок работы

1. 6.0 Persistent Task Foundation.
2. 6.1 Cognitive Coordinator над существующим Stage 5 path.
3. 6.2 первый DEEP contract + bounded router.
4. 6.3 Goal/Internal State/Choice integration.
5. 6.4 Executor/Verification integration.
6. 6.5 Sleep lifecycle integration.
7. 6.6 recovery/unified trace.
8. 6.7 mini experiments только поверх работающего baseline.
9. 6.8 representative end-to-end acceptance и полный regression.

Каждый slice должен иметь собственные targeted tests и не менять статус Stage до подтверждённого поведения.
