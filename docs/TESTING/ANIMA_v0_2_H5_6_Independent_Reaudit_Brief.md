# ANIMA v0.2 — H5.6 Independent Reaudit после R6.0–R6.4

**Роль:** независимый архитектурный, технический и релизный аудитор (ChatGPT Work / отдельный reviewer).  
**Язык:** русский; оригинальные имена методов/классов/файлов, статусов и кодов находок сохранить.  
**Репозиторий:** `VankoRokh/ANIMA`.  
**Единственный проверяемый snapshot (40 символов):** `f70d879a88d88f63777646b0a65448765610402d`.  
**Замороженная ветка:** `audit/v02-h56-r6-post-remediation-candidate`.  
**Расположение этого ТЗ:** `work/v02-h56-independent-audit-prep:docs/TESTING/ANIMA_v0_2_H5_6_Independent_Reaudit_Brief.md`.  
**Важное разделение:** ветка с ТЗ **не** равна проверяемому snapshot. В анализе production code, тестов и документации именно snapshot audit-ветки является источником истины. ТЗ не является доказательством работоспособности.
**Историческая база:** `audit/v02-h55-post-remediation-candidate` @ `affae549d4521495d7502d1051243e7e804077c7`, ранее найдены NEW-01–NEW-07. Ранее проверялось F-01–F-08 после R1–R5.

## 1. Полномочия и запреты

Работай как независимый reviewer. **Не защищай** решения автора, не принимай названия тестов и успешный pytest за доказательство архитектурной корректности. Ищи обходы публичных методов, неявные инварианты, межкомпонентные гонки и неверные обещания API.

**Ничего не изменяй в GitHub:** никаких push/commit/PR/release/tag, обновления branch или удаления данных. Только read-only доступ к Git и создание **новых временных рабочих копий** в изолированном окружении reviewer. Негативные SQL/corruption/crash испытания разрешены исключительно на новых disposable SQLite, JSONL, snapshot/backup и копиях — не на экземплярах владельца. Не меняй тесты/production, чтобы сделать их зелёными. Изменения данных в tmp-fixture описывай как намеренное разрушительное тестирование.

Начни с `git rev-parse HEAD`, `git status --short`, `git show -s --format=%H HEAD`. **Откажись считать аудит выполненным, если HEAD отличается от указанного SHA**, даже если содержимое ветки похоже.

## 2. Сообщённые результаты владельца — не доказательство независимого reviewer

По последовательности R6.0–R6.4 владелец сообщил следующие локальные gate:
- R6.0 — 2054 pytest PASS; `scripts/check.sh` PASS; commit `1ba0bb0c2da147cd3df2ed82f23689818596f4ee`.
- R6.1 — 2067 pytest PASS после исправлений прежних test fixtures; `scripts/check.sh` отдельно на новом SHA не подтверждён в переписке; commit `276f43e8621bd293a12ab624b6dc8e445981cf5c`.
- R6.2 — 2073 pytest PASS; `scripts/check.sh` PASS; commit `43de94b363e449a04fc5393caac213adabb0e633`.
- R6.3 — 2093 pytest PASS; `scripts/check.sh` PASS; commit `264bad5df9cd774f8d68b715cef935249f26eb3a`.
- R6.4 — **2102 pytest PASS за 107,04 с**; `scripts/check.sh` PASS: документация 182 страницы, 1334 ссылки, Python 410 файлов, Python 3.14.4; candidate `f70d879a88d88f63777646b0a65448765610402d`.

Эти результаты считать **OWNER-REPORTED**. Reviewer должен воспроизвести их, если есть исполняемое окружение; статус "PASS independently" допустим только с фактическими exit code, SHA и локальным evidence. Число тестов зависит от окружения/конфигурации и не является самоцелью.

## 3. Первоисточники и boundaries

В snapshot прочитай `docs/TESTING/ANIMA_v0_2_H5_5_Independent_Reaudit_Brief.md`, `tests/README_v02_r6_1.md` … `tests/README_v02_r6_4.md`, `tests/README_v02_h55_remediation.md` и ссылки на первичные F-01–F-08. Обязательно изучи фактическую реализацию:

