# ANIMA v0.2 — R7.3 Storage & Evidence Validation

**Цель:** устранить **H56-04 (P2)** и **H56-05 (P2)** из независимого H5.6.
**Основа:** локально проверенный R7.2 `6c3282d5e848a1e69d29930aa0ee380e5b30266b` (владелец сообщил `2135 passed`, `scripts/check.sh` PASS на Python 3.14.4).
**Источник аудита:** `ANIMA_v0_2_H56_Evidence.zip`, `probes/test_h56_findings.py`, отчёт H5.6.
**Статус:** IMPLEMENTED / LOCAL GATE NOT YET REPORTED.

## H56-04 — неподдерживаемая схема изменяется до отказа

Ранее `MemoryStore._initialize()` без предварительной проверки вызывал
`sqlite3.executescript(SCHEMA_SQL)`. `executescript` выполнял DDL до
чтения `schema_meta.schema_version`. SQLite существующей версии 999
получала таблицы, индексы, FTS и триггеры версии 1 ещё до `ValueError`.

**Контракт R7.3:**

1. Если файл БД уже существует, сначала открыть его **в режиме SQLite
   `mode=ro`** с `PRAGMA query_only=ON` и прочитать schema metadata.
   При явной неизвестной версии — `ValueError` **до открытия writable
   SQLite соединения и до любого DDL**. Это логическая read-only проверка
   SQLite, не обещание побайтовой forensic immutable-копии WAL/SHM.
2. Повторить проверку версии уже под `BEGIN IMMEDIATE` на одном writable
   соединении, чтобы закрыть TOCTOU между read-only preflight и bootstrap.
3. Не использовать `executescript()`: этот метод может выполнить
   неявный `COMMIT` перед DDL. Разбивать постоянный `SCHEMA_SQL` по
   полным SQLite statements через `sqlite3.complete_statement()`;
   каждый `connection.execute(statement)` и INSERT версии находятся
   **в одной транзакции**. Полная ошибка bootstrap откатывает уже
   исполненные DDL, не оставляя частично созданных таблиц.
4. Новая пустая БД создаётся по старому контракту с `SCHEMA_VERSION=1`,
   FTS5, индексами и триггерами. Существующая схема версии 1
   открывается. Если в старой БД нет `schema_meta` или самой
   `schema_version`, сохраняется прежняя политика bootstrap, **не**
   доказательство пригодности реального legacy экземпляра к миграции:
   необходим отдельный read-only H5.0/H5.4b gate.
5. Не создавать новые автоматические migration/repair операции,
   не повышать `SCHEMA_VERSION`, не использовать реальные данные.

## H56-05 — публикация повреждённого неактивного Evidence

В прежнем `KnowledgeLayer._require_published_evidence_raw_sources`
проверялись owner и Raw для всего `supports/contradicts` graph, но не
порядок границ **каждой** Relation. Допускаемое повреждённое legacy
состояние `[00:08,00:07)` не активно на момент публикации в 00:03,
поэтому Knowledge могло стать confirmed с повреждённым graph.

**Контракт R7.3:**

1. `_validate_evidence_interval(created_at, valid_until)` в
   `anima/memory/link_store.py` — единый валидатор временной формы:
   непустые offset-aware ISO 8601 timestamps; `valid_until=None`
   бессрочно, иначе `created_at < valid_until` по абсолютному instant.
   `[start,end)` остаётся полуоткрытым.
2. `LinkStore.create_relation()` для Memory Evidence применяет валидатор
   до INSERT. Прямой путь `KnowledgeLayer` сохраняет проверки
   пересечений против противоположной полярности.
3. `KnowledgeLayer._require_published_evidence_raw_sources()` применяет
   **тот же** валидатор ко всем attached `supports/contradicts` строкам,
   **до** фильтрации по активности, независимо от valid/current/future/expired.
   Ошибка — `ValueError`, без Knowledge status/History/Relation mutation.
   Все переходы `confirm/challenge/reject/supersede` используют этот guard.
4. Все ранее существовавшие проверки канонического Raw, CLOSED активной
   Memory, Source Authority, F-04/R3 opposite-overlap сохраняются. Никакие
   старые malformed intervals автоматически не редактируются.
5. Offline H5.0 продолжает обнаруживать `invalid_relation_interval` /
   `invalid_relation_timestamp` в read-only режиме. Если вход повреждён,
   supported lifecycle отказывает, даже если повреждение не влияет на
   активное Evidence в момент перехода.

## Испытания

`tests/test_v02_r7_3_storage_evidence_validation.py`:

- неизвестные версии `999`, `2`, `-1`, `future-schema`:
  неизменённые SHA256 файла, таблицы и пользовательская фикстура;
- повторное открытие поддерживаемой DB, создание новой DB
  с FTS5 и шестью триггерами;
- ошибка DDL на существующей несовместимой таблице:
  откат ранее выполненных DDL и побайтовая неизменность исходного DB;
- implicit/explicit confirm при инвертированных, пустых и naive
  интервалах future Evidence — атомарный отказ без изменения Raw/History;
- generic LinkStore writer отвергает аналогичные интервалы ещё на INSERT;
- challenge, reject и supersede после намеренного повреждения
  временной SQLite-копии — fail-closed;
- контроль: корректный future finite Evidence сохраняет интервалы и не
  блокирует публикацию; timezone offsets сравниваются как instants.

**Никаких реальных legacy-instance, Github audit branch или пользовательских
данных тесты не изменяют.** SQL повреждение допустимо только внутри
`pytest tmp_path`.

## Локальный gate

Проверить точный SHA worktree:

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python

PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r7_3_storage_evidence_validation.py \
  tests/test_v02_r7_2_lifecycle_write_authority.py \
  tests/test_v02_r7_0_temporal_authority.py \
  tests/test_v02_r6_1_knowledge_write_authority.py \
  tests/test_v02_h55_r4_3_temporal_confirmation.py \
  tests/test_knowledge.py \
  tests/test_v02_h5_4_compatibility.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
```

Результат считать `CLOSED / LOCALLY VERIFIED` **только после**
успешных адресных/полных прогонов и check на точном HEAD.
Зелёные тесты не означают независимую H5.7 приёмку или готовность v0.2 RC.

Следующий этап — R7.4: интеграция, связные отрицательные сценарии,
документация evidence и заморозка кандидата для H5.7 без release/tag.
