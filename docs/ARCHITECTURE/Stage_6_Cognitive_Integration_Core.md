# Stage 6 — реализованный Cognitive Integration Core

> Исторический снимок реализованной и подтверждённой архитектуры Stage 6. Динамический статус проекта хранится только в `docs/project.json`.

## Итоговый контур

Stage 6 объединил ранее раздельные подсистемы ANIMA в один system-owned когнитивный lifecycle:

```text
persistent Goal
    ↓
persistent Task
    ↓
CanonicalTask / deterministic resolution
    ├─ deterministic result
    ├─ insufficient data
    └─ cognitive remainder
            ↓
       system Router
       ├─ FAST
       ├─ DEEP
       └─ CHOICE
            ↓
 validated proposal / verified candidate set
            ↓
 Internal State + ChoiceEngine
            ↓
 validated ExecutionAction
            ↓
 Executor
            ↓
 Receipt → independent Observation → Verification
            ↓
 Goal progress / Task transition
```

Sleep, restart recovery и persistent unified trace участвуют в том же lifecycle.

## Ownership

Подтверждены следующие границы:

- FAST и DEEP — сменяемые cognitive backends, не владельцы ANIMA;
- routing принадлежит системе;
- `Goal`, persistent `Task`, `CanonicalTask` и `ExecutionAction` остаются разными сущностями;
- Internal State не создаёт candidates и влияет только через bounded modifiers ChoiceEngine;
- LLM proposal не изменяет Memory, Task, Goal, Internal State, Sleep или execution stores напрямую;
- успешный execution receipt не завершает Goal без independent Observation/Verification;
- Stage 4 Planner/AgentRun/AgentStep не являются Stage 6 cognitive core.

## Persistent Tasks

`TaskStore` хранит отдельные persistent work units в `tasks.db` с append-only transition history.

Lifecycle baseline:

```text
queued → active ↔ interrupted → completed / failed / cancelled
```

Task может ссылаться на Goal, но не владеет Goal lifecycle и не содержит backend/planner semantics.

## Coordinator, Router, FAST и DEEP

`CognitiveCoordinator` связывает active persistent Task с одним `CanonicalTask`, вызывает authoritative deterministic resolver и возвращает только системную directive.

`CognitiveRouter` работает до model call. Baseline policy Stage 6:

- обычный bounded unresolved reasoning → FAST;
- explicit conflict reasoning → DEEP;
- verified multi-action set без formal policy → system CHOICE при явно включённой capability;
- candidate-shaped unsupported path → BLOCKED.

FAST и DEEP реализуют общий `CognitiveBackend` contract и возвращают `CognitiveProposal`. В production Stage 6 разрешён только `RESPOND`; `PROPOSE_ACTION`, `PROPOSE_TASK` и `REQUEST_CONTEXT` остаются disabled vocabulary/experiment boundaries.

Первый real DEEP profile — `SmolLM3-3B-Q8_0`, но модель не закодирована в DEEP role. FAST/DEEP используют общий neutral llama.cpp transport; model profile заменяем без переноса system ownership.

## Goals, Internal State и Choice

`ActionChoiceCoordinator` принимает только уже проверенный resolver-ом candidate set и существующий active Goal. Candidate IDs обязаны точно совпадать с verified remaining set.

ChoiceEngine сохраняет baseline и bounded state-modified evaluation. Подтверждено причинное влияние `uncertainty` через configured information-gain/risk modifiers; Internal State не получает route/Goal authority.

## Execution и independent verification

Stage 6 использует отдельный system execution boundary без Planner semantics.

`execution.db` хранит operation ledger и, начиная с schema v2, точный validated `ExecutionAction` и связанный `VerificationSpec`. Это позволяет после настоящего process restart восстановить исполнительное намерение без старых Python-объектов из RAM.

Перед side effect повторно проверяются active Task и active Goal. Keyed operations поддерживают reconciliation/replay; uncertain operation не объявляется успешной без reconciliation.

Goal success подтверждается только цепочкой:

```text
VerificationSpec
    ↕
ExecutionAction
    ↓
ExecutionReceipt
    ↓
independent Observation
    ↓
VerificationResult
    ↓
GoalVerificationBridge
```

## Sleep lifecycle

Stage 3 Sleep возвращён в общий Task lifecycle без изменения его persistent contracts.

`TaskSleepLinkStore` сохраняет долговечную связь `Task ↔ Goal ↔ SleepJob`. Один checkpointed SleepJob может переживать несколько sleep/wake cycles.

Sleep запрещён на unresolved execution boundary (`prepared`, `executing`, `uncertain`). После wake Task возвращается в `active`; completed/committed side effect не повторяется из-за sleep/wake.

## Recovery и unified trace

`UnifiedTraceStore` (`trace.db`) сохраняет причинную последовательность Stage 6, но не владеет system state.

Один trace связывает минимум:

- Task и Goal;
- CanonicalTask/source;
- deterministic resolution;
- FAST/DEEP/CHOICE route;
- proposal validation;
- context/provenance summary;
- Internal State modifiers;
- Action/operation/receipt;
- observation/verification;
- Sleep/wake;
- restart recovery;
- terminal Task/Goal outcome.

`Stage6RecoveryCoordinator` координирует существующие subsystem recovery boundaries. После restart:

```text
prepared   → prepared
executing  → uncertain
uncertain  → uncertain
succeeded  → succeeded
```

Committed `succeeded` effect не откатывается и не исполняется повторно.

## Mini experiments 6.7

Stage 6 не включил экспериментальные механизмы автоматически.

- `request_more_context`: bounded system-mediated механизм принят на controlled fixture; реальный model-quality эффект остаётся Inconclusive.
- FAST/DEEP routing: current conservative baseline принят; naive uncertainty-only escalation в DEEP отвергнута как более дорогая без доказанного quality gain.
- Internal State effect: bounded deterministic влияние на Choice подтверждено.

Production flags после экспериментов не изменены.

## Final acceptance 6.8

Финальный controlled-restart scenario подтвердил единый lifecycle:

```text
Goal + Task
→ FAST
→ DEEP
→ system CHOICE
→ Sleep / wake
→ validated execution intent
→ side effect
→ controlled restart
→ executing → uncertain
→ reload Action + VerificationSpec from SQLite
→ reconcile without duplicate write
→ independent Observation
→ Verification
→ Goal completed
→ Task completed
→ persistent trace completed
```

Дополнительные cases подтвердили deterministic/insufficient zero-model paths, invalid proposal rejection, backend failure isolation, backend replacement без переноса Identity/Memory/Task/Goal state и Sleep checkpoint/resume после restart.

Representative acceptance: [TV-0051](../TESTING/Results/TV-0051.md).

## Граница Stage 6

Stage 6 не реализует semantic write/update/revision lifecycle, model-created confirmed Knowledge, unrestricted self-generated Goals, weight training, generative dreaming, Virtual ANIMA, perception, distributed compute или hardware-specific routing.

Следующая стадия может использовать этот core как substrate, но не должна возвращать model ownership над persistence, routing, execution или verification.
