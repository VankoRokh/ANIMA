# Будущие механизмы и открытые вопросы

Этот документ хранит идеи, которые ещё не являются подтверждённой работающей
архитектурой. Порядок реализации и stage-level acceptance находятся в
[Roadmap](README.md); реализованные границы — в
[Architecture](../ARCHITECTURE/README.md), причины принятых решений — в
[ADR](../DECISIONS/README.md).

## Статусы идей

- **Accepted** — архитектурный принцип уже принят и должен сохраняться, пока его не
  пересмотрит отдельное решение.
- **Planned** — направление включено в будущий roadmap, но конкретный дизайн ещё
  может меняться.
- **Draft** — один из возможных дизайнов; обязательств по реализации нет.
- **Experiment** — проверяемая гипотеза. Положительный результат сам по себе не
  переводит её в production architecture.

Отдельно используются два масштаба исследовательской работы:

- **Research Track** — долгоживущий вопрос, пересекающий несколько Stage;
- **Mini Experiment** — ограниченная проверка одной гипотезы с явным результатом
  `Accepted / Rejected / Inconclusive` и ссылкой на evidence.

## Матрица будущих направлений

| Идея | Статус | Возможный этап |
|---|---|---|
| FAST/DEEP routing | Planned | Stage 6 |
| `request_more_context` без прямого доступа модели к Memory | Experiment | Stage 6 |
| Persistent Tasks + Goals + State в общем cognitive loop | Planned | Stage 6 |
| Возврат bounded Executor/Verification из Stage 4 | Planned | Stage 6 |
| Semantic interpretation-to-write | Planned | Stage 7 |
| Write/update/revision/contradiction lifecycle | Planned | Stage 7 |
| Temporal validity и semantic history | Planned | Stage 7 |
| Bootstrap Knowledge | Planned | конец Stage 7 |
| Self-generated Goals | Draft / Experiment | Stage 7+ |
| Interest / novelty drive | Draft / Experiment | Stage 7+ / Stage 8 |
| Synthetic memories тестового экземпляра | Planned test mechanism | Stage 8 |
| 2D Virtual World | Planned | Stage 8 |
| Noise/repetition/contradiction world scenarios | Planned test mechanism | Stage 8 |
| PC ↔ Raspberry Pi 5 workload comparison | Planned | Stage 9 |
| Pico watchdog/telemetry/realtime I/O | Draft | Stage 9 |
| Camera / microphone / audio output pipeline | Planned | Stage 10 |
| Dedicated cameras, microphone array, IMU, actuators | Draft | Stage 11+ |
| Separate personality module | Research Track | не назначено |
| Distributed memory / multiple compute nodes | Research Track | Stage 11+ только при измеренной необходимости |

## Research Track: Memory и данные

**Accepted:** долговременная память разделяет подробный Event, компактный Memory и
актуализированный Knowledge. Entity служит устойчивым якорем, Relation — явной
связью. Путь записи принадлежит системному Memory owner; путь чтения проходит через
Retrieval и Context Builder. Противоречие не должно молча стирать прошлое.

Текущий baseline остаётся намеренно простым: append-only Events, SQLite/FTS,
metadata/entities/relations и bounded Context. Embeddings, vector/graph DB и
LLM-зависимый retrieval вводятся только после измеренного провала baseline.

### Planned для Stage 7

- cognition создаёт semantic proposal, а не прямую запись;
- системная validation/persistence;
- create/update/revision/contradiction;
- temporal validity;
- history/provenance при изменении знания;
- derived consolidation без удаления sources;
- Bootstrap Knowledge через тот же lifecycle.

### Draft / conditional

- LLM/DEEP Memory Composer — только против deterministic baseline на одинаковом corpus;
- semantic embeddings — если FTS/entities/relations дают измеренный retrieval gap;
- vector DB — если semantic index нужен в масштабе, где SQLite недостаточен;
- graph DB — только после benchmark реального ограничения текущих relations;
- deep graph traversal — для конкретного multi-hop сценария;
- LLM entity extraction / NER — после размеченных ошибок текущего Entity Resolution;
- Memory SPLIT — после доказанных Create/Update/Merge и реального смешанного эпизода;
- numerical confidence — если source/status model станет недостаточной;
- importance decay — после данных о накоплении шума и стоимости хранения;
- token-aware Context Builder — при доказанной пользе для конкретных моделей;
- LLM reranking/query expansion — только против deterministic retrieval baseline;
- Asset Processor — после появления perception pipeline;
- distributed memory/sync — не раньше физического расширения и только после
  доказанной idempotency/recovery на одном узле.

## Research Track: FAST / DEEP / Context

**Accepted:** FAST и DEEP — логические когнитивные роли, а не отдельные личности.
LLM остаётся сменяемым cognitive component. Memory, routing authority, Tasks,
verification и execution принадлежат системным сервисам.

