# Когнитивная память: от события до контекста

**Статус:** слой Event/Memory/Knowledge и детерминированный Retrieval реализованы; opt-in `EventRetrieval` используется в релизном профиле. Продвинутый семантический Knowledge lifecycle и новые алгоритмы группировки не считаются завершёнными.

## Разделение данных

```text
source → Event (первичный источник, журнал)
            ↓
      MemoryProcessor
      ├─ selection
      ├─ association
      └─ composition
            ↓
   Memory / source links
      ├─ Entity / Relation
      └─ Knowledge (отдельный статус и provenance)
            ↓
      RetrievalEngine
            ↓
       ContextBuilder
            ↓
     FAST / DEEP consumer
```

**Event** фиксирует получение информации или наблюдение; его payload и источник сохраняются в `events.jsonl`. **Memory** — производное компактное представление одного или связанных событий. **Knowledge** — системно поддерживаемое утверждение с собственным жизненным циклом; нельзя автоматически объявлять его `confirmed` из текста пользователя. **Entity** и **Relation** связывают объекты без замены первичных свидетельств.

Существующие Knowledge statuses: `provisional`, `confirmed`, `challenged`, `superseded`, `rejected`. Они не равны будущим результатам `CONTENT/REVISION` Stage 7, для которых требуется отдельное отображение правил.

## Чтение и сохранение источников

`EventLog` — authoritative raw журнал; `MemoryStore`/`LinkStore` — SQLite структурированных представлений. `MemoryProcessor` решает, создавать ли эпизод, обновлять или связывать с другим; текущая ассоциация основана на детерминированных оценках и может ошибочно соединять похожие сообщения.

`RetrievalEngine` использует фильтры, FTS5, Entity/Relation и scoring. `ContextBuilder` ограничивает число и размер объектов для конкретного потребителя. Выбранная summary может опустить значение, которое по-прежнему есть в raw Event.

`EventRetrieval` — производный SQLite FTS5 индекс над `events.jsonl`, позволяющий точно получать исходные Events и сокращать повторные сканирования при наличии полного индекса. Его состояния `complete / partial / source_changed` принципиальны: частичная индексация **не** позволяет выдавать «не найдено» за доказанное отсутствие информации. При повреждении или смене источника индекс требует контролируемого восстановления.

## Кто чем владеет

- Core/Runtime устанавливают доверие к источникам и возможным действиям, Memory этого не делает.
- Компоновщик не превращает текст в объективную истину.
- FAST/DEEP имеют read-only границы и не меняют raw Events/Knowledge напрямую.
- Провенанс должен позволять вернуться от Memory к исходному Event.
- Эпизодическая Memory **не обязана** отражать каждое несущественное событие отдельной строкой. Но raw история и ссылки на использованные источники не должны исчезать.

## Главные файлы и проверки

| Узел | Код |
| --- | --- |
| Raw журнал | [event_log.py](../../anima/memory/event_log.py) |
| Эпизоды и SQLite | [processor.py](../../anima/memory/processor.py), [memory_store.py](../../anima/memory/memory_store.py) |
| Knowledge и связи | [knowledge.py](../../anima/memory/knowledge.py), [link_store.py](../../anima/memory/link_store.py) |
| Поиск / контекст | [retrieval.py](../../anima/memory/retrieval.py), [context_builder.py](../../anima/memory/context_builder.py) |
| Провенанс / индекс | [provenance.py](../../anima/memory/provenance.py), [event_retrieval.py](../../anima/memory/event_retrieval.py) |

**Исторический результат:** [Stage 1](../STAGES/01_Cognitive_Memory.md), [TV-0014](../TESTING/Results/TV-0014.md), [TV-0015](../TESTING/Results/TV-0015.md). **Развитие:** [Event Retrieval v1](../ROADMAP/Memory_Event_Retrieval_v1_Results.md), [исследования Memory](../RESEARCH/README.md), [ADR-005](../DECISIONS/README.md#adr-005).

## Известные ограничения

Краткие summaries могут терять детали, группировка эпизодов может давать ложные объединения, а поиск зависит от качества индекса, словаря и бюджетов. Зелёный тест на 128 однотипных отчётах не доказывает полноценную Memory intelligence. Эксперименты Shadow Encoding, graph-based retrieval и метапамять не заменяют работающий слой до отдельного решения об интеграции.
