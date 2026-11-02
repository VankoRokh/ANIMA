# Будущие механизмы и открытые вопросы

Этот документ хранит **текущие** research tracks, mini experiments и отложенные механизмы. Завершённая реализация описывается в [Architecture](../ARCHITECTURE/README.md), stage/status — в [Roadmap](README.md) и [project.json](../project.json), причины принятых решений — в [ADR](../DECISIONS/README.md).

Исторические формулировки и прежние experiment hypotheses сохраняются Git history и validation reports; их не нужно выдавать за текущий план.

## Статусы

- **Accepted principle** — архитектурный принцип принят, но не означает, что все возможные реализации завершены.
- **Implemented baseline** — механизм существует и подтверждён в текущей архитектуре.
- **Experiment Accepted / Rejected / Inconclusive** — результат ограниченного эксперимента; не равен production capability автоматически.
- **Planned** — направление относится к будущему Stage, но ещё не реализовано.
- **Research / Draft** — вопрос или дизайн без обязательства реализации.

## Текущее положение

### Stage 6 — завершённый baseline

Реализованы и подтверждены:

- persistent Tasks и связь Task ↔ Goal;
- CognitiveCoordinator;
- system-owned FAST/DEEP/CHOICE routing;
- первый DEEP backend/role;
- Internal State + Choice integration;
- bounded ExecutionAction / Executor / independent Observation / Verification;
- Sleep integration в общий Task lifecycle;
- recovery и UnifiedTrace.

Подробности: [Stage 6 implemented architecture](../ARCHITECTURE/Stage_6_Cognitive_Integration_Core.md), representative acceptance — [TV-0051](../TESTING/Results/TV-0051.md).

Stage 6 не доказал, что DEEP всегда улучшает качество, и не сделал все исследовательские routing/context ideas production policy.

### Stage 7 — semantic boundary принят, implementation Planned

Текущий канонический pre-training boundary:
[Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md).

Приняты semantic concepts и read-only `classify_relation/0.1`, но production write lifecycle не реализован. Открыты DP-08/09/10b/11.

Перед model training обязательны:

```text
reviewed conformance corpus
→ deterministic baseline
→ constrained vanilla inference
→ measure semantic residual
→ only then LoRA/SFT decision
```

Conformance plan: [Stage 7 Semantic Conformance v0](../TESTING/Stage7_Conformance_v0.md).

## Research Track: FAST / DEEP / routing

**Accepted principle:** FAST и DEEP — логические cognitive roles, не личности. Routing, Tasks, Memory, verification и execution остаются system-owned.

### Current conservative routing — Implemented baseline

Stage 6 routing вызывает:

- FAST для bounded unresolved reasoning baseline;
- DEEP для explicit conflict reasoning;
- CHOICE для system-owned selection при допустимом verified candidate set;
- deterministic/blocked paths без model call, когда это возможно.

### EXP-004 — request_more_context

**Mechanism Accepted; model-quality effect Inconclusive.**

System-mediated дополнительный retrieval может быть реализован без прямого Memory ownership модели. Controlled mechanism доказан, но достаточного real-model quality gain для production enablement не показано.

Production capability остаётся disabled до отдельной необходимости/приёмки.

### EXP-005 — FAST/DEEP routing baseline

**Conservative routing Accepted. Naive uncertainty-only escalation Rejected. DEEP incremental quality Inconclusive.**

Наблюдение Stage 6 и последующего audit:

- DEEP значительно дороже FAST на текущих моделях;
- простое правило «uncertainty high → DEEP» не оправдало дополнительную стоимость;
- часть различий FAST/DEEP вызвана моделью и prompt/interface, а не самостоятельным доказанным классом «глубокого мышления».

Открытые исследования:

- task-specific routing по измеренному quality/cost;
- same-model FAST/DEEP controls;
- semantic residual после Stage 7 deterministic preprocessing;
- нужен ли DEEP вообще для конкретного operation profile.

## Research Track: model-facing semantic interface

**Accepted direction:** не создавать новый универсальный cognitive DSL поверх уже существующего IR.

Разделять:

1. semantic ontology/data model;
2. operation-specific model-facing protocol;
3. transport renderer/serialization;
4. optional learned adapter.

Первый baseline:

```text
accepted semantic IR
→ typed bounded operation view
→ JSON renderer
→ constrained generation / validation
→ system-owned interpretation
```

JSON является renderer, а не новой моделью мира.

### Open experiment: constrained generation

Для `classify_relation/0.1` сравнить минимум:

