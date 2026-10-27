# План развития

Статусы, зависимости и текущая работа берутся из [project.json](../project.json).
Цели и проверки этапов описаны ниже; подробности будущих механизмов — в
[исследованиях](Research.md). Порядок этапов сохранён; зависимости в таблице
показывают этот порядок, а не требуют отдельной платы или модели на каждом шаге.

<!-- AUTO:roadmap:START -->
**Текущая работа:** Stage 4.0 — Agent Specification: зафиксировать AgentRun/AgentStep, Tool/Action/Observation, PlannerAdapter, Goal verification, persistence/recovery boundaries и критерии deterministic/LLM validation до начала production-реализации.

**Фокус:** 4 — Agent (InProgress).

| Этап | Проверяемый результат | Статус | Зависимости |
|---|---|---|---|
| [D0 — Documentation](#d0) | Контекст и процедуры работы восстанавливаются из репозитория | Complete | — |
| [0 — Foundation](#stage-0) | Перенос сохраняет идентичность, историю и возможность продолжения | Complete | [D0](#d0) |
| [D1 — Runtime, Tests & Observability](#d1) | Один сценарий запускается headless, наблюдается и проверяется изолированно | Complete | [0](#stage-0) |
| [1 — Cognitive Memory](#stage-1) | Релевантный опыт извлекается с происхождением и ограниченным контекстом | Complete | [0](#stage-0), [D1](#d1) |
| [2 — Internal State](#stage-2) | Влияние внутреннего состояния на выбор причинно прослеживается | Complete | [1](#stage-1) |
| [3 — Sleep](#stage-3) | Консолидация прерывается и возобновляется без потери источников | Complete | [2](#stage-2) |
| [4 — Agent](#stage-4) | Ограниченная задача выполняется инструментом и проверяется наблюдением | InProgress | [3](#stage-3) |
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
| **1.6 Merge / History — Complete** | `OPEN/CLOSED/MERGED`, безопасный Merge и компактная история изменений | Merge не теряет provenance; исходная запись остаётся прослеживаемой; [TV-0009](../TESTING/Results/TV-0009.md) |
| **1.7 Knowledge Layer — Complete** | Knowledge из закрытого подтверждённого опыта; lifecycle `provisional/confirmed/challenged/superseded/rejected` | Противоречие переводит `confirmed → challenged`, но не заменяет знание до закрытия проверки; [TV-0010](../TESTING/Results/TV-0010.md) |
| **1.8 Retrieval — Complete** | ID/filters/entities/FTS/relations/ranking, сначала дешёвые и объяснимые методы | Заранее размеченные query возвращают обязательные IDs в заданном top-k; [TV-0011](../TESTING/Results/TV-0011.md) |
| **1.9 Context Builder — Complete** | Структурированный `ContextBundle` с `knowledge[]/memories[]/events[]`, reason и budget | `max_items/max_chars` соблюдаются; разные consumer policies дают воспроизводимый ограниченный контекст; [TV-0012](../TESTING/Results/TV-0012.md) |
| **1.10 Recovery / Idempotency — Complete** | `event_processing` и безопасное повторение операций после crash | Повтор одного Event не создаёт дубликаты; зависшая обработка обнаруживается и восстанавливается; [TV-0013](../TESTING/Results/TV-0013.md) |
| **1.11 Stage Validation — Complete** | End-to-end corpus примерно 30–100 Events с ожидаемыми Memories/Knowledge/Relations/Context | 37-Event corpus проходит после restart/replay и сохраняет provenance, статусы, Retrieval и bounded Context; [TV-0014](../TESTING/Results/TV-0014.md) |
| **1.12 Performance Baseline — Complete** | Измерены latency/CPU/RAM/storage на синтетических 1k/10k/100k данных | Baseline зафиксирован без SLA; выявлены scaling bottleneck EventProcessing и DEEP provenance; [TV-0015](../TESTING/Results/TV-0015.md) |

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
  временная сортировка хранится отдельными timestamp-полями, а не структурой ID.
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

Начальный canonical corpus для разработки — примерно 10–20 Events; финальная
валидация Stage 1.11 использует 37 raw Events в 11 сессиях. Corpus включает
продолжение эпизодов, независимые темы, tool Event и procedural Memory, связанные
Entities, решение, противоречие, Knowledge challenge/supersession, restart/replay,
Retrieval и FAST/DEEP Context с provenance до raw Events.

Обязательные свойства: 100% обязательных expected IDs находятся в заданном top-k;
у 100% возвращаемых контрольных записей валидный provenance; budget соблюдается;
повторная обработка не размножает данные; restart/recovery сохраняют IDs и выборку;
invalid transition, dangling/missing source и transaction failure дают определённую
ошибку. Функциональный end-to-end baseline подтверждён [TV-0014](../TESTING/Results/TV-0014.md).

Performance baseline [TV-0015](../TESTING/Results/TV-0015.md) измерен на 1k/10k/100k.
Event append сохраняется около 15k/s; SQLite CRUD/lookup и 1-hop остаются около
1 ms, FTS на 100k — около 10 ms p95. При этом DEEP Context достиг 23.4 s p95, а
production EventProcessing batch снизился до 0.41 events/s на 100k. Кодовая
ревизия связывает это с повторными полными сканированиями raw `events.jsonl` в
processing identity check и при построении provenance Event index. Эти ограничения
зафиксированы до оптимизации и служат сравнительным baseline.

**Definition of Done.** На фиксированном end-to-end corpus Events детерминированно
формируют ожидаемые Memories; закрытый опыт создаёт Knowledge; новый противоречащий
опыт переводит его в `challenged`, а закрытая проверка подтверждает или заменяет;
Retrieval и Context Builder возвращают ожидаемый ограниченный контекст; provenance
проходит до source Events; restart и повторная обработка не повреждают данные;
performance baseline зафиксирован. Stage 1 завершён; доказательства собраны в
[TV-0004 — TV-0015](../TESTING/Results/README.md). Отложенные механизмы перечислены
в [Research](Research.md#отложенные-механизмы-памяти-stage-1).

## Stage 2

**Цель и наблюдение.** Доказать, что минимальные Goals и ограниченный Internal State
предсказуемо и причинно влияют на сравнение вариантов, не подменяя саму цель.
Одинаковая ситуация и одинаковые Candidates при neutral/altered state должны давать
заранее ожидаемое изменение score/priority, а trace — полностью объяснять источник
каждого изменения и итогового выбора. Архитектурный выбор зафиксирован в
[ADR-006](../DECISIONS/README.md#adr-006).

**Принципы.** Internal State является регулирующим входом, а не отдельным субъектом
решения: он не создаёт Goal или Candidate и не может молча отменить внешнюю задачу.
Первый baseline детерминирован и независим от LLM. Все значения ограничены
`0.0..1.0`; прямое изменение из произвольных компонентов запрещено. Каждое изменение
проходит через Transition Engine и сохраняет причинную историю. Точные коэффициенты,
веса и рабочий период являются конфигурацией и уточняются тестами, а не считаются
неизменной архитектурой.

### Порядок реализации Stage 2

| Шаг | Результат | Проверка завершения |
|---|---|---|
| **2.0 Specification — Complete** | Зафиксированы Goal, четыре baseline state, causal transitions, time dynamics, Choice и Expression; принят ADR-006 | Документация однозначно задаёт границы Stage 2, invariants и отложенные механизмы |
| **2.1 Internal State Storage — Complete** | Версионируемая конфигурация правил и transactional `internal_state.db` для state/goals/history | Schema создаётся/переоткрывается; constraints и transaction rollback защищают текущие значения и историю |
| **2.2 State History — Complete** | Причинный `StateTransition` с `before/delta/after`, source, rule, reason и optional context | Любое контрольное изменение восстанавливается до причины; прямой обход history/state transaction не допускается |
| **2.3 Goal Model — Complete** | Stable Goal с source, priority, status, success criterion, timestamps и resolution reason; `ACTIVE/BLOCKED/COMPLETED/CANCELLED` | Lifecycle и invalid transitions детерминированы; completed/cancelled Goal больше не участвует в выборе |
| **2.4 State Variables — Complete** | `fatigue/uncertainty/frustration/satisfaction`, range/baseline и правила влияния | Clamp/validation работают; каждое состояние имеет отдельную семантику и не дублирует Goal |
| **2.5 Transition Engine — Complete** | Event/result-driven правила с importance и repetition factors там, где они нужны | Одинаковый вход даёт одинаковый delta; high/low importance и repeated success/failure дают ожидаемо различный эффект |
| **2.6 Time Dynamics — Complete** | Инъецируемое время и lazy elapsed-time evaluation для growth/decay/recovery | Частота цикла и restart не меняют итог; uncertainty не decay; остальные временные правила воспроизводимы |
| **2.7 Goal Progress / Arbitration — Complete** | Проверяемый progress/result и объяснимый порядок нескольких активных Goals | Успех требует observation/criterion; blocked/reactivated и конкурирующие Goals дают определённый порядок без self-goal override |
| **2.8 Choice Engine — Complete** | Candidates получают base evaluation и ограниченные state modifiers с score trace | Neutral/altered state меняет ожидаемый выбор; ни один modifier не имеет неограниченного веса и не создаёт новый Candidate |
| **2.9 Expression Adapter — Complete** | Internal State → зависимый ExpressionProfile | Tone/voice/visual profile меняется от state, но Expression сам не меняет Internal State без отдельного правила |
| **2.10 Runtime Integration — Complete** | Полная цепочка `Event/Result → State/Goal → Candidates → Choice → Trace` в headless Runtime | Scenario snapshot показывает Goals, state, transitions, component scores и выбранный Candidate |
| **2.11 Recovery / Idempotency — Complete** | Crash/restart/replay не дублируют transitions и не создают скрытый time drift | Повтор одного source не применяет эффект дважды; recovery сохраняет state/history/goals согласованными |
| **2.12 Decision Performance — Complete** | Baseline latency/CPU/RAM для Choice с ростом Candidates и диагностикой | Измерены 2/10/100 Candidates: base, state modifiers и modifiers+trace/history; baseline [TV-0016](../TESTING/Results/TV-0016.md), SLA не задаётся |
| **2.13 Stage Validation — Complete** | End-to-end canonical scenarios для четырёх states, Goals, Choice, time, restart и Expression | 13 canonical tests и полный regression suite 306 tests прошли на snapshot `36c8d65`; [TV-0017](../TESTING/Results/TV-0017.md) |

### Goal и регулирующий слой

Goal содержит стабильный ID, `source`, `priority`, `status`, описание/критерий
результата, timestamps и причину разрешения. Самогенерируемые цели на Stage 2 не
реализуются; поле source оставляет для них архитектурное место без преждевременного
механизма authority. Внутренняя оценка, состояние Goal и объективная проверка
результата являются разными фактами: текст «успешно» или вызов инструмента сами по
себе не завершают Goal.

Первый Internal State состоит из четырёх переменных:

| State | Повышение / понижение | Временное поведение | Основное влияние на Choice |
|---|---|---|---|
| `fatigue` | awake duration + workload; recovery/Sleep снижает | растёт относительно настраиваемого `awake_work_period`; восстановление при отдыхе | штрафует дорогие/трудоёмкие варианты, но не отменяет Goal |
| `uncertainty` | недостаток/противоречие информации повышает; подтверждение снижает с учётом importance/quality | пассивно не меняется | повышает ценность information gain и осторожность к необратимому риску |
| `frustration` | повторные неудачи одной стратегии усиливают рост; прогресс/смена стратегии снижает | постепенно возвращается к baseline | снижает склонность повторять подтверждённо неудачный путь и поддерживает альтернативу |
| `satisfaction` | только проверенный прогресс/успех; importance усиливает, однотипные повторы дают diminishing returns | постепенно затухает к baseline | даёт небольшой бонус продолжению доказавшей эффективность стратегии |

Для `fatigue` time component зависит от доли текущего awake-периода относительно
настраиваемой рабочей длительности: ранний рост медленнее, ближе к пределу — выше,
после превышения — ещё выше. Workload добавляет отдельный компонент; Stage 2 может
использовать условные категории стоимости, реальные CPU/GPU/power сигналы вводятся
после измерений на следующих стадиях.

`uncertainty` использует важность ситуации и качество подтверждения: одинаковый
информационный пробел при low/high importance даёт разный delta, а прямое проверенное
наблюдение может снижать значение сильнее косвенного сигнала. Один Event не обязан
сбрасывать uncertainty полностью, если источник неопределённости разрешён только
частично.

Повторная одинаковая ошибка должна увеличивать `frustration` сильнее первой до
ограниченного потолка; серия связывается как минимум с Goal, Candidate/strategy и
failure type. Для `satisfaction` действует обратный принцип: последовательные
однотипные подтверждённые successes дают уменьшающийся прирост. Это не глобальная
reward-функция; максимальное влияние satisfaction на Choice намеренно ограничено
сильнее остальных baseline signals.

### Причинность, время и хранение

Живая state/history/goal информация хранится отдельно от lifecycle `state.json` в
SQLite `internal_state.db`; правила и коэффициенты находятся в версионируемой
конфигурации. Минимальный baseline БД включает текущие state values, state transitions,
goals и goal transitions. Изменение текущего значения и запись его истории выполняются
одной transaction.

`StateTransition` хранит state, timestamp, `before/delta/after`, `cause_type`,
`source_id`, `rule_id`, `reason`; при необходимости — importance, repetition factor,
elapsed time, Goal и Candidate. Временные изменения считаются лениво при значимом
обращении по elapsed time, а не фоновым tick-loop: это исключает зависимость от FPS
и тысячи микрозаписей history. В тестах clock инъецируется.

### Choice и Expression

Choice Engine получает уже существующие Goal и Candidates. Сначала считается
базовая пригодность варианта, затем применяются bounded modifiers Internal State.
Trace обязан показывать вклад base score и каждого modifier, чтобы различие между
neutral и altered state было причинно наблюдаемым. На Stage 2 Planner не требуется:
Candidates задаются сценарием/consumer и служат контролируемым материалом для
проверки механизма выбора.

Expression является зависимым отображением Internal State в параметры тона,
голоса или будущей визуализации. Обратного скрытого пути `Expression → State` нет;
если позднее понадобится такая связь, она должна быть отдельным явным правилом с
источником и history.

### Валидация и доказательства

Canonical scenarios включили neutral/altered Choice; high fatigue; low/high
importance uncertainty; отсутствие passive uncertainty decay; прямое и косвенное
подтверждение; escalating repeated failure frustration; прекращение серии после
смены стратегии; diminishing repeated-success satisfaction; fatigue time/recovery;
конкурирующие и terminal Goals; Expression dependency; ScenarioRunner и
restart/replay/idempotency с одинаковым injected time.

Для контрольных state transitions причина восстанавливается из history, а Choice
trace показывает base evaluation и применённые modifiers. Decision performance
[TV-0016](../TESTING/Results/TV-0016.md) для 100 Candidates дал p95 0.0211 ms на
base ranking, 0.0993 ms на state modifiers и 2.0092 ms на production Choice с
полным trace/history; SLA не задавался.

**Definition of Done.** Goals имеют корректный lifecycle и проверяемые результаты;
четыре baseline state изменяются через причинные transitions, соблюдают диапазон и
временные правила; neutral/altered state предсказуемо меняет оценку Candidates, но
не подменяет Goal; trace объясняет Choice; restart/replay не создают дублирования
или time drift; Expression остаётся зависимым слоем; decision-performance baseline
записан. Финальный targeted validation дал 13 passed, полный regression suite —
306 passed. Stage 2 завершён; доказательства: [TV-0016](../TESTING/Results/TV-0016.md)
и [TV-0017](../TESTING/Results/TV-0017.md). Отложенные расширения перечислены в
[Research](Research.md#отложенные-механизмы-internal-state).

## Stage 3

**Цель и наблюдение.** Доказать, что Sleep способен детерминированно отбирать
ограниченный объём накопленного опыта, обрабатывать его заменяемым processor,
сохранять derived result с полным provenance и после interruption/restart продолжать
с безопасного checkpoint без повторных эффектов. Текст — первый тип данных, но
оркестрация не должна зависеть от текстового payload. Архитектурный выбор зафиксирован
в [ADR-007](../DECISIONS/README.md#adr-007).

**Ключевой invariant.** Sleep работает с ссылками на источники и ограниченными
WorkItems, а не владеет исходными данными. Raw Event/observation, Memory, Knowledge
или будущий Asset не переписываются ради консолидации. Каждый derived result хранит
происхождение и processor/version; chunk считается завершённым только после
атомарной фиксации checkpoint и его локального результата. Большой источник никогда
не требуется загружать целиком, а повторный запуск не должен создавать второй
логический результат той же работы.

Первый обязательный cognitive work type — только `CONSOLIDATE`. Приоритетные
источники baseline: raw Events/observations, CLOSED Memories с валидным provenance
и CONFIRMED Knowledge с evidence. `REFLECT`, replay/counterfactual `SIMULATE` и
генеративный `GENERATE` признаны совместимыми будущими направлениями, но не входят
в Stage 3 baseline: сейчас недостаточно данных и контрольных критериев, чтобы
объективно проверить качество таких выводов.

### Порядок реализации Stage 3

| Шаг | Результат | Проверка завершения |
|---|---|---|
| **3.0 Specification — Complete** | Зафиксированы SleepJob, WorkItem/SourceRef, processor contract, chunk/checkpoint model, provenance, resource budget, large-data readiness и границы cognitive work; принят ADR-007 | Документация однозначно отделяет orchestration от конкретного формата данных и задаёт критерии каждого последующего шага |
| **3.1 Sleep Storage / Lifecycle — Complete** | Transactional `sleep.db` с persistent SleepJob и lifecycle `queued/running/checkpointed/interrupted/completed/failed` | Schema/reopen/constraints/rollback прошли; invalid transitions определены; restart сохраняет job identity и последнее допустимое состояние; [TV-0018](../TESTING/Results/TV-0018.md) |
| **3.2 Source / WorkItem Contract — Complete** | Универсальные `SourceRef` и `WorkItem` с source kind/id, work kind, processor/version, priority, cost hint, status и checkpoint reference без embedding тяжёлого payload | Event/Memory/Knowledge и synthetic Asset refs валидируются одинаковым контрактом; dangling/unsupported source дают явную ошибку; payload большого источника не попадает в `sleep.db`; [TV-0019](../TESTING/Results/TV-0019.md) |
| **3.3 Selection / Scheduling — Complete** | Deterministic selector формирует bounded queue из eligible sources по priority/cost/budget и фиксированному tie-break | Один вход даёт один порядок WorkItems; max items/cost соблюдаются; неeligible/terminal sources не попадают в работу; повтор selection не размножает queue; [TV-0020](../TESTING/Results/TV-0020.md) |
| **3.4 Processor Interface — Complete** | Заменяемый processor contract для source/work kind, chunk processing, checkpoint state и finalize; Sleep orchestration не знает семантику текста/медиа | Deterministic test processor заменяется вторым adapter без изменения scheduler; unsupported kind не получает silent fallback; processor/version сохраняются в trace/result; [TV-0021](../TESTING/Results/TV-0021.md) |
| **3.5 Deterministic Text Consolidation — Complete** | Первый `CONSOLIDATE` processor фильтрует/группирует/сортирует текстовые eligible sources и выдаёт bounded derived consolidation result без удаления исходников | Canonical text corpus даёт ожидаемые группы/порядок/дедупликацию; исходные Event/Memory/Knowledge неизменны; CONFIRMED Knowledge не переписывается без существующих evidence rules; [TV-0022](../TESTING/Results/TV-0022.md) |
| **3.6 Chunk / Checkpoint / Resume — Complete** | Work выполняется ограниченными chunks; после каждого committed chunk хранится cursor/checkpoint, interruption возобновляет следующий незавершённый chunk | Прерывание на каждом контрольном checkpoint и последующий resume дают тот же допустимый final result, что uninterrupted run; уже committed chunk не выполняется повторно; [TV-0023](../TESTING/Results/TV-0023.md) |
| **3.7 Derived Results / Provenance — Complete** | Derived result хранит source refs, processor/version, transformation history и output refs; authority результата отделена от raw/verified source | Каждый результат проходит до фактических source Events/Memories/Knowledge; missing source блокирует завершение; derived output не становится raw observation или CONFIRMED Knowledge автоматически; [TV-0024](../TESTING/Results/TV-0024.md) |
| **3.8 Recovery / Idempotency — Complete** | Persistent operation keys и recovery protocol согласуют `sleep.db` с эффектами в Memory/Knowledge storage после crash/replay | Crash до/после checkpoint/output commit восстанавливается без дубликатов; повтор Job/WorkItem не применяет один эффект дважды; partial operation остаётся диагностируемой; [TV-0025](../TESTING/Results/TV-0025.md) |
| **3.9 Runtime Integration — Complete** | Lifecycle Runtime различает inactive sleep, active SleepJob, safe interruption и возврат к wake без смешивания обычного `sleep()` с незавершённой консолидацией | Headless scenario проходит `wake → sleep processing → checkpoint/interruption → resume/complete → wake`; запрос wake прерывает работу на безопасной границе и не повреждает данные; [TV-0026](../TESTING/Results/TV-0026.md) |
| **3.10 Observability / Resource Budget — Complete** | Snapshot/trace показывает job, queue, текущий WorkItem/chunk, processed/skipped/failed counts, budget и elapsed/CPU/RAM/storage metrics | По snapshot можно восстановить причину выбора и текущий progress; budget exhaustion завершает/приостанавливает работу определённо; метрики не требуют GUI; [TV-0027](../TESTING/Results/TV-0027.md) |
| **3.11 Large-data Readiness — Complete** | Synthetic large-source adapter имитирует многогигабайтный Asset и тысячи chunks без реального media-файла; payload читается лениво через тот же processor contract | Источник логического размера ≥10 GB проходит bounded chunk iteration; interruption на произвольном chunk возобновляется с следующего; DB хранит refs/checkpoints, а не полный payload; память не зависит линейно от общего размера источника; [TV-0028](../TESTING/Results/TV-0028.md) |
| **3.12 Performance Baseline — Complete** | Измерены orchestration/selection/checkpoint/provenance latency, CPU/RAM/storage на 1k/10k/100k WorkItems и large-source chunk workload | Baseline зафиксирован без SLA; selection определён как основной scaling bottleneck, checkpoint/provenance остаются стабильными; [TV-0029](../TESTING/Results/TV-0029.md) |
| **3.13 Stage Validation — Complete** | End-to-end canonical Sleep scenarios объединяют raw/Memory/Knowledge sources, bounded selection, consolidation, interruption/restart, provenance и large-source contract | Uninterrupted и interrupted/resumed runs дают эквивалентный допустимый итог; replay не создаёт дублей; provenance полный; полный regression suite зелёный; [TV-0030](../TESTING/Results/TV-0030.md) |

### Storage, WorkItem и resource boundary

Sleep orchestration хранится отдельно от Cognitive Memory в локальном transactional
`sleep.db`: jobs, work items, checkpoints и metadata derived results. Большие данные
туда не помещаются. `SourceRef` указывает на Event/Memory/Knowledge или будущий Asset;
для тяжёлого Asset сохраняются только stable ID, descriptor/location/checksum/size
там, где они доступны. Реальные binary assets остаются внешним storage и читаются
processor-адаптером по chunks.

Базовый WorkItem содержит как минимум stable ID, Job ID, `work_kind`, source kind/id,
processor/version, priority, estimated cost, status, attempts и checkpoint/cursor.
Первый cost model может быть категориальным (`cheap/normal/expensive`) и нужен не
для «интеллекта», а чтобы scheduler мог сформировать bounded workload. Фиксированное
расписание 16/8 или 12/12 не является частью архитектуры: Sleep запускается и
ограничивается явными runtime/resource условиями.

`sleep.db` и `memory.db` не объявляются одной физической транзакцией. Если processor
создаёт внешний effect через существующий Memory/Knowledge API, согласованность
обеспечивается stable operation/output ID, idempotency и recovery protocol. Это
аналогично уже принятому принципу восстановления между разными хранилищами, а не
попытка скрыть cross-store failure.

### Consolidation baseline

Первый processor работает только с текстовым опытом, но получает его через общий
SourceRef/WorkItem contract. Он может фильтровать неeligible записи, детерминированно
сортировать и группировать источники, убирать точные повторы из derived output и
создавать bounded `ConsolidationResult`/report со ссылками на все источники.
Консолидация не удаляет raw Event, не переписывает CLOSED Memory и не повышает
Knowledge authority сама по себе. Любое изменение Memory/Knowledge проходит через
их существующие lifecycle/evidence rules.

Stage 3 therefore проверяет прежде всего механизм безопасной переработки накопленного
опыта, а не качество свободного reasoning. Reflection старых событий, replay ошибок,
counterfactual simulation и generative dreaming оставляются extension points для
будущих processors. Их outputs должны быть явно hypothetical/derived и никогда не
маскироваться под наблюдение или подтверждённый факт.

### Large-data readiness

Будущие дневные отчёты, видео, аудио и internal telemetry рассматриваются как
источники того же общего типа работы, но со своими processor adapters и chunk
strategies. Stage 3 не требует настоящего видео pipeline: вместо этого synthetic
large-source доказывает, что scheduler/checkpoints/provenance не зависят от загрузки
всего payload в RAM. Это архитектурный тест против будущего полного переписывания,
а не заявление о готовом media understanding.

### Валидация и доказательства

Canonical corpus Stage 3 включает raw observations, CLOSED Memories с provenance,
CONFIRMED Knowledge, неeligible records и synthetic large source. Контрольные
сценарии покрывают complete run, budget exhaustion, interruption/checkpoint,
reopen/resume, replay, wake/recovery, missing/unsupported source и large-source resume.

Обязательные свойства подтверждены: deterministic selection/order; bounded queue и
chunk size; исходники не изменяются скрыто; derived result имеет processor/version и
provenance; completed chunk/job не применяется повторно; interrupted/resumed run
эквивалентен допустимому uninterrupted результату; полный regression предыдущих
стадий остаётся зелёным. Финальная проверка — [TV-0030](../TESTING/Results/TV-0030.md).

Performance baseline [TV-0029](../TESTING/Results/TV-0029.md) измерен на 1k/10k/100k
WorkItems. Selection p95 вырос примерно от 15 ms до 1.775 s и достиг 252 MB peak RSS
на 100k, поэтому это текущий основной scaling bottleneck. Checkpoint commit и
provenance finalize сохранились примерно в диапазонах 0.54–0.61 ms и 1.23–1.34 ms;
storage вырос примерно линейно до 47.9 MB на 100k. Synthetic 10 GiB large-source
завершился после interruption/reopen/direct resume; его current/peak RSS
135.652/170.273 MB сохранён как будущая цель profiling, а не блокер Stage 3.

**Definition of Done.** Sleep имеет persistent lifecycle и bounded deterministic
queue; source/work contracts не привязаны к тексту; deterministic text consolidation
создаёт derived result без потери/перезаписи источников; chunk/checkpoint/resume и
recovery/replay не создают повторных эффектов; provenance проходит до исходного
опыта; runtime безопасно прерывает работу для wake; large-source contract доказан
synthetic test; resource/performance baseline записан; canonical end-to-end scenarios
и полный regression suite проходят. Stage 3 завершён; доказательства собраны в
[TV-0018 — TV-0030](../TESTING/Results/README.md). Reflection/Simulation/Dreaming
не требуются для завершения Stage 3 и остаются в [Research](Research.md#когнитивный-сон).

## Stage 4

**Цель и наблюдение.** Доказать, что существующий Goal может быть преобразован в
ограниченную последовательность реальных действий в sandbox: система получает
bounded Context, формирует несколько допустимых вариантов, применяет существующий
Choice/Internal State, выполняет ровно одно выбранное действие через Tool contract,
получает независимое Observation, проверяет progress/result и либо завершает Goal,
либо делает следующий цикл. Архитектурный выбор зафиксирован в
[ADR-008](../DECISIONS/README.md#adr-008).

**Ключевые invariants.** Planner предлагает, но не исполняет. Executor исполняет
только зарегистрированный Tool. Успешный tool call не равен успешному Goal:
завершение требует Observation и проверки success criterion. Planner/LLM не имеет
прямого writable-доступа к Goal, Memory, Knowledge или Internal State. На baseline
Planner не видит значения Internal State, чтобы их влияние оставалось отдельно
наблюдаемым через Choice. Один agent turn выполняет не более одного реального
Action; длинный план является лишь гипотезой и пересматривается после Observation.

Tool system использует собственный JSON-Schema contract ANIMA и системную metadata
о side effects/reversibility/idempotency/timeout/sandbox scope. Контракт должен быть
пригоден для будущего MCP adapter, но внутренний Agent не зависит от MCP runtime.
`PlannerAdapter` скрывает provider-specific API и возвращает общий структурированный
`PlannerTurn` с ranked `ActionProposal`. Системные Candidate features — risk, effort,
information gain, repeated failure и подобные — вычисляет ANIMA, а не модель.

Operational execution history и долговременный опыт разделены. Persistent
`agent.db` должен стать источником истины для AgentRun/AgentStep, proposal/selection,
execution receipt, observation и operation IDs, необходимых recovery/idempotency.
Значимые действия и результаты публикуются как компактные `agent.*` Events, а
долговременная Memory формируется через обычный Event/Memory pipeline. Большие
outputs не копируются во все слои и при необходимости остаются внешними данными
со stable reference.

### Рабочая декомпозиция Stage 4

Таблица ниже — план текущей итерации, а не неизменяемая архитектура. После 4.0 шаги
можно объединять, дробить или переставлять, если тесты показывают более корректную
границу. Изменение accepted invariants требует отдельного пересмотра ADR-008.

| Шаг | Результат | Проверка завершения |
|---|---|---|
| **4.0 Specification — InProgress** | Зафиксировать AgentRun/AgentStep, PlannerTurn/ActionProposal, Tool/Action/ExecutionReceipt/Observation/VerificationResult, ownership, lifecycle, storage и recovery boundaries | Документация однозначно отвечает, кто создаёт/изменяет каждую сущность, где проходят atomic/idempotent boundaries, что является observation и кто имеет authority завершить Goal |
| **4.1 Agent Storage / Lifecycle — Planned** | Transactional `agent.db` для persistent run/step state и operation identity без копирования Memory/Tool payload | Schema/reopen/constraints/rollback проходят; restart сохраняет run identity и последнее допустимое состояние; invalid lifecycle transition определён |
| **4.2 Tool Contract / Registry — Planned** | Версионированные ToolDescriptor и Registry с JSON Schema, side-effect/reversibility/idempotency/timeout/sandbox metadata | Валидный tool регистрируется; duplicate/version/schema/unsupported tool дают явную ошибку; metadata принадлежит системе, а не Planner |
| **4.3 Action / Observation Contracts — Planned** | Разделены proposal, selected Action, ExecutionReceipt, Observation и verification; данные имеют stable IDs/refs | Tool success не закрывает Goal; observation можно связать с конкретным action/receipt; malformed или dangling refs отклоняются |
| **4.4 Sandbox Executor / Idempotency — Planned** | Первый обратимый файловый sandbox (`list/read/write`) и при необходимости deterministic calculator; Executor не выходит за разрешённый root и использует operation IDs для side effects | Path escape/unknown tool/invalid args/timeout определены; подтверждённый write не повторяется после replay; read-only операции безопасно повторимы |
| **4.5 PlannerAdapter / Deterministic Planner — Planned** | Общий PlannerAdapter возвращает bounded ranked ActionProposals; deterministic planner позволяет тестировать agent loop без LLM | Planner можно заменить без изменения Executor/Choice/Verifier; output schema валидируется; Planner не может исполнить Tool или изменить системное состояние напрямую |
| **4.6 Candidate Adaptation / Choice Integration — Planned** | Proposal преобразуется в существующий Candidate: planner rank даёт ограниченный base preference, системные признаки вычисляются из Tool/history/context, затем Choice применяет Internal State | Один набор proposals при neutral/altered state даёт ожидаемо различный выбор; Planner не может занизить risk/effort или обойти Choice |
| **4.7 Goal Verification / Progress — Planned** | Observation переводится в проверяемый Goal progress/result через deterministic baseline verifier | Положительный tool receipt без нужного состояния не завершает Goal; реальное подтверждение success criterion завершает; failure/partial progress остаются различимы |
| **4.8 Agent Loop / Runtime Integration — Planned** | Полный пошаговый цикл `Goal → Context → proposals → Choice → Action → Observation → verification → next turn` интегрирован в headless Runtime | Многошаговая sandbox-задача завершается без скрытых прямых вызовов; за turn выполняется не более одного Action; cancel/budget/terminal Goal останавливают loop определённо |
| **4.9 Agent Events / Experience Capture — Planned** | Существенные action/observation/result/failure/strategy-change публикуются как компактные `agent.*` Events с refs | EventLog показывает причинную цепочку run без дублирования полного execution history; replay не размножает значимые Events |
| **4.10 Memory Integration — Planned** | Agent experience формирует bounded episodic Memory через обычный processing path, а не прямую запись Planner/Executor | Один multi-step run не превращается в Memory на каждый технический tool call; итоговый эпизод сохраняет Goal, значимые failures/adjustments/result и provenance до Events |
| **4.11 Recovery / Interruption / Replay — Planned** | Crash/restart/timeout/cancel восстанавливают run на безопасной границе; confirmed side effect не выполняется повторно | Прерывание до/после execution/observation commit имеет определённый recovery path; replay не создаёт второй логический effect или второй completed Goal |
| **4.12 LLM Planner Experiment — Planned** | Реальная LLM подключается только через PlannerAdapter и решает тот же canonical sandbox task, что deterministic baseline | Сравниваются schema validity, invalid/forbidden proposals, replanning, Goal success, tool calls, latency, tokens/model cost; смена Planner не требует изменения Agent/Tool/Choice/Verifier contracts |
| **4.13 Observability / Budgets — Planned** | Snapshot/trace показывает run/step, Goal, context budget, proposals, Candidate/Choice trace, selected Action, receipt/observation, verifier result и remaining budgets | По trace можно восстановить причину каждого действия; max steps/tool calls/time/model budget останавливают run определённо без повреждения state |
| **4.14 Performance Baseline — Planned** | Измерить deterministic orchestration/storage/verification отдельно от стоимости LLM и Tool implementation | Baseline зафиксирован без SLA; видна стоимость Agent loop, persistence, Choice/verification и отдельно model/tool latency; bottlenecks записаны до оптимизации |
| **4.15 Stage Validation — Planned** | Canonical scenario объединяет Goal, Context/Memory, failure, Internal State/Choice, strategy change, sandbox actions, restart, verification и повторное использование опыта; отдельный LLM run проходит тот же contract | Success/failure/cancel/recovery имеют определённые outcomes; replay не повторяет confirmed effect; Goal закрывается только по observation; agent experience доступен следующему сходному Goal; полный regression suite зелёный |

### Planner и LLM boundary

Первый Planner baseline deterministic. Это позволяет проверить agent architecture,
не смешивая ошибки orchestration с вероятностным model output. Реальная LLM является
обязательным экспериментом Stage 4, но не владельцем Agent: provider-specific
function/tool calling преобразуется adapter-ом в `ActionProposal`, после чего
validation, Candidate adaptation, Choice, execution и verification выполняются
обычными компонентами ANIMA.

Planner получает Goal, bounded ContextBundle, доступные ToolDescriptors, recent
AgentSteps/Observations, run constraints и remaining budget. На baseline Internal
State values в PlannerRequest не передаются. Planner возвращает несколько ranked
proposals и краткое rationale/expected observation, достаточные для trace; свободный
chain-of-thought не является контрактом и не требуется для хранения. Модель может
сообщить, что считает Goal завершённым или что не знает следующего шага, но такое
сообщение не имеет authority изменить Goal lifecycle.

### Action, observation и опыт

Каждый внешний effect проходит `ToolDescriptor → validated Action → Executor`.
ExecutionReceipt фиксирует факт попытки/выполнения, но Observation отвечает на
вопрос, что реально стало состоянием среды. Для `write(result.txt)` receipt `ok`
недостаточен: verifier должен получить наблюдение, подтверждающее существование и
содержимое файла, если именно это задано success criterion.

Agent execution history нужна для recovery и поэтому хранится полно и технически в
`agent.db`; Memory нужна для будущего поведения и поэтому хранит только полезный
эпизод. Значимые failures, discovery, strategy change и verified outcome проходят
через EventLog, после чего Memory Processor/специализированный agent-experience
adapter может сформировать bounded episodic Memory. Это сохраняет единый путь
происхождения и не позволяет Planner записывать удобную ему версию прошлого.

### Canonical scenario

Начальный контрольный workflow должен быть обратимым и полностью локальным. В
sandbox находятся файлы с данными, а Goal требует найти значения, вычислить
результат, записать `result.txt` и проверить его. Сценарий намеренно содержит
неверное первоначальное предположение об имени файла: первый read должен дать
failure, после чего information-gathering/alternative Action получает преимущество,
система находит реальные файлы, продолжает работу и подтверждает результат чтением.

В расширенной проверке restart происходит после side effect, но до завершения Goal:
recovery не повторяет уже подтверждённый write и продолжает с observation/
verification. После закрытия run значимый опыт превращается в episodic Memory; новый
похожий Goal должен получить этот опыт через ContextBuilder. Такой сценарий впервые
проверяет Stage 1–3 совместно с Agent, а не параллельно им.

### Отложенные механизмы Stage 4

Self-generated Goals, unrestricted shell/browser/desktop control, autonomous
background loops, прямой Planner access к Internal State, автоматическое исполнение
длинного LLM-плана, полноценный MCP runtime, multi-agent coordination, Fast/Deep
model routing и generative self-reflection не нужны для baseline. Их возвращаем
только после измеренного ограничения текущего Agent. Внешние необратимые действия
требуют отдельной policy/confirmation модели и не доказываются файловым sandbox.

**Definition of Done.** Agent имеет persistent recoverable lifecycle и выполняет
только зарегистрированные Tools через sandbox Executor; Planner заменяем и не имеет
прямого execution/write authority; Proposal проходит validation, Candidate adaptation
и существующий Choice; каждый реальный Action заканчивается Observation, а Goal
завершается только независимой проверкой success criterion. Execution history
отделена от долговременной Memory, значимый опыт проходит Event/Memory pipeline,
restart/replay не дублируют confirmed effects. Deterministic baseline и минимум один
реальный LLM Planner проходят один и тот же contract/canonical workflow; resource/
performance baseline записан, а полный regression suite предыдущих стадий остаётся
зелёным. Точная внутренняя декомпозиция может уточняться по данным тестов без
изменения этих invariants.

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