**Planned для Stage 6:** первый реальный DEEP role, bounded routing FAST ↔ DEEP и
общий trace причин вызова.

### Experiment: `request_more_context`

Гипотеза: FAST иногда должен иметь возможность сообщить, что bounded context
недостаточен, но не получать произвольный tool-level доступ к Memory.

Кандидатный контракт:

```text
FAST
  ↓
RequestMoreContext(query / need / budget)
  ↓
System Retrieval
  ↓
new bounded context
  ↓
FAST or DEEP
```

Проверить: качество ответа, количество дополнительных retrieval, latency, budget,
циклы/зацикливание и сохранение provenance. Прямой DB/tool ownership модели не
является целью эксперимента.

### Experiment: FAST/DEEP routing

Сравнить простые deterministic/bounded правила маршрутизации по complexity,
uncertainty и resource budget с более адаптивными вариантами. Проверять качество,
latency, число DEEP calls и возможность объяснить route из trace.

Анализ DEEP сам по себе не означает обучение FAST. Обновление контекста, правил,
модели и весов остаются разными операциями.

## Research Track: Internal State, Goals и autonomy

**Accepted:** Internal State не создаёт варианты и не принимает решение сам.
`fatigue`, `uncertainty`, `frustration`, `satisfaction` и будущие состояния являются
ограниченными причинными факторами. Goal имеет источник, приоритет, lifecycle и
проверяемый критерий результата.

### Planned для Stage 6

Вернуть Goals/Internal State в общий cognitive loop и проверить реальное причинное
влияние на Choice/route без передачи decision authority LLM.

### Draft / Experiment

- scoped frustration/satisfaction для независимых Goals;
- Interest / novelty drive, если relevance + uncertainty не объясняют полезное
  исследовательское поведение;
- tension/caution как отдельные state только при недостатке вычисляемых производных;
- автоматическая калибровка коэффициентов после стабильного baseline;
- LLM-dependent state transitions только как сравниваемый adapter;
- self-generated Goals только после явных authority/conflict rules с внешними
  целями и возможности объективно проверять результат.

Self-generated Goal не должен молча переопределять пользовательскую или системную
цель. Это отдельный уровень автономии, а не побочный эффект генерации текста.

## Research Track: Sleep и consolidation

**Accepted:** Sleep — persistent bounded orchestration с checkpoint/resume,
provenance и безопасным wake. Derived output не становится автоматически
CONFIRMED Knowledge.

### Planned

Stage 6 возвращает Sleep в общий lifecycle. Stage 7 может добавить DEEP-assisted
semantic consolidation при сохранении system-owned persistence.

### Draft / Experiment

- retrospective `REFLECT` после накопления многодневной истории;
- replay реальных `Goal → Choice → observation/result` цепочек;
- counterfactual `SIMULATE`, если predicted outcomes можно сравнить с реальностью;
- generative `GENERATE` / dreaming только при строгом разделении
  real / derived / hypothetical;
- Deep/LLM Sleep Processor только против deterministic consolidation;
- адаптация/обучение FAST во сне — отдельный эксперимент, не следствие Sleep.

Ключевое правило: hypothesis/derived memory всегда хранит ссылки на реальные
sources и не переписывает историю как факт.

## Research Track: Virtual ANIMA

**Planned для Stage 8.** Виртуальная среда должна быть одновременно sandbox,
тестовым полигоном и источником воспроизводимого workload для Stage 9.

Разделяются:

- **Ground truth** мира;
- **Synthetic history** тестового экземпляра;
- **Live events** после запуска.

Synthetic memories предназначены именно для тестов и демонстраций. Они не входят
в настоящую биографию production ANIMA и должны иметь явную маркировку происхождения.

### Planned scenario families

- значимые и незначимые события;
- шум и мусорные observations;
- повторения;
- устаревающие факты;
- прямые противоречия;
- delayed consequences;
- causal chains;
- multi-hop relations;
- false synthetic memory против наблюдаемого ground truth;
- restart/recovery;
- fault injection;
- разные скорости виртуального времени.

Виртуальный мир не должен останавливаться на время inference.

## Research Track: Hardware и переносимость

**Accepted:** физический носитель не определяет личность ANIMA. Hardware выбирается
по измеренному workload, а не наоборот.

### Planned для Stage 9

Первый hardware target — имеющийся Raspberry Pi 5. Reference — PC. Pico может
использоваться для realtime/telemetry/watchdog/GPIO, но не как искусственный хост
для FAST/DEEP/Memory ради модульности.

Сравниваются одинаковые workload/scenario/data conditions. Измерять:

- CPU/RAM;
- storage I/O;
- temperature/throttling;
- FAST/DEEP/retrieval latency;
- Active/Standby/Sleep profile;
- restart/error rate;
- persistent data growth;
- endurance: short → medium → representative 12–24h soak.

