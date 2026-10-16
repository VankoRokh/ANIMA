---
document_type: stage
status: Planned
updated: 2026-10-16
tags: [anima, roadmap, agent]
---

# Stage 4 — Agent

## Goal

Научить ANIMA превращать ограниченную задачу в последовательность действий, проверять результат и безопасно обрабатывать ошибку инструмента.

## Observable result

В sandbox ANIMA получает задачу, строит короткий план, вызывает ограниченный инструмент, проверяет фактический результат и завершает задачу определённым статусом.

## Required work

- [ ] Tool contract с явными аргументами и результатом.
- [ ] Минимальный planner/executor loop.
- [ ] Observation после каждого действия.
- [ ] Timeout/error/cancel.
- [ ] Dry-run или sandbox для опасных действий.
- [ ] Сохранение execution trace в память как опыт, но не как безусловную истину.

## Test scenarios

1. Успешная задача из нескольких шагов.
2. Неверный аргумент инструмента.
3. Timeout/отказ инструмента.
4. Прерывание между шагами и определённое состояние после restart.
5. Повтор команды не дублирует уже подтверждённое необратимое действие без явного разрешения.
6. План считается успешным только по observation результата, а не по факту вызова tool.

## Acceptance criteria

Минимум один законченный sandbox workflow проходит все success/failure/cancel сценарии и имеет полный trace plan → action → observation → result.

## Evidence to save

Полный trace успешного выполнения и один показательный failure/recovery scenario.
