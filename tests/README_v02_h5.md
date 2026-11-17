# ANIMA v0.2 — H5 / Integration, Legacy Data & Release Candidate Gates

**Статус H5:** H5.0 принят; H5.1 подтверждён на x86_64 / Python 3.14.4, Python 3.12 остаётся NOT_TESTED; H5.2 подготовлен к испытаниям. **H5/RC целиком не принят**.  
**База для работ:** H4 `work/v02-h4-identity-guard`, принятый владельцем после `1903 passed` за 86,95 с, без XFAIL. Quality probe: 4 синтетические пары; 0 false merges, 1 false split; precision 1.0, recall 0.5 (эти числа не переносить на реальные данные).  
**Ветка H5.0:** `work/v02-h5-readonly-release-gates`. **Рабочая ветка H5.1:** `work/v02-h5-portability-profile`. **Рабочая ветка H5.2:** `work/v02-h5-fault-recovery`.

## Позиция перед RC

Все девять исходных N1–N9 перешли в обычный PASS на синтетических регрессиях. **Это не равнозначно готовности Release Candidate**: требуется доказательство непротиворечивости старых данных, миграции индекса, отказоустойчивости и совместимости разных путей доступа.

Изначальный план `ANIMA_v0.2_Foundation_Hardening_Plan.md` требует H2.3 (Existing Data), H5 интеграционных и аварийных тестов, Python 3.12/3.14, производительности, backup/restore и независимого ревью. Принятые H2.1/H2.2 не осуществляли автоматическую проверку **всех ранее записанных** Knowledge; этот пробел остаётся отдельным релизным gate.

## H5.0 — Read-only legacy diagnostics (✅ принято по полной регрессии)

`labs/v02_h5_legacy_diagnostic.py` — **только диагностика офлайновой копии**, не миграция. Код:

- подключает SQLite `mode=ro` + `PRAGMA query_only=ON`, НЕ создаёт `MemoryStore` и НЕ запускает `EventLog.write`;
- читает полностью завершённый Raw JSONL и проверяет каждый Event, повторения ID и границу LF;
- проверяет наличие основных таблиц, `PRAGMA quick_check` и `PRAGMA foreign_key_check`;
- проверяет соответствие `schema_meta.schema_version == 1` существующему контракту (не меняет номер версии);
- находит осиротевшие концы и `source_memory_id` Relations, некорректные интервалы, `merged_into` без цели;
- сообщает о `confirmed` без актуального CLOSED Memory support и без confirmation history;
- проверяет `memory_sources` и `done/skipped` из `event_processing` на наличие Raw Event **только если Raw полностью валиден**;
- выводит JSON `healthy/degraded/unverified`, количество проблем и не более 8 идентификаторов на категорию; Memory text в отчёт не включается;
- **никогда ничего не исправляет** и не переписывает history.

**Интерпретация:** `healthy` значит «не обнаружено нарушений по этим конкретным проверкам на предоставленном согласованном снимке». Это НЕ аттестация семантической достоверности, исходных файлов, отсутствия скрытого повреждения индекса, nor cryptographic provenance. Если Raw не передан, состояние `unverified`; если Raw невалиден, ошибки `missing_raw` на основании неполного чтения **не утверждаются**.

`tests/test_v02_h5_legacy_diagnostic.py` — 8 сценариев: здоровое состояние без изменения байтов, direct-confirmed без поддержки/истории, legacy orphan, пропавший Raw для Memory/ledger, torn tail, отсутствие Raw для проверки полноты, неполная схема. **Владелец подтвердил полную регрессию: `1911 passed` за 87,92 с.**

### Запуск на test fixtures

