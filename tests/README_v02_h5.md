# ANIMA v0.2 — H5 / Integration, Legacy Data & Release Candidate Gates

**Статус H5:** H5.0–H5.4b прошли полную регрессию владельца (`1967 passed`) и независимую регрессию аудитора на Python 3.14.4 и 3.12.14 (`1967 passed` на каждой версии). **H5.5 независимый вердикт BLOCKED**: F-01/F-02/F-04 P1. Исправление R1/F-01 в отдельной ветке реализовано, ещё не испытано. ANIMA v0.2 RC не принят.  
**База для работ:** H4 `work/v02-h4-identity-guard`, принятый владельцем после `1903 passed` за 86,95 с, без XFAIL. Quality probe: 4 синтетические пары; 0 false merges, 1 false split; precision 1.0, recall 0.5 (эти числа не переносить на реальные данные).  
**Ветка H5.0:** `work/v02-h5-readonly-release-gates`. **Рабочая ветка H5.1:** `work/v02-h5-portability-profile`. **Рабочая ветка H5.2:** `work/v02-h5-fault-recovery`. **Рабочая ветка H5.3:** `work/v02-h5-performance-profile`. **H5.3b:** `work/v02-h5-performance-diagnostics`. **H5.3c:** `work/v02-h5-performance-entity-query`. **H5.4a:** `work/v02-h5-backup-rollback`. **H5.4b:** `work/v02-h5-compatibility-contract`. **Frozen H5.5 audit:** `audit/v02-h5-rc-candidate` @ `28e8438f8408e85b52e237eaedcf024354a4522a`. **R1 remediation:** `work/v02-h55-evidence-remediation`.

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

## H5.2 — Fault injection & recovery (✅ принято владельцем)

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

**Подтверждено владельцем:** адресные `38 passed` за 2,32 с, полная регрессия `1928 passed` за 87,62 с. H5.2 принят по согласованным сценариям процессных прерываний; physical power-loss не проверялся.

### Ограничения / оставшиеся испытания

- SIGKILL во время полноценного release + параллельный внешний executor, а также недопустимые source authorities остаются предметом независимого аудита; существующие `test_release_v01.py` и H1 покрывают часть сценариев.
- `EventLog.write()` не делает файлового `fsync` на каждом событии, а отдельные SQLite/Raw хранилища не имеют общего транзакционного журнала. Строгую гарантию durability при физическом выключении питания **не заявлять**.
- Стоимость полного `Raw` сканирования на каждом `coordinator.process()` пока не решена: она должна попасть в H5.3 performance decision.
- `PROCESSOR_VERSION="1.0"` после изменения H4 остаётся вопросом H5.4.
- Часть высокорисковых сценариев остаётся за рамками 7 тестов: ручные изменения SQLite и Raw одновременно, consistency враждебного writer, truncation recovery через реальные disk faults.

## H5.3 — Performance & Endurance (измеритель подготовлен; результаты не получены)

Ветка `work/v02-h5-performance-profile` добавляет **только лабораторный измеритель**, без изменения production алгоритмов.

`labs/v02_h5_performance.py` создаёт отдельный ephemeral каталог + дочерний Python-процесс **для каждого** размера нагрузки. Используется детерминированный синтетический поток `conversation.user` с фиксированной структурой текста. Это не эталон реальной пользовательской памяти.

Сценарии по умолчанию: **160 и 640 Raw Events**. Для каждого измеряются:

- `append` — p50, p95, max записи одного Event в Raw;
- `process` — p50, p95, max обработки одного Event через `EventProcessingCoordinator`; индекс эффектов и ссылки `memory_sources` сверяются с количеством Raw;
- сквозные `ingest_wall_s`, `throughput_events_s`, распределение действий `create/update/create_related`;
- `process_early_quartile_p50_ms` против `process_late_quartile_p50_ms` и коэффициент роста для поиска накопления задержек;
- `reopen_ms`, `recovery_first_ms`, `recovery_repeat_ms`; два повторных Recovery должны оставаться идемпотентными;
- `index_initialize_ms`, `index_initial_sync_ms`, `index_unchanged_sync_ms` с требованием `complete`;
- пять повторных запросов к `EventRetrieval.search()`, `RetrievalEngine.retrieve()` и `ContextBuilder.build()` — p50/p95/max;
- размеры `events.jsonl`, `memory.db`, `event_index.db` и `peak_rss_mib` (Linux ru_maxrss, пик всего рабочего процесса).
- сравнение роста p95 обработки и времени первого Recovery для 160→640; `p95` определён методом **nearest-rank**.

