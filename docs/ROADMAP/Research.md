# Будущие механизмы и открытые вопросы

Этот документ хранит **текущие** research tracks, mini experiments и отложенные механизмы. Завершённая реализация описывается в [Architecture](../ARCHITECTURE/README.md), stage/status — в [Roadmap](README.md) и [project.json](../project.json), причины принятых решений — в [ADR](../DECISIONS/README.md).

Исторические формулировки и прежние experiment hypotheses сохраняются Git history и validation reports; их не следует выдавать за текущий production plan. При этом названия основных Research Tracks и Mini Experiments сохраняются как стабильные documentation anchors, чтобы старые ADR/Archive ссылки не ломались при редактуре.

## Статусы

- **Accepted principle** — архитектурный принцип принят, но не означает завершённую реализацию всех вариантов.
- **Implemented baseline** — механизм существует и подтверждён текущей архитектурой.
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

Stage 6 не доказал, что DEEP всегда улучшает качество, и не сделал все routing/context research ideas production policy.

### Stage 7 — semantic boundary принят, implementation Planned

Текущий канонический pre-training boundary: [Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md).

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

## Research Track: FAST / DEEP / Context

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

Наблюдения Stage 6 и последующего audit:

- DEEP значительно дороже FAST на текущих моделях;
- простое правило `uncertainty high → DEEP` не оправдало дополнительную стоимость;
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

Только если JSON interface остаётся реальным bottleneck, сравнить одинаковую semantics через compact typed JSON, line DSL и S-expression. Отдельный DSL принимается только при измеримом преимуществе по quality/tokens/latency/debuggability без semantic regression.

## Research Track: FAST adaptation / LoRA

**Not started.** Qwen3-0.6B остаётся удобным первым FAST training target из-за малого размера и уже известного поведения, но обучение не является текущим следующим шагом.

Допустимая будущая цель адаптера — **protocol/semantic alignment**:

- понимать bounded task structure;
- различать data и service metadata;
- связывать supplied evidence refs;
- сохранять uncertainty/abstention;
- соблюдать typed proposal contract;
- не использовать role/source/confidence/recency как скрытый authority shortcut.

Не помещать в веса как замену системным хранилищам Identity/personality, autobiographical Memory, current Knowledge, Goals/Tasks, lifecycle authority и safety/execution permissions.

Training gate:

1. frozen semantic/profile version;
2. independent train/dev/untouched splits;
3. vanilla + same constrained renderer baseline;
4. meaningful residual semantic errors after deterministic processing;
5. explicit owner decision that LoRA/SFT is justified.

Current audit cases remain regression/history и не являются untouched training benchmark.

## Research Track: Stage 7 lifecycle and Knowledge

### Open DP-08 — authority and lifecycle actions

Нужно определить source authority semantics, correction rights, accepted system-owned action vocabulary и условия, при которых contradiction/support вызывает no-op, verification, challenge или revision. Прямого `relation label → write transition` shortcut быть не должно.

### Open DP-09 — Knowledge read semantics

Нужно явное отображение между public semantic read state и существующими implementation statuses:

```text
provisional
confirmed
challenged
superseded
rejected
```

Temporal applicability, disputes/revisions и historical retrieval должны оставаться видимыми без параллельной неописанной state machine.

### Open DP-10b — dependency re-evaluation

DP-10a уже разделяет Evidence occurrence и Claim equality и определяет replay/dependence. Открыты descendant re-evaluation, alternative grounds, stale/false/pending-review semantics и bounded traversal cost.

### Open DP-11 — production integration

Первая реализация должна оставаться read-only/shadow. Нужно определить, как typed Stage 7 results войдут в Stage 6 dispatcher/validator contracts без обхода существующих guards и без передачи model write authority.

## Research Track: semantic extraction

После измерения deterministic residual отдельная операция может понадобиться для semantic extraction из natural-language fragments.

Возможный будущий profile:

```text
extract_claim/0.x
```

Он может предлагать Claim, EntityRef binding/unresolved, predicate registry binding, polarity/qualifiers, reported/asserted time и source spans. `classify_relation/0.1` не должен превращаться в универсальный parser.

## Research Track: Memory и данные

**Implemented baseline:** Event → Memory → Knowledge; Entity/Relation/provenance; SQLite/FTS; bounded Retrieval/Context.

Будущие механизмы вводятся только после измеренного ограничения baseline:

- embeddings / semantic retrieval;
- vector DB;
- graph DB / deeper traversal;
- LLM reranking/query expansion;
- richer Entity resolution/NER;
- Memory SPLIT;
- asset/media processors;
- distributed memory/sync.

Stage 7 дополнительно требует сохранить Evidence identity/provenance и не превращать contradiction в destructive overwrite.

## Research Track: verification and active investigation

[Semantic Verification v0](Semantic_Verification_v0.md) остаётся scoped concept.

High-significance semantic uncertainty может позже создавать persistent verification Task на Stage 6 substrate вместо отдельного investigator agent. Открыты risk/importance threshold, acquisition cost, task arbitration, влияние resolved verification на Knowledge по DP-08/09 и descendant reassessment по DP-10b.

Models могут интерпретировать evidence; они не назначают себе sensor authority или lifecycle rights.

## Research Track: dynamic Task arbitration / interest

[Dynamic Task Arbitration Concept](Dynamic_Task_Arbitration_Concept.md) остаётся future-scoped.

Potential factors: importance, urgency, delay cost, risk, active Goals, resource budget, switch cost, bounded interest/novelty. Interest — фактор, не authority. Anti-thrashing/aging обязательны, если track станет implementation work.

## Research Track: emergency response

[Emergency Response Mode Concept](Emergency_Response_Mode_Concept.md) остаётся вне текущего baseline.

