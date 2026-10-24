# Документация ANIMA

[О проекте](../README.md) → [текущая работа и этапы](ROADMAP/README.md) →
нужный раздел. Этот же вход используется после перерыва и новым помощником.

| Вопрос | Каноническое место |
|---|---|
| Зачем создаётся ANIMA? | [О проекте](../README.md) |
| Текущая работа и статусы этапов? | [project.json](project.json); представление в [Roadmap](ROADMAP/README.md) |
| Что и как проверять дальше? | [Roadmap](ROADMAP/README.md); [идеи и эксперименты](ROADMAP/Research.md) |
| Как работает подтверждённый код? | [Architecture](ARCHITECTURE/README.md) |
| Почему принято решение? | [Decisions](DECISIONS/README.md) |
| Как проверять и наблюдать процесс? | [Testing](TESTING/README.md) |
| Что доказали показательные прогоны? | [Results](TESTING/Results/README.md) |
| Как установить, обновить, резервировать и вести документацию? | [Operations](OPERATIONS/README.md) |
| Куда переехали прежние документы? | [Archive](ARCHIVE/README.md) |

Правится только изменившийся источник. Затем `python3 scripts/update_docs.py`
обновляет сводки, а `bash scripts/check.sh` проверяет актуальность, ссылки,
достижимость и синтаксис. AUTO-блоки вручную не редактируются.
Схемы и команды — в [Operations](OPERATIONS/README.md#ведение-документации).
