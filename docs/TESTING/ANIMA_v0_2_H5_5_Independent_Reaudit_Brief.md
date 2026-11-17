# ANIMA v0.2 — H5.5: независимый повторный аудит после R1–R5

**Тип:** техническое задание независимому reviewer / ChatGPT Work.  
**Язык отчёта:** русский; исходные имена модулей, API, идентификаторы F-01–F-08 и значения enum сохранять.  
**Аудируемая ветка:** `audit/v02-h55-post-remediation-candidate`. Работать **только на зафиксированном SHA HEAD этой ветки**, записать полный 40-символьный SHA до начала и в каждом отчёте. Не использовать изменяющийся `main` или любую рабочую ветку как источник истины.  
**Исходный аудит H5.5:** `audit/v02-h5-rc-candidate` @ `28e8438f8408e85b52e237eaedcf024354a4522a`, результат **BLOCKED**.  
**Последняя испытанная владельцем R5-ревизия кода:** `3639d4deb4636e14b027dc1ef50703503b697784`; полный pytest **2054 passed / 88,75 с**, **сообщено владельцем**, не воспроизведено независимым reviewer. Аудируемая ветка добавляет к этому коду **только документационные изменения**; reviewer должен проверить Git diff и эту границу.

## 1. Роль и полномочия

Действуй как **независимый технический аудитор**, а не автор предыдущих решений. Проверяй контракты и воспроизводимость, находи неожиданные взаимодействия исправлений и отрицательные сценарии, не подгоняй вывод под ожидаемые 2054 PASS.

**Ничего не изменять** в GitHub: никаких коммитов, push, PR, изменения branch, tag, release, tracked файлов или пользовательских instance-данных. Разрешены только локальная read-only работа с исходниками и **новые временные каталоги** `/tmp` / `pytest tmp_path` для исполняемых и разрушительных проверок. Если Work использует собственный cloud computer, клонируй/checkout именно SHA аудита в изолированный каталог. Не запускай команды, которые могут очистить или перезаписать реальный экземпляр. Внешние сервисы, реальные учётные записи и чужие данные не использовать.

Не изменять код ради прохождения тестов. Обнаруженный дефект оформить как finding с минимальным воспроизводимым сценарием и ожидаемым/фактическим результатом.

## 2. Первичные материалы

В указанном SHA прочитать:

- `README.md`, `docs/README.md`, `docs/versions/v0.1/contract.md` для общих границ версий; v0.1 не смешивать с H5-кандидатом v0.2.
- `tests/README_v02_h5.md`, `tests/README_v02_h55_remediation.md`, `tests/README_v02_h55_r2.md`, `tests/README_v02_h55_r3.md`, `tests/README_v02_h55_r4_1.md` … `tests/README_v02_h55_r4_5.md`, `tests/README_v02_h55_r5.md` для истории конкретных remediation.
- Production: `anima/memory/memory_store.py`, `event_log.py`, `event_processing.py`, `processor.py`, `lifecycle.py`, `knowledge.py`, `link_store.py`, `provenance.py`, `retrieval.py`, `context_builder.py`; `anima/core/assembly.py`, `anima/release_v01.py`, `labs/v02_h5_legacy_diagnostic.py`, `labs/v02_h5_compatibility.py`, `labs/v02_h5_snapshot.py`.
- Испытания: все `tests/test_v02_h55_r*.py`, `test_event_processing.py`, `test_memory_lifecycle.py`, `test_knowledge*.py`, `test_provenance.py`, `test_retrieval.py`, `test_context_builder.py`, `test_v02_h5_4_*.py`, `test_sleep_*.py` и Stage 6/Stage 1 integration tests.

**Внешняя первичная evidence, если предоставлена владельцем отдельно:** `ANIMA_v0.2_H5.5_evidence.zip`, `evidence_manifest.json`, `h55_work/independent_probes.py`, `h55_work/independent.json`, `h55_work/independent_repeat312.json`, `ANIMA_v0.2_H5.5_Independent_Release_Audit.md`. Эти файлы **не входят автоматически в Git**. Не заявлять, что они прочитаны/проверены, пока они реально не доступны. При недоступности использовать source code и новые независимые пробы, а исторические результаты маркировать «сообщены владельцем / в документации».

## 3. Среда и воспроизводимость