```bash
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q \
  tests/test_v02_h5_legacy_diagnostic.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

Результат, подтверждённый владельцем на предыдущем snapshot: **`1911 passed`** за 87,92 с. Новые коммиты H5.1 требуют отдельного прогона. При отказе/ошибке нельзя просто удалить тест или заглушить требование.

### Как обследовать существующий экземпляр без его изменения

1. Остановить ANIMA и все процессы, которые могут записывать в тот же instance root. Убедиться, что файлы больше не изменяются.
2. Создать **новый** отдельный каталог snapshot. Не запускать диагностику на работающей исходной базе.
3. Сделать согласованную SQLite-копию `memory.db` штатным `sqlite3.Connection.backup()`; отдельно скопировать `events.jsonl` после остановки записи. Не копировать только главный `memory.db` из работающего WAL-экземпляра: так теряются незавершённые checkpoint данные.
4. Зафиксировать SHA-256 файлов копии. Для полноценного backup/restore релиза потребуются **все** instance state/db файлы, а не только Memory/EventLog. Данная процедура — лишь диагностический snapshot.
5. Запустить диагностику **на копии**:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_legacy_diagnostic \
  --memory-db /path/to/snapshot/memory.db \
  --events /path/to/snapshot/events.jsonl
```

Пример безопасного SQLite-бэкапа после полной остановки записи:

```bash
export SRC=/path/to/stopped-anima-instance
export SNAP=/path/to/new-empty-h5-snapshot
mkdir -p "$SNAP"

.venv/bin/python - "$SRC/memory.db" "$SNAP/memory.db" <<'PY'
from pathlib import Path
from urllib.parse import quote
import sqlite3
import sys

source, target = map(Path, sys.argv[1:])
if not source.is_file() or target.exists():
    raise SystemExit("Source missing or destination DB already exists")
uri = "file:" + quote(str(source.resolve()), safe="/") + "?mode=ro"
with sqlite3.connect(uri, uri=True) as original:
    with sqlite3.connect(target) as copy:
        original.backup(copy)
PY

cp --no-clobber "$SRC/events.jsonl" "$SNAP/events.jsonl"
sha256sum "$SNAP/memory.db" "$SNAP/events.jsonl"
```

Операции создания `SNAP` и записи backup происходят **только** в новом каталоге копии. `SRC` не следует указывать на живой экземпляр; ни `cp`, ни `sqlite3.backup` не обеспечивают атомарности сразу двух файлов Raw/SQLite без остановки писателя.

## H5.1 — Reproducibility & portability (кандидат; тесты не запускались)

Новое средство `labs/v02_h5_portability.py` создаёт JSON-отчёт о Git HEAD, ветке, `git status --porcelain`, отдельных интерпретаторах CPython, SQLite/FTS5/JSON1, архитектуре и результате адресного pytest для **каждого** интерпретатора. Не обращается к пользовательской памяти, не создаёт миграций. Тесты используют `tmp_path`.

**Контракт результата:**
- `PASS`: доступный CPython 3.14 или 3.12, обнаруженные FTS5/JSON1, реально завершённый pytest с кодом 0, а также чистое дерево и известный HEAD для полного отчёта.
- `NOT_TESTED`: интерпретатор недоступен, отсутствует установленный `pytest`, probe/подпроцесс не завершён; это **не PASS**.
- `UNSUPPORTED`: версия Python/интерпретатор или возможности SQLite не соответствуют проверяемому профилю.
- `FAIL`: выполненный pytest вернул ненулевой код.
- Общий `INCOMPLETE` при любой недостаточности доказательств, включая dirty Git. Скрипт возвращает exit code **2**: это может означать отсутствие Python 3.12, не обязательно дефект ANIMA.

`tests/test_v02_h5_portability.py`: **10 тестов** (8 исходных плюс 2 регрессионных проверки virtualenv/symlink). До исправления владелец подтвердил полную регрессию `1919 passed` за 87,93 с, но первый H5.1 CLI ошибочно раскрывал `.venv/bin/python` в `/usr/bin/python3.14` через `Path.resolve()` и обнаруживал чужое окружение без pytest. Теперь сохраняется путь запуска, а JSON probe включает `sys_prefix`, `sys_base_prefix` и `executable`. **Исправление требует повторного запуска.**

