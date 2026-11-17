# ANIMA v0.2 — H5.4 / Backup, Migration, Compatibility & Rollback

**Статус:** H5.4a и H5.4b ранее **приняты по отчётам владельца**, исходный H5.5 независимо воспроизвёл `1967 passed` на Python 3.14.4 и 3.12.14, но выявил межкомпонентные F-01–F-08. Последняя операционная поправка **R4.5/F-08 (кандидат)** уточняет WAL/SHM границу SQLite backup; H5.5 remediation RC ещё **не принят**.  
**Ветка H5.4a:** `work/v02-h5-backup-rollback`. **Ветка H5.4b:** `work/v02-h5-compatibility-contract`.  
**Основа:** H5.3c после полного прогона владельца: `1947 passed`, 93,68 с. 160/640 × 1/8 Memory × 3 повторения: при 8 Memory process p95 сократился примерно на 28–32% (синтетика; при 1 Memory устойчивого ускорения не установлено).

## H5.4a — Контракт безопасного восстановления

Добавлен исключительно лабораторный CLI `labs/v02_h5_snapshot.py` с операциями `create`, `verify`, `restore`. Ни одна из них не выполняет изменений производственного кода ANIMA, не исправляет legacy Knowledge и не обновляет `schema_version`.

- **Создание** разрешено только для существующего **остановленного** и явно размеченного `anima.release.v0_1/0.1` экземпляра. Требуются `release_profile.json`, `identity.json`, `state.json`, `memory.db`, `events.jsonl`, `internal_state.db`, `core_state.db`; для sandbox также `sandbox_world/virtual_door.db`, `core_work.db`, `tasks.db`, `execution.db`. Существующая `.anima-v01.lock` проверяется неблокирующим `flock` и **не создаётся/не копируется**. Если активен cooperative writer, создание запрещено.
- Перед созданием snapshot выполняется полная **read-only** проверка LF-терминации и структуры Raw Events через `EventLog.load_events()`. Повреждённый/torn Raw нельзя обозначить как recovery-ready snapshot; для его форензик-копии нужен иной, отдельный процесс.
- SQLite-базы копируются с помощью `sqlite3.Connection.backup()` из `mode=ro` соединения после `PRAGMA quick_check(1)`; Raw, Identity, State, release profile и другие обычные файлы копируются побайтово с SHA-256 сравнением источника и копии. SQLite `-wal/-shm/-journal` не копируются: committed state должен содержаться в SQLite backup.

  **Уточнение F-08 / R4.5:** `mode=ro` и `query_only` обеспечивают логическую read-only операцию, но **не гарантируют побайтовую неизменность всего source-root**: SQLite может изменить `-shm` при чтении committed WAL. Успешный `verify` удостоверяет **snapshot**, а не неизменность исходных sidecar-файлов. `create` теперь возвращает `source_read_only_scope=LOGICAL_SQLITE_BACKUP_SIDECARS_MAY_CHANGE` и `forensic_byte_stability_guaranteed=false`. Для forensic исходника нужен отдельный офлайновый побайтовый образ, а SQLite backup следует запускать на **рабочей копии** образа. См. [R4.5/F-08](README_v02_h55_r4_5.md).
- Создание возможно только в **новом** каталоге. Все файлы описаны `h5_snapshot_manifest.json` (SHA-256, размер, тип копирования), создаваемым **последним**: неполный snapshot не имеет manifest и не считается восстановимым. Manifest — контроль целостности, **не криптографическая подпись**; внешний SHA-256 manifest следует записать отдельно.
- **Проверка** сравнивает полный список файлов с manifest, их размеры/хеши и release profile. Повреждение, подмена path с `../`, symlink, отсутствие обязательных файлов → отказ. `verify` не мутирует snapshot.
- **Восстановление** из проверенного snapshot — только в ещё **не существующий** каталог. Исходный экземпляр не изменяется. `event_index.db` сохраняется в snapshot как архивное свидетельство, но **не переносится в активный восстановленный каталог**: его курсор ссылается на прежние `dev/ino` Raw. При `open_release` новый индекс создаётся и синхронизируется с восстановленным `events.jsonl`. Прочие сохранённые БД/Raw и ID копируются без изменения. Никакого автоматического повторного проигрывания `done` или удаления legacy data.
- `restore` не переключает рабочую конфигурацию или символьные ссылки на восстановленный экземпляр. Выбор его как основного и раздельное хранение старого каталога — **ручная операторская операция после проверки**.

