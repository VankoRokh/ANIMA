# Документация ANIMA

[О проекте](../README.md) → [текущая работа и этапы](ROADMAP/README.md) →
нужный раздел. Этот же вход используется после перерыва и новым помощником.

| Вопрос | Каноническое место |
|---|---|
| Зачем создаётся ANIMA? | [О проекте](../README.md) |
| Текущая работа и статусы этапов? | [project.json](project.json); представление в [Roadmap](ROADMAP/README.md) |
| Какой semantic boundary принят для текущего Stage 7 interface slice? | [Stage 7 Semantic Boundary v0](ROADMAP/Stage_7_Semantic_Boundary_v0.md); решение [ADR-010](DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md) |
| Как проверять Stage 7 semantic contract до обучения? | [Stage 7 Semantic Conformance v0](TESTING/Stage7_Conformance_v0.md) |
| Что и как проверять дальше? | [Roadmap](ROADMAP/README.md); [идеи и эксперименты](ROADMAP/Research.md) |
| Как работает подтверждённый код? | [Architecture](ARCHITECTURE/README.md) |
| Почему принято решение? | [Decisions](DECISIONS/README.md) и отдельные ADR-файлы |
| Как проверять и наблюдать процесс? | [Testing](TESTING/README.md) |
| Что доказали показательные прогоны? | [Results](TESTING/Results/README.md) |
| Как установить, обновить, резервировать и вести документацию? | [Operations](OPERATIONS/README.md) |
| Куда переехали прежние документы? | [Archive](ARCHIVE/README.md) |

### Stage 7 design history

Текущий accepted boundary не стирает ранние design baselines. Для контекста и истории решений доступны:

- [SemanticCandidate v0](ROADMAP/Semantic_Candidate_v0.md);
- [Knowledge Lifecycle v0](ROADMAP/Knowledge_Lifecycle_v0.md);
- [Semantic Temporal Conflict v0](ROADMAP/Semantic_Temporal_Conflict_v0.md);
- [Semantic Verification v0](ROADMAP/Semantic_Verification_v0.md);
- [Bootstrap Knowledge v0](ROADMAP/Bootstrap_Knowledge_v0.md);
- [Dynamic Task Arbitration Concept](ROADMAP/Dynamic_Task_Arbitration_Concept.md);
- [Emergency Response Mode Concept](ROADMAP/Emergency_Response_Mode_Concept.md).

Если старый Stage 7 design-файл расходится с [Stage 7 Semantic Boundary v0](ROADMAP/Stage_7_Semantic_Boundary_v0.md), для текущего pre-training/read-only interface slice приоритет имеет accepted boundary. Исторические TV/audit результаты сохраняют исходную терминологию своего времени.

Правится только изменившийся источник. Затем `python3 scripts/update_docs.py`
обновляет сводки, а `bash scripts/check.sh` проверяет актуальность, ссылки,
достижимость и синтаксис. AUTO-блоки вручную не редактируются.
Схемы и команды — в [Operations](OPERATIONS/README.md#ведение-документации).