- `anima/memory/{memory_store,processor,event_processing,lifecycle,knowledge,link_store,provenance,retrieval,context_builder,event_log}.py`;
- `anima/core/assembly.py`, `anima/release_v01.py`, `labs/{v02_h5_legacy_diagnostic,v02_h5_compatibility,v02_h5_snapshot}.py`;
- `tests/test_v02_r6_1_knowledge_write_authority.py`, `tests/test_v02_r6_2_memory_mutation_integrity.py`, `tests/test_v02_r6_3_temporal_context_contracts.py`, `tests/test_v02_r6_4_recovery_owner_integrity.py`, их исходные `test_v02_h55_r*.py`, а также `test_provenance.py`, `test_retrieval.py`, `test_context_builder.py`, `test_event_processing.py` и stage integration tests.

Проверь **diff** относительно H5.5 `affae549d4521495d7502d1051243e7e804077c7`; ожидалось 28 последовательных коммитов, только R6-исправления и связанные тесты/документы, без изменений instance files. Найди возможные неоговорённые изменения.

Внешние архивы прошлых аудитов не входят в Git автоматически; если не предоставлены в Work, помечай их недоступными, а не «проанализированными».

## 4. Обязательная матрица NEW-01–NEW-07

| ID | Проверяемое свойство / минимум независимой атаки |
|---|---|
| **NEW-01 P1 / R6.1** | `LinkStore.create_knowledge` не допускает прямой INSERT `challenged/rejected/superseded/confirmed` без Evidence/History. Проверь альтернативные публичные и internal writers, неожиданную композицию API, статусные SQL helpers, `KnowledgeLayer` transitions, возможность создать status-only Knowledge и получить ложный Retrieval/Knowledge outcome. |
| **NEW-02 P1 / R6.1** | Прямая `LinkStore.create_relation(supports/contradicts)` не изменяет опубликованное Evidence без правил жизненного цикла. Попытайся вставить orphan/unbound/Raw-несоответствующие Evidence в `provisional` ДО `confirm`; проверь полный evidence graph (включая expired/future), разные `source_kind`, `source_memory_id`, legacy rows, History rollback и offline diagnostic. Избегай подмены «Row присутствует» на «Raw доказано». |
| **NEW-03 P1 / R6.2** | Конкурентные `MemoryProcessor.process_event` и `MemoryLifecycle.close → KnowledgeLayer.confirm`: выбор OPEN, пауза перед UPDATE, другой writer завершает Memory/публикует Knowledge, затем первый продолжает. Проверить `BEGIN IMMEDIATE`, fresh state/content, source list, Knowledge History; прямой путь и `EventProcessingCoordinator(connection=...)`; lost updates; обратный порядок writer-lock; исключения и состояние ledger после fail. |
| **NEW-04 P2 / R6.3** | Конечный `supports [t1,t2)` + противоположный `contradicts [t2,∞)`. `confirm` с `source_memory_id` и без него должны иметь согласованную политику в `t1<t<t2`, `t=t2`, до t1, после t2 и с различными timezone offsets. Ни новых бесконечных overlaps, ни дублирующих Relations. Проверить challenged transition, expired/effective proof, `describe` (now) против transition instant. |
| **NEW-05 P2 / R6.3** | `ContextBuilder` через adapter со `stats=None`, отсутствующими/не-bool flags, отсутствующими/несогласованными/отрицательными/`bool` counts, `returned!=len(results)`, `candidates<returned`, `top_k` ограничения и truncated seed. `complete=True` допустимо только при подтверждённых отрицательных признаках truncation. Перепроверь собственные `selection_stats`, FAST/DEEP, trace, budget omission, native RetrievalEngine. |
| **NEW-06 P2 / R6.4** | После `foreign_keys=OFF` удалить Memory без удаления `memory_sources`; `recover()`, `process(done)`, reopen, legacy adoption не должны возвращать `already_done` со ссылкой на phantom owner и не должны менять ledger/Raw. Повторить с несколькими mapping rows (часть валидна, часть orphan), с `skipped`, несколькими версиями processor, concurrent writes. Выяснить ограничения guard по namespace. |
| **NEW-07 P2 / R6.0** | Проверить, что H5.5 audit brief связан в `docs/TESTING/README.md`, documentation check честно PASS, все файлы/ссылки достижимы и нет смешения исторического H5.5/проверяемого H5.6 с release v0.1. |

**Матрица H5.6 должна включать фактический результат каждого NEW-01…07**: `FIXED_VERIFIED / PARTIAL / REGRESSION / NOT_TESTED`, конкретный reproduction, ожидаемое/фактическое и severity остаточного риска. Отдельно проверь, что уже исправленные F-01–F-08 не регрессировали; старые заявленные PASS не подменяют recheck.

## 5. Дополнительные межкомпонентные отрицательные проверки (обязательны)

