# История разработки ANIMA

Эта страница отвечает на вопрос **как развивалась система**, а не на вопрос о готовности текущего релиза. Подробные первичные документы Stage сохранены по прежним адресам; исходные TV не меняются. Статусы `Complete`, `Stopped` и `Planned` относятся к историческому реестру, не к составу `ANIMA v0.1 Foundation`.

## Реестр стадий

Данные таблицы генерируются из [исторического `project.json`](../project.json). Старое поле `current_stage` не является текущим Roadmap продукта. После Stage 6 развитие перестало быть одной линейной цепочкой.

<!-- AUTO:roadmap:START -->
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

**Задача:** воспроизводимая работа с исходниками, документацией и проверками. Исходный D0 завершён 12 октября 2026 года; [TV-0003](../TESTING/Results/TV-0003.md) относится к **отдельной консолидации 24 октября**, когда появились реестр и генератор нынешнего формата. Не датировать оба события одним днём.

**Наследие:** процедуры Git, источники требований и контролируемые проверки. [Исходное описание](../STAGES/D0_Documentation.md).

## Stage 0

**Задача:** отделить Identity, State и события от исполняемого окружения. Выделены EventBus/журнал и данные экземпляра; проверен перенос состояния между сессиями.

**Проверено:** ручной перенос Identity и продолжение сессии 2→3 в [TV-0001](../TESTING/Results/TV-0001.md). Тест не устанавливал все гарантии позднего Core. [Описание](../STAGES/00_Foundation.md).

## D1

**Задача:** отделить Runtime от интерактивной CLI и получить headless, trace, метрики. В [TV-0002](../TESTING/Results/TV-0002.md) сравнивалась обработка трёх событий; точный SHA прогона не записан (`not-recorded`).

**Наследие:** независимая от терминала логика выполнения. [Описание](../STAGES/D1_Runtime_Observability.md).

## Stage 1

**Задача:** превратить сырые Events в сохраняемую и извлекаемую Memory. Добавлены SQLite, Entity/Relation и provenance, ревизии, Knowledge, детерминированная обработка, Retrieval и ограниченный Context.

**Проверено:** в [TV-0014](../TESTING/Results/TV-0014.md) — 37 Events, 11 сессий/эпизодов и восстановление; [TV-0015](../TESTING/Results/TV-0015.md) измерил сканирование. Отдельный поиск по raw Events появился позже, при интеграции памяти. [Описание](../STAGES/01_Cognitive_Memory.md).

## Stage 2

**Задача:** хранение Goal и причинная связь Internal State с допустимым выбором. Четыре переменные — `fatigue`, `uncertainty`, `frustration`, `satisfaction`; состояние корректирует оценку вариантов, но не создаёт новые полномочия.

**Проверено:** [TV-0017](../TESTING/Results/TV-0017.md) — выбор среди предоставленных вариантов, причинная история и повторное открытие. [Описание](../STAGES/02_Internal_State.md).

## Stage 3

**Задача:** долговечная SLEEP-переработка через SourceRef, SleepJob, WorkItem, checkpoints, версию процессора и DerivedResult.

**Проверено:** [TV-0030](../TESTING/Results/TV-0030.md) — restart/resume, provenance и логический источник 10 GiB. Это не равнозначно обязательной фоновой SLEEP-обработке в релизном профиле. [Описание](../STAGES/03_Sleep.md).

## Stage 4

**Задача:** эксперимент с LLM Planner, Tool/Executor, Observation, Verification и recoverable action loop. Экспериментальная архитектура остановлена: общим управлением не должна владеть LLM.

**Проверено:** [TV-0031–0042](../TESTING/Results/README.md); [TV-0042](../TESTING/Results/TV-0042.md) — узкий опыт с реальной моделью. Исполнение, проверка и восстановление унаследованы следующими слоями. [Описание](../STAGES/04_Agent_Experiment.md) и [ADR-008/009](../DECISIONS/README.md#adr-008).

## Stage 5

**Задача:** Canonical IR, Resolver, Projection, сменяемый FAST и проверяемый результат `FastResult`.

**Проверено:** [TV-0043](../TESTING/Results/TV-0043.md) — ограниченный smoke 7/7 на Qwen3-0.6B; точный чистый SHA не записан. `CognitiveProposal` появился **в Stage 6**, не в Stage 5. [Описание](../STAGES/05_FAST_Cognition.md).

## Stage 6

**Задача:** Persistent Task, Coordinator/Router, FAST/DEEP/Choice, системный допуск, независимая Verification, SLEEP и UnifiedTrace в одном контролируемом контуре.

**Проверено:** [TV-0051](../TESTING/Results/TV-0051.md) на `123374b…` — интеграция, прерывание, восстановление и отсутствие повторного файлового эффекта. Дальнейший typed Core и профиль Foundation имеют **собственные** сборки и проверки. [Описание](../STAGES/06_Core_Integration.md).

## Stage 7

**Исторический статус:** `Planned` для полного semantic write/revision lifecycle. Отдельный read-only профиль `classify_relation/0.1` получил принятую границу и корпус. [TV-0052](../TESTING/Results/TV-0052.md): deterministic/preflight 48/50. [TV-0053](../TESTING/Results/TV-0053.md): `Inconclusive`; модельные остаточные случаи не закрыты.

**Не доказано:** production write/revision и устранение открытых DP. [Первичный контракт](../ROADMAP/Stage_7_Semantic_Boundary_v0.md).

## Stage 8

**Исторический статус:** `Planned`. Отдельные P5/P6/VAL и M2/M6-B2 успешно выполняли ограниченные сценарии Godot, но не являются приёмкой всего Stage 8. [Источники лабораторий](../TESTING/Laboratory_Integrations.md).

## Stage 9

**Исторический статус:** `Planned`. [TV-0054](../TESTING/Results/TV-0054.md) — отдельные PC/Pi Core проверки с результатом `Inconclusive`, базовым SHA и локальными изменениями. Не трактовать их как общий release gate или завершённую переносимость.

## Stage 10

**Исторический статус:** `Planned`. Предполагаются подключаемые источники камеры, микрофона и аудиовывод; подтверждённой общей приёмки Stage в проверенных документах нет.

## Stage 11

**Исторический статус:** `Planned`. Физическое расширение предполагается после измерения требований; обязательной конструкции или результатов приёмки нет.

## Что произошло после Stage 6

Развитие **разветвилось**: typed Core v0.1 (P0–P6 и исправления B1–B4), read-only Stage 7, VAL/Godot, экспериментальная Memory (EXP-009, E1–E4, M0–M6-B2) и отдельная сборка `ANIMA v0.1 Foundation`. Это самостоятельные линии доказательств, не последовательное закрытие Stage 7→8→9.

Актуальный состав выпуска см. в [контракте v0.1](../RELEASES/ANIMA_v0_1_Release_Contract.md), [карточке приёмки](../versions/v0.1/acceptance.md) и [дорожной карте](../roadmap.md). Первичные результаты доступны в [реестре TV](../TESTING/Results/README.md) и [лабораторных отчётах](../TESTING/Laboratory_Integrations.md).