`tests/test_v02_h5_3_performance.py`: **8 регрессионных проверок** корректности p95/median, численных ограничений, небольшой end-to-end обработки с полной provenance, независимого subprocess worker, коэффициентов роста и запрета перезаписи JSON-доказательства.

### Запуск

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q \
  tests/test_v02_h5_3_performance.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

Если существующий набор не изменится, расчётно ожидается **`1936 passed`** (1928 + 8). Это не исполненный прогон.

Сбор метрик в новый, отдельный файл **вне репозитория**:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_performance \
  --events 160 640 \
  --output /tmp/anima-h5-performance-160-640.json
```

Повторить отдельный, ранее принятый H1.3 benchmark на тех же CPU/диске:

```bash
PYTHONPATH="$PWD" .venv/bin/python \
  tests/bench_v02_h1_3_index_prefix.py \
  --events 1000 10000 50000
```

Четырёхпарный H4 quality probe (`tests/bench_v02_h4_identity_quality.py`) **не равнозначен** расширенной оценке false merges/splits. Критерий семантической точности на реальных многоязычных потоках нужно определить отдельно. Полный M-T2B/C корпус нельзя заменять этой синтетикой.

### Интерпретация и release gate

Отчёт H5.3 **всегда помечен** `measurement_status=MEASURED_NO_RELEASE_SLO`. Успешный запуск фиксирует поведение, но **не** является доказательством, что задержки приемлемы. Численные бюджеты p50/p95 и предельную загрузку необходимо согласовать **после** получения текущих измерений, не задним числом под увиденные значения.

Сравнить рост размера Raw, пикового RSS, p95 processing и Recovery при увеличении числа событий в 4 раза. Не скрывать O(N) чтение Raw в `EventProcessingCoordinator._require_raw_event` и `_best_candidate` и O(bytes) на H1.3 prefix verification.

**Границы:** измеряется один синтетический запуск на размер (нужны повторные прогоны для дисперсии), без реальной многозадачности, графического окружения, LLM, датчиков, внешнего исполнителя и физического power-loss. Скрипт ничего не удаляет вне `TemporaryDirectory`, пишет отчёт только по явно указанному новому пути. H5.3 не принят, пока не получены результаты измерений и не сформулированы эксплуатационные ограничения.

## H5.3 — Фактические измерения на ноутбуке владельца

**Snapshot:** `5a6f7ac8921178014fda3a7eed3d75abc0517fad`, clean Git, Linux x86_64, CPython 3.14.4, SQLite 3.46.1. Владелец сообщил полную регрессию **`1936 passed` / 88,66 с**; источник измерений — приведённый владельцем JSON `anima.v02.h5.performance/0.1`.

| Измеренная метрика | 160 Raw | 640 Raw |
|---|---:|---:|
| Memory count | 1 | 1 |
| Create / Update | 1 / 159 | 1 / 639 |
| Process p50 | 5,4633 ms | 13,3158 ms |
| Process p95 | 7,8302 ms | 21,3727 ms |
| Process max | 8,7638 ms | 37,512 ms |
| Processing throughput | 175,447 ev/s | 75,423 ev/s |
| Early-quartile median | 3,8862 ms | 5,2758 ms |
| Late-quartile median | 7,1953 ms | 20,0069 ms |
| First recovery | 5,7076 ms | 18,2148 ms |
| Peak worker RSS | 25,398 MiB | 26,273 MiB |
| Event search p95 | 0,858 ms | 1,176 ms |
| Memory search p95 | 0,5254 ms | 0,5753 ms |
| Context build p95 | 0,5317 ms | 0,5249 ms |

При четырёхкратном росте числа событий **process p95 вырос в 2,7295 раза**, первое восстановление — в **3,1913 раза**, скорость упала примерно на 57%. Но оба профиля формировали единственную Memory: это стресс **очень длинного эпизода**, а не покрытие разнородного графа памяти.

H1.3 `prefix_digest` benchmark на том же ноутбуке: checked append median **1,760 ms (1k)**, **10,553 ms (10k)**, **46,129 ms (50k)**. Числа согласуются с прежним ожидаемым `O(bytes)`; это **не константная проверка**. Принцип безопасности не ослаблялся.

**Вердикт:** H5.3 инструмент/данные — **measurement PASS**, эксплуатационная пригодность — **NOT YET ACCEPTED**. Нет согласованного p95 SLO, нет повторных прогонов, нет реальных многоэпизодных профилей. Удобный `MEASURED_NO_RELEASE_SLO` не переводить в релизный `PASS`.

## H5.3b — Диагностика роста задержек (кандидат)

Отдельная ветка `work/v02-h5-performance-diagnostics`. **Production не меняется.**

`labs/v02_h5_scaling_diagnostics.py` измеряет `raw_guard` (`_require_raw_event`), `association` (`_best_candidate`), `raw_scan` (`EventLog.load_events`), общий `process`, количество физических сканирований Raw на Event, Early/Late медианы и Recovery. Вложенные фазы пересекаются по времени: **нельзя** суммировать raw_scan и association как независимые затраты.

Сценарии: **160/640 событий × 1/8 чередующихся текстовых источников × 3 независимых процесса для каждой пары**. Группы отличаются структурным текстовым префиксом (`h53groupXX:`), а не необоснованным Entity ID; проверяются `source_links`, `finalized`, отсутствие смешивания разных групп, отдельно учитываются возможные `extra_memory_fragments`. Вся запись ведётся только в `TemporaryDirectory`.

Новые `tests/test_v02_h5_3_scaling_diagnostics.py` — **8 проверок** статистики, изоляции, реальной обработки минимального корпуса и запрета перезаписи отчёта. **Ещё не запущены.**

Запуск:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q \
  tests/test_v02_h5_3_scaling_diagnostics.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q

PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_scaling_diagnostics \
  --events 160 640 --streams 1 8 --repeats 3 \
  --output /tmp/anima-h53b-160-640.json
```

