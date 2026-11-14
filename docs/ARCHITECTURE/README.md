# Реализованная архитектура

Этот раздел описывает **подтверждённый работающий код**, а не будущие design proposals.
Динамический stage/status хранится в [project.json](../project.json). Будущие механизмы находятся в [Roadmap](../ROADMAP/README.md) и [Research](../ROADMAP/Research.md).

Stage 6 завершён и является текущей реализованной cognitive integration boundary. Его подробный исторический снимок:
[Stage 6 — Cognitive Integration Core](Stage_6_Cognitive_Integration_Core.md).

Принятый Stage 7 semantic boundary пока **не реализован**; он документирован в
[Stage 7 Semantic Boundary v0](../ROADMAP/Stage_7_Semantic_Boundary_v0.md).

## Релизная сборка ANIMA v0.1

**Исполняемая точка входа кандидата:** [`anima/release_v01.py`](../../anima/release_v01.py). Составляет уже существующие `CoreAssembly` и `Runtime` через `build_core`; не заменяет внутренние жизненные циклы своей реализацией. Для текущей версии используется persistent Identity, State, EventLog, EventProcessingCoordinator, MemoryStore/LinkStore, EventRetrieval (opt-in), RetrievalEngine + ContextBuilder, InternalState/GoalStore и CoreIngress/GoalDecision без зарегистрированных внешних источников и исполнительных capabilities.

**Default:** локальный JSONL stdin driver, поддерживает несколько пользовательских reports, bounded чтение памяти, статус и остановку; LLM, сеть, Godot и внешние исполнители отсутствуют. Сообщения `conversation.user` не являются доверенными `state.property` наблюдениями, поэтому не создают Core Beliefs или подтверждённое Knowledge автоматически.

**Только в отдельно включаемой локальной фикстуре:** `--sandbox-door` регистрирует известный сенсор/действие VirtualDoorWorld и проверяет Goal/Task, допуск, keyed effect и independent verification. Реальный внешний доверенный адаптер не входит в релизный профиль.

Профиль возможностей записывается в `release_profile.json`. `flock` защищает от одновременной работы двух штатных экземпляров с одним каталогом. Непустой каталог неизвестного профиля и попытка переключить активный профиль без миграции отклоняются. Это минимальная защита согласованности **кооперативного Linux runtime**, а не система аутентификации операторов или граница для недоверенного локального кода.

**Release gates и доказательства:** [RELEASES](../RELEASES/README.md). Предыдущие Stage 6 и Memory v1 лаборатории остаются источниками кода и исторических свидетельств, но не должны автоматически обозначаться как принятые части v0.1.

## Текущий system-owned контур

```text
raw input / Event / source data
          ↓
      Runtime / stores
          ↓
      persistent Task
          ↓
      CanonicalTask
          ↓
 deterministic resolution
   ├─ deterministic result
   ├─ insufficient data
   └─ cognitive remainder
             ↓
        system Router
        ├─ FAST
        ├─ DEEP
        └─ CHOICE
             ↓
     validated proposal
             ↓
 Internal State + ChoiceEngine
             ↓
  validated ExecutionAction
             ↓
          Executor
             ↓
Receipt → Observation → Verification
             ↓
   Goal progress / Task state
```

Sleep, recovery and UnifiedTrace participate in the same lifecycle.

## Ownership rules

Confirmed boundaries:

- Identity/state/events/memory/tasks/goals/sleep/execution remain system-owned;
- FAST and DEEP are replaceable cognitive backends, not personalities or authorities;
- routing is system-owned and occurs before model invocation;
- model output is proposal-only and cannot directly mutate Memory/Knowledge/Task/Goal/Internal State/Sleep/execution stores;
- Internal State modifies Choice through bounded rules and does not create candidates/goals;
- execution success receipt is not Goal success; independent Observation/Verification is required;
- Stage 4 Planner/AgentRun remains historical/experimental substrate, not the current top-level cognitive owner;
- semantic write/update/revision is not yet implemented by Stage 6.

## Компоненты и подтверждение

