# ANIMA — Event Retrieval v1: production read path and acceptance

**Рабочая ветка:** `experiment/core-memory-information-baseline`.  
**Дата:** 2026-11-11.  
**Статус:** реализация внесена, приёмка CI ожидается (не объявлять VERIFIED до результатов).  
**Основание:** [EXP-009 A/B/C/D Results](Memory_EXP009_Retrieval_ABCD_Results.md), [Memory Architecture Roadmap](Memory_Architecture_v1_Roadmap.md).

## Решение о границах

Вместо замены существующего `RetrievalEngine` вводится отдельная **EventRetrieval** — read-only по смыслу источник опыта, с **производным** индексом `event_index.db`. Компонент не владеет `EventLog` и ничего не записывает в `events.jsonl`; он записывает только свою FTS5 проекцию. Первичные события доступны через их оригинальный `Event ID`, точный `raw_offset` и `raw_length`. Каждая выдаваемая запись перечитывается из первичного JSONL и сверяется с SHA256 указанного диапазона.

**Предоставляемый контракт:**

- `build_core(..., enable_event_retrieval=True).event_retrieval` — явное подключение без изменения поведения `Runtime`, `FAST`, `DEEP` и `ContextBuilder`.
- `status()` возвращает `complete`, `partial`, `source_changed` с объёмом проиндексированного префикса и оставшейся части журнала. **`partial + no_match` не означает отсутствие факта**.
- `sync(max_events=256, max_bytes=2000000)` обрабатывает ограниченный префикс, не включает незавершённую строку, не допускает дублирующихся ID. Данные и checkpoint фиксируются **одной SQLite-транзакцией**.
- `get(event_id)` делает точечный SQLite lookup и проверяет исходные байты; `search(query, top_k, event_types, sources)` использует FTS5, тип/источник фильтруются **до** LIMIT; `events_for_memory(memory_id)` идёт только по существующим `memory_sources`.
- `ProvenanceResolver(..., event_retrieval=index)` — явный быстрый путь для уже существующих Memory/Knowledge provenance views без полного `EventLog.load_events()`; по умолчанию сохраняется прежний режим. Если индекс неполон или повреждён, provenance отказывает, а не выдаёт фиктивное доказательство.
- `rebuild()` явно удаляет **только производную** SQLite-проекцию, оставляя EventLog нетронутым.
- По умолчанию чтение требует `complete`; иначе выдаёт ошибку. Ограниченное `require_complete=False` допустимо для диагностики только при `partial`, с явно возвращённым coverage; `source_changed` всегда блокирует чтение.

**Индексируются** типизированные поля `id/type/source/timestamp/session_id` и текст: для payload с `text` — именно это поле, иначе каноническая JSON-проекция payload. `system.wake/sleep` без содержимого остаются адресуемыми по ID, но не становятся полнотекстовыми Evidence. Запись `world.observation` из legacy dispatcher — **проекция CoreIngress**, а не новое независимое доверенное наблюдение; право оценивать её истинность остаётся у Core/Stage 7.

## Защита и ограничения

1. **Не индексируем повреждённые записи.** Полная строка с невалидным Event rollback-ит транзакцию; обрезанная последняя строка остаётся `partial` до дополнения. При изменении размера, идентичности файла или контрольных head/tail сегментов нужен явно вызванный `rebuild()`. При изменении размера без обновления индекса read-mode — `partial`.
2. **Захват:** SQLite lock и atomic cursor защищают одновременные `sync` в одной БД от дублей; тесты на отдельные процессы и долговечность потери питания — часть будущего C3 gate. Это **не** делает многопроцессную дозапись в JSONL безопасной.
3. **Стоимость:** обычное чтение не перечитывает историю; `status()` использует свойства файла и SQLite, `get()` читает конкретный диапазон, `search()` работает через индекс. `sync()` читает только необработанный хвост и небольшой якорь префикса.
4. **Не криптографическая защита от подмены целого файла.** Якоря фиксируют начало/конец проиндексированного префикса, metadata — обычные изменения файла, каждое возвращённое свидетельство подтверждается собственным SHA256. Неохваченная внутренняя мутация многогигабайтного префикса может остаться невидимой до запроса затронутой записи или полного rebuild/audit. Для hostile tampering нужен отдельный signed hash chain.
5. **Ресурсы:** ограничение одной JSONL строки — 1 МБ; передача больших payload (видео, raw аудио) не является задачей v1. Буферизация индекса обрабатывается ограниченным `max_events/max_bytes`; C3 измерит цену на 10³/10⁴/10⁵ Events и на Raspberry Pi.
6. **Отложено намеренно:** автоматический sync при каждом Runtime event (не добавлять непроверенный второй writer), объединённый ContextBuilder, semantic embeddings и multi-hop reasoning. Их подключение является отдельным integration gate. Нынешний сервис предоставляет read API, не заменяет FAST/DEEP retrieval.

## Gate v1

- Сохранение, поиск ID/текста, typed filter и ссылки на Memory работают без доступа к LLM.
- После restart/double-sync нет дублей; `cursor` и FTS rows совпадают после crash внутри транзакции.
- Недозаписанный хвост не создаёт ложного `complete`; повреждение, ротация и truncation явно останавливают чтение до rebuild.
- Index не мутирует `EventLog`, `MemoryStore` или Core state. Отдельная SQLite-база может быть пересоздана без потери истории.
- Профильные тесты: `tests/test_event_retrieval.py`. Общая регрессия, `scripts/check.sh`, import smoke на Python 3.12–3.14 через GitHub Actions.
- **Приёмка performance** не выводится из correctness-тестов: C3 запускается отдельно на PC/Raspberry Pi и сохраняет p50/p95/p99, RSS, индексное отставание, I/O и восстановление.

## C3 — воспроизводимый PC-baseline

Дополнительно подготовлен [C3 event retrieval workload](../../labs/exp009/event_retrieval_c3.py) с [коротким smoke-тестом](../../tests/test_event_retrieval_c3.py). GitHub Actions на Python 3.14 выполняет **10 000 и 100 000 Events** после полной регрессии и сохраняет JSON c измерениями append/index, p50/p95/p99 по точечному и FTS чтению, задержку дозаписи, объём SQLite/JSONL и peak process RSS.

```bash
out="$(mktemp -d)"
python -m labs.exp009.event_retrieval_c3 --events 10000 --report-dir "$out"
# Тяжёлый отдельный профиль:
python -m labs.exp009.event_retrieval_c3 --events 100000 --report-dir "$out"
```

**Scope:** отдельный EventLog + derived FTS5. В отличие от C2-Runtime, нет EventProcessingCoordinator, Memory generation и Core world observations. Это измерение конкретного search/index компонента, **не** сквозной производительности ANIMA. Результаты CI runners нельзя напрямую переносить на Raspberry Pi. Во время benchmark результаты не записываются в production-память.

## Следующий шаг после correctness gate

Сопоставить EventRetrieval с Memory/Knowledge через бюджетированный **двухканальный Context Builder** (выбирающий Event и Memory отдельно), не превращая их в один список без независимых квот. Перед этим провести C3 на ≥10³ и ≥10⁴ событий и определить acceptable lag; 10⁵ — отдельный крупный профиль. `Stage 7` authority и `Knowledge` admission не менять на этом этапе.
