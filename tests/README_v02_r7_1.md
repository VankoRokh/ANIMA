# ANIMA v0.2 — R7.1 Memory Source Integrity

**Исходная находка:** H56-06 (P2), независимый аудит H5.6 на `f70d879a88d88f63777646b0a65448765610402d`.
**База R7.1:** локально проверенный R7.0 `e56ff0bde0c92c84f914f6ec8f995e92f915933d` (`2117 passed` и `scripts/check.sh` PASS — **сообщено владельцем**).
**Статус R7.1:** IMPLEMENTED / LOCAL TESTS NOT YET REPORTED.

## Дефект и первичный репродуктор

`MemoryProcessor._best_candidate` принимает решение до начала writer-транзакции. В `_score_candidate` участвуют `memory_sources`:
- якоря и `anchor_conflict`;
- `Event.references` и `identity_conflict` (непроверенные заявления о Entity используются как **отрицательное**, не положительное свидетельство);
- `same_session` и `time_gap`.

`MemoryLifecycle.merge(source,target)` может перенести новые source IDs в target без изменения `memories` row: при одинаковых content и timestamp composer оставляет исходный текст. Проверка R6.2 `current != memory` не обнаруживает такое изменение. Поэтому отложенный direct `process_event` может обновить Memory, хотя свежий scorer отказал бы в объединении разных Entity claims.

H5.6 evidence: `probes/test_h56_findings.py::test_stale_source_set_is_rechecked_even_when_memory_row_is_unchanged`, `evidence/source_set_race.log`. Сценарий использует только публичные API и синтетические события.

## Контракт R7.1

1. **Snapshot реальных входов scorer.** `_score_candidate` сохраняет `candidate.source_event_ids` как отсортированный tuple ID *тех Raw-событий*, которые использованы для вычисления score, anchor, session и конфликта источников. Повторное отдельное чтение списка после скоринга не используется для создания snapshot — оно могло бы захватить уже другой набор.
2. **Atomic writer preflight.** Под тем же `BEGIN IMMEDIATE`, что и побочное действие, `_require_fresh_candidate_tx()` перечитывает `memories` row и `SELECT event_id FROM memory_sources ORDER BY event_id`. Обязательны одновременно:
   - существующая OPEN episodic user Memory;
   - полное равенство выбранной строки и текущей строки;
   - точное равенство отсортированного набора source IDs, использованного scorer.
3. **Fail-closed.** При любом расхождении — `ValueError('Stale MemoryProcessor candidate...')` до composer, INSERT `memory_sources`, INSERT `relations`, CREATE/UPDATE Memory. Не делается fallback create, не запускается автоматическая повторная оценка, не меняется Ledger.
4. **Охват путей:** direct `process_event`, `process_event(connection=...)`, а также действия `update`, `create_related` и `create` **с выбранным кандидатом**. Для `candidate=None` путь создания не изменяется: нет выбранного источника для сравнения. Последующая повторная проверка глобального ранжирования/новых кандидатов — отдельная архитектурная граница, не объявленная закрытой R7.1.
5. **Подтверждённое Knowledge:** прежний R6.2 `_require_no_confirmed_knowledge_dependencies()` остаётся обязательным в той же write-транзакции для `update`. `MemoryLifecycle.merge` не ослабляется.
6. **Источники:** Raw payload/подписи не получают криптографической неизменности. Для `entity_ids` текущий H4 API возвращает пустую проверенную группу; при будущем включении авторитетных Entity links соответствующие `about` inputs потребуют отдельной атомарной freshness policy. Внешний SQL вне API и внешний параллельный Raw writer не защищаются этим механизмом.
7. **Отсутствие миграции:** никаких дополнительных колонок `schema_meta`, `revision`, индексов, изменений схемы, переписывания Raw, изменений GitHub audit snapshot или реальных данных. Snapshot хранится в локальном Python candidate dict на время одной операции; не сериализуется в постоянную Memory.

## Негативные испытания

`tests/test_v02_r7_1_memory_source_integrity.py`:
- детерминированный pause scorer → публичный `merge` одинаковых текстов/времени при разных typed Entity claims → row не меняется, source IDs меняются → свежий scorer отвергает target → старый direct процессор обязан отказать без эффектов;
- внешний `connection=` writer-путь со stale candidate также обязан отказать, без нового ledger/Raw;
- `create_related` и `create` с выбранным stale candidate также отказывают до создания новой Memory;
- обычный `update` на неизменной source graph проходит;
- выбор кандидата уже после `merge` не обновляет смешанную Memory, а создаёт отдельную;
- snapshot scorer соответствует тем source IDs, которые были действительно использованы при выборе.

Новые тесты создают данные исключительно через `tmp_path`; гонка управляется `threading.Event`, не ожиданием произвольных sleep. Воспроизводимое состояние H56-06 не требует SQL corruption.

## Локальная приёмка

В чистом worktree точного SHA R7.1:

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python

PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r7_1_memory_source_integrity.py \
  tests/test_v02_r6_2_memory_mutation_integrity.py \
  tests/test_memory_processor.py \
  tests/test_memory_lifecycle.py \
  tests/test_event_processing.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
```

**PASS** только при успешной адресной и полной регрессии, документационном gate и зафиксированном SHA. Все предыдущие 2117 PASS относятся к R7.0; они не доказывают готовность R7.1 или релиза v0.2.

После R7.1 следуют R7.2 (H56-03), R7.3 (H56-04/05) и R7.4 + независимый H5.7.
