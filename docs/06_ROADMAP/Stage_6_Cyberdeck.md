---
document_type: stage
status: Planned
updated: 2026-10-16
tags: [anima, roadmap, hardware]
---

# Stage 6 — Cyberdeck prototype

## Goal

Перенести проверенный программный контур на автономное устройство, выбранное по измеренным bottlenecks Stage 5.

## Observable result

Тот же контрольный workload выполняется на cyberdeck с известными latency, temperature, power и autonomy характеристиками.

## Required work

- [ ] Зафиксировать требования из Stage 5 до выбора платформы.
- [ ] Выбрать compute/storage/accelerator по измерениям.
- [ ] Питание, резерв и safe shutdown.
- [ ] Охлаждение и thermal monitoring.
- [ ] Перенос экземпляра и recovery.
- [ ] Замена основных компонентов без переделки всей системы, где это предусмотрено архитектурой.

## Test scenarios

1. Тот же benchmark, что на ПК/VM.
2. Cold boot / normal shutdown / abrupt power loss с резервом, если предусмотрен.
3. Длительная нагрузка и thermal throttling test.
4. Battery/autonomy test по заранее объявленному профилю нагрузки.
5. Перенос данных туда/обратно без смены `instance_id`.

## Acceptance criteria

До закупки фиксируются целевые пределы latency/RAM/storage/autonomy/temperature. Stage закрывается только если устройство соответствует этим пределам или документированно показывает, какой компонент требует следующей итерации.

## Evidence to save

Сравнение PC vs cyberdeck benchmark, thermal/power profile и recovery test.