Расчётный полный pytest при неизменном составе: **`1944 passed`** (1936 + 8 новых). Это не результат исполнения.

**Критерий следующего решения:** сравнить медиану/диапазон process p95 между 1 и 8 историями, долю raw_guard/association, количество Raw-сканирований и ложных смешиваний. По итогам составить адресный план безопасной оптимизации с независимым негативным gate N1–N9. Не менять Raw authority, Event IDs, idempotence, H1.3 и H2/H4 по результату одного синтетического измерения.

## Принятые результаты H5.3b и переход к H5.3c

По первичному отчёту владельца `anima.v02.h5.scaling/0.1`, **snapshot `7b701a0f19be20bb7771ddd4161614a3d0da3605`**, Git clean, x86_64 / Python 3.14.4 / SQLite 3.46.1:

- Полная регрессия **`1944 passed` / 88,23 с**. В каждой конфигурации выполнены три независимых прогона.
- Для **160 событий / 1 Memory**: process p95 median **7,487 мс**, association p95 median **4,506 мс**, raw guard p95 median **2,117 мс**, throughput median **186,951 событий/с**.
- Для **160 событий / 8 Memory**: process p95 median **17,4898 мс**, association **14,3091 мс**, raw guard **2,248 мс**, throughput **69,687 событий/с**.
- Для **640 событий / 1 Memory**: process p95 median **21,9708 мс**, association **12,2866 мс**, raw guard **8,732 мс**, throughput **75,988 событий/с**.
- Для **640 событий / 8 Memory**: process p95 median **36,7278 мс**, association **26,5307 мс**, raw guard **9,644 мс**, throughput **43,691 событий/с**.
- Raw сканируется **дважды на событие** во всех профилях, то есть 320 чтений при 160 и 1280 при 640.
- `false_cross_group_memory_count=0` и `extra_memory_fragments=0` во всех 12 прогонах; единственная Memory в профильном `streams=1` и ровно восемь в `streams=8`.

**Анализ:** у памяти есть как зависимость от объёма Raw при предварительной проверке и загрузке Event sources, так и заметная зависимость `association` от числа эпизодов. Вложенные времена нельзя складывать: `association` уже включает один из двух полных сканов Raw. Сценарии сугубо синтетические, benchmark не измеряет качество свободной семантики.

### H5.3c — Удаление бесполезных Entity SQL (кандидат)

