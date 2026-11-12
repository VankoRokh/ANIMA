# ANIMA — Memory Architecture v1.0 / v1.1 Roadmap

**Статус:** шаги 0–1 VERIFIED; Event Retrieval v1 (шаг 2) прошёл функциональную приёмку и PC-C3, но Pi/power-loss gate открыт; шаг 3 Memory Encoding — E1 shadow lab PASS, production integration OPEN.  
**Дата решения:** 2026-11-11.  
**Рабочая ветка:** `experiment/core-memory-information-baseline`.  
**Отправной исследованный snapshot:** `cab955f82931feb16e5a7c2bf801e17aa736fd8f`.  
**Основание:** «ANIMA — Memory Architecture Research & Technical Review», 2026-11-11; [EXP-009](Research.md#exp-009--core--memory-информационная-состоятельность), [Stage 7 boundary](Stage_7_Semantic_Boundary_v0.md), [общая дорожная карта](README.md).

> Это **межэтапный рабочий план укрепления Cognitive Memory**, а не новый официальный Stage. Статусы Stage 1/3/6/7 и зависимости определяются [`docs/project.json`](../project.json). Принятие плана не означает, что исследовательские выводы уже реализованы. Изменение публичных контрактов и полномочий требует отдельного решения, тестов и при необходимости ADR.

## 1. Цель и границы

**Цель:** получить воспроизводимую, восстановимую, автономную от LLM и достаточно эффективную систему памяти, которая хранит исходный опыт, организует эпизоды, предоставляет проверяемое извлечение и ограниченную интерпретацию для Core/Cognition и в следующей итерации — переработку через SLEEP.

**Должна обеспечивать:** запись Event с источником; связывание Event→Memory; прямой поиск первичных Events; контролируемое формирование эпизодов; различение Report/Observation/Claim/Evidence/Knowledge; ограниченный контекст и явную неполноту; восстановление после сбоя; read-only интерфейсы другим модулям; измеренные ресурсы.

**Не является целью v1:** замена SQLite графовой СУБД, обязательные embeddings/LLM, обучение весов, универсальное понимание языка, автоматическое установление достоверности из текста, безусловное подтверждение Knowledge, сложная автономная метапамять или полная переработка всех сенсорных потоков.

## 2. Неизменные архитектурные правила

1. **Core сохраняет ownership.** Memory не принимает исполнительные решения и не управляет Goals/Tasks, источниками, допуском действий или политикой Knowledge. FAST/DEEP — заменяемые интерпретаторы.
2. **Raw ≠ projection.** Первичный Event остаётся в своём authoritative store (`events.jsonl` для legacy; `core_state.db` для типизированного допуска). Memory, Event FTS, summaries и derived outputs — восстанавливаемые/версионированные представления. Не объявлять два совместимых представления одного Event независимыми случаями.
3. **Семантические роли разделены.** Event фиксирует получение/наблюдение; Memory организует эпизод; Claim — утверждение; Evidence — конкретное основание с provenance; Knowledge — результат допустимого lifecycle. Факт сообщения не доказывает истинность содержания.
4. **Разделить поиск, ассоциацию и компрессию.** Сжатый `Memory.content` не является единственным источником ни для поиска первичного факта, ни для идентичности эпизода.
5. **Никаких незаметных повышений authority.** LLM/derived результат — предложение. До принятия DP-08/09/10b/11 автоматическая публикация `confirmed` Knowledge запрещена; закрытая Memory сама по себе недостаточна для подтверждения.
6. **Историчность и idempotency.** Источник, Producer, occurrence/version, временная область, связь и причина изменения проверяемы. Replay не создаёт новый эффект. Удаление/merge не оставляет незаметно действующей ложной поддержки.
7. **Измерение перед усложнением.** Графовый обход, vector search и rerank добавляются только при преимуществе на равном корпусе и бюджете. Успешный pytest не заменяет испытания качества, долговечности и реальной нагрузки.

## 3. Последовательность и критерии допуска

Ступени 0–4 готовят **Memory v1.0**; ступень 6 имеет **ранний интеграционный gate** для v1.0. Ступень 5 и полный gate ступени 6 формируют **Memory v1.1**. Ресурсные проверки C3 проходят поперёк этапов; абсолютные SLO задаются отдельно до нагрузочных прогонов.

| Шаг | Работа | Выход | Gate |
| --- | --- | --- | --- |
| **0 — Baseline** | Устранить дефект аннотации `CoreDoorExecution` для заявленных версий Python; исправить fixture тестов документации; выбрать и закрепить single-writer либо атомарный claim; зафиксировать чистый SHA и команды | Воспроизводимая база; регрессия без известных ложных падений | `build_core` импортируется на поддерживаемых версиях; полный pytest + docs check; повтор Event = один эффект; гонка не переводит `done` в `failed` |
| **1 — EXP-009 Retrieval study** | Заморозить корпус, запросы, эталон Event IDs, parser, порядок и бюджет; сравнить **A** Memory-only, **B** Event-only FTS5, **C** Event+Memory FTS5, **D** C + ограниченные source hops | Отчёт с Recall@k/Precision@k (или nDCG), ошибками и стоимостью каждого канала | 20/20 source Event IDs по точным ключам; отрицательные и парафразные запросы; равный корпус/бюджет; D допускается только при доказанном выигрыше |
| **2 — Event Retrieval** | Реализовать read-only Event ID lookup и восстанавливаемый FTS5 индекс; версионированный locator/span; фильтры до LIMIT; quota/полноту/лаг; точечный provenance | `Event Retrieval v1`; независимый доступ к деталям, вытесненным из `Memory.content` | Event↔Memory links раскрываются; crash/replay/rebuild не меняют корректные результаты; источники проверяются; нет полного scan JSONL на каждый штатный lookup |
| **3 — Memory Encoding** | В shadow сравнить текущую группировку с ассоциацией по source refs, времени, типам, Entity и контексту; отделить `association` от `composition` | `Memory Encoding v1` и отчёт об устойчивости эпизодов | Пунктуация/компрессия не меняют группировку без семантической причины; отдельные случаи не склеиваются; provenance сохраняется; модель необязательна |
| **4 — Semantic Memory (read-only)** | Ограниченный typed/свободный вход → mentions/Claim/Evidence refs; Stage 7 deterministic-first; системная проверка schema/source/span/scope/независимости | `Semantic Memory Interface v1` без автоматического Knowledge commit | Нет поддельных source/span и независимых голосов из пересказа; unknown остаётся unknown; ошибки/residual не дают `confirmed` |
| **5 — SLEEP Consolidation** | Использовать WorkItems/checkpoints/DerivedResult; добавить проверяемые версии источников, bounded grouping/summary, shadow/read-only публикацию | `Memory Consolidation v1` | Один эффект при pause/wake/restart; raw доступен; устаревшая версия источника останавливает публикацию; неверная сводка не становится Knowledge |
| **6 — Core Integration** | Проверить сквозной путь Event→Memory/index→Retrieval→Context→Cognition, а затем SLEEP→Derived→read-only Retrieval | `Memory Integration — VERIFIED` | См. сценарии и отдельные gates ниже |

### Шаг 0 — порядок начала

Сначала зафиксировать фактическую регрессию исследованного SHA и версий Python. Исправления выполнять минимальными патчами; не менять заявленный минимум Python без явного решения. Для конкурентной записи допустим первоначальный **single-writer contract**, но его нужно явно документировать и проверять до запуска фоновых обработчиков.

### Шаг 1 — контроль честности сравнения

**Техническое задание и матрица приёмки:** [EXP-009 — Controlled Retrieval A/B/C/D](Memory_EXP009_Retrieval_ABCD_Brief.md). [Подтверждённые результаты](Memory_EXP009_Retrieval_ABCD_Results.md): Event FTS5 выбран начальным baseline; source hops — отдельная возможность, не default. Gold Event IDs и одинаковые бюджеты проверены.

Предыдущее G1 измеряло доступность текстовых маркеров: глубина 0 дала 22/22 при бюджете 10 элементов/1200 символов, а Event-only FTS5 повторил покрытие. **Это не доказательство превосходства графа или полноценной многоуровневой памяти.** Дальнейший опыт должен размечать целевые **Event IDs**, релевантность, типы источников, временную область, независимые перефразы, false positives и отсутствие совпадений. Все варианты используют одно snapshot и один сериализованный бюджет; отдельно сообщать потери при усечении.

### Шаг 2 — контракт индекса

**Production implementation brief:** [Event Retrieval v1 — contract & recovery gates](Memory_Event_Retrieval_v1_Brief.md). Корректность проверяется отдельно от C3-производительности; API opt-in для Core, без изменения маршрута FAST/DEEP.

**Фактический результат шага 2:** [Event Retrieval v1 — результаты](Memory_Event_Retrieval_v1_Results.md): функциональная проверка **PASS** на Python 3.12/3.13/3.14 (1506 тестов в каждой матрице), C3 PC-базовые измерения на **10⁴ и 10⁵ Events** получены. Это не закрывает аппаратный Pi gate и не меняет официальные Stage статусы.

Индекс производный; authoritative первичный Event не переписывается. Для JSONL locator учитывает идентичность журнала и смещение, для typed Core — точечный lookup по PK/ID. Ключ индекса и checkpoint обработанного префикса должны фиксироваться согласованно, с повторяемым догоном после прерывания. Несовпадение source hash/ID → `incomplete/error`, а не молчаливое доверие индексу. Read API различает `no_match`, `partial`, `source_unavailable`, `ambiguous`, `budget_exhausted`. Политика Event types и разрешённых полей согласуется до пилота.

### Шаг 3 — ограничения группировки

**Исследование E1 (shadow):** [Memory Encoding — raw Event association](Memory_Encoding_Shadow_E1_Brief.md). Сравниваем Legacy 64/512 и независимый shadow на одинаковых raw Events; production Memory не меняем до оценки границ эпизодов.

**Подтверждённые E1 результаты:** [Memory Encoding E1 — raw decisions and analysis](Memory_Encoding_E1_Results.md), CI `43094616959`: 20 событий, Legacy 10 ошибочных объединённых пар против 0 у shadow на этом корпусе. Отдельный probe компрессии пока не имеет подтверждённой CI-приёмки.

**E2 — открытая лабораторная проверка:** [Weak episode-link candidates](Memory_Encoding_E2_Brief.md). Неоднозначные связи отмечаются как `unverified` без слияния эпизодов, записи отношений и повышения authority; CI-приёмка ожидается.

**E3 — следующий gate:** [Uncertain episode-link review lifecycle](Memory_Encoding_E3_Review_Brief.md). Слабая связь остаётся `unverified`; новое raw событие может повысить только приоритет проверки `review_ready`, но не превращает гипотезу в факт. Нужны отрицательные тесты на ложные мостики и replay.

**E4 — концептуальный контракт, production-реализация не начата:** [Event → Episode → Story и долговременные исследования неопределённостей](Memory_E4_Architecture_Contract_Draft.md). Учтены условное ожидание, очереди, длительное выполнение, самостоятельная постановка Goal/Task и периодический review важных вопросов без новых Events; планирование остаётся полномочием Core.

**E4 — L1.2 scoped research:** [L1.2 contract](../TESTING/Memory_E4_L12_Contract_v0.md), [L1.2 evaluation](../TESTING/Memory_E4_L12_Evaluation_Results_v0.md): typed report identifiers, conflict-aware source aliases, laboratory CorrectionTarget. Old 57-case frozen result unchanged (41 PASS, 81 NOT_SUPPORTED); the 15-case visible challenge improved from 12/16 to 16/16 but is **not independent**. All 99 forbidden obligations remain unverified; no production Memory or autonomous L2 authorization.

**E4 — исследования перед L2:** [L1.1 challenge results](../TESTING/Memory_E4_L11_Challenge_Results_v0.md), [isolated derived journal](../TESTING/Memory_E4_Derived_Journal_Lab_v0.md), [pre-L2 architecture review](../TESTING/Memory_E4_PreL2_Architecture_Review_v0.md). На 15 новых открытых сценариях 12 PASS/4 FAIL, включая ложный alias reuse и ложное исправление Episode; lab SQLite transaction/replay PASS, но без реального power-loss. **Production E4 и L2 не допущены.** Новые Goal/Task и автоматические действия не реализуются этим экспериментом.

**E4 — замороженный экспериментальный базис:** [Memory E4 Conformance Corpus v0](../TESTING/Memory_E4_Conformance_Corpus_v0_Draft.md), [Freeze Record](../TESTING/Memory_E4_v0_Freeze_Record.md) и [Runner Contract](../TESTING/Memory_E4_Runner_Contract_v0.md). 42 root + 15 отрицательных сценариев; входы и предварительный gold зафиксированы по байтам, но независимой приёмки gold и запуска E4-conformance ещё нет. L0 Shadow только выдаёт сырые решения, без Story/Goal/Task/SLEEP.

Проверять не только качество текста summary, но и **границы эпизода**: перегрев в один сеанс против другого дня, отдельные независимые измерения, повтор доставки, похожие фразы о разных объектах, изменение формата/пунктуации, переразметка уже сжатого эпизода. Эксперимент не имеет права разрушительно перезаписывать действующие Memory до отдельного решения о миграции.

### Шаг 4 — граница Knowledge

Проверка точной цитаты подтверждает привязку к Event, **не истинность** Claim. `classify_relation/0.1` получает уже структурированные Claims/Evidence: extraction из свободного языка испытывается отдельно. `create_candidate/investigate/confirm/challenge/reject/supersede` остаются под правилами системного lifecycle. Полноценную запись Knowledge отложить до решений **DP-08 (authority), DP-09 (current/as-of), DP-10b (re-evaluation), DP-11 (integration)** и отдельной приёмки.

### Шаг 5 — граница SLEEP

Derived summary не заменяет первичное свидетельство и не становится автоматически подтверждённым знанием. Для нескольких входов фиксировать список source revisions и параметры процессора. Между `sleep.db` и `memory.db` потребуются idempotent effect key и сверка версий при публикации; до этого результаты доступны в read-only/shadow.

### Шаг 6 — сквозные сценарии

- **A — запись:** событие сохранено, допустимая Memory создана, ссылки раскрываются.
- **B — перезапуск:** после restart Core находит прежние Event/Memory.
- **C — ранняя деталь:** точное значение найдено в raw Event даже после вытеснения из `Memory.content`.
- **D — неполнота:** «нет подходящего в просмотренной области» не приравнивается к «факта не существует».
- **E — конфликт:** противоречащие утверждения сохраняются с источниками, не разрешаются произвольным выбором.
- **F — SLEEP:** derived результат доступен в отдельном режиме и не стирает raw; требуется для v1.1.
- **G — сбой:** crash до/после записи, индекса, checkpoint и publication → воспроизводимое восстановление без дублей.

Для **Memory v1.0** обязательны A–E и G в read-only маршруте без SLEEP. Для **v1.1** дополнительно F, полный recovery SLEEP и bounded доступ к derived представлениям.

## 4. C3 — отдельный ресурсный gate

Провести тесты на **10³ / 10⁴ / 10⁵ Events** с фиксированным генератором: шум, горячие Entity, поздние события, повторы, длительное поступление. Измерять `p50/p95/p99` write/retrieval, index lag, throughput, peak RSS, диск/Event, время cold/warm lookup, рестарт, backlog и качество Evidence Recall. Один и тот же workload сравнивать на PC и **Raspberry Pi 5 (8 GB)**. До прогона выбрать пороги и допустимые деградации; результаты G1 не переносить на C3 как SLO. При превышении бюджета сначала профилировать SQL планы, scans и размеры проекций, а не заменять backend.

## 5. Что считаем готовым

### Memory v1.0 — рабочий фундамент

Успешные gates 0–4, A–E/G и минимально необходимые C3 измерения. Система регистрирует и связывает raw Events, устойчиво организует эпизоды, находит ранние детали, собирает ограниченный контекст, различает сообщение/наблюдение/Claim/Knowledge и работает без LLM. Это **не** подтверждает автономное обучение или право автоматически менять Knowledge.

### Memory v1.1 — переработка опыта

Выполнен шаг 5, полный шаг 6 с F, проверены версии, checkpoints/replay и ресурсные пределы. Доступна bounded консолидация и проверяемые производные представления; автоматическая публикация подтверждённых знаний остаётся предметом отдельного lifecycle gate.

## 6. Порядок изменений и документация

Для каждого шага: **brief → frozen baseline → isolated/shadow implementation → positive/negative tests → comparison report → решение о внедрении → обновление архитектуры/ADR при изменении контрактов**. Результаты испытаний сохранять в [`docs/TESTING/Results`](../TESTING/Results/README.md); исследовательские гипотезы — в [`Research.md`](Research.md). Не менять `docs/project.json`, Stage status, Core authority и production routing «ради зелёного теста».

**Первое исполняемое задание:** [Stage 0 — Baseline & Remediation Brief](Memory_Stage0_Baseline_Remediation_Brief.md). Его исправления и испытания выполняются до перехода к контролируемому EXP-009. Миграция хранилищ и расширение режима записи требуют отдельного решения.
