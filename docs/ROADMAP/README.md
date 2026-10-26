# План развития

Статусы, зависимости и текущая работа берутся из [project.json](../project.json).
Цели и проверки этапов описаны ниже; подробности будущих механизмов — в
[исследованиях](Research.md). Порядок этапов сохранён; зависимости в таблице
показывают этот порядок, а не требуют отдельной платы или модели на каждом шаге.

<!-- AUTO:roadmap:START -->
**Текущая работа:** Stage 1.11 — Stage Validation: прогнать единый canonical corpus из 30–100 Events через Memory, Knowledge, Retrieval, Context, provenance и restart/replay с заранее заданными проверяемыми результатами.

**Фокус:** 1 — Cognitive Memory (InProgress).

| Этап | Проверяемый результат | Статус | Зависимости |
|---|---|---|---|
| [D0 — Documentation](#d0) | Контекст и процедуры работы восстанавливаются из репозитория | Complete | — |
| [0 — Foundation](#stage-0) | Перенос сохраняет идентичность, историю и возможность продолжения | Complete | [D0](#d0) |
| [D1 — Runtime, Tests & Observability](#d1) | Один сценарий запускается headless, наблюдается и проверяется изолированно | Complete | [0](#stage-0) |
| [1 — Cognitive Memory](#stage-1) | Релевантный опыт извлекается с происхождением и ограниченным контекстом | InProgress | [0](#stage-0), [D1](#d1) |
| [2 — Internal State](#stage-2) | Влияние внутреннего состояния на выбор причинно прослеживается | Planned | [1](#stage-1) |
| [3 — Sleep](#stage-3) | Консолидация прерывается и возобновляется без потери источников | Planned | [2](#stage-2) |
| [4 — Agent](#stage-4) | Ограниченная задача выполняется инструментом и проверяется наблюдением | Planned | [3](#stage-3) |
| [5 — Virtual ANIMA](#stage-5) | Длительная работа на ПК/VM имеет измеренный ресурсный профиль | Planned | [4](#stage-4) |
| [6 — Cyberdeck](#stage-6) | Измеренная нагрузка переносится на автономное устройство | Planned | [5](#stage-5) |
| [7 — Modular embodiment](#stage-7) | Узлы диагностируются и заменяются без потери данных экземпляра | Planned | [6](#stage-6) |
<!-- AUTO:roadmap:END -->

## D0

12 октября 2026 документация была вынесена из чатов в репозиторий: Markdown/Mermaid,
VS Code и дополнительная навигация Obsidian. Владелец проверил Setup/Check,
редакторы и восстановление временного экземпляра. Публикация:
[e155c69](https://github.com/VankoRokh/ANIMA/commit/e155c695e6c5dc17c6cc0ec62a05d624031f0dd8).
Позднейшее упрощение системы описано в [ADR-004](../DECISIONS/README.md#adr-004).
Реальное независимое резервирование пользовательского экземпляра этим не подтверждено.

## Stage 0

13 октября 2026 проверена восстанавливаемая основа жизненного цикла: постоянный ID,
сессии, raw events и selected memory, валидация, безопасная запись состояния,
штатные EOF/Ctrl+C и каталог данных независимо от cwd. Две сессии и перенос
должны сохранять историю; неверные данные должны давать понятную ошибку.
Доказательство: [TV-0001](../TESTING/Results/TV-0001.md).
Выделение CLI (SW-07) выполнено позднее и также защищено регрессией.

## D1

21 октября 2026 проверены независимый Runtime, ScenarioRunner, snapshot,
изолированный harness, постоянный regression suite, trace и lifecycle/resource metrics.
Критерий: эквивалентность CLI/headless, сохранение Foundation и наблюдаемая причина
ошибки сценария без доступа к рабочим данным. Доказательство:
[TV-0002](../TESTING/Results/TV-0002.md).
GUI/TUI, telemetry server, удалённая отладка и графики оставлены до измеренной потребности.

## Stage 1

**Цель и наблюдение.** Доказать полный цикл долговременной памяти
`Event → Memory → Knowledge → Retrieval → Context Builder`: релевантный опыт
возвращается на фиксированном корпусе, каждый результат ведёт к исходным событиям,
противоречия не затирают прошлое, а рабочий контекст ограничен явным бюджетом.
Условия старта — Foundation и диагностический harness D1. Архитектурный выбор
зафиксирован в [ADR-005](../DECISIONS/README.md#adr-005).

**Принципы.** Сначала deterministic baseline и объяснимые правила, затем усложнение.
Event — подробный append-only журнал произошедшего; Memory — компактный опыт
ограниченного эпизода; Knowledge — актуализированное утверждение из закрытого
подтверждённого опыта. Entity служит устойчивым якорем, Relation — явной связью.
Topic не хранится отдельной сущностью: это динамическая область связанных данных.
Memory Processor отвечает за путь записи, Context Builder — за путь чтения.

**Хранение.** `events.jsonl` остаётся append-only журналом. Структурированные
Memories/Knowledge/Entities/Relations/History и состояние обработки событий
хранятся в SQLite `memory.db`; FTS5 служит baseline полнотекстового поиска.
Большие изображения/аудио/видео позже хранятся отдельно как Assets, а Events
ссылаются на них. Старый `memories.jsonl` не мигрируется: тестовые данные не имеют
ценности, compatibility layer не нужен. Public IDs стабильны и независимы от
внутренних integer keys; время — ISO 8601 с UTC offset.

### Порядок реализации Stage 1

| Шаг | Результат | Проверка завершения |
|---|---|---|
| **1.0 Specification** | Зафиксированы Event/Memory/Knowledge, Entity/Relation, Processor, Composer, Context Builder, lifecycle и storage baseline | Документация однозначно описывает границы Stage 1 и отложенные механизмы |
| **1.1 Event Foundation — Complete** | Универсальный Event: stable ID, timestamp, type, source, session_id, payload, references | Валидные/невалидные события, duplicate ID, повреждённая JSONL-строка и restart дают определённый результат; [TV-0004](../TESTING/Results/TV-0004.md) |
| **1.2 Memory Store — Complete** | SQLite `memory.db`, schema, transactions, indexes, FTS5 | CRUD, rollback, reopen, constraints, FTS и базовые relation queries проходят тесты; [TV-0005](../TESTING/Results/TV-0005.md) |
| **1.3 Entities / Relations / Provenance — Complete** | Entity aliases, универсальные relations и цепочка `Knowledge → Memory → Event` | Для каждого контрольного объекта происхождение восстанавливается до source Events; [TV-0006](../TESTING/Results/TV-0006.md) |
| **1.4 Memory Processor — Complete** | Selection и объяснимый Association; `HIGH → UPDATE`, `MEDIUM → CREATE + related_to`, `LOW → CREATE` | На canonical corpus каждый Event попадает в ожидаемый эпизод, причины решения видны в trace; [TV-0007](../TESTING/Results/TV-0007.md) |
| **1.5 Memory Composer — Complete** | Заменяемый deterministic `RuleBasedComposer`, ограниченный `content` | CREATE/UPDATE сохраняют решения, результаты, причины, ограничения и открытые вопросы без копирования шума; [TV-0008](../TESTING/Results/TV-0008.md) |
| **1.6 Merge / History — Complete** | `OPEN/CLOSED/MERGED`, безопасный Merge и компактная история изменений | Merge не теряет provenance; исходная запись остаётся прослеживаемой; SPLIT не требуется; [TV-0009](../TESTING/Results/TV-0009.md) |
| **1.7 Knowledge Layer — Complete** | Knowledge из закрытого подтверждённого опыта; lifecycle `provisional/confirmed/challenged/superseded/rejected` | Противоречие переводит `confirmed → challenged`, но не заменяет знание до закрытия проверки; [TV-0010](../TESTING/Results/TV-0010.md) |
| **1.8 Retrieval — Complete** | ID/filters/entities/FTS/relations/ranking, сначала дешёвые и объяснимые методы | Заранее размеченные query возвращают обязательные IDs в заданном top-k; [TV-0011](../TESTING/Results/TV-0011.md) |
| **1.9 Context Builder — Complete** | Структурированный `ContextBundle` с `knowledge[]/memories[]/events[]`, reason и budget | `max_items/max_chars` соблюдаются; разные consumer policies дают воспроизводимый ограниченный контекст; [TV-0012](../TESTING/Results/TV-0012.md) |
| **1.10 Recovery / Idempotency — Complete** | `event_processing` и безопасное повторение операций после crash | Повтор одного Event не создаёт дубликаты; зависшая обработка обнаруживается и восстанавливается; [TV-0013](../TESTING/Results/TV-0013.md) |
| **1.11 Stage Validation** | End-to-end corpus примерно 30–100 Events с ожидаемыми Memories/Knowledge/Relations/Context | Полный сценарий проходит после restart и сохраняет provenance, статусы и retrieval |
| **1.12 Performance Baseline** | Измерены latency/CPU/RAM/storage на синтетических 1k/10k/100k данных | Результаты записаны без преждевременных SLA и оптимизаций |

### Правила Memory Processor

Selection решает `process/skip`. Association никогда не сравнивает Event со всей
памятью: сначала используются `OPEN` Memories, task/session/domain, Entities и FTS,
затем небольшой набор кандидатов получает объяснимый score. Высокое совпадение
обновляет открытый эпизод; среднее создаёт новый связанный эпизод; низкое — новый
независимый. Консервативная ошибка предпочтительнее: лишние Memories можно позже
объединить, неверное склеивание искажает историю.

Episodic Memory представляет ограниченный по времени и смыслу эпизод, а не вечный
документ по теме. `OPEN` Memory можно уточнять и сокращать; `CLOSED` по умолчанию
не переписывается поздним опытом. `MERGED` сохраняет ссылку на итоговую запись.
`content` — самодостаточная смысловая выжимка; metadata хранит навигацию и
происхождение. Composer является заменяемым модулем и не является storage.

Knowledge создаётся из закрытого подтверждённого опыта или набора связанных
закрытых Memories. Новая связанная ветка сама по себе не переписывает знание.
Подтверждённое Knowledge при существенном противоречии сначала становится
`challenged`, затем после закрытия проверки возвращается в `confirmed` либо
переходит в `superseded/rejected`; старое знание не удаляется. Числовой confidence
на Stage 1 не требуется: используются status, supporting/contradicting sources.

### Инженерный baseline

- `memory.db`: memories, memory_sources, knowledge, knowledge_sources, entities,
  entity_aliases, memory_entities, knowledge_entities, relations, history,
  event_processing и FTS indexes.
- Одна универсальная таблица `relations`; дробить её только после измеренной
  проблемы скорости или целостности.
- Internal SQLite key — integer; public ID — UUIDv4 с type-prefix (`ev_`, `mem_`,
  `kn_`, `ent_`, `rel_`, `asset_`). UUIDv4 выбран для совместимости с Python 3.12+;
  временная сортировка хранится отдельными timestamp-полями.
- `importance`: `0=low`, `1=normal`, `2=high`, `3=critical`; relevance всегда
  важнее importance при retrieval.
- `event_processing`: `pending/processing/done/failed/skipped`, processor/version,
  attempts и timestamps. Зависшие операции восстанавливаются при старте; Sleep
  позднее может повторно разбирать backlog/failed.
- Все изменения Memory/Knowledge/relations в одном действии выполняются SQLite
  transaction; JSONL и SQLite не обязаны быть общей атомарной транзакцией.
- History хранит существенные delta/change records, а не полную копию каждой версии.
- Context Builder возвращает структурированный `ContextBundle`; Stage 1 использует
  `max_items/max_chars`, token-aware budget откладывается до конкретной модели.
- Graph navigation по умолчанию ограничена одним hop; второй допускается только
  при явной необходимости.

### Валидация и доказательства

Начальный canonical corpus для разработки — примерно 10–20 Events; к финальной
валидации расширяется до 30–100. Он включает продолжение одного эпизода,
независимые эпизоды, шум, повтор, procedural memory, связанные Entities,
решение, противоречие, Knowledge challenge/confirmation или supersession,
restart и failed processing. Для corpus заранее задаются ожидаемые Memories,
Knowledge, Relations и query → expected IDs.

Обязательные свойства: 100% обязательных expected IDs находятся в заданном top-k;
у 100% возвращаемых контрольных записей валидный provenance; budget соблюдается;
повторная обработка не размножает данные; restart/recovery сохраняют IDs и выборку;
invalid transition, dangling/missing source и transaction failure дают определённую
ошибку. Показательный итог Stage сохраняется по правилам [Testing](../TESTING/README.md).

Performance на Stage 1 только измеряется: Event append, Memory create/update,
Entity/Knowledge lookup, FTS, 1-hop relation, Context Builder, batch processing,
CPU, peak RAM и DB size на 1k/10k/100k синтетических данных. Оптимизация вводится
только после измеренного bottleneck.

**Definition of Done.** На фиксированном end-to-end corpus Events детерминированно
формируют ожидаемые Memories; закрытый опыт создаёт Knowledge; новый противоречащий
опыт переводит его в `challenged`, а закрытая проверка подтверждает или заменяет;
Retrieval и Context Builder возвращают ожидаемый ограниченный контекст; provenance
проходит до source Events; restart и повторная обработка не повреждают данные;
performance baseline зафиксирован. Отложенные механизмы перечислены в
[Research](Research.md#отложенные-механизмы-памяти-stage-1).

## Stage 2

**Цель и наблюдение.** Минимальные цели и ограниченные внутренние переменные
причинно влияют на выбор. Одинаковый вход при neutral/altered state даёт ожидаемое
различие приоритетов с объяснимой цепочкой причин.

**Работа.** Цель имеет источник, приоритет, статус, критерий результата и отмену.
Определяются диапазоны переменных, изменение/decay/recovery и сохранение.
Внешнее эмоциональное выражение зависит от внутреннего слоя.

**Сценарии и приёмка.** Одинаковые входы с разными контролируемыми состояниями;
значения в диапазоне; у каждого изменения source/reason в trace. Restart не
создаёт скрытого дрейфа; завершённая/отменённая цель больше не активна; внешнее
выражение не меняет внутренний слой без отдельного правила. Все контрольные
сценарии дают предсказуемое направление выбора и воспроизводимое состояние.

**Регрессия и доказательства.** Предыдущие этапы; сравнение neutral/altered и trace причин.

## Stage 3

**Цель и наблюдение.** Sleep job запускается, прерывается, продолжается и
повторяется; итог валиден, происхождение сохранено, стоимость измерена.

**Работа.** Жизненный цикл queued/running/checkpointed/interrupted/complete/failed,
checkpoint/resume, deterministic consolidation, история преобразований,
idempotency/deduplication и resource metrics. Deep/LLM — сравниваемый адаптер после baseline;
адаптация Fast остаётся отдельным [EXP-002](Research.md#exp-002).

**Сценарии и приёмка.** Полный запуск и прерывания на каждом контрольном checkpoint
дают эквивалентный допустимый итог; повтор не размножает дубликаты. Каждый derived
record ведёт к эпизодам. Ошибка не повреждает валидные данные. Измеряются elapsed
time/RAM, а при модели — load/inference cost. Resume, provenance и ограниченная
идемпотентность подтверждены; ресурсный профиль записан.

**Регрессия и доказательства.** В частности retrieval Stage 1 после консолидации;
interrupted/resumed trace, сравнение повторов и baseline/Deep resource profile, если адаптер введён.

## Stage 4

**Цель и наблюдение.** В sandbox ограниченная задача проходит plan → action →
observation → result и заканчивается определённым статусом.

**Работа.** Tool contract с аргументами/результатом, planner/executor loop,
наблюдение после действия, timeout/error/cancel, dry-run или sandbox для опасных
операций. Execution trace сохраняется как опыт с проверяемым результатом.

**Сценарии и приёмка.** Многошаговый успех, неверные аргументы, отказ/timeout,
прерывание между шагами и определённое состояние после restart. Повтор команды
не повторяет подтверждённое необратимое действие без явного разрешения. Успех
подтверждается observation. Хотя бы один полный workflow проходит success/failure/cancel.

**Регрессия и доказательства.** Предыдущие этапы; успешный trace и один failure/recovery.

## Stage 5

**Цель и наблюдение.** Локальная система длительно выполняет wake/sleep/action
cycles, переживает рестарты/restore и имеет измеренные CPU/RAM/storage/latency.

**Работа.** Service lifecycle, long-run со сбором метрик, ограничение роста данных,
reboot/recovery, вторая чистая установка, фиксация software/model versions и
независимая резервная копия тестового экземпляра.

**Сценарии и приёмка.** Много циклов без ручной помощи; штатный restart и аварийное
завершение между циклами; restore на второй установке; динамика RAM/storage;
benchmark до/после без необъяснимой регрессии. До валидации задаётся длительность:
ориентир — не менее 24 часов суммарно либо эквивалентное число циклов. Нет
повреждения данных, измерены ресурсный профиль и насыщение, перенос подтверждён.

**Регрессия и доказательства.** Предыдущие этапы; long-run таблица/график,
restart/recovery и реальные аппаратные bottlenecks.

## Stage 6

**Цель и наблюдение.** Тот же workload работает на автономном cyberdeck с
известными latency, temperature, power и autonomy.

**Работа.** Требования из Stage 5 до выбора compute/storage/accelerator; питание,
резерв/safe shutdown, охлаждение, thermal monitoring, перенос/recovery и
предусмотренная архитектурой заменяемость компонентов.

**Сценарии и приёмка.** PC benchmark на устройстве; cold boot/shutdown и потеря
питания с резервом, если предусмотрен; thermal throttling, battery test по
объявленной нагрузке, перенос туда/обратно с прежним ID. До закупки задаются
пределы latency/RAM/storage/autonomy/temperature. Устройство соответствует им
либо измерениями показывает, какой компонент требует следующей итерации —
это сохранённый критерий этапа, а не обещание готового изделия.

**Регрессия и доказательства.** Программный workload/recovery; PC vs cyberdeck,
thermal/power profile и восстановление.

## Stage 7

**Цель и наблюдение.** Отказ/отключение/замена физического узла диагностируются;
система безопасно деградирует, восстанавливает связь и продолжает работу.

**Работа.** Версионированные contracts, heartbeat/health, offline/reconnect/sync,
benchmarks зрения/звука, первый привод с feedback и safety bounds, процедура
замены. Схемы/чертежи публикуются после испытаний.

**Сценарии и приёмка.** Disconnect/reconnect, потеря связи во время операции,
совместимая замена, поздние/повторные сообщения, упор привода в предел/препятствие,
отказ периферии без повреждения identity/memory. Все обязательные узлы имеют
диагностику; канонические данные сохраняются; привод останавливается в заданных пределах.

**Регрессия и доказательства.** Предыдущие software/hardware свойства;
failure/reconnect trace, replacement и измеренный safety test первого привода.

## Правила приоритета

Сначала наблюдаемость и deterministic baseline, затем более сложный механизм.
Новую модель вводим там, где есть задача и benchmark. Закупки следуют измеренным
ограничениям ноутбука/VM. GUI нужен, когда параллельные состояния уже неудобно
анализировать через trace/CLI. Новая идея входит в этап только если без неё нельзя
получить или проверить его результат. Будущие критерии уточняются перед стартом;
календарные сроки и конкретная комплектация здесь не обещаются.
