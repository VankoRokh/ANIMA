# ANIMA v0.2 — H5.5 R4.5 / F-08: SQLite WAL/SHM read-only contract

**Статус:** R4.5/F-08 принят по полному прогону владельца: **`2044 passed` за 89,61 с**. Отдельная независимая проверка F-08 на новом SHA ещё не выполнялась; v0.2 RC **BLOCKED**.  
**Ветка:** `work/v02-h55-r4-wal-readonly-contract`, создана от принятого R4.4 @ `fb057e95b88905c3796b114a50305d9fcd97d6b1`.  
**R4.4 подтверждён владельцем:** полная регрессия `2038 passed` за 88,34 с после исправления Stage 6 тестового адаптера.  
**Frozen independent audit:** `audit/v02-h5-rc-candidate` @ `28e8438f8408e85b52e237eaedcf024354a4522a`.

## F-08: точное наблюдение независимого аудитора

Источник: `ANIMA_v0.2_H5.5_Independent_Release_Audit.md`, раздел «F-08 · WAL и точность read-only договора»; `ANIMA_v0.2_H5.5_evidence.zip`, `h55_work/independent_probes.py::snapshot_wal`, JSON-результаты `h55_work/independent*.json`.

После остановки размеченного release дочерний процесс открыл `memory.db`, включил `PRAGMA journal_mode=WAL`, закоммитил контрольную строку и вышел через `os._exit(74)`, оставив `memory.db-wal` и `memory.db-shm`. `create_snapshot()` прочитал SQLite с `mode=ro`, выполнил `PRAGMA query_only=ON` и `Connection.backup()`, затем восстановил закоммиченную строку в новом каталоге. **Это корректное логическое восстановление WAL.**

Однако **SHA-256 исходного `memory.db-shm` изменился**, при сохранении размера 32768 байт; Raw, Identity и основной `memory.db` в данном опыте не изменились. Поэтому прежнее обещание «весь исходный root побайтово неизменен» **неверно**. `mode=ro` означает read-only для SQL, а не неизменность вспомогательных физических файлов SQLite.

## Решение R4.5

**Утверждённый узкий контракт:** лабораторный `labs/v02_h5_snapshot.py create` — **logical offline backup**, а не forensic evidence copy. SQLite может обновить `-shm` и иные transient sidecars исходного каталога даже при остановленном приложении и корректном `mode=ro`. Ни `sqlite3.backup()`, ни `quick_check`, ни успешный `verify` не удостоверяют неизменность всех исходных файлов.

- В docstring `labs/v02_h5_snapshot.py` и `_read_only_sqlite_backup()` устранена неверная blanket-гарантия физической неизменности.
- Результат `create_snapshot()` и JSON CLI **аддитивно** содержат:
  ```json
  {
    "source_read_only_scope": "LOGICAL_SQLITE_BACKUP_SIDECARS_MAY_CHANGE",
    "forensic_byte_stability_guaranteed": false
  }
  ```
  Это **ограничение обещания**, а не утверждение, что bytes обязательно изменились. Ни один кодовый путь не скрывает изменение `-shm` и не объявляет source `forensic immutable`.
- Старые `SCHEMA=anima.v02.h5.snapshot/0.1`, manifest и `release_v01.PROTOCOL` **не менялись**. `verify` и `restore` сохраняют прежнюю семантику. Компоненты Memory/Raw/Knowledge не менялись. `-wal/-shm/-journal` по-прежнему не копируются в логический snapshot: их committed содержимое переносит `sqlite3.backup()`.
- **Если требуется судебно-техническая, побайтовая сохранность источника**, сначала остановить все писатели и **вне ANIMA** создать отдельно хранимый физический, офлайновый образ/клон исходных `*.db`, `*-wal`, `*-shm`, Raw и остальных файлов, сохранить доверенные хеши; выполнять SQLite backup **только на отдельной рабочей копии**, никогда на оригинальном доказательстве. Это процедура оператора, а не автоматически обещанная способность CLI.
- У `flock` остаётся граница только кооперативного писателя; hot-backup multi-DB+Raw при активных независимых writers и power-loss durability **не гарантированы**. Нет silent migration/legacy repairs/повторного replay `done`.
- Результат CLI не является signed forensic attestation. Не перепутать SHA-256 hash manifest на snapshot с криптографическим доказательством неизменности source.

## Проверки R4.5

Добавлено **6 новых pytest cases** в `tests/test_v02_h55_r4_5_wal_scope.py`:

1–3. Полное воспроизведение `snapshot_wal` для `memory.db`, `internal_state.db`, `core_state.db`: дочерний процесс с `os._exit(74)`, committed WAL, `create → verify → restore`, закоммиченная строка восстановлена, в snapshot нет физических `-wal/-shm`, Raw и Identity исходника проверены. **Не требовать, чтобы SHM обязательно изменился**: это зависит от SQLite/OS/состояния wal-index; гарантия отсутствует независимо от наблюдения.
4. В обычном (без принудительно оставленного WAL) экземпляре сообщение о forensic byte stability всё равно `false`; существующий manifest не меняется.
5. JSON CLI `create` прямо сообщает scope и отсутствие гарантии.
6. Практическая offline процедура: скопировать stopped исходник **со всеми** WAL/SHM на отдельную working copy через физическое копирование; выполнять SQLite backup только на working copy; проверить побайтовую неизменность **оригинала** и восстановленную WAL строку.

**Подтверждено владельцем:** полный pytest `2044 passed` / 89,61 с (2038 базовых + 6 новых). Это не означает, что весь исправленный H5.5 прошёл независимый аудит.

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r4_5_wal_scope.py \
  tests/test_v02_h5_4_snapshot_restore.py \
  tests/test_v02_h5_4_compatibility.py \
  tests/test_v02_h55_r4_4_context_coverage.py \
  tests/test_release_v01.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

## Приёмка и оставшиеся release gates

Принимать R4.5 лишь по результатам адресных и полной регрессий и подтверждения, что CLI **не** обещает forensic source bytes. Исходное аудиторское замечание F-08 — **contract correction**, а не обнаруженная потеря WAL или неисправность sqlite3.backup.

После подтверждения F-08 в пределах этого эксплуатационного scope все восемь исходных finding будут иметь отдельный disposition, **но RC не возникает автоматически**. После R4.5 отдельно подготовлен [R5 / обязательный Raw для standalone](README_v02_h55_r5.md) (ещё не испытан). До решения об RC остаются проверка legacy instances, portability Pi/aarch64, согласованный performance budget и **новый независимый H5.5 на новом замороженном SHA**.