- unconstrained diagnostic output;
- constrained JSON/grammar output через существующий llama.cpp transport;
- одинаковую semantic task при neutral prompt.

Структурная валидность измеряется отдельно от semantic accuracy.

### Open experiment: renderer comparison

Только если JSON interface остаётся реальным bottleneck, сравнить одинаковую semantics через:

- compact typed JSON;
- line DSL;
- S-expression.

Отдельный DSL принимается только при измеримом преимуществе по quality/tokens/latency/debuggability без semantic regression.

## Research Track: FAST adaptation / LoRA

**Not started.** Qwen3-0.6B остаётся удобным первым FAST training target из-за малого размера и уже известного поведения, но обучение не является текущим следующим шагом.

Допустимая будущая цель адаптера — **protocol/semantic alignment**, например:

- понимать bounded task structure;
- различать data и service metadata;
- связывать supplied evidence refs;
- сохранять uncertainty/abstention;
- соблюдать typed proposal contract;
- не использовать role/source/confidence/recency как скрытый authority shortcut.

Не помещать в веса как замену системным хранилищам:

- Identity/personality;
- autobiographical Memory;
- current Knowledge database;
- Goals/Tasks;
- lifecycle authority;
- safety/execution permissions.

Training gate:

1. frozen semantic/profile version;
2. independent train/dev/untouched splits;
3. vanilla + same constrained renderer baseline;
4. meaningful residual semantic errors after deterministic processing;
5. explicit owner decision that LoRA/SFT is justified.

Current audit cases remain regression/history and не являются untouched training benchmark.

## Research Track: Stage 7 lifecycle and Knowledge

### Open DP-08 — authority and lifecycle actions

Need to define:

- source authority semantics;
- correction rights;
- accepted system-owned action vocabulary;
- when contradiction/support causes no-op, verification, challenge or revision;
- no direct relation label → write transition shortcut.

### Open DP-09 — Knowledge read semantics

Need explicit mapping between public semantic read state and existing implementation statuses:

```text
provisional
confirmed
challenged
superseded
rejected
```

Temporal applicability, disputes/revisions and historical retrieval must remain visible without creating a parallel undocumented state machine.

### Open DP-10b — dependency re-evaluation

Accepted DP-10a already separates Evidence occurrence from Claim equality and handles replay/dependence.

Still research/design:

- descendant re-evaluation when premise changes;
- multiple alternative grounds;
- when derived outputs become stale vs false vs pending review;
- bounded dependency traversal/cost.

### Open DP-11 — production integration

First implementation should remain read-only/shadow.

Research question: how typed Stage 7 operation results later enter Stage 6 dispatcher/validator contracts without bypassing existing RESPOND/candidate guards or handing models write authority.

## Research Track: semantic extraction

After `classify_relation/0.1` deterministic residual is measured, a separate operation may be needed for semantic extraction from natural-language source fragments.

Possible future profile:

```text
extract_claim/0.x
```

Potential responsibilities:

- bounded source fragment → proposed Claim;
- mention → supplied EntityRef binding or unresolved;
- predicate registry binding;
- polarity/qualifier extraction;
- reported time / assertion time interpretation;
- source span references;
- explicit unsupported/insufficient output.

Do not silently expand `classify_relation/0.1` into a universal parser.

## Research Track: Memory / retrieval

**Implemented baseline:** Event → Memory → Knowledge; Entity/Relation/provenance; SQLite/FTS; bounded Retrieval/Context.

Future mechanisms remain conditional on measured gaps:

- embeddings / semantic retrieval;
- vector DB;
- graph DB / deeper traversal;
- LLM reranking/query expansion;
- richer Entity resolution/NER;
- Memory SPLIT;
- asset/media processors;
- distributed memory/sync.

None are Stage 7 requirements merely because they are technically possible.

## Research Track: verification and active investigation

[Semantic Verification v0](Semantic_Verification_v0.md) remains a scoped concept.

High-significance semantic uncertainty may later create a persistent verification Task using Stage 6 substrate rather than a second investigator agent.

Open questions:

- risk/importance threshold;
- evidence acquisition cost;
- task scheduling/arbitration;
- how resolved verification affects Knowledge under DP-08/09;
- how derived descendants are reassessed under DP-10b.

Models may interpret evidence; they do not assign themselves sensor authority or lifecycle rights.

## Research Track: dynamic Task arbitration / interest

[Dynamic Task Arbitration Concept](Dynamic_Task_Arbitration_Concept.md) remains future-scoped.