**Ограничение:** `flock` кооперативный; непубличный процесс, пишущий SQLite/Raw напрямую, не заблокирован. Общий атомарный snapshot нескольких БД + Raw при работающих некооперативных писателях **не гарантирован**. Поэтому source должен быть остановлен; CLI не является hot-backup сервисом и не подтверждает power-loss durability.

**Не использовать** операции `create`/`restore` на реальных пользовательских данных до принятия тестов и независимого ревью. Все H5.4a испытания используют `pytest tmp_path`.

## Набор H5.4a

`tests/test_v02_h5_4_snapshot_restore.py`: **12 тестов**:
1. Сохраняет идентичность, Raw Event ID, legacy `done`/attempts и полноценный FTS-поиск после restore; исходные файлы остаются неизменными.
2. Сохраняет историю эффектов sandbox-world без нового выполнения действия после повторного открытия.
3. Отказывает при активном `open_release` с удерживаемой блокировкой без создания snapshot.
4. Отказывает перезаписывать существующий snapshot или восстановленный instance.
5. Отказывает при повреждённом Raw snapshot до создания целевого каталога.
6. Не принимает исходный неразмеченный экземпляр и символьные ссылки на внешние файлы.
7. Проверяет additive миграцию индекса `event_index_state` без `prefix_digest/indexed_count` **только на восстановленном тестовом каталоге**: Raw ID сохранён, prefix digest пересчитан.
8. Сохраняет legacy `confirmed` без валидного Evidence **без автоматического ремонта** и выдаёт `degraded` через H5.0.
9. Не признаёт snapshot из release с отсутствующим `identity.json`.
10. Не позволяет символьной ссылке в родительском каталоге обойти запрет вложенного snapshot.
11. Не допускает manifest path traversal или запись вне целевого каталога.
12. Отказывает в создании recovery-ready snapshot при исходном незавершённом Raw JSONL, не изменяя повреждённый источник.

### Запуск на тестовых данных

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q \
  tests/test_v02_h5_4_snapshot_restore.py \
  tests/test_v02_h5_legacy_diagnostic.py \
  tests/test_v02_h1_3_prefix_digest.py \
  tests/test_release_v01.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Подтверждено владельцем:** `35 passed` (адресные) / 2,57 с, `1959 passed` (полная регрессия) / 89,24 с. Это evidence выполнения на ноутбуке владельца, не независимое воспроизведение.

### Команды после приёмки (только остановленный, проверенный экземпляр)

```bash
PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_snapshot create \
  --source /ABSOLUTE/PATH/TO/STOPPED-RELEASE-INSTANCE \
  --destination /ABSOLUTE/PATH/TO/NEW-SNAPSHOT

PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_snapshot verify \
  --snapshot /ABSOLUTE/PATH/TO/NEW-SNAPSHOT

PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_snapshot restore \
  --snapshot /ABSOLUTE/PATH/TO/NEW-SNAPSHOT \
  --destination /ABSOLUTE/PATH/TO/NEW-RESTORED-INSTANCE
```

Операции возвращают JSON с хешем manifest; для внешнего хранения идентичности использовать `sha256sum /ABSOLUTE/PATH/TO/NEW-SNAPSHOT/h5_snapshot_manifest.json`. При ошибке до manifest может остаться **частичная** новая папка: её нельзя восстанавливать; инструмент намеренно не удаляет и не переиспользует такую директорию автоматически.

## H5.4b — Pinned ledger & legacy authority (принят по тестам, ограничения H5.5 сохраняются)

| Контракт | Текущее состояние | Риск / решение |
|---|---|---|
| `release_v01.PROTOCOL` | `anima.release.v0_1/0.1` | Внутренний v0.2 Foundation Hardening не даёт права молча повышать публичный протокол. Сохранить до отдельной спецификации. |
| `MemoryStore.SCHEMA_VERSION` | `1` | Сохранять при H5.4a; нет новой Memory schema migration. |
| `EventProcessingCoordinator.PROCESSOR_VERSION` | `1.0` | После H4 изменилась семантика, но старые `done` остаются завершёнными. **Не переключать версию наугад**, иначе старые события могут быть переобработаны и создать новые эффекты. |
| `EventRetrieval` index schema | additive `prefix_digest`, `indexed_count` | На месте — проверяемая миграция и пересчёт старого префикса. При восстановлении в новый каталог — отбросить производный индекс и построить из Raw. |
| Старые `confirmed` / `about` / `relations` | не исправлены автоматически | H5.0 обнаруживает ряд нарушений Evidence/Orphan. Исторические `about` без достоверной authority provenance требуют отдельного review; нельзя считать все `about` действительными или безусловно удалить. |
| Python 3.12 / Pi | `NOT_TESTED` | Отдельное обязательное/условное evidence, не подменять результатами 3.14. |

