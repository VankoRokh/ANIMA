# Дорожная карта ANIMA

**Назначение:** здесь находятся только **текущая рабочая цель**, критерии движения к ней и архивный реестр исторических этапов. Подробности реализованных механизмов перенесены в [архитектуру](../ARCHITECTURE/README.md), а последовательность завершённых работ — в [историю стадий](../STAGES/README.md). Исследовательские планы не являются автоматическими обязательствами релиза.

## Текущая цель — ANIMA v0.1

Создать устойчивую детерминированную основу с постоянной Identity, управлением событиями, Memory, bounded Retrieval, Goals/Tasks и безопасным восстановлением. **Ноутбук Linux x86-64 — основной стенд.** Для первой версии не требуются LLM, Godot, Raspberry Pi, периферия, полный Stage 7 Knowledge lifecycle или метапамять.

**Источник обязательных требований:** [контракт v0.1](../RELEASES/ANIMA_v0_1_Release_Contract.md).  
**Последняя доказательная база:** [локальная приёмка](../RELEASES/ANIMA_v0_1_Notebook_Evidence.md) и [аудит рисков](../RELEASES/ANIMA_v0_1_Gap_Audit.md).  
**Устройство:** [архитектурная карта](../ARCHITECTURE/README.md).  
**Статус:** прошедший функциональную проверку кандидат; тег и официальная процедура выпуска не оформлены. Не смешивать `FUNCTIONAL_GATE_PASS` с закрытием всех исследовательских Stage.

### Действия до принятия v0.1

| Порядок | Действие | Что считается результатом |
| --- | --- | --- |
| 1 | Релизная граница | Утверждён минимальный контракт и исключён scope будущих модулей |
| 2 | Сборка | Штатный постоянный headless-профиль `anima.release_v01` с проверяемыми полномочиями |
| 3 | Функциональные проверки | Повторный запуск, raw provenance, Memory, context, sandbox Goal/Task и отказы без непредусмотренных эффектов |
| 4 | Ограничения и ресурсы | Фиксированная нагрузка, измерения без подмены их универсальным SLA |
| 5 | Финальная регрессия | Точный clean Git snapshot, `check.sh`, полный pytest на поддерживаемых Python |
| 6 | Выпуск | Итоговое решение о статусе, версия, Git tag и документ об известных ограничениях |

Критерии этой таблицы детализированы **только** в [R-01–R-10](../RELEASES/ANIMA_v0_1_Release_Contract.md). Повторное создание отдельных дорожных карт внутри Roadmap не требуется.

## Что уже сделано

Подробная история со свидетельствами находится в [истории D0, 0, D1, 1–6](../STAGES/README.md). Отдельно доступны [тематические механизмы архитектуры](../ARCHITECTURE/README.md) и [перечень испытаний](../TESTING/Results/README.md). Завершённый этап означает, что **оговорённые тогда** критерии прошли проверку, а не что вся будущая функциональность подсистемы уже готова.

## Что отложено и где хранится

