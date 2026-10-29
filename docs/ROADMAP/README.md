# План развития

Статусы, зависимости и текущая работа берутся из [project.json](../project.json).
Roadmap описывает только цель, границы и проверяемый результат этапа. Реализованные
детали находятся в [Architecture](../ARCHITECTURE/README.md), причины решений — в
[ADR](../DECISIONS/README.md), показательные доказательства — в
[Testing Results](../TESTING/Results/README.md).

<!-- AUTO:roadmap:START -->
**Текущая работа:** Stage 5.3 — Local FAST LLM: подключить реальную локальную модель через ACI к уже проверенному bounded ContextBundle, не передавая модели владение Memory или системной оркестрацией.

**Фокус:** 5 — FAST Cognition & Memory Integration (InProgress).

| Этап | Проверяемый результат | Статус | Зависимости |
|---|---|---|---|
| [D0 — Documentation](#d0) | Контекст и процедуры работы восстанавливаются из репозитория | Complete | — |
| [0 — Foundation](#stage-0) | Перенос сохраняет идентичность, историю и возможность продолжения | Complete | [D0](#d0) |
| [D1 — Runtime, Tests & Observability](#d1) | Один сценарий запускается headless, наблюдается и проверяется изолированно | Complete | [0](#stage-0) |
| [1 — Cognitive Memory](#stage-1) | Релевантный опыт извлекается с происхождением и ограниченным контекстом | Complete | [0](#stage-0), [D1](#d1) |
| [2 — Internal State](#stage-2) | Влияние внутреннего состояния на выбор причинно прослеживается | Complete | [1](#stage-1) |
| [3 — Sleep](#stage-3) | Консолидация прерывается и возобновляется без потери источников | Complete | [2](#stage-2) |
| [4 — Agent / LLM Planner Experiment](#stage-4) | Проверен recoverable action loop, но роль LLM Planner признана архитектурным отклонением; результаты 4.0–4.12 сохранены | Stopped | [3](#stage-3) |
| [5 — FAST Cognition & Memory Integration](#stage-5) | FAST использует ограниченный контекст Cognitive Memory и участвует в текстовом цикле без владения памятью или системным состоянием | InProgress | [1](#stage-1), [D1](#d1) |
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

**FAST Cognition & Memory Integration — Current.**

### Цель

Создать первый настоящий когнитивный модуль ANIMA: небольшую сменяемую FAST-модель,
которая получает текущий текстовый вход и ограниченный релевантный контекст из
Cognitive Memory, формирует ответ/интерпретацию и может предлагать смысловые
кандидаты для памяти, не получая прямого владения Memory или системным состоянием.

Первый рабочий контур:

```text
conversation.user Event
        ↓
Event / Memory pipeline
        ↓
Retrieval + Context Builder
        ↓
ANIMA Cognitive Interface
        ↓
FAST
        ↓
FAST result
        ├─ response
        ├─ memory interpretation/candidate
        └─ request for more context
```

### Границы baseline

- только текстовые `conversation.user` Events;
- существующие EventLog, MemoryProcessor, Retrieval, ContextBuilder и provenance;
- одна локальная FAST LLM через заменяемый backend/adapter;
- FAST не пишет напрямую в `memory.db`, `events.jsonl` или другие stores;
- FAST не меняет Identity, Knowledge authority, Goals или Internal State напрямую;
- модель можно перезапустить/заменить, а накопленный опыт остаётся у ANIMA;
- Internal State, Sleep, DEEP, Tools, AgentLoop и физическая периферия не участвуют
  в baseline и не нужны для завершения Stage 5.

### Рабочая декомпозиция Stage 5

| Шаг | Результат | Проверка завершения |
|---|---|---|
| **5.0 Architecture / ACI — Complete** | Зафиксированы ответственность FAST, минимальные `FASTRequest/FASTResult`, граница ACI и ownership данных | Код и документация отделяют FAST от Agent/System ownership; граница подтверждена targeted tests и полным regression suite |
| **5.1 Deterministic FAST harness — Complete** | Простая заменяемая test-реализация FAST проходит тот же ACI без LLM | `tests/test_fast_cognition.py`: 5 passed; полный regression suite: 662 passed на Python 3.14.4 |
| **5.2 Memory read bridge — Complete** | Текущий текстовый запрос преобразуется в bounded Retrieval/ContextBundle для FAST | Реальный MemoryStore/Retrieval/ContextBuilder передаёт релевантную Memory в `FastRequest`; FAST budget и provenance сохраняются |
| **5.3 Local FAST LLM — InProgress** | Реальная локальная модель подключена через ACI; transport не определяет архитектуру cognition | Модель отвечает на текущий текст, используя переданный ContextBundle; backend можно заменить без изменения Memory |
| **5.4 Cross-session recall** | Информация из прошлой сессии используется после полного нового model call/session | Модель без chat-history правильно отвечает только благодаря `memory.db → Retrieval → Context`; источник ответа прослеживается до Event |
| **5.5 Memory interpretation** | FAST может выделить из нового текста смысловой memory candidate/interpretation | Результат FAST остаётся proposal; системный Memory path валидирует и сохраняет его с source Event/provenance |
| **5.6 Revision / contradiction** | Новый текст может уточнить или оспорить прошлую информацию без скрытой перезаписи истории | Старая и новая информация остаются прослеживаемыми; FAST не получает authority молча заменить Knowledge |
| **5.7 Model replacement** | Один и тот же экземпляр ANIMA продолжает recall после restart и смены FAST backend/model | Identity/Memory сохраняются; новая модель получает тот же ACI/context contract и не требует миграции личности |
| **5.8 Observability / performance** | Видны input, selected memory context, FAST result, latency/tokens и memory effects | Можно отделить ошибки retrieval, context assembly, model reasoning и memory processing; baseline сохранён без SLA |
| **5.9 Stage validation** | Канонический текстовый сценарий объединяет ingest, recall, restart, update/conflict и model replacement | ANIMA накапливает и повторно использует опыт через внешнюю память; полный regression suite предыдущих этапов остаётся зелёным |

5.0–5.1 подтверждены на snapshot `260a5bd`: документационные проверки прошли,
`tests/test_fast_cognition.py` дал 5 passed, полный regression suite — 662 passed.
5.2 подтверждён на snapshot `bb7e8a8`: `tests/test_fast_memory_read_bridge.py` —
3 passed, объединённые FAST tests — 8 passed, полный regression suite — 665 passed.
Отдельный Validation Report не создаётся: это обычные успешные рабочие проверки, а
не показательный stage-level эксперимент.

### Первый канонический сценарий

1. В сессии A пользователь сообщает простой устойчивый факт/отношение.
2. Event и существующий Memory pipeline сохраняют опыт с provenance.
3. FAST/model process завершается; никакая скрытая chat history не переносится.
4. В сессии B пользователь задаёт вопрос, требующий этого прошлого опыта.
5. Retrieval/Context Builder находят релевантную Memory и передают её FAST.
6. FAST формирует корректный ответ; trace показывает использованный memory ID и
   source Event.
7. Позже пользователь уточняет или меняет исходную информацию; новая запись не
   уничтожает старое происхождение.

**Definition of Done.** FAST является сменяемым cognitive consumer ANIMA, а не
владельцем памяти или главным runtime loop; cross-session recall зависит от
Cognitive Memory, а не model chat history; FAST может предлагать семантическую
интерпретацию нового опыта через контролируемый memory path; provenance сохраняется;
restart и замена модели не уничтожают опыт; ошибки retrieval/model/memory processing
различимы по trace.

## Stage 6

**Cognitive Integration — Planned.** После доказанного FAST возвращаем DEEP,
reasoning routing, persistent Tasks, Goals/Internal State, Sleep cognition и полезные
части Stage 4 исполнительного слоя. Их объединяем вокруг уже работающего cognition,
а не заставляем LLM владеть системной оркестрацией.

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
