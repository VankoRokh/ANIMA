---
document_type: reference
status: Reference
updated: 2026-10-12
tags: [anima]
---

# Реестр модулей

Это канонический список компонентов ANIMA. ID сохраняется при переименовании; новый модуль получает новый ID. Реализация на одной плате или разделение на несколько узлов не меняет логическую ответственность.

**Решение** обозначает согласование направления: Accepted, Draft или Experiment. **Реализация** обозначает фактическую готовность: Planned, Prototype, Implemented, Tested, Stable или Deprecated. Accepted не означает готовый код. [Подробные правила](../09_OPERATIONS/Documentation_Rules.md).

Все существующие классы отмечены Prototype: один успешный сценарий не подтверждает устойчивость к сбоям. Выделенные будущие модули ещё не имеют исходного кода.

| ID | Модуль | Решение | Реализация | Точное описание |
|---|---|---|---|---|
| CORE-01 | Идентичность | Accepted | Prototype | [Описание](../02_ARCHITECTURE/Core.md#core-01) |
| CORE-02 | Состояние экземпляра | Accepted | Prototype | [Описание](../02_ARCHITECTURE/Core.md#core-02) |
| CORE-03 | События и EventBus | Accepted | Prototype | [Описание](../02_ARCHITECTURE/Core.md#core-03) |
| MEM-01 | Сырой журнал EventLog | Accepted | Prototype | [Описание](../02_ARCHITECTURE/Memory.md#mem-01) |
| MEM-02 | Фильтр MemoryFilter | Accepted | Prototype | [Описание](../02_ARCHITECTURE/Memory.md#mem-02) |
| MEM-03 | Хранилище MemoryStore | Accepted | Prototype | [Описание](../02_ARCHITECTURE/Memory.md#mem-03) |
| MEM-04 | Чтение EpisodicMemory | Accepted | Prototype | [Описание](../02_ARCHITECTURE/Memory.md#mem-04) |
| MEM-05 | Рабочая память и контекст | Draft | Planned | [Описание](../02_ARCHITECTURE/Memory.md#mem-05) |
| MEM-06 | Семантическая память | Draft | Planned | [Описание](../02_ARCHITECTURE/Memory.md#mem-06) |
| MEM-07 | Извлечение памяти | Draft | Planned | [Описание](../02_ARCHITECTURE/Memory.md#mem-07) |
| MEM-08 | Оценка важности | Experiment | Planned | [Описание](../02_ARCHITECTURE/Memory.md#mem-08) |
| MEM-09 | Забывание и сжатие | Draft | Planned | [Описание](../02_ARCHITECTURE/Memory.md#mem-09) |
| COG-01 | Fast | Accepted | Planned | [Описание](../02_ARCHITECTURE/Fast_Deep.md#cog-01) |
| COG-02 | Deep | Accepted | Planned | [Описание](../02_ARCHITECTURE/Fast_Deep.md#cog-02) |
| COG-03 | Внутренние эмоциональные оценки | Accepted | Planned | [Описание](../02_ARCHITECTURE/Emotions.md#cog-03) |
| COG-04 | Внешнее эмоциональное выражение | Accepted | Planned | [Описание](../02_ARCHITECTURE/Emotions.md#cog-04) |
| COG-05 | Цели и мотивация | Draft | Planned | [Описание](../02_ARCHITECTURE/Goals.md#cog-05) |
| SLP-01 | Оркестратор сна | Draft | Planned | [Описание](../02_ARCHITECTURE/Sleep.md#slp-01) |
| SLP-02 | Консолидация памяти | Draft | Planned | [Описание](../02_ARCHITECTURE/Sleep.md#slp-02) |
| SLP-03 | Адаптация Fast | Experiment | Planned | [Описание](../02_ARCHITECTURE/Sleep.md#slp-03) |
| IF-01 | Командный интерфейс | Accepted | Prototype | [Описание](../02_ARCHITECTURE/Interfaces.md#if-01) |
| IF-02 | Голосовой интерфейс | Draft | Planned | [Описание](../02_ARCHITECTURE/Interfaces.md#if-02) |
| IF-03 | Инструменты и действия | Draft | Planned | [Описание](../02_ARCHITECTURE/Interfaces.md#if-03) |
| HW-01 | Основной вычислитель Core / Deep | Accepted | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-01) |
| HW-02 | Переносимый Fast-узел | Accepted | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-02) |
| HW-03 | Сменный носитель экземпляра | Accepted | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-03) |
| HW-04 | Питание и резерв | Draft | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-04) |
| HW-05 | Зрение | Draft | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-05) |
| HW-06 | Звуковая периферия | Draft | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-06) |
| HW-07 | Движение и ориентация | Draft | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-07) |
| HW-08 | Охлаждение и корпус | Draft | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-08) |
| HW-09 | Соединения и обмен между узлами | Draft | Planned | [Описание](../04_HARDWARE/Hardware_Architecture.md#hw-09) |

## Прочитать связи

[System Map](System_Map.md) показывает общий поток, [System Architecture](../02_ARCHITECTURE/System_Architecture.md) — фактическую и целевую структуру. Операционный статус работы находится в [Project Status](Project_Status.md).

Принятое направление может иметь черновые детали интерфейса. Это отмечается внутри карточки; оно не означает, что конкретная плата, модель или формула утверждена.
