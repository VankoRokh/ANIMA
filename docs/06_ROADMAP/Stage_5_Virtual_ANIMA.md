---
document_type: stage
status: Planned
updated: 2026-10-16
tags: [anima, roadmap, virtual]
---

# Stage 5 — Virtual ANIMA

## Goal

Получить длительно работающий локальный прототип на обычном ПК/VM и измерить реальные пределы, прежде чем покупать специальное железо.

## Observable result

ANIMA проходит многократные wake/sleep/action cycles, переживает рестарты и восстановление, а её CPU/RAM/storage/latency profile известен.

## Required work

- [ ] Background/service lifecycle.
- [ ] Long-run scenario с автоматическим сбором метрик.
- [ ] Ограничение роста журналов/памяти.
- [ ] Reboot/restart/recovery scenarios.
- [ ] Развёртывание на второй чистой установке.
- [ ] Фиксация software/model versions.
- [ ] Реальная независимая резервная копия тестового экземпляра.

## Test scenarios

1. Длительный прогон с множеством жизненных циклов без ручного вмешательства.
2. Плановый restart и аварийное завершение между циклами.
3. Restore на второй установке.
4. Наблюдение роста RAM/storage во времени.
5. Один и тот же benchmark до и после long-run не показывает необъяснимой регрессии.

## Acceptance criteria

Перед финальной валидацией задаётся целевая длительность (ориентир — не менее 24 часов суммарной работы или эквивалентное число циклов). Система завершает её без повреждения данных; resource profile и точки насыщения измерены; перенос на вторую установку подтверждён.

## Evidence to save

Long-run report с графиком/таблицей ресурсов, restart/recovery result и перечнем реальных аппаратных bottlenecks.
