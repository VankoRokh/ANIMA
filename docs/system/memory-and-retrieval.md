# Memory, Knowledge и Retrieval

**Назначение:** сохранить происхождение информации при преобразовании raw Events в Memory и в ограниченный контекст. `EventLog` и производные структуры выполняют разные роли.

## Запись

```text
Runtime.user_input("report")
 → conversation.user → events.jsonl (EventLog)
 → EventProcessingCoordinator
 → MemoryProcessor + RuleBasedComposer
 → MemoryStore / LinkStore (SQLite)
 → source_events и provenance
```

Событие фиксирует факт приёма сообщения; его содержание не считается доказанным состоянием мира. `Memory` — производное представление одного или нескольких Events, которое может опустить детали. `Entity` и `Relation` — структурные связи. `Knowledge` имеет отдельные статусы `provisional`, `confirmed`, `challenged`, `superseded`, `rejected`; статус не повышается автоматически из пользовательского текста.

**Первоисточник** для raw Events — `events.jsonl`; `MemoryStore` и `LinkStore` владеют производными записями и связями. Typed `Core Event` сначала принадлежит `core_state.db` и только потом может появиться в legacy raw-журнале как downstream-проекция. [Разница источников](events-and-authority.md).

## Два пути чтения

| Запрос v0.1 | Источник | Реализация | Ограничение |
| --- | --- | --- | --- |
| `search_events` | Исходные Events | [`EventRetrieval`](../../anima/memory/event_retrieval.py), SQLite FTS5 | `top_k=5`; требуется полный индекс |
| `context` | Производные Memory | [`RetrievalEngine`](../../anima/memory/retrieval.py) → [`ContextBuilder`](../../anima/memory/context_builder.py) | `kinds=("memory",)`, `max_items=4`, `max_chars=900`; не вызывает FAST-модель |
| `EventRetrieval.get(event_id)` | Raw Event по ID | EventRetrieval и проверка исходных байтов | Внутренний API, не отдельная команда JSONL |

`EventRetrieval` хранит в `event_index.db` **восстанавливаемый** индекс: `raw_offset`, `raw_length`, `raw_sha256` и курсор. При чтении возвращает исходные байты после проверки SHA-256. `partial` означает незавершённый индекс; `source_changed` требует явного восстановления индекса. Нельзя выдавать отрицательный поиск без подтверждённой полноты.

`ContextBuilder` ограничивает представление для потребителя, не делает итогового вывода и не заменяет первичный Event. Присутствие метки consumer `FAST` в v0.1 — политика построения контекста, а не inference.

## Восстановление, ограничения и проверка

Индекс EventRetrieval можно явно перестроить из неизменённого журнала; замена исходника требует сверки, а не молчаливого чтения старого индекса. Для восстановления Memory и её source links необходимо сохранить весь экземпляр. Между JSONL и SQLite нет одной физической транзакции.

Группировка `RuleBasedComposer` и эвристические ассоциации могут связывать лишние события либо терять значимые слова в summary; наличие FTS5 не решает семантический поиск без лексического пересечения. EXP-009 обнаружил ограничения обхода графа и прямого поиска: это причина сохранения двух путей, а не доказательство универсального превосходства индекса.

**История и основания:** [Stage 1](../history/stages.md#stage-1), [EXP-009 / Event Retrieval](../ROADMAP/Memory_EXP009_Retrieval_ABCD_Results.md), [C3](../ROADMAP/Memory_Event_Retrieval_v1_Results.md). **Код:** [event_log.py](../../anima/memory/event_log.py), [event_processing.py](../../anima/memory/event_processing.py), [processor.py](../../anima/memory/processor.py), [memory_store.py](../../anima/memory/memory_store.py), [link_store.py](../../anima/memory/link_store.py), [provenance.py](../../anima/memory/provenance.py). **Проверки:** [test_event_retrieval.py](../../tests/test_event_retrieval.py), [test_release_v01.py](../../tests/test_release_v01.py), [TV-0014](../TESTING/Results/TV-0014.md).
