---
document_type: stage
status: Planned
updated: 2026-10-16
tags: [anima, roadmap, sleep]
---

# Stage 3 — Sleep

## Goal

Добавить прерываемую и воспроизводимую консолидацию опыта, которая улучшает структуру памяти без потери происхождения и неконтролируемого размножения выводов.

## Observable result

Sleep job можно запустить, прервать, продолжить и повторить; итог остаётся валидным, provenance сохраняется, а ресурсная стоимость измерена.

## Required work

- [ ] Sleep job lifecycle: queued/running/checkpointed/interrupted/complete/failed.
- [ ] Checkpoint/resume.
- [ ] Детерминированная первая версия консолидации без обязательной LLM.
- [ ] История преобразований и source links.
- [ ] Правила idempotency/deduplication.
- [ ] Resource metrics.
- [ ] Только после baseline — адаптер Deep/LLM как сравниваемый вариант.
- [ ] EXP-002 по адаптации Fast остаётся отдельным экспериментом.

## Test scenarios

1. Полный запуск и запуск с прерыванием на нескольких checkpoints дают эквивалентный допустимый итог.
2. Повторная обработка тех же данных не создаёт бесконечные дубликаты.
3. Любой итоговый summary/derived record ведёт к исходным эпизодам.
4. Ошибка посередине не повреждает уже валидные данные.
5. Измеряются elapsed time и RAM; при наличии модели — также model load/inference cost.
6. Regression Stage 1 проходит после консолидации.

## Acceptance criteria

Resume работает после каждого контрольного checkpoint; provenance не теряется; повторный запуск идемпотентен в заданных пределах; ресурсный профиль измерен и документирован.

## Evidence to save

Interrupted/resumed trace, сравнение результатов повторных запусков и resource profile baseline vs Deep adapter, если Deep уже вводится.
