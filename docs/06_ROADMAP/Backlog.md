---
document_type: reference
status: Reference
updated: 2026-10-16
tags: [anima, roadmap]
---

# Очередь работы

Backlog содержит **только ещё не завершённую работу и отложенные вопросы**. История выполненных SW/D0 задач остаётся в Git и результатах завершённых Stage.

## Сейчас — D1 Runtime, Tests & Observability

| ID | Задача | Готово, когда |
|---|---|---|
| D1-01 | Runtime/controller | жизненный цикл запускается без зависимости от CLI |
| D1-02 | Headless scenario runner | тестовый сценарий выполняется без `input()` и возвращает structured result |
| D1-03 | Diagnostic snapshot/trace | ключевые состояния и переходы доступны машинно и человеку |
| D1-04 | Isolated test harness | все сценарии используют временный `ANIMA_DATA_DIR` |
| D1-05 | Stage 0 regression suite | ключевые foundation-сценарии запускаются одной командой |
| D1-06 | Test process output | процесс теста наблюдаем без чтения внутренних файлов вручную |
| D1-07 | Final D1 validation | CLI/headless эквивалентность и regression evidence сохранены |

## Следом — Stage 1 Memory

- event/episode IDs и provenance;
- deterministic retrieval baseline;
- working-context budget;
- benchmark corpus и query set;
- metadata/importance baseline;
- duplicate/conflict rules;
- recovery/regression.

## Отложенные исследования

| Направление | Когда возвращаемся |
|---|---|
| LLM/Deep model | после появления baseline, test harness и конкретной задачи, где модель даёт измеримое преимущество |
| GUI debug window | когда structured trace/CLI перестанут обеспечивать достаточную наблюдаемость |
| Embeddings/vector DB | если deterministic retrieval перестанет удовлетворять benchmark Stage 1 |
| Обучение Fast | отдельный EXP-002 после работоспособного Sleep pipeline |
| CM5/accelerator | после Stage 5 и измерения bottlenecks ноутбука |
| Полный корпус/череп | после доказанного cyberdeck и модульных периферийных прототипов |
| Автономные приводы | после module contracts, diagnostics и safety loop |
| Site/docs generator | только если ручная Markdown-навигация реально станет узким местом |

## Правило приоритета

Новая идея попадает в текущий Stage только если без неё невозможно получить или проверить его observable result. В остальных случаях она фиксируется здесь или как Experiment и не меняет текущий порядок разработки.
