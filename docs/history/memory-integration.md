# Memory Integration — от сырого Event к Foundation

**Роль:** хронология интеграции и судьбы решений. Исследование алгоритма, самостоятельный лабораторный PASS и включение в релиз — **разные** события.

## 1. Исходный baseline и вопрос извлечения

Stage 1 создал `EventLog`, SQLite `MemoryStore`, `LinkStore`, эпизодическое представление, Knowledge и `ContextBuilder`. Raw `events.jsonl` оставался первичным источником. Исследовательские проверки G1 и дальнейший EXP-009 показали риск потери деталей при сжатии и ограниченном контексте. Не считать G1 доказательством превосходства графовой архитектуры.

## 2. EXP-009 — выбор канала

На одном синтетическом корпусе и бюджете 10 элементов / 1200 символов варианты A/B/C/D дали:

| Вариант | Прямые Event-ID попадания | Достижимые через source links | Нецелевые Events |
| --- | ---: | ---: | ---: |
| A: Memory-only | 0/45 (по контракту) | 24/45 | 0 (не мера ложных Memory) |
| B: Event-only | **41/45** | **41/45** | 15 |
| C: Event+Memory flat | 40/45 | 40/45 | 15 |
| D: C + один source hop | 36/45 | **43/45** | 39 |

`43/45 reachable` **не равно** `43/45 displayed`: связанные события могли не попасть в ограниченный ответ. Два смысловых парафраза без лексического совпадения ни один вариант не решил. Выбрали raw `EventRetrieval` на SQLite FTS5 и **не** включили D в default, сохранив Memory и raw Event как два пути чтения. [Первичный результат EXP-009](../ROADMAP/Memory_EXP009_Retrieval_ABCD_Results.md) на `5d679e0a7ca9866270d6f13c02175cf7fa46dec0`.

## 3. Event Retrieval C3

В [реализации v1](../../anima/memory/event_retrieval.py) индекс хранит ID, байтовый offset/length, digest и курсор; `complete/partial/source_changed` задают честность выдачи. [C3-отчёт](../ROADMAP/Memory_Event_Retrieval_v1_Results.md) на `f27a6428e6b5b6cc26585d299def9305bd6a5e4d` подтвердил функциональный gate на Linux x86-64 и отдельные синтетические масштабы 10k/100k. Это не Raspberry Pi, power-loss и не SLA для всех модулей.

## 4. M0–M6-B2: рост полномочий без скрытого переноса

| Срез | Что проверено | Чего он не разрешает |
| --- | --- | --- |
| M0 | Два Python-процесса, raw Event, Memory links, EventRetrieval, bounded Context | Создание исполнимой Goal |
| M1 | Context перед отдельно заданной оператором typed Goal | Текст Memory не выдаёт authority |
| M2 | Реальный Godot, обычное исполнение и прерывания до/после эффекта | Универсальный SIGKILL/physical exactly-once |
| M3 | Read-only preview предложения | Создание Goal без approval |
| M4 | Явное первое host approval, одна unbound Goal | Binding или исполнение |
| M5 | Отдельный binding approval и новое зарегистрированное наблюдение | Исполнительный модуль |
| M6-A | Третье разрешение и одноразовый эффект старого тестового мира | Перенос capability в Godot |
| M6-B1 | New Godot lineage, `source/producer/epoch/revision`, явный mapping approval | Права на действие; 8/8 live, ноль эффектов |
| M6-B2 | Независимые target P2/P3-A и конкретная Godot operation | Глобальный firewall; CI 10/10, ноутбук 10/10, `true_sigkill_tested=false` |

Исходные протоколы и фактические ограничения сохранены в [архивной сводке интеграций](../TESTING/Laboratory_Integrations.md) и отчётах по каждому M-срезу. Отдельные approval, source authority и readback — системные, не производные из свободного текста.

## 5. Граница Foundation

Релиз включает `EventRetrieval`, полное проверяемое индексирование, ограниченный Memory Context и возможность точечного raw provenance. E1–E4, Stage 7 write/revision и M6-B2 как обязательный Godot runtime **не входят** в базовый профиль. Конкретные требования — в [контракте](../versions/v0.1/contract.md), включённые механизмы — в [архитектуре Memory](../system/memory-and-retrieval.md).

**Не доказано:** полнота смыслового поиска, идеальная сегментация эпизодов, production-допуск E4/L2, физически независимый source authentication. Для E4 сохранён `NO-GO` до отдельной приёмки.
