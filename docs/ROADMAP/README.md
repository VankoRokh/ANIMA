# План развития ANIMA

**Источник статусов и зависимостей — [`docs/project.json`](../project.json).** Таблица ниже создаётся автоматически. Этот документ содержит только ближайшие задачи и минимальные критерии этапов, а не повторяет историю всех промежуточных коммитов.

## Ближайший маршрут

1. **Core v0.1:** завершить повторный независимый аудит источников наблюдений, Belief, Goals/Tasks, допуска действий, независимой Verification, повторов и recovery; зафиксировать точный проверенный SHA. [Критерии ревизии](Core_v0_1_Audit_Boundaries.md).
2. **Virtual Lab:** P5-A/B/C и интерфейс Normal/Debug завершили локальные испытания, **Core не подключён**. [Сводка полигона](Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md).
3. **P6 — интеграция Core ↔ Lab:** только после аудита проектировать доверенный адаптер с реальными полномочиями источников и повторной проверкой результатов.
4. **Stage 7:** принят [семантический контракт](Stage_7_Semantic_Boundary_v0.md) для ограниченного read-only интерфейса, но полный жизненный цикл Knowledge остаётся Planned. Открыты DP-08/09/10b/11; [корпус соответствия](../TESTING/Stage7_Conformance_v0.md).

**Технические ориентиры:** [архитектура](../ARCHITECTURE/README.md), [рабочий план Core/VAL](Core_v0_1_VAL_v0_1_Plan_Draft.md), [результаты испытаний](../TESTING/Results/README.md), [принятые решения](../DECISIONS/README.md), [исследовательский backlog](Research.md), [старые редакции](../ARCHIVE/Development_Snapshots.md).

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

## D0

**Документация — Complete.** Источники истины, генерируемые сводки и сохранение истории в Git. [Результаты](../TESTING/Results/TV-0003.md).

## Stage 0

**Основа — Complete.** Идентичность экземпляра, состояние, журнал событий и восстановление. [TV-0001](../TESTING/Results/TV-0001.md).

## D1

**Среда исполнения и проверки — Complete.** Изолированные тесты, наблюдаемость, запуск без GUI. [TV-0002](../TESTING/Results/TV-0002.md).

## Stage 1

**Когнитивная память — Complete.** Эпизоды, знания, происхождение сведений, извлечение и ограниченный контекст. [Результаты](../TESTING/Results/README.md).

## Stage 2

**Внутреннее состояние — Complete.** Состояние влияет на выбор, но не владеет решениями. [Результаты](../TESTING/Results/README.md).

## Stage 3

**Сон и консолидация — Complete.** Ограниченная обработка, контрольные точки и продолжение после прерывания. [Результаты](../TESTING/Results/README.md).

## Stage 4

**Эксперимент LLM Planner — Stopped.** Полезные проверки Executor/Observation/Recovery сохранены; передача системных полномочий LLM признана ошибочной. [ADR-008/009](../DECISIONS/README.md#adr-008), [результаты](../TESTING/Results/README.md).

## Stage 5

**FAST и когнитивная память — Complete.** Детерминированное разрешение до вызова модели, проверка ответа и сменяемый FAST без владения состоянием. [TV-0043](../TESTING/Results/TV-0043.md).

## Stage 6

**Когнитивная интеграция — Complete (официальный Stage).** Системный Coordinator, Tasks/Goals, FAST/DEEP, допуск и подтверждение действий, Sleep и восстановление. Статус Stage 6 **не равен** окончательной заморозке отдельно аудируемого Core v0.1. [Реализованная архитектура](../ARCHITECTURE/Stage_6_Cognitive_Integration_Core.md), [TV-0051](../TESTING/Results/TV-0051.md).

## Stage 7

**Семантический жизненный цикл — Planned.** [Принятый read-only boundary](Stage_7_Semantic_Boundary_v0.md) отделяет Claim/Evidence/Source/Producer, область времени, CONTENT/REVISION и правило «сначала детерминированное». Write/update/revision Knowledge требуют отдельной политики полномочий и проверки. [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md).

## Stage 8

**Виртуальная ANIMA — Planned.** Взаимодействие Core с независимым миром, где отделены истина среды, тестовая история и реальные события. Подготовительный [Virtual Lab](Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md) не является реализацией Stage 8.

## Stage 9

**Raspberry Pi — Planned.** Одинаковая нагрузка на ПК и Pi 5, корректность, ресурсы и длительная стабильность; дополнительное железо — по измеренным требованиям.

## Stage 10

**Восприятие и взаимодействие — Planned.** Камера, микрофон и вывод звука через заменяемые интерфейсы, без автоматической записи сырого потока в Memory.

## Stage 11

**Физическое расширение — Planned.** Форма, приводы, питание и дополнительные узлы выбираются после проверки этапов 9–10, а не заранее.

## Порядок изменений

Изменение архитектуры требует ADR и тестового критерия. Обычный успешный прогон не порождает новый документ; значимые результаты сохраняются в [журнале испытаний](../TESTING/Results/README.md). Исторические черновики доступны через [неизменяемую ссылку на Git](../ARCHIVE/Development_Snapshots.md).