### Принятый технический принцип H5.4b

`EventProcessingCoordinator.PROCESSOR_VERSION = "1.0"` обозначает **namespace идемпотентности** по ключу `(event_id, processor, processor_version)`, а не идентичность всех семантических алгоритмов MemoryProcessor. После H4 новые ассоциации изменились, но старые `done/skipped` без отдельной явной миграции должны остаться финализированными. Просто поднять номер до `2.0` опасно: старые `done` перестали бы учитываться новым coordinator, возник бы риск повторной обработки и дублирования эффектов.

В `labs/v02_h5_compatibility.py` добавлен **read-only аудит только согласованной офлайновой копии** `memory.db` + `events.jsonl`, совместно с H5.0. Никакого `MemoryStore`, новой схемы, `EventProcessingCoordinator.recover()`, фонового исправления, reprocessing, переписывания Raw или изменения status не производится.

Диагностика возвращает:
- `NO_ISSUES_DETECTED`: не обнаружены нарушения проверяемых контрактов. Это **не** автоматическое разрешение RC, миграции или запуска реального экземпляра.
- `REVIEW_REQUIRED`: встречены исторические `memory → entity:about` без достаточных метаданных о полномочиях источника или записи `memory_processor` из других версий. Эти записи не объявляются ложными автоматически; они требуют отдельной ручной аттестации на копии.
- `BLOCKED`: H5.0 выявил нарушения integrity, отсутствует Raw для любого processing row, `done` без `memory_sources`, `skipped` с `memory_sources`, незавершённая обработка с уже сохранёнными Memory sources или один Event обработан под разными версиями.

Список finding ограничен 8 идентификаторами на категорию; тексты Memory не экспортируются. Отчёт содержит реальное распределение ledger по версиям и status, ожидаемые `SCHEMA_VERSION=1`, `PROTOCOL=anima.release.v0_1/0.1` и `PROCESSOR_VERSION=1.0`.

**8 новых тестов** в `tests/test_v02_h5_4_compatibility.py`: чистое состояние и неизменность файлов, legacy `about` + повтор старого `done` + новый конфликтующий Entity claim, иной processor version, двойная версия одного Event, `done` без источника, `skipped` с неожиданным источником, `pending` с источником, `pending` без Raw.

Команды локального прогона:
```bash
git status --short
git rev-parse HEAD
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h5_4_compatibility.py \
  tests/test_v02_h5_4_snapshot_restore.py \
  tests/test_v02_h5_legacy_diagnostic.py \
  tests/test_v02_h4_identity_guard.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Фактически выполнено:** владелец сообщил `1967 passed` на Python 3.14.4; независимый H5.5 повторил `1967 passed` на Python 3.14.4 и 3.12.14 для исходного SHA. Это **не доказательство отсутствия** позднее найденных F-01–F-08; исправления H5.5 требуют отдельной приёмки.

После приёмки запускать CLI можно **только на согласованной offline-копии**, например на новом snapshot из H5.4a:
```bash
PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_compatibility \
  --memory-db /path/to/SNAPSHOT/memory.db \
  --events /path/to/SNAPSHOT/events.jsonl \
  --output /tmp/anima-h54b-compatibility.json
```

Для `REVIEW_REQUIRED` или `BLOCKED` exit code 2 — это статус диагностики, не повод игнорировать проблему или запускать repair. Реальные исторические `about` и `confirmed` не следует переименовывать в доверенные знания без authority/provenance review.

**Решение, требующее утверждения до RC:** как фиксировать изменение семантики процессора H4, не перезапуская старые финализированные события; какие legacy записи маркировать как `requires_review` без неподтверждённой автоматической коррекции. Дальнейшее расширение H5.4 — отдельный version/migration contract, не скрытый побочный эффект snapshot.

**Rollback:** только выбор **отдельной** сохранённой копии, без перезаписи оригинала. Изменения схемы в тесте legacy index на копии обратного `down migration` не требуют: архивированный исходный snapshot остаётся нетронутым. Любую будущую необратимую миграцию предварительно блокировать без отдельного rollback contract.

**H5/RC:** текущая приёмка H5.4a/b не означает приёмки v0.2 RC. После корректирующих этапов R1–R4.5 необходимы отдельная оценка standalone/unbound Raw provenance, проверка реальных legacy данных на согласованной копии и новый независимый H5.5 на новом фиксированном SHA.