### Запуск H5.1

```bash
git status --short
git rev-parse HEAD
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q \
  tests/test_v02_h5_portability.py
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**До исправления:** владелец сообщил `1919 passed` за 87,93 с. **После двух новых тестов:** расчётно ожидается `1921 passed` — это пока не результат исполнения.

Проверка реальных интерпретаторов и публикация machine-readable отчёта **вне репозитория**:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_portability \
  --python .venv/bin/python \
  --python python3.12 \
  --output /tmp/anima-h5-portability-symlink-fix.json
```

При успешном исправлении на машине владельца ожидается `runs[0].status=PASS`, `runs[0].probe.pytest_available=true`, `runs[0].probe.sys_prefix` указывает на `.venv`, а путь `runs[0].resolved` сохраняет `/.venv/bin/python`, **не** `/usr/bin/python3.14`. Прогон Python 3.12 остаётся отдельным.

Если Python 3.12 не установлен или в нём нет pytest, его запуск будет помечен `NOT_TESTED`; отчёт `INCOMPLETE` и возврат 2 — корректное отсутствие evidence. **Не устанавливать библиотеки в рабочее окружение или менять project interpreter ради косметического PASS.** Можно предоставить изолированное окружение Python 3.12 позднее.

**Границы:** адресный H5.1 набор специально ограничен: H0, H1.3, H2.2, H3.1–H3.2, H4, H5.0 и Stage1. Он **не** заменяет полную регрессию на 3.14, настоящий процессный crash test или проверку Raspberry Pi/aarch64. Отсутствующий aarch64 сохраняется в статусе `NOT VERIFIED`.

## Принятые результаты H5.1

По отчёту владельца **на snapshot `8d7f2f79fd10aa6c27ffd660891ef164a852b24d`**:
- `1921 passed` за 88,08 с, полная регрессия CPython 3.14.4, Linux x86_64.
- Адресный profile `65 passed` за 1,52 с; `sys_prefix` — проектное `.venv`, SQLite 3.46.1, FTS5/JSON1 доступны.
- `git status_porcelain` пустой; report для CPython 3.14.4 — `PASS`.
- `python3.12` не найден — `NOT_TESTED`, поэтому агрегированный profile `INCOMPLETE`.

**Решение:** H5.1 выполнен для профиля 3.14.4; кросс-версионная совместимость 3.12 **не подтверждена** и остаётся релизным вопросом. Не использовать `INCOMPLETE` как доказательство ошибки производственного кода.

## H5.2 — Fault injection & recovery (кандидат; локально не запускался)

`tests/test_v02_h5_2_fault_recovery.py` добавляет 7 сценариев:

1. **Принудительный `os._exit(73)` в отдельном процессе** после Raw append и создания ещё незафиксированного Memory, но до `SQLite COMMIT`. После рестарта: SQLite rollback, Raw не потерян, Recovery принимает его один раз, 3 повтора без дубля.
2. Raw append выполнен до вызова EventProcessingCoordinator → restart/adoption/replay, затем EventRetrieval догоняет Raw до полного индекса.
3. Memory processing уже зафиксирован, но индекс ещё не создан → restart, sync; без повторной обработки.
4. Искусственное исключение на втором Raw во время SQLite index transaction → rollback строк, FTS и курсора; повторный sync после reopen восстанавливает производный индекс.
5. Подмена содержимого в **середине** проиндексированного JSONL с последующим append → индекс отклоняет расширение, курсор и количество строк сохраняются.
6. Незавершённая физическая LF-строка → `recover()` и `EventLog.write()` отказ; EventRetrieval показывает `partial` и не выдаёт ложного `complete`.
7. Два отдельных Linux-процесса: блокировка `_single_writer` не выдаётся второму; после уничтожения держателя ОС освобождает блокировку.

