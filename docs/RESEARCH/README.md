# Исследования ANIMA

**Назначение:** карта гипотез, экспериментов, принятых отдельных механизмов и ограничений. Здесь **нет** обязательного рабочего плана выпуска. Актуальные требования к `ANIMA v0.1 Foundation` — [контракт](../versions/v0.1/contract.md), фактическая сборка — [архитектура](../system/README.md), оставшиеся релизные действия — [Roadmap](../roadmap.md).


**Диагностика v0.1 R-08:** [разнородные события, источники и Context](v01-r08-diversity-probe.md) — эксперимент, который помог выявить и исправить ложное объединение Memory. [Принятая ресурсная граница и остаточные ограничения](../versions/v0.1/resources.md) зафиксированы отдельно; сама лаборатория не расширяет универсальные гарантии v0.1.

## Правила доказательств

- **Research / Proposed** — гипотеза или дизайн, без подтверждённого результата.
- **Validated Lab** — успех конкретного теста на конкретном корпусе, SHA и окружении. Не означает production integration.
- **Implemented / Integrated** — механизм присутствует в коде или в названной сборке; это не статус релизной приёмки.
- **Release Accepted** — требуется отдельный gate на конкретном чистом Git tree и решение по требованиям версии.
- **Failed / Inconclusive / NO-GO** — не удалять; отрицательные наблюдения определяют границы безопасности и следующий эксперимент.

Используем оригинальные технические имена и ID, но объяснения на русском. Внутри каждого обзора — цель, метод, первичные материалы, результат, граница вывода и решение о применении. **Исторические документы и TV не редактируются задним числом.**

## Каталог

| Направление | Состояние и главное решение | Читать |
| --- | --- | --- |
| EXP-009 / Event Retrieval v1 | Контролируемый A/B/C/D; выбран отдельный индекс исходных Events, встроен в базовый релизный read path | [Поиск и происхождение данных](retrieval.md) |
| Memory Encoding E1–E4 | E1 shadow PASS; E2/E3 — отдельные лабораторные границы; E4 authority/crash/scale только в изолированной лаборатории, production **NO-GO** | [Кодирование и отзыв](memory-encoding.md) |
| Stage 7 / Semantic Boundary | Frozen read-only `classify_relation/0.1`; deterministic baseline PASS, model residual Inconclusive | [Семантика](semantics.md) |
| VAL / Godot, P5/P6, M0–M6-B2 | Изолированные и live проверки; M6-B2 10/10 CI и 10/10 отдельный ноутбучный JSON; не весь Stage 8 или релиз | [Виртуальная среда и интеграции](virtual-world.md) |
| ANIMA v0.2 / Continuous Lifecycle | **Research / Active:** E0 выявил пробелы, E1.2–E1.4 проверены в лаборатории; E1-min и E2 не приняты, это не функции релиза | [Исторический план эксперимента](continuous-lifecycle-v02.md) |
| E1.1 / World DTOs | **Validated Lab / в составе E1.2–E1.4**: типизированные world contracts, отрицательные unit и real-Godot наблюдения/действия, без доказательства аутентификации | [Граница контрактов E1.1](e1-world-contracts-v02.md) |
| E1.2 / LifecycleWorld | **Validated Lab / E1.2 PASS**: observe-only по умолчанию; реальный Godot 4.7.2, P5/P6, M2; действия включаются только в E1.3/E1.4 opt-in режимах | [Первый мир и доказательства E1.2](e1-lifecycle-world-v02.md) |
| E1.3 / Virtual effects & readback | **Validated Lab / E1.3 PASS:** opt-in `world.move/pick/drop`, свежий sensor proof; журнал операций добавляется отдельно в E1.4 | [Действия мира E1.3](e1-world-effects-v02.md) |
| E1.4 / Operation Ledger | **Validated Lab / E1.4 PASS:** opt-in 256-record journal, replay/status/conflict, fail-closed `UNKNOWN`; **E1-min и E2 ещё не приняты** | [Журнал и доказательства E1.4](e1-operation-ledger-v02.md) |
| E1-min / Independent Acceptance | **PASS_LAB_RESTRICTED:** 5/5 CI, 4 black-box маршрута, 256 операций; доверенный operator порт и persistency **не доказаны**. Только lab, не release/E2 approval | [Вердикт и доказательства](e1-min-acceptance-report-v02.md) · [ТЗ](e1-min-acceptance-brief-v02.md) |
| E2.1 / Core-owned guarded gateway | **PASS_LAB_APP_BOUNDARY:** Core-bound read-only observation, guarded bearer roles, pinning и raw TCP spoof denial; **не** OS sandbox / Raw / Stage6 execution | [Вердикт и доказательства](e2-1-acceptance-report-v02.md) · [Контракт](e2-core-world-boundary-v02.md) |
| E2.2 / Raw capture and provenance | **PASS_LAB_RAW_POINTER:** atomic complete WorldObservation + Core digest event, crash replay; **не** self-contained Core Raw / Context / FAST / Knowledge | [Вердикт и доказательства](e2-2-acceptance-report-v02.md) · [Контракт](e2-raw-provenance-v02.md) |
| E2.3 / Directed sensor and cognitive proposal schema | **PASS_LAB_SENSOR_ONLY:** real Godot relative 90° view + opaque IDs + turn/step replay, only lab proposal validator; **не** карта, Memory, Core action или FAST | [Приёмка, evidence и риски](e2-3-perception-acceptance-v02.md) · [Направление E2.3–E3](e2-cognitive-initiative-v02.md) |
| E2.4a / Core-backed associative working memory | **PASS_LAB_ASSOCIATIVE_MEMORY:** 3 Raw+Core events/seed, visual recall vs memory-off, observed changes and same-view associations; **не** топологическая карта, CognitiveCoordinator или FAST | [Результаты, ограничения, дальнейший план](e2-4-working-memory-acceptance-v02.md) |
| E2.4b / Verified relative viewpoint | **PASS_LAB_RELATIVE_POSE:** readback Godot operation_status + next Core Raw verifies turn/step and relative pose; **не** full topo map, Core Stage6/FAST | [Приёмка, ограничения, доказательства](e2-4b-relative-pose-acceptance-v02.md) |
| E2.5a / Read-only cognitive initiative | **PASS_LAB_READ_ONLY_INITIATION:** stub предлагает следующий bounded Retrieval после результата первого, Core-backed Raw proof и DecisionRecord; **не** настоящая FAST, нативный Core Admission или Goal/Action | [Результаты, негативные тесты, будущая FAST](e2-5a-cognitive-initiative-acceptance-v02.md) |
| E2.5b / Visual deterministic decision loop | **PASS_LAB_DETERMINISTIC_CLOSED_LOOP:** реальный Godot STEP/RUN, выбранные по сенсору turn/step, Core-backed Raw, verified readback + durable lab decision; **не** FAST или Core-native Stage6 | [Отчёт, риски, запуск](e2-5b-visual-decision-lab-acceptance-v02.md) |
| E2.5c / Stage2 Goal/Task + Stage6 spatial action | **PASS_LAB_STAGE2_STAGE6_SPATIAL:** agent-selected turn/step through canonical Goal/Task, ExecutionStore, SandboxExecutor, readback + next Core Raw; **не** generic CoreGoalDecision или FAST | [Приёмка, лимиты и команды](e2-5c-stage6-spatial-acceptance-v02.md) |
| E2.5c-M / Paired memory and stale location | **PASS_LAB_PAIRED_MEMORY_CONFLICT:** Godot 7/8, FAMILIAR 2 vs 4 actions (с/без памяти), RELOCATED 4 vs 2 с доказательным пересмотром гипотезы; **не** real FAST / native Stage6 | [Приёмка и границы эксперимента](e2-5c-memory-conflict-acceptance-v02.md) |
| E2.6 / R9 remediation | **Research / R9.4.1a observable state**: offline measurements/harness; R9.4.2 policy unchanged; independent audit pending | [Реестр R9](e2-6-r9-remediation-v02.md) · [Characterization и протокол](e2-6-r940-characterization-v02.md) · [Observable state / R9.4.1a](e2-6-r941a-observable-v02.md) |
| Core P0–P6 и аудит B1–B4 | Исправления и независимые ограничения; исторический путь реализации | [История Core](../history/core-v0.1.md) |
| Pi, FAST/DEEP/SLEEP, perception, метапамять | Отдельные пробы и будущие варианты; не навязаны Foundation | [Аппаратные и дальнейшие направления](future-directions.md) |

