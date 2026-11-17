# ANIMA v0.2 — H5 Independent Review Brief (неисполняемое ТЗ для Work)

**Тип работы:** независимая техническая проверка состояния Foundation Hardening без права изменять GitHub.  
**Репозиторий:** `VankoRokh/ANIMA`.  
**Рабочая ветка:** `work/v02-h5-readonly-release-gates`.  
**Snapshot:** reviewer обязан зафиксировать **фактический** `git rev-parse HEAD` перед началом. Не подменять snapshot именем ветки.  
**База:** после H4 владелец сообщил `1903 passed` / 86,95 с, quality probe 4 pairs: false merges 0, false splits 1. Эти результаты **reported by owner**, не считать независимым воспроизведением.

## Роль

Вы — независимый reviewer, не участник предыдущей реализации и не автор оправданий архитектуры. Проверяйте наблюдаемое поведение и первичные файлы, а не только наличие успешных тестов и зелёную документацию. Нужен воспроизводимый вердикт о готовности к H5/RC.

**Запрещено:** менять исходники, тесты, миграции, пользовательские файлы, `main` или архив исходных данных; запускать destructive/repair команды на реальных хранилищах; подменять тестовый контроль ожидаемыми результатами; трактовать benchmark из 4 пар как оценку семантической точности на реальных данных.

**Разрешено:** read-only GitHub, собственные временные каталоги/копии для запуска pytest, процессные аварийные испытания только на синтетическом экземпляре, диагностика кодовых путей и подготовка отчёта. При отсутствии исполнения явно отделять inspection от reproduction.

## Источники и scope

1. Независимый `ANIMA R1-S1 Structural Memory Audit` от 17.11.2026 (N1–N9), результаты M-T2/M-T2B/M-T2C и утверждённые контрактные цели.
2. `ANIMA_v0.2_Foundation_Hardening_Plan.md`, особенно INV-E1/E2/E3/K1/K2/R1/Q1/A1/M1 и H2.3/H5.
3. Тесты `tests/test_v02_h0_foundation_contracts.py` (9 обычных PASS на H4), `test_v02_h1_*`, `test_v02_h2_*`, `test_v02_h3_*`, `test_v02_h4_*`, `test_v02_h5_legacy_diagnostic.py`.
4. `anima/memory/{event_log,event_processing,event_retrieval,memory_store,knowledge,link_store,retrieval,processor,provenance,context_builder}.py`, `anima/release_v01.py`, `labs/v02_h5_legacy_diagnostic.py`.

## Проверочные вопросы высокого риска

**Raw → Recovery → Index.** Реальный write order между двумя хранилищами; ошибки неполного LF; атомарность или её отсутствие; versioned recovery; валидность cached prefix hash после SQLite rollback и параллельного индексатора; подмена Raw в середине; осмысленность `complete` и отрицательного поиска при старом индексе.

**Evidence/Knowledge.** Нельзя ли создать `confirmed` через другие низкоуровневые пути, SQL/API или `supersede` без годного Evidence? Что произойдёт с историческими `confirmed`, истёкшими источниками, доказательством от merged/open Memory? Нет ли orphan в memory_sources, legacy tables или в `ProvenanceResolver`? Проверить новый H5.0 diagnostic на clean and deliberately dirty fixtures, совместимость с WAL snapshot, отсутствие записи в источники.

**Entity/Episode.** Не используется ли всё ещё неподтверждённая ссылка как положительный authority в каком-то другом production пути? Экспериментальный Shadow не принимать за production. При пустом references + явном references на другой стороне не возникает ли скрытого merge? Какая цена false splits, как она растёт при длинных потоках и языках, отличных от английского? Проверить известные C1/C3/C4/C5 без подбора тестов под outcome.

**Time/Retrieval.** Единый `[created_at,valid_until)` во всех текущих consumers, explicit/history разграничение; смешанные часовые пояса; FTS ранжирование и `top_k` после SQL-фильтрации; truthfulness `fts_truncated` и coverage.

**Compatibility.** Старые базы без столбцов index; `PROCESSOR_VERSION="1.0"` при смене алгоритма; отсутствие незаметной перенумерации/переобработки; `release_v01.PROTOCOL` ещё v0.1; snapshot backup/restore всех компонентов; сценарий `memory.db` со старыми orphan relation; не менять оригинальные пользовательские данные автоматически.

**Fault injection.** Исключения до/после Raw append, после Memory transaction, после Index sync, в момент reopen; повторный replay; два независимых процесса против общего каталога; отсутствующие/удалённые data; read-only диагностика старой БД. Не заявлять реальные power-loss гарантии по симулированным сигналам.

**Performance.** Повторить 160/640 Events и 1k/10k/50k index-prefix benchmark, измерить p50/p95, память, скорость восстановления и предельную нагрузку. Зафиксировать budget и известный линейный overhead, не скрывать O(N) полный просмотр Raw у `_require_raw_event` и `recover`.

## Минимальное воспроизведение

- Сохранить SHA `HEAD`, ветку, Python, SQLite, CPU architecture и `git status --short`.
- Полный pytest на Python 3.14.4. Для Python 3.12 — доступный subset, честно сообщать пропуски и причины.
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
