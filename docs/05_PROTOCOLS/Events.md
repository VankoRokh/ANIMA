---
document_type: reference
status: Reference
updated: 2026-10-12
tags: [anima]
---

# События и форматы хранения

Здесь описана фактическая схема 00.1-alpha. Строгий контракт, ID и версия схемы пока отсутствуют.

## Event

| Поле Python | Поле JSON | Значение |
|---|---|---|
| event_type | type | Строковое имя события |
| payload | payload | Данные события; для служебных событий None/null |
| timestamp | timestamp | datetime.now().isoformat(timespec="seconds") |

Время локальное, без UTC offset. Event не проверяет типы и не назначает event_id.

## Текущие события

| type | payload | Когда возникает |
|---|---|---|
| wake | null | После сохранения awake и увеличения сессии |
| user_input | {"text": "..."} | Один пользовательский ввод |
| sleep | null | Перед записью status: sleeping |

Пример сырого события — только синтетические данные:

```json
{"type":"user_input","payload":{"text":"Проверка ANIMA"},"timestamp":"2026-10-12T12:00:00"}
```

## Выбранное воспоминание

MemoryFilter создаёт другой формат:

```json
{"source":"user_input","timestamp":"2026-10-12T12:00:00","content":{"text":"Проверка ANIMA"}}
```

Записывается в memories.jsonl, только если payload.text после strip() не пуст. content сохраняет исходный payload, включая исходные пробелы.

## Состояние

| Поле | Значение/обновление |
|---|---|
| name | ANIMA |
| version | 00.1-alpha |
| status | created, awake или sleeping |
| session | 0 при создании; увеличивается в wake |
| created_at | Время создания состояния |
| last_wake | null до первого пробуждения, затем время |
| last_sleep | null до первого сна, затем время |
| events_processed | Общий счётчик всех обработанных событий |

state.json — один JSON-объект; журналы — JSONL, по одному объекту на строку. Последовательность: [Event Pipeline](../03_SOFTWARE/Event_Pipeline.md).

## Следующая версия контракта — Draft

Рассматриваем event_id, instance_id/source_node, schema_version, время с часовым поясом, связь воспоминания с событием и подтверждение обработки. Конкретная схема и миграция старых данных требуют ADR и проверок до распределённого обмена.

Не считать эти поля существующими. [Module Contracts](Module_Contracts.md).