## Где находятся первичные данные

**Канонические тематические обзоры** — в `docs/RESEARCH/`. Ранее созданные файлы `docs/ROADMAP/`, исторические перечни из [legacy-index](legacy-index.md), `docs/TESTING/` и отчёты `TV-*.md` **сохраняют исходные адреса**. Это deliberate compatibility, а не свидетельство, что их названия «Roadmap» делают их актуальным планом.

[Исторический реестр исследовательских вопросов](../ROADMAP/Research.md) объединяет идеи разных дат; отдельные пометки `OPEN` внутри него означают состояние **того исторического текста**, а не автоматически состояние нынешнего релиза. [Архив исходных лабораторий](../TESTING/Laboratory_Integrations.md) хранит команды и ограничения сценариев. [Реестр TV](../TESTING/Results/README.md) — исходные metadata, версии и результаты.

## От исследования к продукту

`Гипотеза → frozen критерии и данные → отрицательные проверки → воспроизводимый lab → явное решение → production code → release gate`. Успех в одном звене не подменяет соседнее. Нельзя выдавать метку `source="user"` за аутентификацию или переносить выполнение Godot по уже существовавшему разрешению другой среды.

## Совместимость со старым индексом

Прежние якоря сохранены для существующих ссылок. Сами исторические перечни находятся в [неизменённом по смыслу индексе](legacy-index.md); он фиксирует прежнюю группировку, но не новый статус релиза.

## Отдельные направления

[Историческая таблица направлений](legacy-index.md#отдельные-направления).

## Иерархия

[Историческая классификация](legacy-index.md#иерархия); актуальные правила доказательств — [выше](#правила-доказательств).

## Карта прежних исследовательских документов

[Прежняя карта Roadmap и исследовательских файлов](legacy-index.md#карта-прежних-исследовательских-документов).

R9.4.1b: [Baseline Model Experiments — Q/I/H/T-recorded](e2-6-r941b-baseline-model-experiments-v02.md), real-model baseline на неизменённой policy; 2640 received, controlled ID sensitivity и limitations зафиксированы.

R9.4.2: [Cognitive Control Policy](e2-6-r942-cognitive-control-v02.md), opt-in versioned read-only laboratory control; baseline replay preserved.

R9.4.3: [Retrieval Efficiency и R942 targeted hardening](e2-6-r943-retrieval-efficiency-v02.md), versioned lexical profiles и separate held-out offline metrics.

R9.4.4: [Controlled Evaluation](e2-6-r944-controlled-evaluation-v02.md), 560 paired T-fresh comparisons; benefit gate INCONCLUSIVE, отрицательный completeness finding сохранён.