| Компонент | Ответственность | Код | Проверка |
|---|---|---|---|
| Runtime | system-owned assembly/session runtime | [runtime.py](../../anima/runtime.py) | [test_runtime.py](../../tests/test_runtime.py) |
| Identity / state / events | persistent identity, lifecycle state, raw event flow | [state.py](../../anima/core/state.py) | [test_state.py](../../tests/test_state.py) |
| Cognitive Memory | Event → Memory → Knowledge and evidence/provenance storage | [knowledge.py](../../anima/memory/knowledge.py) | [test_knowledge.py](../../tests/test_knowledge.py) |
| Retrieval / Context | bounded memory read and context projection | [retrieval.py](../../anima/memory/retrieval.py) | [test_retrieval.py](../../tests/test_retrieval.py) |
| Canonical IR / resolver | deterministic resolution before model cognition | [ir.py](../../anima/ir.py) | [test_resolution.py](../../tests/test_resolution.py) |
| Cognitive routing / coordination | system FAST/DEEP/CHOICE routing and coordination | [routing.py](../../anima/cognition/routing.py) | [test_cognitive_routing.py](../../tests/test_cognitive_routing.py) |
| FAST cognition | bounded replaceable primary cognitive backend | [fast_llm.py](../../anima/cognition/fast_llm.py) | [test_fast_llm_backend.py](../../tests/test_fast_llm_backend.py) |
| DEEP cognition | explicitly routed expensive cognitive backend | [deep_llm.py](../../anima/cognition/deep_llm.py) | [test_deep_dispatch_integration.py](../../tests/test_deep_dispatch_integration.py) |
| Internal State / Choice | bounded state influence and system candidate selection | [choice_engine.py](../../anima/internal_state/choice_engine.py) | [test_choice_engine.py](../../tests/test_choice_engine.py) |
| Persistent Tasks | persistent work units distinct from Goal/CanonicalTask | [store.py](../../anima/tasks/store.py) | [test_task_store.py](../../tests/test_task_store.py) |
| Execution / Verification | validated side effects, receipts, observations and independent verification | [coordinator.py](../../anima/execution/coordinator.py) | [test_stage6_execution_verification.py](../../tests/test_stage6_execution_verification.py) |
| Sleep lifecycle | persistent bounded Sleep orchestration integrated with Tasks | [task_lifecycle.py](../../anima/sleep/task_lifecycle.py) | [test_stage6_sleep_lifecycle.py](../../tests/test_stage6_sleep_lifecycle.py) |
| UnifiedTrace / recovery | persistent causal trace and restart reconciliation | [unified_trace.py](../../anima/diagnostics/unified_trace.py) | [test_stage6_unified_trace_recovery.py](../../tests/test_stage6_unified_trace_recovery.py) |

Representative validation history is indexed in [Testing Results](../TESTING/Results/README.md). Stage 6 final acceptance: [TV-0051](../TESTING/Results/TV-0051.md).

## Cognitive Memory boundary

Persistent memory keeps three distinct levels:

```text
Event → Memory → Knowledge
```

- Event preserves raw occurrence/history;
- Memory is compact episodic/semantic experience;
- Knowledge has its own lifecycle and evidence links;
- Entity and Relation provide stable semantic links;
- provenance remains traceable toward source Events.

Current storage uses SQLite/FTS baseline rather than embeddings/vector/graph DB by default.

Existing Knowledge implementation statuses remain:

```text
provisional
confirmed
challenged
superseded
rejected
```

Stage 7 documentation must not invent a second production status vocabulary without an explicit accepted mapping (open DP-09).

## Stage 5 deterministic/cognitive boundary

Stage 5 established that formal/easy cases remain outside the LLM:

```text
CanonicalTask
     ↓
resolver
 ├─ deterministic result
 ├─ insufficient data
 └─ cognitive remainder → projection → FAST
```

Exact arithmetic uses exact rational/Decimal semantics. Missing data is distinguished from infeasible/no admissible action. Model output is validated against allowed outputs and does not own persistence.

Representative acceptance: [TV-0043](../TESTING/Results/TV-0043.md).

## Stage 6 Cognitive Integration Core

Stage 6 added the integrated system substrate:

- persistent Tasks and Task↔Goal linkage;
- `CognitiveCoordinator` and system `CognitiveRouter`;
- explicit FAST/DEEP/CHOICE routes;
- common `CognitiveProposal` validation boundary;
- Internal State and Choice integration;
- validated `ExecutionAction` plus persisted `VerificationSpec`;
- independent Observation/Verification;
- Sleep integration with Task lifecycle;
- restart/recovery across execution uncertainty;
- persistent UnifiedTrace.