Potential factors:

- importance;
- urgency;
- delay cost;
- risk;
- active Goals;
- resource budget;
- switch cost;
- bounded interest/novelty.

Interest is a factor, not authority. Anti-thrashing/aging remain design requirements if this track becomes implementation work.

This is not part of `classify_relation/0.1`.

## Research Track: emergency response

[Emergency Response Mode Concept](Emergency_Response_Mode_Concept.md) remains explicitly out of the current baseline.

Potential future principle: under safety-critical uncertainty, allow conservative reversible system-owned action before perfect diagnosis while preserving uncertainty and verification need.

No model may activate emergency authority merely by generating an emergency label.

## Research Track: Internal State / Goals / autonomy

**Implemented baseline:** Goals and bounded Internal State participate in Stage 6 Choice with causal trace.

Still Research/Draft:

- per-Goal/scoped state refinements;
- interest/novelty drive;
- new state variables only when current factors cannot express required behavior;
- automatic coefficient calibration;
- self-generated Goals with explicit authority/conflict policy.

Self-generated Goal must not silently override external/user/system goals.

## Research Track: Sleep / consolidation

**Implemented baseline:** persistent bounded Sleep orchestration with checkpoint/resume/recovery is integrated with Stage 6 Tasks.

Still Research/Draft:

- multi-day reflection;
- replay of real Goal→Choice→result chains;
- counterfactual simulation;
- generative dreaming with strict real/derived/hypothetical separation;
- DEEP-assisted semantic consolidation;
- model adaptation during Sleep as a separate experiment.

Sleep does not automatically imply training.

## Research Track: Bootstrap Knowledge

[Bootstrap Knowledge v0](Bootstrap_Knowledge_v0.md) remains a scoped Stage 7 concept.

Accepted boundaries:

- versioned curated Source/provenance;
- no provenance-free bootstrap exception;
- Knowledge vs system policy separation;
- fake autobiographical memory excluded from production;
- synthetic history only in explicit test/virtual instances.

Write-through bootstrap ingestion waits for DP-08/09/10b/11.

## Research Track: Virtual ANIMA

**Planned Stage 8.** Virtual environment should provide both interactive sandbox and reproducible workload.

Separate:

- world ground truth;
- synthetic test history;
- live events after runtime start.

Scenario families should include meaningful events, noise, repetition, stale information, contradictions, delayed consequences, causal chains, multi-hop relations, restart/recovery and fault injection.

The world must not stop simply because inference is slow.

## Research Track: hardware and portability

**Planned Stage 9.** Reference platform remains PC; first physical validation target is Raspberry Pi 5.

Measure the same workload on both where possible:

- correctness;
- CPU/RAM/storage I/O;
- temperature/throttling;
- FAST/DEEP/retrieval latency;
- Active/Standby/Sleep resource profile;
- restart/error rate;
- persistent data growth;
- endurance/soak behavior.

Pico is suitable only for justified realtime/telemetry/watchdog/GPIO roles, not as an artificial cognitive host.

CM5/Zero/accelerators/distributed nodes are implementation options, not roadmap requirements before measured need.

## Research Track: perception and interaction

**Planned Stage 10.** Start with available laptop camera/microphone/audio before buying specialized hardware.

Stable source/output interfaces should allow later device replacement without changing cognitive ownership.

Raw continuous media must not automatically become long-term Memory. Perception should produce bounded observations/events with provenance and quality metadata.

## Research Track: physical expansion

**Stage 11+, intentionally broad.** Dedicated cameras, microphone arrays, IMU, actuators, power architecture, cooling and distributed compute are selected only from measured Stage 9–10 requirements.

Physical form does not define ANIMA identity.

## Research Track: identity and personality

**Accepted principle:** continuity is carried by Identity + Memory + rules/state, not one model or one prompt.

A separate personality module remains Research. Do not turn a large hidden system prompt into an unaudited second state database.

## Current research priority

Near-term priority order:

```text
1. finish documentation/conformance fixation for accepted Stage 7 boundary
2. build owner-reviewed 40–50 root conformance corpus
3. implement read-only deterministic evaluator / typed boundary
4. add constrained generation for true semantic residual
5. rerun vanilla Qwen on a fresh corpus
6. decide whether a model classifier adds value at all
7. only then consider LoRA/SFT
8. review DP-08/09/10b/11 before Knowledge write integration
```

This ordering is deliberate: the project should not manufacture work for an LLM when deterministic semantics already solve the problem.