| Категория | Где искать | Статус для v0.1 |
| --- | --- | --- |
| Новые алгоритмы Memory, E1–E4, EXP-009 | [Исследовательский реестр](../RESEARCH/README.md), [Memory Architecture v1](Memory_Architecture_v1_Roadmap.md) | Реализованные части учитываются отдельно; остальные не блокируют |
| Core/P6/VAL/Godot | [Исследования](../RESEARCH/README.md), [Lab](Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md) | Дополнительные полигоны, не обязательный runtime |
| Семантический lifecycle Knowledge | [Stage 7 boundary](Stage_7_Semantic_Boundary_v0.md), [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md) | Принятый контракт отдельных границ, полная реализация открыта |
| Raspberry Pi, сенсоры, физическое воплощение | [Исторические Stage 9–11](#stage-9), [исследования](../RESEARCH/README.md) | За пределами обязательной приёмки |
| Новые версии FAST/DEEP/SLEEP и метапамять | [Исследования](../RESEARCH/README.md) | Идеи для будущих релизов, не точный план |

**Об остальных релизах:** направления развития сохраняются как идеи в [RELEASES](../RELEASES/README.md). Подробная дорожная карта следующей версии составляется **только при начале её разработки**.

## Исторический реестр этапов

**Важное пояснение.** Таблица ниже генерируется из [`docs/project.json`](../project.json), который отражает **прежнюю сквозную последовательность Stage**. Там `current_stage=7` и Stage 7 `Planned` — историческая точка остановки старого полного плана, **а не перечень блокеров для ANIMA v0.1**. Нельзя читать зависимости Stage 7→8→9→10→11 как обязательный путь к текущему релизу. Эти статусы не были переписаны ради нового представления истории.

<!-- AUTO:roadmap:START -->
**Текущая работа:** Stage 6 Cognitive Integration Core завершён и подтверждён TV-0051. Для Stage 7 принят pre-training semantic boundary v0: immutable qualified/time-scoped Claim, отдельные Evidence/Source/Producer/provenance, typed Value v0, explicit temporal semantics, независимые CONTENT/REVISION results и read-only classify_relation/0.1 с deterministic-first processing. Stage 7 implementation остаётся Planned; DP-08, DP-09, полная dependency policy DP-10 и production integration DP-11 открыты. До model training обязательны conformance corpus и измерение реального model residual; LoRA/SFT не начаты.

**Фокус:** 7 — Semantic Lifecycle & Refinement (Planned).

| Этап | Проверяемый результат | Статус | Зависимости |
|---|---|---|---|
| [D0 — Documentation](#d0) | Контекст и процедуры работы восстанавливаются из репозитория | Complete | — |
| [0 — Foundation](#stage-0) | Перенос сохраняет идентичность, историю и возможность продолжения | Complete | [D0](#d0) |
| [D1 — Runtime, Tests & Observability](#d1) | Один сценарий запускается headless, наблюдается и проверяется изолированно | Complete | [0](#stage-0) |
| [1 — Cognitive Memory](#stage-1) | Релевантный опыт извлекается с происхождением и ограниченным контекстом | Complete | [0](#stage-0), [D1](#d1) |
| [2 — Internal State](#stage-2) | Влияние внутреннего состояния на выбор причинно прослеживается | Complete | [1](#stage-1) |
| [3 — Sleep](#stage-3) | Консолидация прерывается и возобновляется без потери источников | Complete | [2](#stage-2) |
| [4 — Agent / LLM Planner Experiment](#stage-4) | Проверен recoverable action loop, но роль LLM Planner признана архитектурным отклонением; результаты 4.0–4.12 сохранены | Stopped | [3](#stage-3) |
| [5 — FAST Cognition & Memory Integration](#stage-5) | FAST использует ограниченный контекст Cognitive Memory и участвует в текстовом цикле без владения памятью или системным состоянием | Complete | [1](#stage-1), [D1](#d1) |
| [6 — Cognitive Integration Core](#stage-6) | FAST, DEEP, routing, Tasks, Goals, Internal State, Sleep и проверяемый исполнительный слой участвуют в одном наблюдаемом когнитивном цикле без передачи LLM системного ownership | Complete | [5](#stage-5), [2](#stage-2), [3](#stage-3) |
| [7 — Semantic Lifecycle & Refinement](#stage-7) | Semantic write/update/revision/consolidation работают с provenance и authority rules; bootstrap knowledge проходит через тот же проверяемый lifecycle | Planned | [6](#stage-6), [1](#stage-1), [3](#stage-3) |
| [8 — Virtual ANIMA](#stage-8) | ANIMA непрерывно действует в наблюдаемой 2D-среде с synthetic history, live events, ручными и автоматизированными сценариями | Planned | [7](#stage-7) |
| [9 — Raspberry Pi Validation](#stage-9) | Один и тот же workload воспроизводимо сравнивается на PC и Raspberry Pi 5; Pico используется только там, где полезен realtime/telemetry контур; сняты performance и endurance показатели | Planned | [8](#stage-8) |
| [10 — Perception & Interaction](#stage-10) | Камера, микрофон и аудиовывод подключаются через стабильные source/output interfaces и преобразуются в наблюдаемые Events без захламления Memory сырыми потоками | Planned | [9](#stage-9) |
| [11 — Physical Expansion](#stage-11) | После измеренных требований подключается специализированная физическая периферия и исследуется первое устойчивое физическое воплощение без потери Identity/Memory | Planned | [10](#stage-10) |
<!-- AUTO:roadmap:END -->

## Подробные исторические этапы и постоянные ссылки

Следующие заголовки сохранены также для совместимости со ссылками из первичных TV-отчётов. **Полные описания завершённых этапов вынесены из Roadmap**, чтобы не дублировать архитектуру.

## D0

[Документирование проекта](../STAGES/D0_Documentation.md) — завершено. [TV-0003](../TESTING/Results/TV-0003.md).

## Stage 0

[Identity, Events и переносимость](../STAGES/00_Foundation.md) — завершено. [TV-0001](../TESTING/Results/TV-0001.md).

## D1

[Runtime, тесты, наблюдаемость](../STAGES/D1_Runtime_Observability.md) — завершено. [TV-0002](../TESTING/Results/TV-0002.md).

## Stage 1

[Когнитивная память](../STAGES/01_Cognitive_Memory.md) — завершено. [TV-0014](../TESTING/Results/TV-0014.md).

## Stage 2

[Внутреннее состояние](../STAGES/02_Internal_State.md) — завершено. [TV-0017](../TESTING/Results/TV-0017.md).

## Stage 3

[SLEEP и консолидация](../STAGES/03_Sleep.md) — завершено. [TV-0030](../TESTING/Results/TV-0030.md).

## Stage 4

[Agent/LLM Planner experiment](../STAGES/04_Agent_Experiment.md) — **остановлен** после проверенных прототипов; исполнительные результаты использованы позднее. [ADR-008](../DECISIONS/README.md#adr-008).

## Stage 5

[FAST и детерминированный resolver](../STAGES/05_FAST_Cognition.md) — завершено. [TV-0043](../TESTING/Results/TV-0043.md).

## Stage 6

[Системная когнитивная интеграция](../STAGES/06_Core_Integration.md) — завершено. [TV-0051](../TESTING/Results/TV-0051.md).

## Stage 7

Семантический жизненный цикл — **исторически Planned**, отдельный read-only контракт [Stage 7](Stage_7_Semantic_Boundary_v0.md) принят; не считать закрытым. [TV-0052](../TESTING/Results/TV-0052.md) проверял baseline, [TV-0053](../TESTING/Results/TV-0053.md) имеет результат `Inconclusive`.

## Stage 8

Виртуальная ANIMA — **Planned** в прежней последовательности; [Godot/VAL лаборатория](Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md) не равна завершённому Stage 8.

## Stage 9

Raspberry Pi — **Planned** в прежней последовательности; отдельные предварительные Core Pi/PC испытания описаны в [TV-0054](../TESTING/Results/TV-0054.md). Для v0.1 Pi **не требуется**.

## Stage 10

Восприятие: камера, микрофон, звук — прежняя идея, **Planned**, без обязательного объёма текущего релиза.

## Stage 11

Физическое расширение — прежняя идея, **Planned**, не проект обязательного устройства для v0.1.

## Правило обновления плана

Текущие требования меняются в [RELEASES](../RELEASES/README.md); история этапов и её причины — в [STAGES](../STAGES/README.md) и [DECISIONS](../DECISIONS/README.md); работающий код — в [ARCHITECTURE](../ARCHITECTURE/README.md); исследования — в [RESEARCH](../RESEARCH/README.md). Не смешивать `Validated Lab`, `Integrated` и `Release Accepted`. Не переписывать исторический TV-отчёт при изменении новых требований. После настоящего выбора нового релиза подробный план формируется отдельно от этого исторического реестра.
