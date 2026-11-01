# Cognitive Resolution Integration Specification

> **Утверждённый контракт Stage 5.** Реализованные детали и остающиеся closure checks отделены от требований ниже. Динамический статус/focus хранится только в [project.json](../project.json); документ не объявляет Stage завершённым.
>
> Основание: экспериментальная серия Structured Request / Semantic Memory / Adaptive IR / Deterministic Resolution (Tests H–M1) на ветке `work/context-grounding-v0`.

## 0. Явное уточнение приоритетов и scope

Исходный [Stage 5 roadmap](README.md#stage-5) планировал после read path semantic
interpretation-to-write и revision/contradiction. Одобренный после H–M1 приоритет —
сначала стабилизировать Canonical IR, exact deterministic resolution, epistemic
handling, projected cognition, legacy/projected ACI и audit этой границы.
Это изменение плана сохраняет исходный intent как
[отложенную работу](README.md#отложенный-исходный-scope-stage-5); semantic persistence,
write/update/revision и temporal fact lifecycle не являются closure gate Stage 5.
Не требуется Runtime/CLI, Agent/Planner или executor integration.

Принятые уточнения реализации: Canonical IR находится на уровне ANIMA (`anima/ir.py`);
`process_task(CanonicalTask)` не требует text retrieval; unknown candidates отличаются
от known-empty universe. При полных данных отсутствие admissible action — typed
`DETERMINISTIC_RESULT / NO_ADMISSIBLE_ACTION`, а не insufficient data.

## 1. Цель

Интегрировать в основной когнитивный путь ANIMA подтверждённый принцип:

> **LLM получает только ту часть задачи, которую ANIMA не может надёжно решить детерминированно.**

Production-контур должен уметь:

1. представить текущую задачу в общем внутреннем формате ANIMA;
2. применить строгие машинно-проверяемые правила до вызова LLM;
3. отличить однозначный результат от нехватки данных и от настоящей когнитивной задачи;
4. передать когнитивному модулю только минимально достаточную проекцию;
5. сохранить FAST сменяемым backend, который не владеет Memory, Identity, Goals, State или orchestration.

## 2. Канонический путь

```text
conversation.user / future perception / internal event
        ↓
Input Adapter / Language Frontend
        ↓
Canonical ANIMA IR
        ↓
Memory / Working Context evidence
        ↓
Deterministic Resolution
        │
        ├─ DETERMINISTIC_RESULT
        │      ↓
        │   result / render / execute downstream
        │
        ├─ INSUFFICIENT_DATA
        │      ↓
        │   epistemic handling / acquire data / clarification
        │
        └─ COGNITIVE_REQUIRED
               ↓
        Cognitive Router
               ↓
        Adaptive Projector
               ↓
          FAST (Stage 5)
          DEEP (future)
```

`FAST_REQUIRED` из экспериментальных скриптов **не является production-контрактом**. Production route должен называться `COGNITIVE_REQUIRED`, чтобы deterministic layer не зависел от конкретного когнитивного backend.

На Stage 5 `Cognitive Router` может маршрутизировать все поддерживаемые `COGNITIVE_REQUIRED` задачи в FAST. Интерфейс не должен препятствовать добавлению DEEP на Stage 6.

## 3. Границы ответственности

### 3.1 Canonical ANIMA IR

Canonical IR — общий внутренний контракт ANIMA, а не структура FAST prompt.

Он должен быть независим от:

- конкретной LLM;
- Qwen / Granite / SmolLM и других backend;
- конкретного prompt format;
- текстового интерфейса;
- будущих voice / vision / sensor / API источников.

IR хранит достаточно полную внутреннюю информацию для runtime и audit. Model-facing представление строится отдельно.

Первая production-версия должна быть минимальной и типизированной. Не требуется заранее проектировать универсальную ontology.

Минимально допустимые концепты:

- operation / task kind;
- source/input identity;
- subject/entity references, если они уже разрешены;
- requested field / predicate, если он уже разрешён;
- relevant evidence/facts;
- current state / constraints / candidates, когда применимо; unknown candidate universe (`None`) отличается от явно известного пустого (`()`);
- formal policies, когда применимо;
- raw input как provenance/fallback, а не как основной внутренний протокол;
- requested/allowed output contract.

Canonical IR не должен содержать ожидаемый тестовый ответ или скрытый oracle.

### 3.2 Input Adapter / Language Frontend

Frontend не является второй LLM и не должен превращаться в огромный набор эвристик.

Первая production-интеграция обязана быть консервативной:

- детерминированно нормализовать только подтверждённые конструкции;
- сохранять raw input;
- не выдумывать entity, predicate, fact или intent;
- при невозможности безопасно структурировать запрос сохранять его как когнитивную задачу, а не притворяться, что parsing успешен.

Широкий general-purpose русский Language Frontend **не входит** в эту интеграцию.

### 3.3 Deterministic Resolver

Resolver применяет только явно определённые, машинно-проверяемые операции.

Разрешено:

- exact lookup по уже разрешённому structured evidence;
- точная арифметика и сравнения: accepted decimal literals не проходят через binary float, runtime не округляет произвольно; non-terminating decimal result безопасно покидает deterministic path;
- deterministic derived values;
- hard constraints;
- candidate elimination;
- формальные policies;
- однозначные rule-derived результаты.

Запрещено:

- угадывать intent;
- интерпретировать расплывчатый natural language;
- создавать новые policy;
- выбирать «разумнее» без формального критерия;
- silently resolve conflicts, для которых нет формальной политики;
- обращаться к LLM внутри resolver.

Основной safety-инвариант:

```text
false deterministic result > missed deterministic optimization
```

При сомнении задача должна покидать deterministic path.

### 3.4 Resolution result

Минимальные production routes:

```text
DETERMINISTIC_RESULT
INSUFFICIENT_DATA
COGNITIVE_REQUIRED
```

Результат должен быть типизированным и содержать диагностическую причину.

`DETERMINISTIC_RESULT`:

- содержит однозначный value/result либо typed `NO_ADMISSIBLE_ACTION` с `value=None`, когда complete known candidate universe исключён hard constraints или явно пуст;
- не вызывает FAST;
- может содержать derived trace.

`INSUFFICIENT_DATA`:

- не означает автоматически «ответить пользователю, что данных нет»;
- не вызывает FAST только ради генерации отсутствующего частного факта;
- должен позволять указать missing fields / evidence requirements / возможный следующий источник данных;
- дальнейшая политика получения данных остаётся отдельной ответственностью.

`COGNITIVE_REQUIRED`:

- означает, что после строгих правил остаётся реальная интерпретация, trade-off или другой когнитивный остаток;
- может содержать допустимые candidates, derived state и причины unresolved;
- не содержит решения.

### 3.5 Formal Policies

Formal Policy принадлежит ANIMA, а не prompt.

Policy должна быть машиночитаемой. Минимальный контракт первой версии может поддерживать только доказанный тип:

```text
ACTION_PRIORITY
```

Минимальные поля:

- policy id;
- type;
- scope/target при необходимости;
- ordered action priority или эквивалентные machine-readable параметры;
- enabled/active state, если уже требуется текущим кодом.

Правила:

1. policy применяется только после hard constraints;
2. policy не может вернуть действие, которое уже отклонено hard constraints;
3. одна или несколько policies, согласующиеся на одном winner, могут дать deterministic result;
4. конфликтующие policies без формального precedence → `COGNITIVE_REQUIRED`;
5. malformed/incomplete policy не становится deterministic authority;
6. natural-language preference сама по себе не является Formal Policy.

Policy precedence за пределами доказанного случая **не проектировать сейчас**.

### 3.6 Adaptive Projector

Projector не решает задачу.

Его контракт:

> получить Canonical IR + Resolution context и создать минимально достаточное представление для выбранного cognitive consumer.

Projector может:

- удалять нерелевантные поля;
- нормализовать структуру;
- выбирать relevant evidence;
- включать derived values, уже вычисленные runtime;
- включать provenance/confidence/time только когда они нужны конкретной задаче;
- адаптировать renderer под конкретный backend без изменения Canonical IR.

Projector не может:

- выполнять скрытый cognitive choice;
- изобретать evidence;
- менять hard constraints;
- вычислять финальный результат, если это не было сделано resolver;
- подменять Formal Policy текстовой подсказкой.

### 3.7 Cognitive Router

Router получает `COGNITIVE_REQUIRED` после deterministic resolution.

Stage 5 contract:

```text
supported cognitive task → FAST
```

Но API должен оставлять возможность будущего:

```text
simple bounded task → FAST
high depth / large context / high uncertainty → DEEP
```

DEEP не реализуется в этой интеграции.

### 3.8 FAST

Существующий принцип ACI сохраняется:

- FAST — сменяемый low-latency cognitive backend;
- FAST не владеет Memory;
- FAST не пишет напрямую в persistent stores;
- FAST не владеет Identity, Goals, Internal State или system orchestration;
- модель может быть заменена без потери экземпляра ANIMA.

Существующие `FastRequest`, `FastResult`, `FastBackend`, `FastCognition` сохраняют legacy
non-null text/context assumptions. Projected requests используют отдельные
`ProjectedFastRequest` / `ProjectedFastBackend.complete_projected`; неподдерживаемая
capability отклоняется до вызова. LLM backend может явно поддерживать оба интерфейса.

Допустима backward-compatible эволюция ACI или новый adapter над ним, если существующие Stage 5.1/5.2 тесты продолжают проходить.

## 4. Взаимодействие с текущей Memory architecture

Эта интеграция **не создаёт новую Semantic Memory database/schema**.

Существующие:

```text
MemoryStore
KnowledgeLayer
LinkStore
RetrievalEngine
ContextBuilder
ProvenanceResolver
```

остаются authoritative memory path.

Canonical IR может переносить structured evidence, полученное из текущего runtime/context, но persistence новой semantic fact schema не входит в scope.

Semantic Memory write/update/consolidation, temporal fact lifecycle и conflict write policy будут проектироваться отдельно после стабильного read/cognition pipeline.

## 5. Production scope

Codex должен реализовать минимальный production slice, который подтверждает новый путь и не расширяет Stage 5 лишними подсистемами.

Обязательные возможности:

1. типизированный Canonical IR contract;
2. типизированный Resolution result с тремя routes;
3. deterministic resolver с доказанными классами правил;
4. hard-constraint candidate filtering;
5. минимальный Formal Policy `ACTION_PRIORITY`;
6. adaptive model-facing projection;
7. cognitive route, который на Stage 5 вызывает FAST только для supported `COGNITIVE_REQUIRED` с допустимым output;
8. observability, позволяющая увидеть:
   - route;
   - deterministic reason;
   - rejected/remaining candidates;
   - applied policy IDs;
   - backend attempts отдельно от successful completions (successful `call_history` не является счётчиком attempts);
   - terminal backend failure, bounded failure classification и task/source identity, с сохранением exception propagation без retry/fallback;
   - projected model view;
   - final result.

## 6. Explicit non-goals

Не реализовывать в этой работе:

- DEEP;
- general cognitive router heuristics beyond Stage 5 FAST mapping;
- Semantic Memory write path;
- новую semantic DB/schema migration;
- automatic ontology growth;
- full natural-language parser;
- LLM-based Language Frontend;
- policy learning;
- policy precedence system;
- autonomous policy creation;
- AgentLoop resurrection;
- LLM Planner ownership;
- Tools/Executor integration;
- Internal State decision integration;
- Sleep/DEEP consolidation changes;
- physical sensors/periphery.

Если для завершения задачи кажется необходимым один из этих пунктов, Codex должен остановиться на интерфейсе/stub и отметить необходимость, а не расширять scope самостоятельно.

## 7. Experimental evidence to preserve

Экспериментальные scripts/tests являются evidence и **не импортируются production-кодом**.

Ключевые результаты:

- Structured Request / Semantic Memory prototype: structured exact retrieval и safe defer показали жизнеспособность общего IR подхода.
- Test I: Qwen3-0.6B повысила результат на нормализованном structured input с 6/7 до 7/7, но verbose IR оказался тяжелее raw input.
- Test J: adaptive projection существенно сократила token/latency cost, но показала слабость маленькой модели в строгой arithmetic/rule execution.
- Test K: derived intermediate state не гарантировал соблюдение строгого правила моделью.
- Test L: deterministic resolution boundary — 9/9, `false_deterministic=0`, `missed_deterministic=0`.
- Test M: assembled pipeline корректно маршрутизировал 6/6 задач, сохранил 4 из 6 model calls; единственная final error была textual preference choice внутри FAST.
- Test M1: machine-readable Formal Policy — 3/3, `false_deterministic=0`, `missed_deterministic=0`.

Relevant experiment files include:

```text
scripts/run_structured_request_semantic_memory_experiment.py
scripts/run_fast_structured_ir_model_experiment.py
scripts/run_fast_adaptive_ir_projection_experiment.py
scripts/run_fast_cognitive_preprocessing_experiment.py
scripts/run_deterministic_resolution_boundary_experiment.py
scripts/run_end_to_end_resolution_pipeline_experiment.py
scripts/run_formal_policy_resolution_experiment.py
```

Codex may use them as behavioral references but must not copy whole experimental runners into `anima/`.

## 8. Integration constraints for Codex

Before editing production code Codex must inspect at least:

```text
anima/cognition/fast.py
anima/cognition/fast_llm.py
anima/memory/context_builder.py
anima/memory/retrieval.py
anima/memory/knowledge.py
anima/memory/link_store.py
anima/internal_state/choice_engine.py
anima/diagnostics/
tests/test_fast_cognition.py
tests/test_fast_memory_read_bridge.py
```

The exact file layout of new modules may be chosen after repository audit, but these architectural separations are mandatory:

```text
Canonical IR != FAST request format
Deterministic Resolver != LLM
Formal Policy != prompt text
Adaptive Projector != decision engine
COGNITIVE_REQUIRED != FAST ownership
Memory ownership != model ownership
```

Prefer small modules with explicit dataclasses/enums/protocols over one large orchestration file.

Do not change persistent schema unless explicitly required and approved.

Do not delete or rewrite experimental evidence during integration.

Do not modify Agent/Planner architecture as part of this task.

## 9. Backward compatibility

The implementation must preserve existing verified behavior unless a change is explicitly required by this specification.

At minimum keep green:

```text
tests/test_fast_cognition.py
tests/test_fast_memory_read_bridge.py
```

and all currently passing regression tests from previous stages.

Existing `ContextBuilder.build(..., consumer="FAST")` budget/provenance semantics remain authoritative until separately changed.

Existing FAST backend replacement contract must remain valid.

## 10. Required new tests

Production tests must cover at least:

### IR / validation

- valid minimal canonical task;
- invalid/missing required identifiers;
- raw input preserved without becoming authority;
- model-specific fields are absent from Canonical IR.

### Resolution

- exact structured fact → `DETERMINISTIC_RESULT`;
- exact structured fact absent → `INSUFFICIENT_DATA`;
- deterministic comparison YES/NO;
- missing deterministic input → `INSUFFICIENT_DATA`;
- single action after hard constraints → deterministic;
- multiple valid actions without policy → `COGNITIVE_REQUIRED`;
- known-empty/all hard-rejected candidates при полных данных → typed deterministic `NO_ADMISSIBLE_ACTION`;
- omitted/unknown candidate universe → `INSUFFICIENT_DATA`;
- unsupported rules/policies не стирают известные missing requirements;
- unverified-only cognitive request без admissible output не вызывает backend и не выдаётся за доказанную infeasibility;
- unsupported/open operation → `COGNITIVE_REQUIRED`;
- zero false-deterministic cases in the canonical boundary corpus.

### Formal Policy

- one `ACTION_PRIORITY` policy → unique deterministic winner;
- no policy → `COGNITIVE_REQUIRED`;
- two agreeing policies → deterministic winner;
- conflicting policies → `COGNITIVE_REQUIRED`;
- malformed policy → non-deterministic safe fallback;
- policy cannot resurrect hard-rejected action.

### Adaptive Projection

- projection contains only task-relevant fields;
- deterministic-only/audit metadata is omitted unless required;
- conflict task includes confidence/time/provenance when necessary;
- projection cannot mutate Canonical IR;
- backend-specific renderer change does not change Canonical IR.

### Routing / end-to-end

Mixed corpus must prove:

- deterministic result → zero model calls;
- insufficient data → zero model calls;
- supported cognitive task с admissible output → exactly one FAST call; заведомо unsatisfiable constrained request не вызывает backend;
- final response retains route/model-call trace;
- model backend remains replaceable;
- backend attempts, successful completions и terminal failures/classification различимы и наблюдаемы с task/source identity;
- restart/backend replacement does not mutate Memory/Identity ownership.

Use fake/deterministic FAST backends for normal CI. Real Qwen validation remains an explicit manual/benchmark test and must not be required for unit CI.

## 11. Acceptance criteria

Integration is accepted only if all conditions hold:

1. production code imports no experimental runner;
2. Canonical IR is model-independent;
3. resolver has no LLM dependency;
4. production route uses `COGNITIVE_REQUIRED`, not `FAST_REQUIRED`;
5. deterministic result and insufficient-data paths make zero FAST calls;
6. Formal Policy is machine-readable and applied after hard constraints;
7. policy conflict does not silently choose a winner;
8. Adaptive Projector does not become a hidden decision engine;
9. existing FAST/Memory tests pass;
10. new targeted tests pass;
11. full regression suite passes;
12. no persistent schema migration is introduced;
13. final diff contains no unrelated refactor;
14. documentation is updated only after behavior is implemented and verified;
15. final implementation report separates:
    - architecture changes;
    - files changed;
    - tests/results;
    - remaining limitations;
    - follow-up work deliberately left out of scope.

## 12. Implementation workflow

Recommended execution order for Codex:

1. audit current code and tests;
2. propose minimal file/module mapping against this specification;
3. implement typed contracts first;
4. implement resolver + policy with unit tests;
5. implement adaptive projection;
6. add Stage 5 cognitive routing to existing FAST path;
7. add mixed end-to-end tests with fake backend and model-call counting;
8. run targeted existing FAST/Memory tests;
9. run full regression suite;
10. inspect final diff for unrelated changes;
11. only then update implemented Architecture/Stage status documentation.

Do not mark the integration complete merely because unit tests for the new modules pass.

## 13. Deferred follow-up

After this integration is stable, revisit separately:

1. Semantic Memory read/write schema and update lifecycle;
2. temporal/confidence conflict resolution policies;
3. richer Language Frontend and entity/predicate normalization;
4. Cognitive Router FAST/DEEP selection;
5. integration with Internal State, Goals and task system;
6. response rendering versus internal action/result representation;
7. cross-model benchmark using the same fixed model-facing task contract.

The next architectural phase begins only after the current read/resolution/cognition path is stable in production code.
