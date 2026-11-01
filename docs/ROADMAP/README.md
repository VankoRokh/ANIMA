# План развития

Статусы, зависимости и текущая работа берутся из [project.json](../project.json).
Roadmap описывает только цель, границы и проверяемый результат этапа. Реализованные
детали находятся в [Architecture](../ARCHITECTURE/README.md), причины решений — в
[ADR](../DECISIONS/README.md), показательные доказательства — в
[Testing Results](../TESTING/Results/README.md).

<!-- AUTO:roadmap:START -->
**Текущая работа:** Stage 5 завершён: принят scope canonical IR → deterministic resolution → projected cognition → FAST integration; representative acceptance evidence — TV-0043, real-model projected smoke прошёл все семь acceptance cases. Unrestricted text output остаётся semantic, не byte-exact. Stage 6 запланирован, работа не начата. Semantic persistence/write lifecycle, DEEP, Agent/Planner, execution, Sleep, Internal State integration, broader parsing/data acquisition/rendering остаются будущей работой.

**Фокус:** 6 — Cognitive Integration (Planned).

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
| [6 — Cognitive Integration](#stage-6) | FAST, DEEP, routing, Tasks, Goals и исполнительный слой объединяются вокруг работающего когнитивного контура | Planned | [5](#stage-5), [2](#stage-2), [3](#stage-3) |
| [7 — Virtual ANIMA](#stage-7) | Непрерывная система работает в виртуальной среде и имеет измеренный ресурсный профиль | Planned | [6](#stage-6) |
| [8 — Cyberdeck](#stage-8) | Измеренная нагрузка переносится на автономное устройство | Planned | [7](#stage-7) |
| [9 — Modular embodiment](#stage-9) | Узлы диагностируются и заменяются без потери данных экземпляра | Planned | [8](#stage-8) |
<!-- AUTO:roadmap:END -->

## D0

Документация вынесена в репозиторий и имеет канонические источники истины.
Изменения статусов идут через `project.json`; AUTO-блоки генерируются скриптом.

## Stage 0

**Foundation.** Постоянный instance ID, lifecycle/state, sessions, raw Events,
безопасная запись и перенос data directory переживают restart/restore. Базовая
непрерывность экземпляра определяется сохранёнными данными, а не конкретным
процессом или компьютером. Доказательство: [TV-0001](../TESTING/Results/TV-0001.md).

## D1

**Runtime, Tests & Observability.** Headless Runtime, ScenarioRunner, trace,
изолированный test harness и общая система проверок позволяют воспроизводимо
наблюдать поведение без рабочей пользовательской базы. Доказательство:
[TV-0002](../TESTING/Results/TV-0002.md).

## Stage 1

**Cognitive Memory — Complete.** Реализован проверяемый цикл
`Event → Memory → Knowledge → Retrieval → Context Builder` с provenance,
ограниченным контекстом, recovery и performance baseline. Это основной фундамент
Stage 5: FAST должен получать память через Retrieval/Context Builder, а не владеть
БД или заменять её собственным контекстом модели.

Доказательства: [TV-0004 — TV-0015](../TESTING/Results/README.md).
Архитектурный выбор: [ADR-005](../DECISIONS/README.md#adr-005).

## Stage 2

**Internal State — Complete.** Goals, ограниченные состояния, Choice и причинная
история подтверждены как отдельный регулирующий слой. На Stage 5 код сохраняется и
регрессируется, но состояния и Choice **не входят в FAST baseline**, чтобы сначала
проверить чистое взаимодействие cognition с памятью.

Доказательства: [TV-0016 — TV-0017](../TESTING/Results/README.md).
Архитектурный выбор: [ADR-006](../DECISIONS/README.md#adr-006).

## Stage 3

**Sleep — Complete.** Persistent bounded orchestration, checkpoint/resume,
derived results и provenance подтверждены. На Stage 5 Sleep остаётся существующей,
но замороженной подсистемой; когнитивный Sleep с DEEP вернётся после рабочего FAST.

Доказательства: [TV-0018 — TV-0030](../TESTING/Results/README.md).
Архитектурный выбор: [ADR-007](../DECISIONS/README.md#adr-007).

## Stage 4

**Agent / LLM Planner Experiment — Stopped after 4.12.**

Stage 4 доказал полезные свойства исполнительного слоя: persistent AgentRun/Step,
Tool contracts, sandbox Executor, Action/Receipt/Observation/Verification,
idempotency/recovery, capture значимого опыта и реальную интеграцию локальной LLM.
Результаты 4.0–4.12 и отчёты не удаляются.

При аудите 29 октября 2026 обнаружено архитектурное отклонение: `PlannerAdapter`
стал когнитивным владельцем proposal generation, а FAST/DEEP начали трактоваться
как будущие разновидности Planner. Это расходится с исходной схемой ANIMA, где LLM
являются сменяемыми когнитивными органами, а события, память, задачи, routing,
verification и исполнение принадлежат системным сервисам. Эксперимент с Qwen также
показал, что модель тратилась на служебный Planner/tool contract вместо работы со
смыслом и памятью.

Поэтому 4.13–4.15 не выполняются в рамках этого Stage. Stage не объявляется
Complete и получает статус `Stopped`. Полезный код Executor/Tool/Observation/
Verification/recovery сохраняется для последующей Cognitive Integration, но
`LLM Planner` не является канонической моделью cognition ANIMA.

Доказательства остановленного пути: [TV-0031 — TV-0042](../TESTING/Results/README.md).
Исходное решение и его пересмотр: [ADR-008](../DECISIONS/README.md#adr-008),
[ADR-009](../DECISIONS/README.md#adr-009).

## Stage 5

**FAST Cognition & Memory Integration.** Текущий статус и фокус берутся только из
[project.json](../project.json); этот раздел задаёт scope и критерии, а не второй
реестр статусов. Авторитетный контракт —
[Cognitive Resolution Integration Spec](Cognitive_Resolution_Integration_Spec.md).

### Эволюция scope

Исходный план 5.0–5.9 включал read path, затем semantic interpretation-to-write,
revision/contradiction и объединённый сценарий записи/обновления памяти.
Экспериментальная серия H–M1 и последующие одобренные архитектурные уточнения
изменили приоритет: сначала стабилизируется model-independent read/resolution/
projected-cognition boundary. Это явное изменение плана, а не признание исходных
write/revision целей выполненными. Исторические цели 5.5/5.6 сохранены ниже как
[отложенная работа](#отложенный-исходный-scope-stage-5).

### Утверждённый production slice

```text
conversation.user → conservative frontend → CanonicalTask + bounded context
structured CanonicalTask ────────────────────────────────┘
                              ↓
                    deterministic resolution
                    ├─ deterministic value / no admissible action
                    ├─ insufficient data / missing requirements
                    └─ supported cognitive remainder → projection → FAST
```

В scope входят Canonical IR (`anima/ir.py`), exact structured evidence lookup,
точная арифметика и constraints, insufficient-data handling, machine-readable
`ACTION_PRIORITY`, projected cognition, uniform allowed-output validation и
наблюдаемость этой границы. Frontend не угадывает intent/entity/fact.

Event path использует существующий `ContextBuilder` ровно один раз, сохраняя FAST
budget и provenance. Structured task сразу поступает в resolution без FTS,
фиктивного текста или Event ID. `FastRequest`/`FastBackend.complete` остаются legacy
ACI; `ProjectedFastRequest`/`ProjectedFastBackend.complete_projected` задают явную
новую capability. FAST не владеет Memory, Identity, Goals, routing или Runtime.

### Проверяемые результаты Stage 5

| Исходный шаг / уточнение | Результат в текущем scope | Критерий acceptance |
|---|---|---|
| 5.0–5.2 Architecture / harness / Memory read | Legacy ACI и authoritative Memory read path сохраняются | Backend replacement, bounded context и source provenance проходят regression |
| 5.3 Local FAST LLM | Локальная модель поддерживает явную projected capability | Opt-in production-pipeline smoke подтверждает доставку projected information и ровно один call для supported cognitive task |
| Canonical IR / deterministic boundary | Общий IR отделён от resolver и модели; правила машинно проверяемы | Exact decimals/constraints, policy agreement/conflict, missing requirements, unknown/empty candidates и output contracts проверены |
| 5.4 Cross-session recall | Новая сессия/чистый backend получает прошлый опыт из Memory | Selected evidence прослеживается до Event, без model chat history |
| 5.7 Backend replacement | Замена backend не меняет Memory/Identity ownership | Read stack/backend реконструируются с сохранением данных и provenance |
| 5.8 Observability | Видны route, context/view, attempts, completions, failure classification и final result | Zero-call paths, successful call и terminal backend exception различимы; нет retry/fallback |
| 5.9 Stage validation | Канонический read/resolution/cognition сценарий и его failure cases | Targeted и полный обычный pytest, integrity, representative acceptance report и projected real-model smoke проходят |

5.0–5.1 исторически подтверждены на snapshot `260a5bd`: FAST tests — 5 passed,
полный suite — 662 passed. 5.2 подтверждён на `bb7e8a8`: Memory bridge — 3 passed,
объединённые FAST tests — 8 passed, полный suite — 665 passed. Это условия прошлых
проверок, а не текущие счётчики или повторяющиеся статусы. Для тех рабочих проверок
отдельный TV report не создавался; закрытие всего Stage требует representative
report по [правилам Testing](../TESTING/README.md).

### Канонический сценарий текущего scope

1. Существующий системный Memory path сохраняет опыт с source Event/provenance.
2. В новой сессии реконструированный read stack получает bounded relevant context.
3. ANIMA нормализует только безопасно распознанный input и применяет strict rules.
4. Deterministic/insufficient routes не вызывают backend; неподдержанный constrained
   request без admissible output также не вызывает заведомо бесполезный backend.
5. Supported cognitive remainder проходит projection и один вызов FAST.
6. Allowed-output validation проверяет final value независимо от его источника.
7. Successful completion и terminal failure наблюдаемы; Memory/Identity сохраняются
   после реконструкции backend. Update/write/revision сценарий здесь не требуется.

**Definition of Done.** Завершён именно утверждённый read/resolution/projected-
cognition slice: IR и ownership boundaries соблюдены, exact rules не дают false
deterministic results, missing information не выдумывается моделью, hard constraints
предшествуют policies, conflicting/malformed policies не выбирают deterministic
winner. Подтверждены bounded Memory/provenance, cross-session read, explicit backend
capabilities, uniform output validation и failure audit. Пройдены production tests,
обычный full regression и небольшой real-model projected smoke; сохранён stage-level
report и согласованы документы. Runtime/CLI integration, semantic writes и соседние
подсистемы не являются условием закрытия этого slice.

### Отложенный исходный scope Stage 5

| Историческое намерение | Явно отложенная будущая работа |
|---|---|
| 5.5 Memory interpretation | Semantic interpretation-to-write adapter, проверка и сохранение предложенных facts/candidates системным Memory owner |
| 5.6 Revision / contradiction | Semantic write/update/revision lifecycle, temporal fact lifecycle, conflict write policy и сохранение истории изменений |
| Write/update часть исходного 5.9 | Отдельная будущая интеграционная проверка после проектирования persistence/lifecycle |

Semantic persistence/schema, write/update/revision и temporal lifecycle возвращаются
в план отдельным решением после стабильного read pipeline. Исторический intent
сохраняется; он не реализован и не считается пройденным в Stage 5. Полезные границы
из [ADR-009](../DECISIONS/README.md#adr-009) сохраняются без возврата LLM Planner.

## Stage 6

**Cognitive Integration — Planned.** После доказанного FAST возвращаем DEEP,
reasoning routing, persistent Tasks, Goals/Internal State, Sleep cognition и полезные
части Stage 4 исполнительного слоя. Их объединяем вокруг уже работающего cognition,
а не заставляем LLM владеть системной оркестрацией. Semantic persistence/write,
interpretation-to-write и temporal revision lifecycle остаются отдельно планируемой
[отложенной работой](#отложенный-исходный-scope-stage-5), а не неявным обязательством
текущего Stage. Начало следующего этапа требует отдельного решения.

## Stage 7

**Virtual ANIMA — Planned.** Непрерывный runtime, несколько источников Events,
виртуальная среда/периферия, fault injection и длительные сценарии. Мир не должен
останавливаться на время inference.

## Stage 8

**Cyberdeck — Planned.** Перенос измеренного software workload на автономное
устройство после профилирования CPU/RAM/storage/latency/power/thermal.

## Stage 9

**Modular embodiment — Planned.** Физические сенсоры/исполнители и заменяемые узлы
подключаются через стабильные interfaces; отказ или замена не должны уничтожать
Identity/Memory и должны иметь наблюдаемое безопасное поведение.

## Правила приоритета

- LLM — сменяемый когнитивный орган, не хранилище личности и не главный runtime loop.
- Рутинные операции и ownership данных остаются у обычных системных компонентов.
- Сначала минимальный работающий контур, затем только измеренно нужное усложнение.
- Каждый новый механизм должен иметь наблюдаемый сценарий и regression test.
- Завершённые Stage 2/3 не обязаны участвовать в каждом следующем baseline: готовый
  компонент можно временно заморозить, если он мешает проверить новую границу.
