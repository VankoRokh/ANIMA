# План развития

Статусы, зависимости и текущая работа берутся из [project.json](../project.json).
Roadmap описывает цель, границы и проверяемый результат этапов. Реализованные детали
находятся в [Architecture](../ARCHITECTURE/README.md), причины решений — в
[ADR](../DECISIONS/README.md), показательные доказательства — в
[Testing Results](../TESTING/Results/README.md), а неутверждённые направления и
эксперименты — в [Research](Research.md).

**Рабочий проектный план (не утверждён как новый Stage):** [Core v0.1 и Virtual ANIMA Lab v0.1](Core_v0_1_VAL_v0_1_Plan_Draft.md). Он описывает порядок подготовки standalone Core, его проверок и последующего подключения к виртуальной среде; статусы `project.json` не меняет.

<!-- AUTO:roadmap:START -->
**Текущая работа:** Stage 6 Cognitive Integration Core завершён и подтверждён TV-0051. Для Stage 7 принят pre-training semantic boundary v0: immutable qualified/time-scoped Claim, отдельные Evidence/Source/Producer/provenance, typed Value v0, explicit temporal semantics, независимые CONTENT/REVISION results и read-only classify_relation/0.1 с deterministic-first processing. Stage 7 implementation остаётся Planned; DP-08, DP-09, полная dependency policy DP-10 и production integration DP-11 открыты. До model training обязательны conformance corpus и измерение реального model residual; LoRA/SFT не начаты.

**Фокус:** 7 — Semantic Lifecycle & Refinement (Planned).

