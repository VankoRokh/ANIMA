# SLEEP и восстановление

**Назначение:** прерываемая пакетная обработка источников с checkpoint, provenance и явными бюджетами. Это не отдельная личность и не синоним перевода Runtime в состояние `sleeping`.

## Два значения сна

| Операция | Что выполняет | В штатном v0.1 |
| --- | --- | --- |
| `Runtime.sleep()` | Фиксирует `system.sleep`, обрабатывает Event и переводит `AnimaState` в `sleeping` | Да, при нормальном закрытии |
| `SleepRuntimeIntegration` + `process_sleep_work()` | Управляет `SleepJob`, `WorkItem`, chunk, checkpoint, DerivedResult | **Нет**; отдельно инъецируемый модуль |

В `build_core` для v0.1 `sleep_runtime=None`: наличие метода `sleep()` не означает фоновый запуск консолидации, DEEP или обучения модели.

## Конвейер SLEEP WorkItem

```text
SourceRef → SleepSelector (eligibility / priority / budget)
 → SleepJob → WorkItem (processor + версия)
 → SleepChunkExecutor (bounded chunks)
 → checkpoint и DerivedResult (provenance, source identity)
 → validate / resume / pause / complete
```

`SourceRef` фиксирует ссылку на исходные данные, не создаёт второй authoritative источник. Процессоры заменяемы; в базовой лаборатории `DeterministicTextConsolidationProcessor` создаёт ограниченный текстовый результат, не универсальную семантическую память.

`SleepJob` и `WorkItem` хранятся долговечно в `sleep.db`; завершённый chunk не должен выполняться повторно после reopen. WorkItems выбираются с учётом ограничений допуска, количества, времени и ресурсов. Отдельные DerivedResults хранят происхождение, идентичность операции и версию процессора.

## Границы восстановления

`Runtime._ensure_recovered()` вызывает `sleep_runtime.recover()` только при подключённом модуле. В состоянии `running` после сбоя нельзя считать WorkItem завершённым без проверки. Состояния выполнения внешней операции `prepared/executing/uncertain` нельзя безусловно смешивать со SLEEP checkpoint. Разные SQLite-хранилища не имеют общей физической транзакции.

Синтетический источник 10 GiB из Stage 3 проверял логику chunking и resume, а не обработку реального видео объёмом 10 GiB. Расширенная «переработка во сне» и метапамять остаются исследовательскими направлениями.

**Код:** [contracts.py](../../anima/sleep/contracts.py), [store.py](../../anima/sleep/store.py), [selection.py](../../anima/sleep/selection.py), [execution.py](../../anima/sleep/execution.py), [recovery.py](../../anima/sleep/recovery.py), [runtime_integration.py](../../anima/sleep/runtime_integration.py), [task_lifecycle.py](../../anima/sleep/task_lifecycle.py). **Проверки:** [test_stage6_sleep_lifecycle.py](../../tests/test_stage6_sleep_lifecycle.py), [TV-0030](../TESTING/Results/TV-0030.md), [TV-0048](../TESTING/Results/TV-0048.md). **История:** [Stage 3](../history/stages.md#stage-3), [Stage 6](../history/stages.md#stage-6).