### Draft после Stage 9

- отдельные вычислительные узлы;
- distributed sync;
- removable identity/storage carrier;
- автономное питание/UPS;
- backplane / Ethernet / other transport;
- dedicated cooling/case.

Конкретные CM5/Zero/accelerator решения не являются roadmap requirement до
измеренной необходимости.

## Research Track: Perception & Interaction

**Planned для Stage 10:** начать с уже имеющихся laptop camera, microphone и audio
output. Устройства должны подключаться через стабильные source/output interfaces.

Visual/audio raw streams не становятся Memory автоматически. Perception pipeline
должен формировать bounded observations/events с provenance и quality/confidence.

### Draft для Stage 11+

- dedicated camera;
- stereo/dual camera;
- microphone array;
- speakers;
- IMU/accelerometer/gyro;
- pan/tilt;
- physical actuators;
- specialised peripheral nodes.

Покупка конкретного hardware должна следовать измеренным требованиям Stage 9–10.

## Research Track: Identity и personality

**Accepted:** continuity определяется переносимой Identity + Memory + rules/state,
а не одной моделью или prompt.

**Research:** отдельный `personality module` пока не утверждён. Наблюдаемая
индивидуальность может формироваться из Identity, accumulated Memory, Goals,
Internal State, policies и semantic history. Если отдельный personality package
появится, он должен иметь чёткий ownership и переживать замену FAST/DEEP.

Не следует превращать personality в большой скрытый system prompt, который
фактически становится вторым неаудируемым хранилищем состояния.

## Интерфейсы и действия

**Planned:** предложение действия и фактический результат остаются разными
событиями. Выполнение должно иметь independent observation/verification; текст
«успешно» от модели не является evidence исполнения.

Stage 6 может вернуть безопасные обратимые элементы Executor/Verification из
Stage 4. Более широкие реальные interfaces появляются после Virtual ANIMA.

Для независимых узлов до выбора транспорта нужны versioned contracts: sender,
receiver, schema, units, timeout, errors, retry/idempotency, ordering/conflicts и
minimal behavior при отказе узла. Общий mutable state не становится сетевым
контрактом автоматически.

## Mini Experiments

### EXP-001 — Internal weight for memory selection

**Experiment / Planned, результата нет.** Гипотеза: внутренние оценки могут
улучшать отбор полезного опыта при ограниченном memory budget. Сравнить обычный
retrieval/selection с дополнительным state-derived weighting на одном corpus.

### EXP-002 — Selected experience improves FAST

**Experiment / Planned, результата нет.** Отдельно сравнивать context/rule updates
и обучение весов. Нужны фиксированная модель, независимый evaluation set, rollback
и измерение quality/latency/RAM/energy/regressions.

### EXP-003 — Local reinforcement for peripheral task

**Experiment / Planned, результата нет.** Проверить локальное подкрепление на одной
ограниченной задаче simulation/peripheral control. Глобальная reward-функция для
личности не вводится.

### EXP-004 — Request more context

**Experiment / кандидат Stage 6.** Проверить system-mediated дополнительный
retrieval по запросу FAST/DEEP без прямого Memory tool ownership.

### EXP-005 — FAST/DEEP routing baseline

**Experiment / кандидат Stage 6.** Сравнить bounded deterministic routing с более
адаптивными вариантами на одинаковом наборе задач и resource budget.

### EXP-006 — Semantic conflict lifecycle

**Experiment / кандидат Stage 7.** Проверить create → contradiction → revision →
retrieval, сохраняя обе source histories и не назначая winner без authority rule.

### EXP-007 — Virtual memory/noise corpus

**Experiment / кандидат Stage 8.** Проверить память на контролируемой смеси важного,
мусорного, повторяющегося, устаревающего и противоречивого опыта с известным ground
truth.

### EXP-008 — PC/Pi endurance parity

**Experiment / кандидат Stage 9.** Один фиксированный Virtual ANIMA workload
выполнить на PC и Pi 5, затем сравнить correctness, latency, resources и endurance.

## Исторический Stage 4 small-model finding

Qwen3-0.6B показала, что старый Agent/Tool/Choice/Verifier loop технически работает,
но Planner ownership оказался архитектурно неверным, а model reliability —
ограниченной. Результат сохранён как историческое evidence, а не как основание
возвращать LLM Planner. См. [TV-0042](../TESTING/Results/TV-0042.md).

Текущие model benchmarks Stage 5 исследуют уже другой workload: prepared projected
cognition после deterministic resolution. Их нельзя напрямую трактовать как
процентное улучшение над Planner benchmark.

## Отложенные проектные задачи

Независимый backup реального экземпляра, лицензия проекта и права на модели требуют
отдельного решения. Открытая публикация кода не заменяет лицензию. Полноценный сайт
документации оправдан только если Markdown-навигация станет реальным bottleneck.
