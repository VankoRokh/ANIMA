# ANIMA v0.2 — H5.5 / Независимый Release Candidate Audit

**Статус:** H5.5 ещё не проведён. **v0.2 RC НЕ ПРИНЯТ.**  
**Роль:** внешний reviewer, а не исполнитель предыдущих изменений.  
**Репозиторий:** `VankoRokh/ANIMA`.  
**Фиксированная проверяемая ревизия:** `28e8438f8408e85b52e237eaedcf024354a4522a`.  
**Только для чтения:** `audit/v02-h5-rc-candidate`, зафиксирована на указанном commit.  
**Документация передачи задания:** `work/v02-h5-independent-audit-prep` (отдельная ветка; новые docs-коммиты НЕ меняют проверяемую ревизию).  
**Результат владельца перед аудитом:** адресные H5.4b + смежные `37 passed` за 1,22 с; вся регрессия `1967 passed` за 95,42 с. **Reported by owner**, не независимо воспроизведено.

## 1. Полномочия и ограничения

Проведи независимый технический, архитектурный и release-аудит именно фиксированной ревизии. **Не изменяй GitHub-репозиторий, ветки, исходники, тесты, документацию, production-данные, существующие instance roots или архивные Raw.** Не запускай repair/migration/delete в пользовательском экземпляре. Разрешены локальные одноразовые копии, лабораторные fixtures, запуск тестов, собственные воспроизводящие скрипты и отдельный отчёт.

Если Work имеет только GitHub-чтение и не может выполнить код, не придумывай запуск: помечай наблюдения `SOURCE INSPECTED` и оставляй `NOT REPRODUCED`. Если первичные отчёты R1-S1/N1–N9/M-T2B/C отсутствуют в доступных источниках, запроси их у владельца либо цитируй как `REPORTED BY OWNER`. Не считай 1967 тестов, симулированный SIGKILL или четыре синтетические пары доказательством всех гарантий.

## 2. Непереговорные инварианты

Проверь исходный документ `ANIMA_v0.2_Foundation_Hardening_Plan.md` и первичный R1-S1 отчёт (если доступен). Построй таблицу инвариантов `INV-E1/E2/E3/K1/K2/R1/Q1/A1/M1` со ссылками на **точные** production-пути, тесты и собственный воспроизведённый результат. Не придумывай расшифровки этих меток, если исходного документа нет.

1. **Raw authority:** не принимать Memory, Belief, Knowledge или finalized ledger без требуемого исходного Event; не путать Event.claim с Verified Entity identity. Raw недоверяемые typed references не дают `about` сами по себе.
2. **Event processing:** `(event_id, processor, processor_version)` — namespace идемпотентности. В версии `1.0` старые `done/skipped` не переобрабатываются; изменение H4 semantics не превращается в молчаливую повторную проекцию. `pending/failed`, missing Raw, duplicate versions — разные случаи.
3. **Evidence/Knowledge:** confirmed требует валидное CLOSED Memory evidence, support history и provenance; старые orphan/legacy confirmed могут существовать. Проверить границы runtime API vs direct SQL, выборочное и полное восстановление.
4. **Retrieval/index:** prefix digest и `indexed_count` корректно проверяют старый байтовый префикс при изменениях, tombstones, неполном JSONL и SQLite rollback; `coverage.complete` не заявляется без доказательства.
5. **Temporal relations:** единая семантика временных интервалов в `LinkStore`, `RetrievalEngine`, `ContextBuilder` и `ProvenanceResolver`.
6. **Backup/restore:** `labs/v02_h5_snapshot.py` работает только на остановленной размеченной v0.1 release, без overwrite, с проверкой manifest и сохранением Raw/identity; после переноса не активирует старый inode-bound `event_index.db`. Проверить последствия `wal`/журналов, отсутствие атомарности multi-DB без остановки писателя, безопасность путей/symlink.
7. **Legacy compatibility:** `labs/v02_h5_legacy_diagnostic.py` и `labs/v02_h5_compatibility.py` — read-only на согласованных offline copies. `REVIEW_REQUIRED` для legacy `about` не означает ложь; `NO_ISSUES_DETECTED` не означает подтверждённую семантику.
8. **Execution safety:** sandbox actions, Goal/Task и proof остаются независимы от текстовых пользовательских утверждений. При восстановлении эффект не должен применяться повторно.

## 3. Обязательное воспроизведение (при наличии исполняемого окружения)

Сначала зафиксируй `git rev-parse HEAD`, `git status --porcelain`, `python -VV`, `sqlite3.sqlite_version`, CPU arch, место хранения fixtures и hashes исходных тестовых copies. **HEAD должен совпадать с SHA выше**, а дерево быть чистым.

### Набор A — Регрессия

- Полный `PYTHONPATH="$PWD" .venv/bin/python -m pytest -q` для Linux x86_64 / CPython 3.14.4 (или явно раскрыть отличие окружения).
- Адресные H0–H5.4b: `tests/test_v02_h0_foundation_contracts.py`, `test_v02_h4_identity_guard.py`, `test_v02_h5_2_fault_recovery.py`, `test_v02_h5_4_snapshot_restore.py`, `test_v02_h5_4_compatibility.py`, `test_v02_h5_legacy_diagnostic.py`.
- M-T2B/C — первичные воспроизводящие скрипты или доступные существующие регрессии. Не заменять отдельные негативные кейсы суммарной оценкой.

### Набор B — Новые отрицательные испытания сверх текущего pytest

