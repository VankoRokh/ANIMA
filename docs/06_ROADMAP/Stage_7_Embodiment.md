---
document_type: stage
status: Planned
updated: 2026-10-16
tags: [anima, roadmap, embodiment]
---

# Stage 7 — Modular embodiment

## Goal

Добавить физические сенсорные и исполнительные модули так, чтобы отказ, отключение или замена отдельного узла не уничтожали целостность экземпляра.

## Observable result

ANIMA видит состояние модулей, обнаруживает отказ, безопасно деградирует, восстанавливает связь и продолжает работу после замены совместимого узла.

## Required work

- [ ] Версионированные module contracts.
- [ ] Heartbeat/health/diagnostic state.
- [ ] Offline/reconnect/synchronization rules.
- [ ] Зрение и звук с отдельными benchmarks.
- [ ] Первый привод с feedback и safety bounds.
- [ ] Процедура физической замены узла.
- [ ] Документация схем/чертежей только после испытаний прототипа.

## Test scenarios

1. Отключение и повторное подключение периферийного узла.
2. Потеря связи во время операции.
3. Замена узла на совместимый новый экземпляр.
4. Дубликаты/поздние сообщения после reconnect не ломают состояние.
5. Привод упирается в ограничение/препятствие и переходит в безопасное состояние.
6. Отказ одной периферии не повреждает core identity/memory.

## Acceptance criteria

Все обязательные узлы имеют диагностируемое состояние; disconnect/reconnect и замена проходят без потери канонических данных; actuator safety scenarios завершаются в заданных пределах.

## Evidence to save

Failure/reconnect trace, replacement test и измеренный safety test первого исполнительного модуля.