Все операции с повреждениями, исключениями, смертью процессов и SQLite происходят **только в `pytest tmp_path`**. Эти испытания имитируют **процессный crash/rollback**, не реальную потерю питания. На других платформах два процессно-специфичных теста SKIP, не PASS.

### Запуск H5.2

```bash
git status --short
git rev-parse HEAD
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h5_2_fault_recovery.py \
  tests/test_event_processing.py \
  tests/test_release_v01.py \
  tests/test_v02_h1_2_finalized_raw.py \
  tests/test_v02_h1_3_prefix_digest.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Расчёт:** `1928 passed` (1921 + 7), если все существующие тесты остались неизменными. Это **не исполненный результат**.

### Ограничения / оставшиеся испытания

- SIGKILL во время полноценного release + параллельный внешний executor, а также недопустимые source authorities остаются предметом независимого аудита; существующие `test_release_v01.py` и H1 покрывают часть сценариев.
- `EventLog.write()` не делает файлового `fsync` на каждом событии, а отдельные SQLite/Raw хранилища не имеют общего транзакционного журнала. Строгую гарантию durability при физическом выключении питания **не заявлять**.
- Стоимость полного `Raw` сканирования на каждом `coordinator.process()` пока не решена: она должна попасть в H5.3 performance decision.
- `PROCESSOR_VERSION="1.0"` после изменения H4 остаётся вопросом H5.4.
- Часть высокорисковых сценариев остаётся за рамками 7 тестов: ручные изменения SQLite и Raw одновременно, consistency враждебного writer, truncation recovery через реальные disk faults.

## H5.3 — Performance / long-run (TODO)

До приёмки зафиксировать **численные** p50/p95 бюджета и максимально допустимую производственную нагрузку. Повторить наборы 160/640 Events и длинный поток, получить:

- ingest latency p50/p95, throughput, peak RSS, startup/reopen latency;
- размер Raw/Memory/Index и рост при N;
- стоимость H1.3 `prefix_digest` при 1k/10k/50k: принятый ориентир ноутбука 1.934/10.480/46.662 ms verified append, но **O(bytes)** остаётся;
- стоимость Recovery полного EventLog, повторного bootstrap, FTS и фильтрации;
- оценка ложных объединений/разделений на расширенном M-T2B/C, не только 4 пары H4.

Не уменьшать верификацию ради benchmark без независимого safety review.

## H5.4 — Migration, compatibility & rollback (TODO)

- Бэкап всех файлов и manifest hash; пробное восстановление в **новый каталог**.
- Старый индекс без `prefix_digest/indexed_count` → additive миграция на копии с проверкой старых row hashes; повторное открытие и повтор миграции должны быть безопасны.
- Сверка `memory.db` и Raw до/после, в том числе отслеживание legacy orphan/confirmed без support. Автоматически удалять или объявлять их восстановленными **запрещено**.
- Особый контракт: `EventProcessingCoordinator.PROCESSOR_VERSION == "1.0"` при изменённом H4-поведении. Уточнить, является ли это допустимым условием compatibility (старые done не перерабатываются) или требуется versioned projection/договор с миграцией; **не менять версию наугад**.
- `anima.release_v01` и `PROTOCOL=anima.release.v0_1/0.1` — действующий интерфейс; название внутренней ветки v0.2 не даёт права считать protocol автоматически обновлённым.
- Для schema migrations с невозможным downgrade — явно указать восстановление из backup.

## H5.5 — Independent review & RC (TODO)

Нужен внешний по отношению к автору изменений review snapshot с воспроизведением отрицательных и аварийных тестов, особенно N1/N2 authority, H2.3 legacy, H1.3 cache/DB checkpoints, performance O(N), аварийные переходы. Пакет для reviewer — `tests/H5_INDEPENDENT_REVIEW_BRIEF.md`.

**Граница этапа:** H5.0 — только наблюдение на копиях, H5 целиком не принят. Пока нет H5.1–H5.5, запрещено маркировать v0.2 `RC` или `stable` даже при зелёном pytest.