1. Состояния прерывания до/после Raw append, во время SQLite transaction, до/после index-sync и при повторном `recover()`, без дублей Memory/Action.
2. Исторические `done/skipped` в v1.0, такой же Event ID в v2.0, `pending` при наличии Memory source, orphan relations и отсутствующий Raw. Сравнить собственный диагностику H5.4b и реальное поведение Coordinator — они не обязаны совпадать для повреждённых данных.
3. Подмена середины Raw и append: отказ из-за `prefix_digest`/row count, неизменность cursor/FTS; legacy index без digest до/после миграции.
4. Неподтверждённый, поддельный, неактивный Entity ID; старый `about` из некорректного источника и новый несовместимый claim. Проверить отсутствие authority laundering через ассоциацию или retrieval.
5. Странные часы и временные интервалы; один и тот же момент в разных UTC offsets.
6. Snapshot при активной кооперативной блокировке; при отсутствующем файле state; source с `-wal`; malicious manifest/path traversal; повторное восстановление поверх существующего каталога; rebuild EventRetrieval из Raw в новом каталоге.

Испытания с SIGKILL/ошибкой SQLite делай **только** в disposable fixtures. Не имитируй power-loss и не утверждай доказательство физической долговечности.

### Набор C — Runtime/portability

- Исполнить адресный H5.1 probe по Python 3.14.4, и отдельно Python 3.12, **если он действительно доступен**. На текущем окружении владельца Python 3.12 был `NOT_TESTED` — это открытая совместимость, не `PASS`.
- Если доступен Raspberry Pi 5 / aarch64, выполнить smoke с указанием Python/SQLite/FTS5; если нет — `NOT_TESTED`.
- `anima.release_v01.PROTOCOL` по-прежнему `anima.release.v0_1/0.1`. Не объявлять публичный протокол v0.2 без нового контракта.

### Набор D — Производительность/качество

Оперируй **измерениями, а не обещаниями**. Контрольные данные владельца:

| Нагрузка | H5.3b p95 | H5.3c p95 | Условие |
|---|---:|---:|---|
| 160 Events / 1 Memory | 7,487 ms | 8,8671 ms | возможное ухудшение; причинность не установлена |
| 160 Events / 8 Memory | 17,4898 ms | 12,5847 ms | −28,0% |
| 640 Events / 1 Memory | 21,9708 ms | 24,0368 ms | возможное ухудшение; причинность не установлена |
| 640 Events / 8 Memory | 36,7278 ms | 25,0338 ms | −31,8% |

Проверь `tests/bench_v02_h1_3_index_prefix.py` (1k/10k/50k): пользователь сообщил verified append 1,760/10,553/46,129 ms, около `O(bytes)`. H5.3c не устранял два полных Raw сканирования на каждое Event. Не заявлять приемлемое SLO или linear scaling без заранее утверждённого бюджета и повторных измерений. H4 benchmark 4 пары, false merges 0, false split 1: не переносить precision/recall на реальные данные.

## 4. Открытые release-gates: нельзя автоматически закрывать

| Gate | Известный статус перед независимым аудитом |
|---|---|
| Полный pytest Python 3.14.4 x86_64 | 1967 PASS — **reported by owner**, не независимое воспроизведение |
| Legacy diagnostics на синтетике | PASS; реальные старые данные **не проверены** |
| Python 3.12 | **NOT_TESTED** |
| Raspberry Pi 5 / aarch64 | **NOT_TESTED** в H5 |
| Реальное многокомпонентное backup/restore | лабораторное PASS, пользовательское **не проверено** |
| Пределы latency/throughput и RAM | измерения есть, эксплуатационный SLO **не утверждён** |
| Raw физическая запись/отключение питания | **NOT VERIFIED** |
| Legacy `about` authority provenance | некоторые записи требуют **REVIEW_REQUIRED** |
| Версии ledger/process vs правила H4 | pinned `1.0`, нужен независимый анализ последствий |

Если выявлен P0/P1, требующий изменения production, вердикт для RC — `BLOCKED`; исправлять в **новой ветке только по отдельной команде владельца**, затем повторять аудит нового SHA. Если не хватает данных для ключевых обязательных gate, вердикт — `INSUFFICIENT EVIDENCE` либо `BLOCKED` согласно последствиям.

## 5. Формат независимого заключения

Составь отчёт на русском языке, сохрани оригинальные имена модулей, классов и контрактов.

1. **Проверенный SHA**, среда, источники, воспроизводимость и права/ограничения reviewer.
2. **VERDICT H5.5:** `READY`, `BLOCKED` или `INSUFFICIENT EVIDENCE` — отдельно `source review`, `test/recovery`, `data compatibility`, `performance`, `RC`.
3. Таблица `Finding ID | severity P0/P1/P2 | file:line | preconditions | reproduce | expected/actual | impact | recommended change`.
4. Матрица H0–H5.4, N1–N9 и исходных инвариантов из плана с раздельными статусами `REPORTED / INSPECTED / REPRODUCED / NOT_TESTED / FAIL`.
5. Все повторно проведённые негативные испытания с точными командами, seed, stdout/stderr, временными путями, exit codes; если воспроизведения не было — сообщи.
6. Отдельные решения по Python 3.12, Pi, power loss, legacy `about`, SLO и правилам новой модели ассоциаций, в том числе список возможных **явно поддерживаемых ограничений RC**.
7. Рекомендации по устранению блокеров в порядке критичности — **без редактирования репозитория**.

**Выводить READY только при достаточных независимых доказательствах для явно объявленного scope. Не считать «1967 passed» достаточным доказательством качества всей памяти или состояния реального экземпляра.**
