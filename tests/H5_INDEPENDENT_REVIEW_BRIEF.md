# ANIMA v0.2 — H5 Independent Review Brief (неисполняемое ТЗ для Work)

**Тип работы:** независимая техническая проверка состояния Foundation Hardening без права изменять GitHub.  
**Репозиторий:** `VankoRokh/ANIMA`.  
**Рабочая ветка:** `work/v02-h5-backup-rollback` (H5.0–H5.2 приняты в оговорённых пределах; H5.3c полный pytest принят владельцем, H5.4a backup/restore — ещё не испытан).  
**Snapshot:** reviewer обязан зафиксировать **фактический** `git rev-parse HEAD` перед началом. Не подменять snapshot именем ветки.  
**База:** после H4 владелец сообщил `1903 passed` / 86,95 с, quality probe 4 pairs: false merges 0, false splits 1; после H5.0 — `1911 passed` / 87,92 с; после H5.1 — `1921 passed` / 88,08 с, адресный suite 65 PASS на Python 3.14.4 (SQLite 3.46.1, x86_64), Python 3.12 `NOT_TESTED`. Владелец также сообщил по H5.2: адресные `38 passed` / 2,32 с, полная регрессия `1928 passed` / 87,62 с. Эти результаты **reported by owner**, не считать независимым воспроизведением. H5.3 владелец сообщил `1936 passed` / 88,66 с, benchmark 160/640 Events: process p95 7,8302/21,3727 ms, memory_count 1/1; throughput 175,447/75,423 events/s. H5.3b по отчёту владельца: `1944 passed` / 88,23 с; 12 независимых измерений (160/640 × 1/8 streams × 3), при 640/8 Memory association p95 median 26,531 мс, process p95 median 36,7278 мс, throughput median 43,691 событий/с, Raw scans/event median 2. H5.3c измерен владельцем на snapshot `2c8c60e886ca659f9b84b4bb47d0057e3780ba72` (clean Git, 12 прогонов): 160/8 Memory process p95 median 17,4898→12,5847 мс (−28,0%); 640/8 Memory 36,7278→25,0338 мс (−31,8%), zero cross-group merges и fragments. При 1 Memory p95 хуже (+18,4% / +9,4%); причины не доказаны. **Полный pytest H5.3c владелец сообщил: `1947 passed` за 93,68 с; независимое воспроизведение ещё не выполнено.** Все измерения — reported by owner; эксплуатационный SLO не утверждён.

## Роль

Вы — независимый reviewer, не участник предыдущей реализации и не автор оправданий архитектуры. Проверяйте наблюдаемое поведение и первичные файлы, а не только наличие успешных тестов и зелёную документацию. Нужен воспроизводимый вердикт о готовности к H5/RC.

**Запрещено:** менять исходники, тесты, миграции, пользовательские файлы, `main` или архив исходных данных; запускать destructive/repair команды на реальных хранилищах; подменять тестовый контроль ожидаемыми результатами; трактовать benchmark из 4 пар как оценку семантической точности на реальных данных.

**Разрешено:** read-only GitHub, собственные временные каталоги/копии для запуска pytest, процессные аварийные испытания только на синтетическом экземпляре, диагностика кодовых путей и подготовка отчёта. При отсутствии исполнения явно отделять inspection от reproduction.

## Источники и scope

1. Независимый `ANIMA R1-S1 Structural Memory Audit` от 17.11.2026 (N1–N9), результаты M-T2/M-T2B/M-T2C и утверждённые контрактные цели. **Если первичные отчёты не находятся в доступном репозитории, запросить их как отдельные вложения и пометить непроверяемые тезисы как reported, а не воспроизведённые.**
2. `ANIMA_v0.2_Foundation_Hardening_Plan.md`, особенно INV-E1/E2/E3/K1/K2/R1/Q1/A1/M1 и H2.3/H5.
3. Тесты `tests/test_v02_h0_foundation_contracts.py` (9 обычных PASS на H4), `test_v02_h1_*`, `test_v02_h2_*`, `test_v02_h3_*`, `test_v02_h4_*`, `test_v02_h5_legacy_diagnostic.py`, `test_v02_h5_portability.py`, `test_v02_h5_2_fault_recovery.py`, `test_v02_h5_3_performance.py`, `labs/v02_h5_portability.py`, `labs/v02_h5_performance.py`, `labs/v02_h5_scaling_diagnostics.py`, `tests/test_v02_h5_3_scaling_diagnostics.py`, `tests/test_v02_h5_3_entity_query_short_circuit.py`, `tests/test_v02_h5_4_snapshot_restore.py`, `labs/v02_h5_snapshot.py`.
4. `anima/memory/{event_log,event_processing,event_retrieval,memory_store,knowledge,link_store,retrieval,processor,provenance,context_builder}.py`, `anima/release_v01.py`, `labs/v02_h5_legacy_diagnostic.py`.

## Проверочные вопросы высокого риска

**Raw → Recovery → Index.** Реальный write order между двумя хранилищами; ошибки неполного LF; атомарность или её отсутствие; versioned recovery; валидность cached prefix hash после SQLite rollback и параллельного индексатора; подмена Raw в середине; осмысленность `complete` и отрицательного поиска при старом индексе.

**Evidence/Knowledge.** Нельзя ли создать `confirmed` через другие низкоуровневые пути, SQL/API или `supersede` без годного Evidence? Что произойдёт с историческими `confirmed`, истёкшими источниками, доказательством от merged/open Memory? Нет ли orphan в memory_sources, legacy tables или в `ProvenanceResolver`? Проверить новый H5.0 diagnostic на clean and deliberately dirty fixtures, совместимость с WAL snapshot, отсутствие записи в источники.

