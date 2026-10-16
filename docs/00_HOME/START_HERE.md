---
document_type: guide
status: Accepted
updated: 2026-10-16
tags: [anima]
---

# Начать или вернуться к ANIMA

ANIMA — проект модульного ИИ-агента с сохраняемым опытом и перспективой переноса между вычислителями и физическими носителями. Подробное описание: [ANIMA](ANIMA.md).

## Быстро вернуться к работе

1. [Project Status](Project_Status.md) — что работает, чем занимаемся сейчас и какие есть ограничения.
2. [Roadmap](../06_ROADMAP/Roadmap.md) — куда движется проект и какой Stage следующий.
3. Страница нужного модуля через [Module Index](Module_Index.md).
4. При необходимости — соответствующий ADR и код.
5. Перед изменениями выполнить `bash scripts/check.sh`.

Не требуется читать всю документацию перед каждой задачей.

## Новый компьютер

Использовать [Setup](../09_OPERATIONS/Setup.md). Для переноса существующего экземпляра — [Recovery](../09_OPERATIONS/Recovery.md).

```bash
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/run.sh
```

## Новый ИИ-помощник

Начать с [AI_CONTEXT](AI_CONTEXT.md). Затем читать только документы, связанные с текущей задачей.

## Где что находится

| Нужно узнать | Источник |
|---|---|
| Текущее состояние | [Project Status](Project_Status.md) |
| Общая архитектура | [System Architecture](../02_ARCHITECTURE/System_Architecture.md) |
| Конкретный модуль | [Module Index](Module_Index.md) |
| Порядок разработки | [Roadmap](../06_ROADMAP/Roadmap.md) |
| Правила тестирования | [Test Strategy](../07_EXPERIMENTS/Test_Strategy.md) |
| Показательные проверки | [Test Results](../07_EXPERIMENTS/Test_Results.md) |
| Причины решений | [ADR](../08_DECISIONS/README.md) |
| Работа и восстановление | [Operations](../09_OPERATIONS/Development.md) |

## Полный индекс

[Индекс документации](../README.md)
