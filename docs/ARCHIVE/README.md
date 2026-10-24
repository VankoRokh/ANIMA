# Архив и карта миграции

Прежние версии доступны в Git на снимке
[до миграции](https://github.com/VankoRokh/ANIMA/tree/0d535372f644316dcc9bab3c4ac9fbc20e559e05/docs).
Полные дубликаты не переносятся в отдельную живую копию. Существенные идеи,
ограничения, причины решений и доказательства объединены по карте ниже.
AI_CONTEXT и compatibility Current_Stage удалены; общий вход — docs/README.

## Исходный аудит

12 октября 2026 исходный [007b652](https://github.com/VankoRokh/ANIMA/commit/007b652ad5c66f1fe143c793c8c9390031f61be2)
содержал 15 файлов, README с названием, без docs/scripts/tests; Identity и CLI
были заготовками. Базовый тест на Python 3.12.14: session=1, sleeping, 3 raw events,
1 selected memory. Найдены SW-01 (чтение сырого журнала вместо выбранной памяти),
SW-02 (ID), SW-03 (безопасная запись), SW-04 (валидация), SW-05 (прерывание),
SW-06 (каталог независимо от cwd), SW-07 (выделение CLI). Эти наблюдения относятся
к исходному commit, а не к нынешним ограничениям.

D0 на Python 3.12.14 зафиксировал 48 страниц, 282 ссылки и 32 карточки. К моменту
этой миграции старый Check насчитывал 52 страницы, 244 ссылки, 32 карточки.
Это исторические снимки, не поддерживаемые метрики живой документации.
Первый workflow требовал patch → локальную проверку/commit/push владельца →
повторное чтение GitHub из-за ограничений прежнего подключения; это историческое
наблюдение, а не требование текущего инструмента. Независимый backup реального
экземпляра не подтверждался этими проверками.

## Перенос страниц

У смешанных страниц (Memory/Core/Interfaces/System Architecture) подтверждённое
поведение находится в Architecture, а будущие части — в
[Research](../ROADMAP/Research.md). Старые номера CORE/MEM/COG/SLP/IF/HW сохранены
там, где помогают соотнести идеи; статусы карточек больше не дублируются.

| Прежний путь | Новое место |
|---|---|
| `docs/00_HOME/AI_CONTEXT.md` | [Каноническое место](../README.md) |
| `docs/00_HOME/ANIMA.md` | [Каноническое место](../../README.md) |
| `docs/00_HOME/Module_Index.md` | [Каноническое место](../ARCHITECTURE/README.md) |
| `docs/00_HOME/Project_Status.md` | [Каноническое место](../ROADMAP/README.md) |
| `docs/00_HOME/START_HERE.md` | [Каноническое место](../README.md) |
| `docs/00_HOME/System_Map.md` | [Каноническое место](../ARCHITECTURE/README.md) |
| `docs/01_CONCEPT/Identity_and_Continuity.md` | [Каноническое место](../DECISIONS/README.md#adr-001) |
| `docs/01_CONCEPT/Principles.md` | [Каноническое место](../../README.md) |
| `docs/01_CONCEPT/Vision.md` | [Каноническое место](../../README.md) |
| `docs/02_ARCHITECTURE/Core.md` | [Каноническое место](../ARCHITECTURE/README.md) |
| `docs/02_ARCHITECTURE/Emotions.md` | [Каноническое место](../ROADMAP/Research.md) |
| `docs/02_ARCHITECTURE/Fast_Deep.md` | [Каноническое место](../ROADMAP/Research.md) |
| `docs/02_ARCHITECTURE/Goals.md` | [Каноническое место](../ROADMAP/Research.md) |
| `docs/02_ARCHITECTURE/Interfaces.md` | [Каноническое место](../ARCHITECTURE/README.md) |
| `docs/02_ARCHITECTURE/Memory.md` | [Каноническое место](../ARCHITECTURE/README.md) |
| `docs/02_ARCHITECTURE/Sleep.md` | [Каноническое место](../ROADMAP/Research.md) |
| `docs/02_ARCHITECTURE/System_Architecture.md` | [Каноническое место](../ARCHITECTURE/README.md) |
| `docs/03_SOFTWARE/Event_Pipeline.md` | [Каноническое место](../ARCHITECTURE/README.md) |
| `docs/03_SOFTWARE/Repository_Audit.md` | [Каноническое место](README.md#исходный-аудит) |
| `docs/03_SOFTWARE/Software_Architecture.md` | [Каноническое место](../ARCHITECTURE/README.md) |
| `docs/04_HARDWARE/Hardware_Architecture.md` | [Каноническое место](../ROADMAP/Research.md#аппаратные-направления) |
| `docs/05_PROTOCOLS/Events.md` | [Каноническое место](../ARCHITECTURE/README.md#каталог-и-контракты-данных) |
| `docs/05_PROTOCOLS/Module_Contracts.md` | [Каноническое место](../ROADMAP/Research.md#контракты-независимых-узлов) |
| `docs/06_ROADMAP/Backlog.md` | [Каноническое место](../ROADMAP/Research.md) |
| `docs/06_ROADMAP/Current_Stage.md` | [Каноническое место](../ROADMAP/README.md) |
| `docs/06_ROADMAP/Roadmap.md` | [Каноническое место](../ROADMAP/README.md) |
| `docs/06_ROADMAP/Stage_0_Foundation.md` | [Каноническое место](../ROADMAP/README.md#stage-0) |
| `docs/06_ROADMAP/Stage_1_Memory.md` | [Каноническое место](../ROADMAP/README.md#stage-1) |
| `docs/06_ROADMAP/Stage_2_Internal_State.md` | [Каноническое место](../ROADMAP/README.md#stage-2) |
| `docs/06_ROADMAP/Stage_3_Sleep.md` | [Каноническое место](../ROADMAP/README.md#stage-3) |
| `docs/06_ROADMAP/Stage_4_Agent.md` | [Каноническое место](../ROADMAP/README.md#stage-4) |
| `docs/06_ROADMAP/Stage_5_Virtual_ANIMA.md` | [Каноническое место](../ROADMAP/README.md#stage-5) |
| `docs/06_ROADMAP/Stage_6_Cyberdeck.md` | [Каноническое место](../ROADMAP/README.md#stage-6) |
| `docs/06_ROADMAP/Stage_7_Embodiment.md` | [Каноническое место](../ROADMAP/README.md#stage-7) |
| `docs/06_ROADMAP/Stage_D0_Documentation.md` | [Каноническое место](../ROADMAP/README.md#d0) |
| `docs/06_ROADMAP/Stage_D1_Runtime_Observability.md` | [Каноническое место](../ROADMAP/README.md#d1) |
| `docs/07_EXPERIMENTS/README.md` | [Каноническое место](../ROADMAP/Research.md#exp-001) |
| `docs/07_EXPERIMENTS/Test_Results.md` | [Каноническое место](../TESTING/Results/README.md) |
| `docs/07_EXPERIMENTS/Test_Strategy.md` | [Каноническое место](../TESTING/README.md) |
| `docs/08_DECISIONS/ADR-000-documentation-system.md` | [Каноническое место](../DECISIONS/README.md#adr-000) |
| `docs/08_DECISIONS/ADR-001-instance-continuity.md` | [Каноническое место](../DECISIONS/README.md#adr-001) |
| `docs/08_DECISIONS/ADR-002-fast-deep.md` | [Каноническое место](../DECISIONS/README.md#adr-002) |
| `docs/08_DECISIONS/ADR-003-local-reinforcement.md` | [Каноническое место](../DECISIONS/README.md#adr-003) |
| `docs/08_DECISIONS/ADR-004-documentation-workflow.md` | [Каноническое место](../DECISIONS/README.md#adr-004) |
| `docs/08_DECISIONS/README.md` | [Каноническое место](../DECISIONS/README.md) |
| `docs/09_OPERATIONS/Backup.md` | [Каноническое место](../OPERATIONS/README.md#резервирование) |
| `docs/09_OPERATIONS/Development.md` | [Каноническое место](../OPERATIONS/README.md#запуск-и-обновление) |
| `docs/09_OPERATIONS/Documentation_Rules.md` | [Каноническое место](../OPERATIONS/README.md#ведение-документации) |
| `docs/09_OPERATIONS/Recovery.md` | [Каноническое место](../OPERATIONS/README.md#восстановление) |
| `docs/09_OPERATIONS/Setup.md` | [Каноническое место](../OPERATIONS/README.md#установка) |
| `docs/99_ARCHIVE/README.md` | [Каноническое место](README.md) |
| `docs/README.md` | [Каноническое место](../README.md) |