| Этап | Проверяемый результат | Статус | Зависимости |
|---|---|---|---|
| [D0 — Documentation](#d0) | Контекст и процедуры работы восстанавливаются из репозитория | Complete | — |
| [0 — Foundation](#stage-0) | Перенос сохраняет идентичность, историю и возможность продолжения | Complete | [D0](#d0) |
| [D1 — Runtime, Tests & Observability](#d1) | Один сценарий запускается headless, наблюдается и проверяется изолированно | Complete | [0](#stage-0) |
| [1 — Cognitive Memory](#stage-1) | Релевантный опыт извлекается с происхождением и ограниченным контекстом | Complete | [0](#stage-0), [D1](#d1) |
| [2 — Internal State](#stage-2) | Влияние внутреннего состояния на выбор причинно прослеживается | Complete | [1](#stage-1) |
| [3 — Sleep](#stage-3) | Консолидация прерывается и возобновляется без потери источников | Complete | [2](#stage-2) |
| [4 — Agent / LLM Planner Experiment](#stage-4) | Проверен recoverable action loop, но роль LLM Planner признана архитектурным отклонением; результаты 4.0–4.12 сохранены | Stopped | [3](#stage-3) |
| [5 — FAST Cognition & Memory Integration](#stage-5) | FAST использует ограниченный контекст Cognitive Memory и участвует в текстовом цикле без владения памятью или системным состоянием | Complete | [1](#stage-1), [D1](#d1) |
| [6 — Cognitive Integration Core](#stage-6) | FAST, DEEP, routing, Tasks, Goals, Internal State, Sleep и проверяемый исполнительный слой участвуют в одном наблюдаемом когнитивном цикле без передачи LLM системного ownership | Complete | [5](#stage-5), [2](#stage-2), [3](#stage-3) |
| [7 — Semantic Lifecycle & Refinement](#stage-7) | Semantic write/update/revision/consolidation работают с provenance и authority rules; bootstrap knowledge проходит через тот же проверяемый lifecycle | Planned | [6](#stage-6), [1](#stage-1), [3](#stage-3) |
| [8 — Virtual ANIMA](#stage-8) | ANIMA непрерывно действует в наблюдаемой 2D-среде с synthetic history, live events, ручными и автоматизированными сценариями | Planned | [7](#stage-7) |
| [9 — Raspberry Pi Validation](#stage-9) | Один и тот же workload воспроизводимо сравнивается на PC и Raspberry Pi 5; Pico используется только там, где полезен realtime/telemetry контур; сняты performance и endurance показатели | Planned | [8](#stage-8) |
| [10 — Perception & Interaction](#stage-10) | Камера, микрофон и аудиовывод подключаются через стабильные source/output interfaces и преобразуются в наблюдаемые Events без захламления Memory сырыми потоками | Planned | [9](#stage-9) |
| [11 — Physical Expansion](#stage-11) | После измеренных требований подключается специализированная физическая периферия и исследуется первое устойчивое физическое воплощение без потери Identity/Memory | Planned | [10](#stage-10) |
<!-- AUTO:roadmap:END -->

## D0

Документация вынесена в репозиторий и имеет канонические источники истины.
Изменения статусов идут через `project.json`; динамические сводки не должны иметь
несколько независимых ручных источников.

## Stage 0

**Foundation — Complete.** Постоянный instance ID, lifecycle/state, sessions, raw
Events, безопасная запись и перенос data directory переживают restart/restore.
Доказательство: [TV-0001](../TESTING/Results/TV-0001.md).

## D1

**Runtime, Tests & Observability — Complete.** Headless Runtime, ScenarioRunner,
trace и изолированный test harness позволяют воспроизводимо наблюдать поведение.
Доказательство: [TV-0002](../TESTING/Results/TV-0002.md).

## Stage 1

**Cognitive Memory — Complete.** Проверен цикл
`Event → Memory → Knowledge → Retrieval → Context Builder` с provenance,
bounded context, recovery и performance baseline.
Доказательства: [TV-0004 — TV-0015](../TESTING/Results/README.md).

## Stage 2

**Internal State — Complete.** Goals, ограниченные состояния, Choice и причинная
история подтверждены как отдельный регулирующий слой, а не самостоятельный владелец
решений. Доказательства: [TV-0016 — TV-0017](../TESTING/Results/README.md).

## Stage 3

**Sleep — Complete.** Persistent bounded orchestration, checkpoint/resume,
derived results и provenance подтверждены. Доказательства:
[TV-0018 — TV-0030](../TESTING/Results/README.md).

## Stage 4

**Agent / LLM Planner Experiment — Stopped after 4.12.** Эксперимент доказал
полезные свойства Executor/Tool/Observation/Verification/recovery, но показал, что
LLM Planner как владелец proposal generation противоречит архитектуре ANIMA.
Результаты 4.0–4.12 сохранены; полезный исполнительный код возвращён позднее под
system ownership без возврата Planner ownership.

Доказательства: [TV-0031 — TV-0042](../TESTING/Results/README.md).
Решения: [ADR-008](../DECISIONS/README.md#adr-008),
[ADR-009](../DECISIONS/README.md#adr-009).

## Stage 5

**FAST Cognition & Memory Integration — Complete.** Авторитетный scope сохранён в
[Cognitive Resolution Integration Spec](Cognitive_Resolution_Integration_Spec.md).
Stage доказал model-independent boundary:

```text
input
  ↓
Canonical IR + bounded context
  ↓
deterministic resolution
  ├─ deterministic result / no admissible action
  ├─ insufficient data
  └─ cognitive remainder → projection → FAST
                              ↓
                        final validation
```

FAST остаётся сменяемым cognitive consumer и не владеет Memory, Identity, Goals,
routing или Runtime. Cross-session read, backend replacement, observability,
projected cognition и failure audit подтверждены representative acceptance.
Доказательство: [TV-0043](../TESTING/Results/TV-0043.md).

Отложенные старые цели 5.5/5.6 — semantic interpretation-to-write,
write/update/revision и temporal lifecycle — **не считаются выполненными** и
перенесены в Stage 7.

## Stage 6

**Cognitive Integration Core — Complete.** Утверждённый target/decomposition сохранён в
[Stage 6 Cognitive Integration Core](Stage_6_Cognitive_Integration_Core.md), а
реализованная архитектура — в
[Architecture: Stage 6 Cognitive Integration Core](../ARCHITECTURE/Stage_6_Cognitive_Integration_Core.md).

Stage 6 объединил под system ownership:

- persistent Tasks и Goal linkage;
- CognitiveCoordinator и явный FAST/DEEP routing;
- первый DEEP backend/role без отдельной личности или authority;
- Internal State и Choice как причинные факторы, а не владельцы решения;
- bounded Executor/Observation/independent Verification;
- Sleep в общем Task lifecycle;
- recovery и UnifiedTrace;
- разделение Action → Receipt → Observation → Verification → Goal progress.

Модель остаётся proposal-only: routing, persistence, execution, verification и системные переходы принадлежат ANIMA. Stage 6 не доказал преимущество DEEP по качеству во всех задачах и не превратил `request_more_context` или adaptive routing в обязательную production policy — эти вопросы остаются research.

Доказательства: [TV-0044 — TV-0051](../TESTING/Results/README.md), итоговая приёмка — [TV-0051](../TESTING/Results/TV-0051.md).

## Stage 7

**Semantic Lifecycle & Refinement — Planned. Semantic boundary v0 accepted; production implementation not started.**

Канонический pre-training/read-only контракт:
[Stage 7 Semantic Boundary v0](Stage_7_Semantic_Boundary_v0.md).
Причина решения: [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md).
Conformance-план: [Stage 7 Semantic Conformance v0](../TESTING/Stage7_Conformance_v0.md).

### Принятый первый slice

Перед production write lifecycle вводится ограниченный read-only/shadow semantic interface:

- immutable qualified/time-scoped Claim;
- Evidence identity отдельно от Claim equality;
- Source отдельно от Producer;
- typed Value v0 + registry-owned predicate/cardinality/qualifiers;
- `observed_at`, `asserted_at`, `received_at`, `created_at` и world-valid scope не смешиваются;
- `Unknown != Unbounded`;
- CONTENT и REVISION — независимые facet results;
- `SUPPORT`, `CONTRADICTION`, `COMPATIBLE_DISTINCT`, `TEMPORAL_SUCCESSION`, `CORRECTION`, insufficiency/not-comparable/unsupported;
- `classify_relation/0.1` сравнивает ровно два supplied Claims и bounded Evidence;
- deterministic-decidable cases не должны вызывать LLM;
- conformance corpus и измерение реального semantic residual предшествуют LoRA/SFT.

### Открытые решения

До write-through lifecycle остаются открыты:

- DP-08 — authority/lifecycle actions/correction rights;
- DP-09 — public Knowledge read semantics и mapping на текущие statuses;
- DP-10b — полная re-evaluation policy для derived descendants;
- DP-11 — production integration с Stage 6 routing/validators.

Stage 7 не считается начатым только из-за принятия semantic boundary. Первый implementation slice должен быть отдельным read-only/shadow capability после фиксации conformance fixtures.

### Design history и scoped concepts

Ранние design baselines сохранены для контекста; при конфликте с accepted boundary текущий slice следует `Stage_7_Semantic_Boundary_v0.md`:

- [SemanticCandidate v0](Semantic_Candidate_v0.md);
- [Knowledge Lifecycle v0](Knowledge_Lifecycle_v0.md);
- [Semantic Temporal Conflict v0](Semantic_Temporal_Conflict_v0.md);
- [Semantic Verification v0](Semantic_Verification_v0.md);
- [Bootstrap Knowledge v0](Bootstrap_Knowledge_v0.md).

Отдельные будущие concepts не входят автоматически в текущий Stage 7 slice:

- [Dynamic Task Arbitration](Dynamic_Task_Arbitration_Concept.md);
- [Emergency Response Mode](Emergency_Response_Mode_Concept.md).

### Bootstrap Knowledge

Финальная часть Stage 7 может загрузить первый небольшой набор настоящих
фундаментальных знаний ANIMA: собственная архитектура и ограничения, базовые
понятия мира и системные определения. Bootstrap остаётся versioned curated source,
проходит общий provenance/lifecycle и не является искусственной биографией.
Synthetic memories предназначены для Stage 8 test instances.

**Definition of Done (предварительная).** Новая, уточняющая и противоречащая
информация проходит system-owned semantic lifecycle; история не переписывается
молча, provenance сохраняется, а bootstrap dataset не требует особых обходных
правил памяти. До этого read-only interface и conformance являются подготовительным
slice, а не доказательством полного Stage 7.

## Stage 8

**Virtual ANIMA — Planned.**

### Главный вопрос

Как ведёт себя интегрированная ANIMA в непрерывной среде, где события существуют
независимо от скорости inference и имеют объективный ground truth?

### Планируемая среда

Создать понятное 2D-пространство с наблюдаемым интерфейсом. Мир должен отделять:

1. **Ground truth** — фактическое состояние виртуального мира;
2. **Synthetic history** — искусственные воспоминания только тестового экземпляра;
3. **Live events** — события, произошедшие уже во время запуска.

Интерфейс должен позволять видеть мир и основные диагностические представления:
Events, Memory selection, Tasks/Goals, Internal State, FAST/DEEP route, Actions и
trace, не делая UI источником истины.

### Режимы проверки

**Manual sandbox:** ручное создание/изменение объектов, задач, конфликтов, ошибок
и разговоров с ANIMA.

**Automated scenarios:** воспроизводимые сценарии с десятками/сотнями/тысячами
событий, в том числе шумом, повторениями, устареванием, противоречиями,
причинными цепочками и multi-hop зависимостями.

Мир не должен останавливаться на время inference. Fault injection и recovery
являются частью среды, а не декоративным эффектом.

**Definition of Done (предварительная).** ANIMA длительно живёт в виртуальном мире,
использует прошлый и текущий опыт, а её поведение можно проверять против ground
truth автоматическими и ручными сценариями.

## Stage 9

**Raspberry Pi Validation — Planned.**

### Главный вопрос

Может ли доказанный software workload работать на Raspberry Pi 5 с приемлемой
стабильностью и измеримыми ресурсными характеристиками?

### Scope

Reference platform остаётся PC. На Pi 5 последовательно проверяются конфигурации,
в которых локально размещаются Core, Memory, FAST, DEEP и orchestration в разных
сочетаниях. Pico используется только для оправданных realtime/telemetry/watchdog/
GPIO задач; когнитивные компоненты на Pico не переносятся ради самого переноса.

Один и тот же workload Stage 8 должен использоваться для сравнения PC и Pi 5.
Измеряются CPU, RAM, storage I/O, temperature/throttling, FAST/DEEP/retrieval
latency, Active/Standby/Sleep workload, restart/error rate и рост persistent data.

Планируются endurance tiers: короткий functional run, средний прогон и
representative soak примерно 12–24 часа, если предыдущие проверки стабильны.

**Definition of Done (предварительная).** Для одинакового сценария существуют
воспроизводимые PC/Pi 5 показатели и понятна конфигурация, в которой Pi 5 может
быть вычислительным носителем ANIMA без скрытых потерь функциональности.

## Stage 10

**Perception & Interaction — Planned.**

### Главный вопрос

Может ли ANIMA получать реальные visual/audio observations и отвечать через
физический output, не привязывая cognition к конкретному устройству?

Первый стенд использует уже доступную периферию ноутбука: camera, microphone и
audio output. Источники оформляются через стабильные interfaces (`CameraSource`,
`AudioInput`, `AudioOutput` или их будущие эквиваленты), чтобы позже заменить
устройство без изменения cognitive ownership.

Планируемые конвейеры:

```text
camera → frames → preprocessing → observations/events
microphone → VAD/STT → events
ANIMA output → text/speech intent → TTS → speaker
```

Сырые непрерывные потоки не должны автоматически становиться Memory. Perception
сначала формирует bounded observations/events с provenance и quality/confidence.

**Definition of Done (предварительная).** Замена конкретной камеры/микрофона не
требует изменения cognition; perception имеет наблюдаемый latency/error profile и
не захламляет долговременную память необработанными потоками.

## Stage 11

**Physical Expansion — Planned, intentionally broad.**

Этап не фиксирует заранее форму корпуса или конкретный набор устройств. После
Stage 9–10 реальные измерения определяют, какие dedicated cameras, microphones,
speakers, IMU/accelerometers, приводы, питание, охлаждение и физические interfaces
имеют смысл.

Цель — первое устойчивое физическое воплощение ANIMA, где отказ/замена периферии
не уничтожают Identity/Memory и имеют наблюдаемое безопасное поведение.
Конкретная форма тела, distributed nodes и дополнительные вычислители остаются
Research до появления измеренной необходимости.

## Параллельные Research и mini experiments

Roadmap — обязательная магистраль. Не каждая полезная гипотеза становится Stage.
Параллельные направления ведутся в [Research](Research.md):

- **Research Track** — долгоживущий вопрос, который может пересекать несколько Stage;
- **Mini Experiment** — ограниченная проверка одной гипотезы с явным результатом;
- успешный experiment не становится production architecture автоматически;
- результат фиксируется как Accepted / Rejected / Inconclusive и при необходимости
  приводит к ADR или изменению roadmap.

## Правила приоритета

- LLM — сменяемый когнитивный орган, не хранилище личности и не главный runtime loop.
- Рутинные операции и ownership данных остаются у обычных системных компонентов.
- Сначала минимальный работающий контур, затем только измеренно нужное усложнение.
- Каждый новый механизм должен иметь наблюдаемый сценарий и regression test.
- Один и тот же workload предпочтительно переносится между платформами для честного
  сравнения, а не переписывается под желаемый результат.
- Обсуждённая идея не считается частью архитектуры, пока её статус явно не повышен
  до Accepted или Planned с конкретным местом в roadmap.
