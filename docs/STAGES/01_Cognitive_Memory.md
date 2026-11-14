# Stage 1 — Когнитивная память

**Исторический статус:** завершено (`Complete`). **Назначение:** хранить опыт вне языковой модели и предоставлять ограниченный, прослеживаемый контекст.

## Исходная проблема

Журнал событий сам по себе не предоставляет эпизоды, смысловые связи, актуальные утверждения или удобный поиск. Сводка памяти, напротив, не может заменять первичный источник.

## Основные результаты

1. **Event Foundation:** строгие типы, `ev_<UUIDv4>`, источник, сессия, время, ссылки; долговечный `events.jsonl`.
2. **Memory Store:** `memory.db` (SQLite) хранит эпизоды, историю изменений, статусы, источники и метаданные.
3. **Entity / Relation / Provenance:** сущности и связи поддерживают организацию опыта; происхождение восстанавливается до первичных Events.
4. **Memory Processor:** selection, association, composition и контролируемый жизненный цикл эпизода `open / closed / merged`. Компоновка детерминированная, но не гарантирует идеального разделения смысловых эпизодов.
5. **Knowledge baseline:** `provisional / confirmed / challenged / superseded / rejected`; отмена или пересмотр утверждения не стирает историю его оснований.
6. **Retrieval + Context Builder:** SQLite FTS5, структурные фильтры, ссылки и бюджеты `FAST/DEEP`; полный журнал событий не обязан помещаться в контекст.
7. **Recovery:** восстановление обработки без создания повторных записей для уже завершённых входов.

## Подтверждение

Канонический [TV-0014](../TESTING/Results/TV-0014.md) проверял 37 raw Events в 11 сессиях, 11 автоматически сформированных эпизодов, restart/replay, Knowledge challenge/supersession, retrieval и бюджет Context. [TV-0015](../TESTING/Results/TV-0015.md) измерил 1k/10k/100k и выявил рост цены повторных полных сканирований raw журнала; `Passed` там означает завершённый baseline, **не** хороший SLO. Подэтапы TV-0004–TV-0013 доступны в [реестре](../TESTING/Results/README.md).

## Границы

Stage 1 не доказал универсального извлечения фактов, надёжности семантического Knowledge из произвольного текста или постоянной скорости на больших журналах. Более поздний [Event Retrieval v1](../ROADMAP/Memory_Event_Retrieval_v1_Results.md) является отдельным проверенным развитием read path; эксперименты Encoding/Graph/Meta-memory не приняты автоматически в production.

**Код:** [EventProcessing](../../anima/memory/event_processing.py), [Processor](../../anima/memory/processor.py), [Store](../../anima/memory/memory_store.py), [Retrieval](../../anima/memory/retrieval.py).  
**Архитектура:** [Память и источники](../ARCHITECTURE/Memory_and_Retrieval.md); решение [ADR-005](../DECISIONS/README.md#adr-005).
