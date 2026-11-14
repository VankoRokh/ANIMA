# SLEEP: программный сон, консолидация и восстановление

**Статус:** базовый механизм Stage 3 реализован; связь с persistent Tasks подтверждена Stage 6. Расширенные ночные анализаторы, метапамять и обучение моделей не являются частью базового SLEEP.

## Зачем нужен отдельный слой

SLEEP — режим **управления ограниченной работой**, а не ещё одна LLM. Он позволяет обрабатывать большие объёмы данных по частям, прекращать работу на безопасной границе и продолжать после прерывания. Источник данных остаётся у владельца Event/Memory/Knowledge/Asset; оркестратор хранит ссылки, а не копии сырого массива.

```text
SourceRef + выбранная задача
        ↓
SleepSelector (eligibility / priority / budget)
        ↓
SleepJob → WorkItem (processor / version)
        ↓
SleepChunkExecutor → checkpoint + local result
        ↓
DerivedResult (provenance, authority, version)
        ↓
Проверка → продолжение / пауза / завершение
```

## Механизмы

- `SleepJob` и `WorkItem` хранятся в `sleep.db` с жизненным циклом и историей переходов.
- `SleepSelector` формирует детерминированный порядок из допущенных источников с учётом приоритета, стоимости, максимального числа задач и бюджета.
- `SleepChunkExecutor` фиксирует checkpoint **после** завершённого chunk; процесс восстановления не должен запускать зафиксированный chunk повторно.
- Заменяемые processors отделены от расписания; `DeterministicTextConsolidationProcessor` предоставляет базовый ограниченный текстовый результат.
- `DerivedResultRepository` сохраняет происхождение, идентичность операции и целостность производной записи.
- `SleepObservability` предоставляет историю, статус, обработанное количество, причину остановки и ресурсные измерения.

В Stage 6 появилось долговечное `Task ↔ Goal ↔ SleepJob` соответствие; Sleep не должен скрыто завершать уже произошедшее внешнее действие или запускаться на неопределённой исполнительной границе (`prepared/executing/uncertain`).

## Восстановление и ограничения

В режиме работы `running` после аварийного процесса требуется явная recovery-процедура; автоматическое признание работы успешно завершённой недопустимо. Состояния внешнего действия и Sleep checkpoint **не являются** единой транзакцией, если находятся в разных SQLite. Безопасность поддерживается фиксированными идентификаторами, идемпотентностью и восстановлением, а не ложной гарантией атомарности между БД.

Synthetic 10 GiB workload демонстрирует работу по логическим chunks, **не** реальную обработку видеофайла такого объёма. SLEEP не доказывает глубокой самостоятельной переработки знаний.

## Код и доказательства

[contracts.py](../../anima/sleep/contracts.py), [store.py](../../anima/sleep/store.py), [selection.py](../../anima/sleep/selection.py), [execution.py](../../anima/sleep/execution.py), [recovery.py](../../anima/sleep/recovery.py), [text_consolidation.py](../../anima/sleep/text_consolidation.py), [task_lifecycle.py](../../anima/sleep/task_lifecycle.py).  
**Исторические проверки:** [Stage 3](../STAGES/03_Sleep.md), [TV-0030](../TESTING/Results/TV-0030.md), [TV-0048](../TESTING/Results/TV-0048.md), [ADR-007](../DECISIONS/README.md#adr-007).
