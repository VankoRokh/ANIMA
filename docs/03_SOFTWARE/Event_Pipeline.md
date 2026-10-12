---
document_type: reference
status: Reference
updated: 2026-10-12
tags: [anima]
---

# Текущий конвейер событий

Исходный код: [main.py](../../main.py), EventBus и модули памяти. Этот порядок описывает реальную реализацию 00.1-alpha.

## Порядок обработки

```mermaid
flowchart TD
    Q["EventBus.next_event"] --> L["EventLog.write"]
    L --> F{"Непустой user_input?"}
    F -->|Да| B["MemoryFilter.create_memory"]
    B --> M["MemoryStore.write"]
    M --> S["AnimaState.register_event"]
    F -->|Нет| S
    S --> N{"Есть следующее событие?"}
    N -->|Да| Q
    N -->|Нет| E["Возврат в main"]
```

Каждое вычитанное событие сначала пишется в events.jsonl. Только выбранное событие дополнительно пишется в memories.jsonl. Счётчик events_processed увеличивается после успешного завершения записей.

## Сессия

1. Создаются объекты хранения; AnimaState загружает или создаёт state.json.
2. wake() сохраняет awake, увеличивает session и обновляет last_wake.
3. Событие wake передаётся через конвейер.
4. CLI показывает состояние и последние сырые события.
5. Одна строка пользователя становится user_input; она проходит через конвейер.
6. Enter создаёт событие sleep; после его обработки AnimaState.sleep() сохраняет sleeping.
7. Процесс завершается.

Даты не имеют часового пояса. События разных запусков не имеют уникального ID.

## Форматы

| Хранилище | Поля | Содержание |
|---|---|---|
| events.jsonl | type, payload, timestamp | Все обработанные события |
| memories.jsonl | source, content, timestamp | Непустой пользовательский ввод |
| state.json | name, version, status, session и другие | Состояние экземпляра |

[Events](../05_PROTOCOLS/Events.md) содержит точную схему.

## Сбой между операциями

Записи в journal, selected memory и state не образуют единую транзакцию. Ошибка после journal может оставить событие в журнале без увеличения счётчика или выбранной записи. Очередь уже вычитана; автоматического повтора нет.

Повторное исполнение без ID может создать дубликат. Решение требует отдельного изменения и проверок, оно не включено в документационную работу.

## Известное несоответствие чтения

EpisodicMemory загружает events.jsonl, поэтому надписи о memories в CLI не отражают выбранный опыт. Просто поменять путь нельзя: main.py читает type/payload, а memories.jsonl содержит source/content.

Следующее исправление: SW-01 в [Backlog](../06_ROADMAP/Backlog.md). Подсистемы: [Core](../02_ARCHITECTURE/Core.md), [Memory](../02_ARCHITECTURE/Memory.md).
