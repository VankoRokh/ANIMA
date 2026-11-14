# EXP-009 и Event Retrieval v1

## Исследовательский вопрос

Сохраняются ли конкретные исходные детали при поиске через сжатые `Memory` и ограниченный `Context`? Это вопрос **доступности первичного опыта**, а не доказательства правдивости Events.

## Контролируемое сравнение A/B/C/D

[Первичный результат](../ROADMAP/Memory_EXP009_Retrieval_ABCD_Results.md), **11 ноября 2026**, SHA `5d679e0a7ca9866270d6f13c02175cf7fa46dec0`, [CI](https://github.com/VankoRokh/ANIMA/actions/runs/43086187762). 20 синтетических `conversation.user` Events, 5 Memories, 20 source links, 32 запроса, 4 стратегии и 4 бюджета (512 сравнений). Проверенные бюджеты и gold определены до сравнения, источником ID служат Events реального Runtime.

| Метод | Direct Event-ID hits | Reachable через Memory links | Строгие нецелевые Events |
| --- | ---: | ---: | ---: |
| A — Memory-only | 0/45 по определению | 24/45 | 0 — **не мера качества Memory** |
| B — Event-only | **41/45** | **41/45** | 15 |
| C — Event+Memory flat | 40/45 | 40/45 | 15 |
| D — C + один source hop | 36/45 | **43/45** | 39 |

Таблица — при **10 items / 1200 chars**; знаменатель 45 — сумма gold попаданий, а не 45 различных Events. `reachable` **не равно** `displayed`: прямое свидетельство могло не войти в бюджет. Два смысловых парафраза без лексического пересечения не были найдены ни одним вариантом. Вывод: **B** выбран как отдельный raw read path, а `Memory-only` сохранён отдельно; D не принят по умолчанию из-за загрязнения контекста.

## Реализованный Event Retrieval v1

[Исполняемый `EventRetrieval`](../../anima/memory/event_retrieval.py) индексирует исходный `events.jsonl` в производный SQLite FTS5 `event_index.db`, сохраняет `event_id`, raw offset/length/SHA256 и прогресс. `complete/partial/source_changed` не дают объявлять `no_match` при неполной истории. `get(Event ID)` перепроверяет raw bytes; `events_for_memory` следует существующим явным source links, а не делает общий graph walk.

[Функциональный gate и PC C3](../ROADMAP/Memory_Event_Retrieval_v1_Results.md), SHA `f27a6428e6b5b6cc26585d299def9305bd6a5e4d`, [CI Python 3.12/3.13/3.14](https://github.com/VankoRokh/ANIMA/actions/runs/43091261376): профильные 79 PASS, полные 1506 PASS для каждого interpreter. Синтетический набор 10 000 / 100 000 Events дал `get` p95 **0,8750 / 2,0641 мс** и FTS p95 **1,0846 / 2,2652 мс**. Это **не SLA**, не real power-loss и не Pi; рабочая память измерена для целого benchmark-процесса.

## Решение и применение

**В Foundation подключён** EventRetrieval для `search_events` и exact provenance, а `context` использует отдельные Memory Retrieval и ContextBuilder. На `release_v01` при неполном индексе применяется fail-closed. [Архитектура и фактические лимиты](../system/memory-and-retrieval.md). Это факт включения в конкретную сборку, **не** принятие универсального Memory v1.0/1.1.

**Открыто:** лексическая слепота к парафразам, ограниченность репрезентативности корпуса, стоимость полного переиндексирования после source change, реальная latency на больших живых потоках, provenance across transformations и будущая политика объединения raw/Memory контекста. См. [историю интеграции](../history/memory-integration.md) и [Memory v1 Roadmap как исторический источник](../ROADMAP/Memory_Architecture_v1_Roadmap.md).