The canonical detailed document is [Stage 6 — Cognitive Integration Core](Stage_6_Cognitive_Integration_Core.md).

### FAST/DEEP status

FAST/DEEP are roles, not fixed models. Current experimental defaults may change without changing the architecture.

Stage 6 experiments showed:

- conservative routing mechanism works;
- `request_more_context` mechanism was accepted experimentally, but real quality benefit remains inconclusive;
- naive uncertainty-only DEEP escalation was rejected as more expensive without proven gain;
- bounded Internal State influence on Choice is demonstrable.

Therefore DEEP is not documented as universally superior reasoning. Its current value must continue to be measured per task.

## Execution semantics

The execution boundary separates intent, side effect, observation and verified outcome:

```text
ExecutionAction
      ↓
Executor
      ↓
ExecutionReceipt
      ↓
independent Observation
      ↓
VerificationResult
      ↓
Goal progress
```

A successful tool/OS receipt does not by itself complete a Goal.

`execution.db` persists exact validated action intent and verification specification needed for restart/reconciliation. `executing → uncertain` after restart remains conservative until reconciliation/observation establishes the result.

## Sleep boundary

Sleep is a software orchestration mode, not a third cognitive model.

Confirmed properties:

- persistent jobs/work items/checkpoints;
- bounded chunk processing;
- safe wake/interruption;
- restart recovery;
- derived results preserve provenance and do not inherit source authority automatically;
- Task↔Goal↔Sleep linkage participates in Stage 6 lifecycle.

Generative dreaming, unrestricted reflection and FAST weight adaptation during Sleep are not implemented guarantees.

## Каталог и контракты данных

Default data location is `<project>/data`; `ANIMA_DATA_DIR` may select another location.

| File | Purpose |
|---|---|
| `identity.json` | persistent instance identity |
| `state.json` | lifecycle/session/event counter state |
| `events.jsonl` | append-only raw Events |
| `memory.db` | Cognitive Memory / Knowledge / Entities / Relations / provenance |
| `internal_state.db` | Internal State, Goals, causal transitions and source recovery ledger |
| `sleep.db` | Sleep jobs/work/checkpoints/derived results |
| `tasks.db` | persistent Stage 6 Tasks |
| `execution.db` | execution operation ledger, validated action and verification spec |
| `trace.db` | persistent UnifiedTrace |

Backup/restore must preserve the entire instance data directory. Code clone alone is not instance continuation.

## Current limitations

Confirmed current limitations include:

- EventBus FIFO remains RAM-only; persistence is in the raw Event log/recovery path rather than a persistent broker queue;
- JSONL and SQLite commits are not one physical transaction; recovery/idempotency close the gap at logical-operation level;
- Memory automatic close/merge policy remains limited and explicit;
- semantic write/update/revision lifecycle from the accepted Stage 7 boundary is **not implemented**;
- Stage 7 `Claim`/`Evidence`/typed relation contract is documentation-only until a later implementation slice;
- existing Knowledge status/read semantics have not yet been remapped to Stage 7 public semantic read states (DP-09 open);
- full Evidence dependency descendant re-evaluation remains open DP-10b;
- production Stage 6 dispatcher does not yet expose `classify_relation/0.1` (DP-11 open);
- DEEP quality advantage is not generally proven; model selection remains empirical;
- `request_more_context` quality benefit remains inconclusive and production-disabled;
- embeddings/vector/graph DB/distributed memory are not part of the confirmed baseline;
- self-generated Goals and broad autonomy authority are not confirmed;
- generative dreaming and model weight training are not part of the confirmed runtime;
- Virtual ANIMA, perception and hardware-specific routing remain future stages.

## Stage 7 boundary

Accepted documentation only:

- [Stage 7 Semantic Boundary v0](../ROADMAP/Stage_7_Semantic_Boundary_v0.md);
- [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md);
- [Stage 7 Semantic Conformance v0](../TESTING/Stage7_Conformance_v0.md).

The first authorized implementation direction is read-only/shadow semantic evaluation with deterministic-first processing. Production Knowledge writes require separate acceptance of DP-08/09/10b/11.

## Documentation note

Earlier detailed architecture text remains available through Git history. This README intentionally acts as the current architecture index and confirmed-boundary summary so completed Stage 6 behavior is not described as future work.