1. `git rev-parse HEAD`, `git status --short`, `python --version`, `python -m sqlite3 -v` (если поддерживается), ОС и архитектура. Проверить чистоту checkout до и после.
2. Выполнить весь `python -m pytest -q -rx` на CPython **3.14.4** и **3.12.14**, если обе версии реально доступны; строго различать PASS / FAIL / NOT_TESTED. Начальные `2054 passed` — референс владельца, а **не обязательное число** на другой платформе.
3. `bash scripts/check.sh` и проверки документации, если исполняемое окружение доступно. Если скрипт может изменять tracked файлы — сначала изучить его, затем запускать только при соблюдении read-only Git-границы; результаты не подменять предположениями.
4. Отдельно сохранять JSON/текст с командами, exit code, Python/SQLite версиями и всеми фактическими outputs в рабочем временном каталоге. Не выдавать сообщение stdout за доказательство успешного exit code.
5. Не объявлять CPython 3.12/aarch64 PASS на основании чужого ранее выполненного прогона; для Pi/aarch64 без железа ставить **NOT_TESTED**.

## 4. Обязательная матрица повторных контрпримеров F-01–F-08

Проверять **новые ожидаемые безопасные результаты**, а не старые assert'ы аудитора, которые специально ожидали воспроизводимый дефект.

| Finding | Строго проверить |
|---|---|
| **F-01 / R1** | `confirm → MemoryStore.update_memory` (content/reopen/importance/closed_at) и `confirm → MemoryLifecycle.merge` для source **и** target; атомарный отказ; Knowledge, History, Raw, source links остаются прежними. Другие Memory и provisional не заморожены. |
| **F-02 / R2+R5** | Отсутствующий, фиктивный, повторяющийся, malformed, torn Raw; `build_core` и отдельно открытый `MemoryStore` без `schema_meta`; потерянная/replaced Raw; перезапуск; `bind_event_log` канонического пути; **все** переходы `KnowledgeLayer.confirm/challenge/reject/supersede`; validate до/после транзакции. Отдельно проверить альтернативные публичные writer API `LinkStore.create_knowledge(status=...)` и прямой low-level writer: допускают ли изменение статуса без `KnowledgeLayer`? Не называть `source_event_id` семантической аттестацией содержимого Memory. |
| **F-03 / R4.1** | `EventProcessing done → delete_memory`, reopened store, multiple events/versions, `recover` и `process` по утраченной projection. Запрет операции или явный fail-closed, без `already_done/memory_id=None`, без replay/двойного эффекта. `skipped` без Memory должен остаться допустимым. |
| **F-04 / R3** | Запрет противоположных `supports/contradicts` в одном и другом порядке под `BEGIN IMMEDIATE`, в `LinkStore` **и** внутреннем `KnowledgeLayer` writer; current/future/expired, точная граница и timezone offsets. Для legacy SQL-инъекции только в `tmp_path` H5 diagnostic должен выдать finding и H5.4b `BLOCKED`, без auto-repair. Разные Memory могут иметь разные позиции. |
| **F-05 / R4.2** | `MemoryLifecycle.merge` переносит `about` только в `[max(relation.created_at, merged_at), relation.valid_until)`, не делает future (2099) связь действующей сейчас, не воскрешает expired, не удаляет provenance `source_memory_id`, правильно обрабатывает target coverage и offsets. |
| **F-06 / R4.3** | `KnowledgeLayer.confirm` с `source_memory_id` и без аргумента даёт одинаковую temporal семантику на active/future/expired opposite evidence; `challenge/reject` также учитывают момент события. При создании новой Relation будущий интервал не должен допускать overlap. Историческое конфликтное состояние воспроизводить только disposable direct SQL. |
| **F-07 / R4.4** | `RetrievalEngine` seed-limit FTS/filters/top-k и `ContextBuilder.retrieval_coverage`; случаи `candidates==returned` с неполным первичным поиском; FAST/DEEP, trace, budget. Неподдерживаемый/неполный интерфейс adapter не может ложно объявить `complete=True`. |
| **F-08 / R4.5** | `sqlite3.backup()` восстанавливает committed WAL, `-shm` может физически измениться; API/CLI честно обещает **logical offline backup**, не forensic byte-read-only. `verify/restore`, manifest и данные должны быть сохранны. Для строгой побайтовой доказательной копии применить отдельный offline image → working copy; не считать SHM всегда изменённым. |

## 5. Дополнительные независимые атаки и межкомпонентные переходы

Это **приоритет**, а не факультативное «посмотреть, если осталось время»:

- **Authority boundary:** все способы изменить Knowledge, включая `LinkStore`, `KnowledgeLayer`, прямые `MemoryStore` SQL helpers и статусные параметры. Проверить, не может ли caller создать или выдать `confirmed/rejected/challenged/superseded` в обход Raw, Evidence и History. Разделить поддерживаемый public API, internal API и повреждение извне через direct SQL.
- **Raw/Memory/Knowledge consistency:** наличие физического Raw ID против содержания Memory, подмена Raw, разные Event IDs у Memory, временные аномалии, импорт чужого файла `events.jsonl`, corrupted ledger. Честно признать предел «Raw ID exists» без semantic/source-authority proof.
- **Temporal & transaction integrity:** вставка opposite Evidence после подтверждения, повторная проверка в другом экземпляре, atomic rollback при `ValueError`, time-of-check/time-of-use в SQLite + JSONL, пересекающиеся intervals и влияние `updated_at`.
- **Recovery and audit:** намеренно сломать исходник только в `tmp_path` и убедиться, что `recover`, H5.0 и H5.4b не маскируют повреждённое состояние. Snapshot/restore отдельно от WAL forensic-контракта.
- **Performance/availability:** измерить стоимость полного Raw scan при подтверждении Knowledge с ростом EventLog; многопроцессный/многопоточный рост WAL и ограничение времени. Не оптимизировать во время аудита, не объявлять устойчивость без SLO.
- **Legacy:** `schema_meta` отсутствует, неизвестная версия, legacy `confirmed` без Raw, исторические `about` без достаточных полномочий. Не мигрировать и не переписывать данные автоматически. Реальный legacy-instance **NOT_TESTED**, если владелец не предоставил отдельную допустимую копию.
- **Regression coverage:** сравнить утверждения документации и реально проверяемые invariants; зафиксировать фальшивые позитивные результаты и пути, которые обычный pytest не охватывает.

Ограничивать негативные пробы разумным временем и размером фикстур; при ограничениях Work перечислить непроверенное, не симулировать исполнение.

## 6. Контракт отчёта

Подготовить **один независимый отчёт на русском** с исходными названиями API и точным SHA:

1. **Executive verdict:** `PASS`, `BLOCKED` или `REVIEW_REQUIRED` для *проверенного набора release gates*, отдельно от `v0.2 RC READY`. Сам факт `2054 passed` не означает PASS аудита.
2. **Environment & provenance:** SHA, OS, Python, SQLite, архитектура, доступность архива предыдущего аудита, перечень действительно исполненных команд, exit status, длительность.
3. **F-01–F-08 disposition:** для каждого `FIXED_VERIFIED / PARTIAL / REGRESSION / NOT_TESTED` + первичный воспроизводимый сценарий, ожидаемое и фактическое, адресные файлы/строки, вывод.
4. **Новые finding:** уникальные `NEW-xx`, severity `P0/P1/P2/P3`, влияющий контракт, точный минимальный reproduction, наблюдаемый impact, рекомендация без изменения репозитория.
5. **Таблица uncovered boundaries:** реальные legacy DB, Pi/aarch64, physical power loss, noncooperative writers, semantic validity, performance/SLO, непрерывность работы. Не выдавать предположение за результат.
6. **Decision & next actions:** что блокирует релиз; что допустимо принять только с документированной scope-границей. Отдельно **APPROVE RC / BLOCK RC / NEEDS EVIDENCE**, но не выпускать tag или release.
7. **Evidence:** сохраняемые локальные отчёты/скрипты и exact commands, без выкладывания пользовательских данных.

**Не вносить исправления.** Приоритет — воспроизводимые доказательства, в том числе фактические raw ответы. Если упираешься в лимит окружения, отчёт должен отражать выполненное и явно маркировать `NOT_TESTED` вместо оптимистического заключения.

## 7. Decision boundary

Ревизия остаётся **кандидатом для повторного аудита**, а **не ANIMA v0.2 RC**, пока независимый reviewer не изучит SHA и не вынесет заключение. Даже при `PASS` испытаний разрешение на релиз требует отдельного решения владельца о границах legacy/portability/performance и о publication/tag. `main`, release v0.1 и исходная замороженная H5.5 ветка не изменяются.

**ТЗ является частью documentation-only audit preparation.** Если SHA, доступные инструменты или материалы отличаются от ожидаемых, reviewer обязан отразить это в отчёте, а не подменять источники.