1. **Authority & provenance:** public-vs-internal API, SQL direct write, SQLite `schema_meta` Raw binding, проверка всех связей Knowledge, provenance от нескольких Events/Memory, неполная/битая/подменённая Raw, различие между ID existence и semantic/source-authority proof.
2. **Atomicity/TOCTOU:** concurrency в `KnowledgeLayer`, `MemoryStore`, `MemoryProcessor`, `MemoryLifecycle`, `EventProcessingCoordinator`, Source mutation после successful confirmation, rollback всей транзакции; cross-file JSONL/SQLite границу явно задокументировать.
3. **Temporal:** validity intervals, противоположное Evidence после подтверждения, future/expired/historical relation, смешанные UTC offsets, равные границы, старые повреждённые Relations. Особое внимание: изменение существующего `supports` через разные public writers или сохранение конечного `valid_until`.
4. **Recovery/compatibility:** forged or partially missing `memory_sources`, stale `done` vs physical Memory, `skipped`, other processor versions, legacy schema, H5.0 + H5.4b read-only diagnosis и `PRAGMA foreign_key_check`, backup/reopen и replay idempotence.
5. **Coverage semantics:** невнимательные/ошибочные adapters и противоречивые stats, расхождение `ContextBundle.truncated` с `retrieval_coverage.complete`, `top_k` и budget; bounding of FTS/filters, точность trace.
6. **Operational constraints:** реальный performance impact R6 в многопоточном/многопроцессном режиме, полное сканирование Raw, SQLite lock wait, startup/recovery cost, WAL restore/logical backup. Любой SLO без измерений маркировать NOT_TESTED.

Разрешено развивать собственные негативные сценарии; **нельзя** считать приведённый список исчерпывающим. Неизвестные/неподтверждённые свойства не объявлять «безопасными по умолчанию». При найденной уязвимости не менять код; зафиксировать воспроизводимый test в временном каталоге.

## 6. Запуски и evidence

Если окружение позволяет:
- `git rev-parse HEAD; git status --short; python --version`, ОС/архитектура, `sqlite3.sqlite_version`;
- `bash scripts/check.sh` после чтения скрипта и подтверждения отсутствия вредных изменений;
- `PYTHONPATH="$PWD" python -m pytest -q -rx`, отдельно ключевые R6 suites;
- Отрицательные standalone tests в новом `tmp_path`, fault injection, restart, broken schema, mutation checks; проверять код возврата/exit status, точное число тестов, durations, отсутствие изменений checkout.
- Желательно CPython 3.14.4; CPython 3.12/3.13/ARM64 не заявлять PASS без фактического прогона. Отсутствие ARM64/RPi, реальной legacy DB или power loss явно пометить NOT_TESTED.
- Для каждого сценария сохранять команды, минимальные входные данные, версии, expected/actual, stderr/stdout, timing в отдельных локальных evidence-файлах. Никаких user secrets и персональных данных.

## 7. Формат итогового отчёта и release gate

Требуется **один подробный независимый отчёт на русском**:
1. Executive verdict: `PASS / BLOCKED / REVIEW_REQUIRED` **для аудита**, отдельно `APPROVE_RC / BLOCK_RC / NEEDS_EVIDENCE` как рекомендация, НЕ действие.
2. Target provenance: точный SHA, diff с H5.5, branch, clean checkout, versions, реально доступные внешние evidence.
3. Матрица **NEW-01–07** с risk/status/evidence/repro + матрица **F-01–08** на отсутствие регрессий.
4. Новые findings: последовательные `H56-01...`, severity `P0/P1/P2/P3`, затронутый API и инвариант, минимальное воспроизведение, expected/actual, impact, конкретная рекомендуемая правка.
5. Итоги fresh negative probes и результаты тестов с **кодами завершения**, не просто «прошло».
6. Uncovered boundaries: untrusted SQL, Raw semantic authority, races with uncooperative external writers, Pi/ARM64, реальные legacy instances, durability/power loss, backend LLM (не цель Core).
7. Список блокирующих факторов, отдельные nonblocking risks и условия выхода в RC, без публикации релиза.

**Правило приёмки:** нет права автоматически назначить v0.2 RC или менять выпуск. Даже если H5.6 выдаст PASS, final release decision принимает владелец. Отсутствующие исходники, недоступные архивы или невоспроизведённые сценарии маркировать **NOT_TESTED**, а не заменять предположением.

**Не изменять GitHub и пользовательские данные.** Вердикт должен опираться на собственную независимую проверку точного snapshot `f70d879a88d88f63777646b0a65448765610402d`.