Ветка `work/v02-h5-performance-entity-query` **не меняет семантику**: в `MemoryProcessor._score_candidate` при `entity_ids=[]` больше не вызывается `_memory_entities(memory_id)`. После H4 `_event_entity_ids()` проверяет ID, но выдаёт пустой список доверенных привязок; следовательно прежний `entity_overlap=0` независимо от результата SQLite. При **непустом** `entity_ids` прежняя логика SQL-проверки и начисления бонуса сохранена. Тесты устанавливают этот контракт.

Это **только первая безопасная микрооптимизация**. Два полных сканирования Raw остаются неизменными. Никакого кэширования Raw без новой модели инвалидации, никакого обхода H1.3, никакой миграции или коррекции старых `about`. 

Добавлены **3 регрессионных теста** в `tests/test_v02_h5_3_entity_query_short_circuit.py`. Расчёт полной регрессии при неизменном составе: **`1947 passed`** (1944 + 3). Локального исполнения нового изменения ещё не было.

```bash
git status --short
git rev-parse HEAD
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q \
  tests/test_v02_h5_3_entity_query_short_circuit.py \
  tests/test_v02_h5_3_scaling_diagnostics.py \
  tests/test_v02_h4_identity_guard.py \
  tests/test_v02_h0_foundation_contracts.py
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_scaling_diagnostics \
  --events 160 640 --streams 1 8 --repeats 3 \
  --output /tmp/anima-h53c-160-640.json
```

Для A/B нужно сравнить **медианы трёх прогонов H5.3b против H5.3c** в каждой паре `count/streams`. Не объявлять ускорение гарантированным до получения результатов, рассматривать разброс `min/max`, отсутствие ложных объединений/разделений и полную регрессию. Если эффекта практически нет, **не наращивать оптимизацию наугад**: следующая область профилирования — пакетный доступ к Memory sources, синтаксический анализ источников и индексированное получение Raw с точной инвалидацией.

## Фактические A/B-результаты H5.3c (reported by owner)

**Baseline:** H5.3b `7b701a0f19be20bb7771ddd4161614a3d0da3605`; **Candidate:** H5.3c `2c8c60e886ca659f9b84b4bb47d0057e3780ba72`. Два clean Git snapshot; Linux x86_64 / CPython 3.14.4 / SQLite 3.46.1. В каждом snapshot 160/640 событий × 1/8 Memory × 3 независимых запуска; все 24 измерения представлены владельцем. H5.3c **в полной регрессии пока не подтверждён**: не считать benchmark доказательством `1947 PASS`.

| Нагрузка | Process p95 baseline → H5.3c (медианы трёх) | Изменение p95 | Association p95 baseline → H5.3c | Throughput baseline → H5.3c |
|---|---|---:|---|---|
| 160 / 1 Memory | 7,487 → 8,8671 мс | +18,4% | 4,506 → 4,961 мс | 186,951 → 179,172 ev/s |
| 160 / 8 Memory | 17,4898 → 12,5847 мс | **−28,0%** | 14,3091 → 9,1795 мс | 69,687 → 100,270 ev/s |
| 640 / 1 Memory | 21,9708 → 24,0368 мс | +9,4% | 12,2866 → 13,0327 мс | 75,988 → 75,562 ev/s |
| 640 / 8 Memory | 36,7278 → 25,0338 мс | **−31,8%** | 26,5307 → 15,6439 мс | 43,691 → 60,839 ev/s |

**Разброс:** все три `process p95` прогона восьми-Memory варианта H5.3c быстрее всех трёх baseline: для 160 событий диапазоны 12,3601–12,8832 vs 16,0848–17,5127 мс; для 640 событий 24,8156–25,3378 vs 29,2163–39,1272 мс. В single-Memory сценариях новый p95 хуже по медиане, но время `raw_guard` также выросло без изменения его кода; причинность этих отклонений по последовательному A/B **не установлена**. Для строгого разбора нужны чередующиеся запуски A/B/A/B при сопоставимой загрузке ноутбука.

**Корректность:** все 12 новых запусков показали ноль межгрупповых слияний и дополнительных фрагментов Memory, `raw_scans_total=2 × event_count`, то же распределение `create/update`, что у baseline. Это свидетельство **синтетического** соответствия, не замена H0–H4, M-T2C или полного pytest. Профиль `MEASURED_NO_RELEASE_SLO`, SLO для релиза не утверждался.

