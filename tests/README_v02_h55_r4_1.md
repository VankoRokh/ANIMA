# ANIMA v0.2 — H5.5 R4.1 / F-03 (Finalized Projection Retention)

**Статус:** R4.1/F-03 **принят владельцем** по адресным `73 passed` за 3,01 с и полной регрессии `2007 passed` за 88,16 с. Независимый повторный H5.5 ещё не выполнен.  
**Ветка:** `work/v02-h55-r4-projection-retention`, основана на принятом R3 @ `65d09495c31d7b094283ee16b01edf9929927417`.  
**R3 подтверждён владельцем:** адресные `68 passed` за 1,51 с; полная регрессия `1999 passed` за 88,71 с.  
**RC:** `BLOCKED` (R4.1 — только первый из пяти P2; raw-unbound R2 и независимый повторный review остаются).

## Первичный контрпример F-03

Источник — переданный владельцем независимый архив `ANIMA_v0.2_H5.5_evidence.zip`, `h55_work/independent_probes.py::projection_delete`, `h55_work/independent.json`, отчёт `ANIMA_v0.2_H5.5_Independent_Release_Audit.md`.

Аудитор выполнял:
1. `open_release(root)`; `report("h55deleted marker")` создаёт Event и Memory, `event_processing` фиксирует `done`.
2. `core.memory_store.delete_memory(memory_id)` **успешно** удалял Memory без Knowledge/history Relations. `memory_sources` удалялись каскадно; Raw Event и `done` оставались.
3. После нового `open_release()` обработка исходного Event возвращала `{"action":"already_done","memory_id":null}`. `context` терял Memory, хотя `search_events` продолжал находить Raw.
4. `analyze_snapshot` фиксировал `done_without_source` и `BLOCKED`, но обычный Recovery **не восстанавливал** projection.

Повторная обработка `done` без отдельной модели tombstone/revision нарушила бы идемпотентность. Поэтому стратегия R4.1 — **запрет разрушительной операции + fail-closed детекция существующего повреждения**.

## Исправление

### A. Штатный writer — `anima/memory/memory_store.py::delete_memory()`

В одной `BEGIN IMMEDIATE` транзакции перед `DELETE` выполняется проверка:
```sql
SELECT ep.event_id, ep.processor_version
FROM memory_sources AS ms
JOIN event_processing AS ep ON ep.event_id = ms.event_id
WHERE ms.memory_id = ?
  AND ep.processor = 'memory_processor'
  AND ep.status = 'done'
ORDER BY ep.event_id, ep.processor_version
LIMIT 1;
```
При наличии такого источника выбрасывается `ValueError("Cannot delete Memory with finalized Event processing projection: ...")`. Никакой `DELETE`, изменение ledger, каскадное удаление source links или перезапись Raw не происходит. Проверяются все версии processor, чтобы новый код не снимал защиту старого `done`.

`MemoryStore` без `done` (исторический прямой ввод, несвязанные standalone/тестовые экземпляры) сохраняет прежнюю семантику удаления при отсутствии иных History/Relation зависимостей. Исторические `skipped` не обязаны иметь Memory и не превращаются в `done`.

### B. Coordinator — `anima/memory/event_processing.py`

- `recover()` теперь **до `_bootstrap_missing`** проверяет финализированные записи `done` текущей версии processor: если `memory_sources` не содержит Event, выдаёт `ValueError("Finalized Event processing missing Memory source(s) ...; recovery refused")`. `skipped` исключены.
- `_replay_result()` не может больше возвращать ложный `already_done` с `memory_id=None`. При legacy-повреждении он выдаёт `ValueError("Finalized Event processing missing Memory source ...; replay refused")`.
- Не меняются `PROCESSOR_VERSION="1.0"`, Event statuses, `attempts`, Raw EventLog, Memory schema, EventProcessing._bootstrap_missing, процедура idempotent recovery. **Автоматически восстанавливать старые `done` запрещено.**

**Ограничение:** direct SQL, ручное удаление SQLite-файлов или некооперативные writers могут обойти запрет штатного `delete_memory`. В этом случае `recover` или `replay` обнаружит нарушение **только при обращении к текущей версии ledger**; глобальное восстановление без операторского протокола не предлагается. Исторические экземпляры с F-03 требуют ручного triage офлайновой копии и H5.4b diagnostic; молчаливого repair нет.

## Тесты

Новый файл `tests/test_v02_h55_r4_1_projection_retention.py` — **8 тестов**:

1. Первичный аудиторский `open_release → report → delete → reopen/replay/context/search`: delete отказывает, Raw/Memory/ledger неизменны, context содержит Memory, replay возвращает тот же `memory_id`.
2. Старый `processor_version="0.9"` c `done` также защищает связанную Memory.
3. Независимый `MemoryStore(memory.db)` не может обойти сохранённую `done`-зависимость.
4. Одна Memory с двумя финализированными Events не может быть удалена.
5. Unfinalized standalone Memory без History/Relations по-прежнему разрешено удалить.
6. Прямое legacy SQL-повреждение только в `pytest tmp_path`: `process()` не возвращает ложный успех и не меняет `done`/Raw.
7. Прямое legacy SQL-повреждение: `recover()` отказывает перед adoption новых Raw Events и не выполняет replay. H5.4b сообщает `BLOCKED`.
8. `skipped` Event с отсутствующей Memory успешно проходит `recover()`.

**Подтверждено владельцем:** адресные `73 passed` / 3,01 с и полная регрессия `2007 passed` / 88,16 с. Следующий R4.2 требует отдельной проверки.

### Локальный запуск

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r4_1_projection_retention.py \
  tests/test_event_processing.py \
  tests/test_v02_h2_2_memory_dependencies.py \
  tests/test_v02_h5_4_compatibility.py \
  tests/test_v02_h55_r1_evidence_lifecycle.py \
  tests/test_v02_h55_r2_raw_provenance.py \
  tests/test_v02_h55_r3_evidence_consistency.py \
  tests/test_release_v01.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

### Приёмочный критерий

Все восемь новых проверок и полная регрессия успешны. Результат `delete_memory` для `done` не меняет ни исходную Memory, ни Ledger, ни Raw; повторный `open_release` сохраняет Memory в Context. Старое повреждение обнаруживается с `ValueError`, без replay и без усугубления состояния.

Проверить также H5.2 fault-recovery и H5.4a backup/restore до независимого review.

## После R4.1

R4.2 — F-05 (Temporal Relations при `MemoryLifecycle.merge`) — [подготовлен в следующей ветке](README_v02_h55_r4_2.md), ещё не испытан.  
R4.3 — F-06 (одинаковые правила `KnowledgeLayer.confirm()` с/без source ID при будущих Relations).  
R4.4 — F-07 (передача `Retrieval.fts_truncated` в `ContextBuilder`).  
R4.5 — F-08 (уточнение forensic byte-read-only границы SQLite WAL/SHM snapshot).

Нельзя объявлять v0.2 RC без независимого аудита исправленного SHA, решения по R2 unbound Legacy и определения оставшихся release-gates.