Future principle: при safety-critical uncertainty система может предпочесть conservative reversible action до perfect diagnosis, сохраняя uncertainty и verification need. Model не получает emergency authority генерацией label.

## Research Track: Internal State / Goals / autonomy

**Implemented baseline:** Goals и bounded Internal State участвуют в Stage 6 Choice с causal trace.

Still Research/Draft:

- per-Goal/scoped state refinements;
- interest/novelty drive;
- новые state variables только если текущих факторов недостаточно;
- automatic coefficient calibration;
- self-generated Goals с явным authority/conflict policy.

Self-generated Goal не должен молча переопределять внешний/user/system Goal.

## Research Track: Sleep и consolidation

**Implemented baseline:** persistent bounded Sleep orchestration с checkpoint/resume/recovery интегрирована с Stage 6 Tasks.

Still Research/Draft:

- multi-day reflection;
- replay реальных Goal→Choice→result chains;
- counterfactual simulation;
- generative dreaming с разделением real/derived/hypothetical;
- DEEP-assisted semantic consolidation;
- model adaptation during Sleep как отдельный experiment.

Sleep не означает training автоматически.

## Research Track: Bootstrap Knowledge

[Bootstrap Knowledge v0](Bootstrap_Knowledge_v0.md) остаётся scoped Stage 7 concept.

Accepted boundaries: versioned curated Source/provenance, отсутствие provenance-free bootstrap exception, Knowledge/policy separation, fake autobiography вне production, synthetic history только в test/virtual instances. Write-through ingestion ждёт DP-08/09/10b/11.

## Research Track: Virtual ANIMA

**Planned Stage 8.** Virtual environment должна быть одновременно interactive sandbox и reproducible workload.

Разделяются world ground truth, synthetic test history и live events. Scenario families должны включать meaningful events, noise, repetition, stale information, contradictions, delayed consequences, causal chains, multi-hop relations, restart/recovery и fault injection. Мир не должен останавливаться из-за медленного inference.

## Research Track: Hardware и переносимость

**Planned Stage 9.** Reference platform остаётся PC; первый physical validation target — Raspberry Pi 5.

На одинаковом workload измерять correctness, CPU/RAM/storage I/O, temperature/throttling, FAST/DEEP/retrieval latency, Active/Standby/Sleep resource profile, restart/error rate, persistent data growth и endurance/soak behavior.

Pico подходит только для оправданных realtime/telemetry/watchdog/GPIO ролей. CM5/Zero/accelerators/distributed nodes — implementation options, а не roadmap requirements до измеренной необходимости.

## Интерфейсы и действия

**Accepted boundary:** предложение действия и фактический результат — разные события. Выполнение требует independent Observation/Verification; текст `success` от модели не является evidence исполнения.

Для независимых узлов до выбора транспорта нужны versioned contracts: sender/receiver, schema, units, timeout, errors, retry/idempotency, ordering/conflicts и minimal behavior при отказе узла. Общий mutable state не становится сетевым контрактом автоматически.

### Research Track: perception and interaction

**Planned Stage 10.** Начать с доступных laptop camera/microphone/audio. Stable source/output interfaces должны позволять замену устройств без изменения cognitive ownership.

Raw continuous media не становится long-term Memory автоматически. Perception должен выдавать bounded observations/events с provenance и quality metadata.

## Research Track: physical expansion

**Stage 11+, intentionally broad.** Dedicated cameras, microphone arrays, IMU, actuators, power architecture, cooling и distributed compute выбираются только из измеренных Stage 9–10 requirements. Physical form не определяет ANIMA identity.

## Research Track: identity and personality

**Accepted principle:** continuity несут Identity + Memory + rules/state, а не одна model или prompt. Отдельный personality module остаётся Research; большой скрытый system prompt не должен превращаться во вторую неаудируемую базу состояния.

## Mini Experiments

Mini Experiments сохраняют стабильные IDs как исторические/research anchors. Их status ниже обновлён по текущему состоянию проекта.

### EXP-001 — Internal weight for memory selection

**Planned / no result.** Проверить, улучшает ли bounded state-derived weighting отбор полезного опыта при ограниченном memory budget по сравнению с обычным retrieval/selection.

### EXP-002 — Selected experience improves FAST

**Planned / no result.** Раздельно сравнивать context/rule updates и weight training; нужны fixed model, independent evaluation set, rollback и quality/resource metrics.

### EXP-003

**Planned / no result.** Local reinforcement for peripheral task: проверить локальное подкрепление на одной bounded simulation/peripheral-control задаче. Глобальная reward-функция личности из этого не следует.

### EXP-004 — Request more context

**Mechanism Accepted; quality effect Inconclusive.** System-mediated дополнительный retrieval архитектурно допустим; production enablement не подтверждён.

### EXP-005 — FAST/DEEP routing baseline

**Partly Accepted / Partly Rejected / quality Inconclusive.** Conservative explicit routing принят; naive uncertainty-only escalation отвергнут; общий incremental DEEP quality не доказан.

### EXP-006 — Semantic conflict lifecycle

**Planned Stage 7.** Проверять semantic relation/lifecycle только после принятия DP-08/09/10b/11; read-only relation classification предшествует write-through experiment.

### EXP-007 — Virtual memory/noise corpus

**Planned Stage 8.** Контролируемая смесь important/noise/repeated/stale/contradictory experience с известным ground truth.

### EXP-008 — PC/Pi endurance parity

**Planned Stage 9.** Один фиксированный Virtual ANIMA workload на PC и Pi 5 с сопоставлением correctness, latency, resources и endurance.

## Current research priority

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

Этот порядок намеренный: проект не должен искусственно оставлять работу LLM там, где deterministic semantics уже дают точный ответ.