**Решение по H5.3c:** владелец сообщил полную регрессию `1947 passed` за 93,68 с; микрооптимизация принята в оговорённой синтетической области. Два полных Raw сканирования и вопросы общего performance SLO остаются. Более глубокая оптимизация Raw/association без отдельного подтверждения безопасности не выполняется.

## H5.4 — Migration, compatibility & rollback (прошла штатные тесты; H5.5 нашёл межкомпонентные дефекты)

**Подробное ТЗ:** [README_v02_h5_4.md](README_v02_h5_4.md).

**H5.4a подтверждён владельцем:** адресные `35 passed` / 2,57 с, полная регрессия `1959 passed` / 89,24 с. Snapshot, SHA-256 manifest, restore в новый каталог, legacy index rebuild, sandbox state и отрицательные проверки пройдены на синтетических экземплярах. Backup/restore настоящего пользовательского экземпляра, физическая долговечность и некооперативные писатели не испытаны.

**H5.4b** реализован в `work/v02-h5-compatibility-contract`; независимый аудитор воспроизвёл штатный успех тестов, но также обнаружил F-04 (ложный `NO_ISSUES_DETECTED` на противоречащих active evidence). В `labs/v02_h5_compatibility.py` — read-only аудит ledger и старых `about`; в `tests/test_v02_h5_4_compatibility.py` — 8 проверок. Версия `PROCESSOR_VERSION="1.0"` трактуется как namespace идемпотентности; повысить её без отдельной миграции — риск повторного проигрывания `done`. Старые `about` без авторизационного доказательства помещаются в категорию **REVIEW_REQUIRED**, не удаляются и не считаются автоматически ложными. Несоответствие Raw и ledger — **BLOCKED**.

```bash
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h5_4_compatibility.py \
  tests/test_v02_h5_4_snapshot_restore.py \
  tests/test_v02_h5_legacy_diagnostic.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Фактически воспроизведено:** `1967 passed` на Python 3.14.4 и 3.12.14 в независимом H5.5; наличие F-04 подтверждает недостаточность исходного набора тестов для общей непротиворечивости Evidence.

**Открытый RC вопрос:** реальная legacy DB пока не обследовалась. Без полномочий источников старых `about` нельзя признать их достоверными или автоматически пересобрать. Python 3.12 остаётся `NOT_TESTED`. Не маркировать v0.2 как RC при одном green pytest.

## H5.5 — Независимый аудит: BLOCKED, корректирующий цикл открыт

**Frozen code:** `28e8438f8408e85b52e237eaedcf024354a4522a` (`audit/v02-h5-rc-candidate`). Независимый H5.5 source/reproduction: **1967 PASS** на CPython 3.14.4 и **1967 PASS** на CPython 3.12.14, плюс восемь отдельно воспроизведённых контрпримеров. Raw EventLog, Recovery, индекс, sandbox-effect на проверенных сценариях выдержали дополнительные испытания.

**Вердикт RC — BLOCKED:** P1 F-01 (мутирование подтверждённой Memory через merge/update), F-02 (Knowledge confirmation без обязательного Raw), F-04 (противоположные active supports/contradicts не обнаруживаются H5 diagnostic). P2: F-03/F-05/F-06/F-07/F-08. Данные реальных экземпляров, Pi/aarch64 и измеримый эксплуатационный SLO не проверены. Никакие из исходных 1967 тестов не служат доказательством отсутствия этих дефектов.

**План и текущее исправление:** [README_v02_h55_remediation.md](README_v02_h55_remediation.md). R1/F-01 закрывает только переходы `confirm → merge/update` через штатные API, сохраняя исходную ревизию и Knowledge/Raw/History. Новые тесты пока **не выполнены**; расчёт `1975 passed`. R2/F-02, R3/F-04, R4/P2 — после отдельной проверки.

**H5.4b historical note:** предыдущий раздел был написан до независимого аудита; `1967 passed` теперь воспроизведены на двух версиях Python. Заявление об отсутствии ошибок Evidence/Knowledge по этим тестам было опровергнуто новыми межкомпонентными сценариями.

**RC не объявлять** до устранения P1, независимого повторного проверки нового SHA и явной политики оставшихся границ.

