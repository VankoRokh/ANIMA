# ANIMA v0.2 — R6.4 Recovery Owner Integrity

**Статус:** IMPLEMENTED / LOCAL TESTS NOT YET REPORTED.
**Основа:** R6.3, коммит `264bad5df9cd774f8d68b715cef935249f26eb3a`.
**Finding:** независимый аудит H5.5 post-remediation, **NEW-06 (P2)**.
**План:** локальный gate → H5.6 независимый повторный аудит всех R6.

## Дефект

В исторически повреждённой SQLite БД можно отключить `PRAGMA foreign_keys` на отдельном соединении и удалить родительскую запись `memories`, сохранив запись в `memory_sources`. Прежний `_require_finalized_memory_sources()` проверял только существование строки `memory_sources`, а `_replay_result()` возвращал её `memory_id` без JOIN на существующий `memories.public_id`. В результате `done` мог ошибочно возвращать `already_done` со ссылкой на отсутствующую Memory.

Строка `memory_sources` **не** является доказательством существования Memory. Независимый аудит отверг такой сценарий.

## Контракт исправления

1. `EventProcessingCoordinator._durable_memory_sources(connection, event_id)` возвращает только подтверждённые через JOIN существующие Memory owners. Если найден **хотя бы один orphan**, возникает `ValueError`, даже если другая ссылка этого Event ещё валидна.
2. `recover()` в read-only preflight до `_bootstrap_missing()` ищет `done` с отсутствующими строками `memory_sources` **или** с orphan rows, используя LEFT JOIN `event_processing → memory_sources → memories`. Любой дефект блокирует весь recovery, без изменения ledger или Raw и без повторного исполнения.
3. `_replay_result()` не сообщает `already_done` без существующего Memory owner. Проверка проходит в той же read-транзакции, что и получение mapping.
4. `_bootstrap_missing()` не усыновляет legacy source как `done`, если `memory_sources` содержит orphan owner; ошибка вызывает rollback всей операции bootstrap. Это касается даже случаев, когда Event не имеет текущей processing ledger.
5. `skipped` продолжает работать без Memory. Нормальные `done`, replay и legacy adoption остаются допустимыми.
6. Никаких tombstone, auto-repair, SQL migration, изменения `PROCESSOR_VERSION`, перезаписи Raw либо операторского автоматического восстановления не добавлено.

**Область гарантий:** штатные публичные API для текущей пары `processor_name/processor_version`. Recovery preflight не объявляется полной проверкой произвольных исторических processor versions; полноценная offline диагностика продолжает выполнять `PRAGMA foreign_key_check` и выдавать `orphan_memory_source_owner`. Некооперативный SQL вне системных API не предотвращается, но обнаруженный orphan отвергается при recovery/replay/adoption.

## Испытания

`tests/test_v02_r6_4_recovery_owner_integrity.py` — **9 pytest cases**:
- повреждённый `done` не позволяет `recover()` выполнить adoption другого Raw Event;
- повторный `process(done)` отказывает, а ledger остаётся неизменным;
- новый экземпляр Core после reopen отказывает в replay/recovery;
- даже при одновременном валидном и отсутствующем owner Event считается повреждённым;
- legacy source с orphan без ledger не может быть принят как `done`;
- корректные done/replay/recover и legacy adoption не регрессируют;
- `skipped` без Memory остаётся допустимым;
- offline H5.0 обнаруживает orphan owner и H5.4b сообщает BLOCKED.

Повреждение производится исключительно отдельным `sqlite3.connect` в `pytest tmp_path` c `PRAGMA foreign_keys=OFF`. Ни один реальный экземпляр не затрагивается.

## Локальная приёмка

Создать отдельный worktree R6.4 с точным HEAD коммитом ветки. Пример из корня worktree:

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python

PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r6_4_recovery_owner_integrity.py \
  tests/test_v02_h55_r4_1_projection_retention.py \
  tests/test_event_processing.py \
  tests/test_v02_h5_4_compatibility.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
```

**Приёмка:** чистая адресная регрессия, полный pytest, документационный gate и точный SHA. До этого R6.4 не считается VERIFIED. R6.4 НЕ означает готовность v0.2 RC: результат всех исправлений R6 проверяется в H5.6 независимым reviewer на новом неизменяемом snapshot.