**Entity/Episode.** Не используется ли всё ещё неподтверждённая ссылка как положительный authority в каком-то другом production пути? Экспериментальный Shadow не принимать за production. При пустом references + явном references на другой стороне не возникает ли скрытого merge? Какая цена false splits, как она растёт при длинных потоках и языках, отличных от английского? Проверить известные C1/C3/C4/C5 без подбора тестов под outcome.

**Time/Retrieval.** Единый `[created_at,valid_until)` во всех текущих consumers, explicit/history разграничение; смешанные часовые пояса; FTS ранжирование и `top_k` после SQL-фильтрации; truthfulness `fts_truncated` и coverage.

**Compatibility.** Старые базы без столбцов index; `PROCESSOR_VERSION="1.0"` при смене алгоритма; отсутствие незаметной перенумерации/переобработки; `release_v01.PROTOCOL` ещё v0.1; snapshot backup/restore всех компонентов; сценарий `memory.db` со старыми orphan relation; не менять оригинальные пользовательские данные автоматически.

**Fault injection.** Исключения до/после Raw append, после Memory transaction, после Index sync, в момент reopen; повторный replay; два независимых процесса против общего каталога; отсутствующие/удалённые data; read-only диагностика старой БД. Не заявлять реальные power-loss гарантии по симулированным сигналам.

**Performance.** Проверить 160/640 Events через `labs/v02_h5_performance.py`, а затем разницу одной Memory и чередующихся восьми Memory через `labs/v02_h5_scaling_diagnostics.py` (три повтора, фазовое измерение Raw guard/association); отдельно 1k/10k/50k index-prefix benchmark. Сверить p50/p95/max обработки, пропускную способность, индекс, Retrieval, Context, пик RSS и скорость восстановления; не трактовать `MEASURED_NO_RELEASE_SLO` как PASS. Потребовать повторный прогон для разброса. Зафиксировать бюджет и известный линейный overhead, не скрывать O(N) полный просмотр Raw у `_require_raw_event` и `recover`.

## Минимальное воспроизведение

- Сохранить SHA `HEAD`, ветку, Python, SQLite, CPU architecture и `git status --short`.
- Полный pytest на Python 3.14.4. Для Python 3.12 — доступный subset, честно сообщать пропуски и причины. H5.1 CLI обязан показывать `NOT_TESTED` для отсутствующих интерпретаторов и `INCOMPLETE` для грязного Git; это не эквивалент независимого подтверждения.
- Изолированные tests для H5.0 + N1–N9, затем аварийные и отрицательные сценарии сверх существующих тестов.
- Diagnostic запускать **только на согласованных временных копиях** (не реальных экземплярах).
- Проверить, что результаты независимого прогона воспроизводимы при смене порядка тестов и повторном запуске.
- При отсутствии доступа к исполняемому окружению собрать кодовый аудит, указать несостоявшиеся эксперименты и статус `NOT VERIFIED`, а не `PASS`.

## Формат заключения

1. **VERDICT:** `READY / BLOCKED / INSUFFICIENT EVIDENCE` — отдельно для H5.0 и для v0.2 RC.
2. Таблица `Finding ID | Severity (P0/P1/P2) | Exact location | Reproducer | Actual | Expected | Consequence | Fix proposal`.
3. Сводная матрица N1–N9, INV-E1...M1 и реально выполненных fault/compat/perf испытаний.
4. Критичные скрытые сценарии, которых не покрывают 1903 исторических теста.
5. Чёткая граница между `reported by owner`, `source inspected`, `independently reproduced`.
6. Требования к migration/backup/rollback и список нерешённых release blockers.
7. Рекомендация по очередности устранения проблем, **без непосредственных изменений репозитория**.

**Не выдавать готовность v0.2 RC по одному удачному pytest.** Если найдён P0 по целостности Raw, восстановлению или доверенности Evidence, вынести `BLOCKED` и приложить детерминированный репродуктор.

## Дополнительный H5.3c review gate

Прежде чем рекомендовать дальнейшие оптимизации, сравнить `_score_candidate` до/после по полному N1–N9, H4, C1/C3/C4/C5, 160/640 × 1/8 groups × 3, а не только по одномоментной скорости. Защитить semantics при `entity_ids=[]` и явно непустых authorised IDs. Проверить, что `_require_raw_event`, сырой `EventLog`, Recovery и проверка индекса не менялись. При ухудшении корректности или заметном росте false splits возвращать `BLOCKED` независимо от ускорения.

## Дополнительный H5.4 reviewer gate

Проверить `tests/README_v02_h5_4.md`: snapshot создаётся **только** при доступной кооперативной блокировке остановленного размеченного экземпляра; не копируются lock/WAL aux и не включается устаревший inode-bound `event_index.db` после restore; остальные DB проходят SQLite backup и восстановление без потери Raw ID, Knowledge и идентичности. Требовать доказательства, что исходная Memory/Raw не изменена, manifest повреждённой копии обнаруживается, восстановление никогда не перезаписывает существующий экземпляр, а legacy `confirmed`/orphan НЕ ремонтируются молча.

**Открытый вопрос:** `PROCESSOR_VERSION=1.0` при изменённой H4 логике — явно решить контракт совместимости old `done`/new projection, а не менять версию для косметического релиза. Публичный protocol остаётся `anima.release.v0_1/0.1`. H5.4a `1958 passed` — только расчёт до исполнения. Даже при green pytest v0.2 RC требует независимой проверки, реального migration dry-run и решения по 3.12/performance budget.
