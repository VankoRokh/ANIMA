# ANIMA v0.2 — H5.7 Independent Reaudit после R7.0–R7.4

**Роль:** независимый архитектурный, технический, интеграционный и релизный reviewer.  
**Язык отчёта:** русский; сохраняй точные имена Python API, статусов, схем, finding ID, веток и SHA.  
**Репозиторий:** `VankoRokh/ANIMA`.  
**Единственный целевой snapshot (40 hex):** `03ec97448d7e805a1dd34729140a47fd31c53774`.  
**Замороженная аудит-ветка:** `audit/v02-h57-r7-post-integration-candidate`.  
**Это ТЗ находится ТОЛЬКО в другой ветке:** `work/v02-h57-independent-audit-prep:docs/TESTING/ANIMA_v0_2_H5_7_Independent_Reaudit_Brief.md`.  
**Предыдущий аудит:** H5.6 `audit/v02-h56-r6-post-remediation-candidate` @ `f70d879a88d88f63777646b0a65448765610402d`; вердикт **BLOCKED / BLOCK_RC**.  
**Ранее аудированная H5.5 база:** `affae549d4521495d7502d1051243e7e804077c7`.  

**Критическое разделение:** HEAD ветки с ТЗ **не является** проверяемым кодом. Выполняй любые tests, source inspection, negative probes и review на SHA `03ec9744...` и не включай коммит с этим ТЗ в проверяемый snapshot.

## 1. Полномочия и независимость

Ты — **независимый reviewer**, а не разработчик, защищающий R7. Не считать 2166 PASS доказательством устранения ошибок. Проверяй альтернативные входы и API, сочетания исправлений и их последствия для других контуров. Повторяй наиболее рискованные сценарии самостоятельно, не полагаясь на имена, описания или ожидаемые результаты тестов автора.

**Запрещены:** любые изменения GitHub, push/commit/PR/tag/release, изменение веток `audit/` и `work/`, изменение production/test code ради PASS, работа с экземплярами пользователя, секретами или исходными Raw. Негативные SQL, damage, crash, fault-injection, recovery и concurrency эксперименты — только на **новых disposable** SQLite/JSONL/backup и временных копиях. Если что-то требует destructive experiment на реальных данных — отмечай `NOT_TESTED`.

Не выдавай `APPROVE_RC` автоматически по успешному pytest; ни этот аудит, ни это ТЗ не уполномочены публиковать релиз.

В начале зафиксируй:
```bash
git rev-parse HEAD
git show -s --format=%H HEAD
git status --short
python --version
python -c 'import platform, sqlite3; print(platform.platform(), platform.machine(), sqlite3.sqlite_version)'
```
При другом HEAD — **не считать аудит данного snapshot выполненным**. Предпочтительна чистая, отдельная checkout/worktree без локальных правок. Запиши точную проверенную ревизию и environment в evidence.

## 2. Что сообщает владелец (не independent evidence)

После H5.6 проведены R7.0–R7.4. Владелец сообщил успешные локальные проверки, все на Python 3.14.4:

| Этап | Owner-reported full pytest | Состояние |
|---|---:|---|
| R7.0 Temporal Knowledge Authority | 2117 PASS | `scripts/check.sh` PASS |
| R7.1 Memory Source Integrity | 2124 PASS | `scripts/check.sh` PASS |
| R7.2 Lifecycle Write Authority | 2135 PASS | `scripts/check.sh` PASS |
| R7.3 Storage & Evidence Validation | 2156 PASS | `scripts/check.sh` PASS |
| R7.4 Integration & Release Gate | **2166 PASS / 98.52 s** | `scripts/check.sh` PASS: 182 pages, 1334 local links; Python 416 files, 3 VS Code JSON, 3 Bash, CLI extraction, no instance/personal tracked files |

**R7.4 HEAD:** `03ec97448d7e805a1dd34729140a47fd31c53774`. Не менялся production-код на R7.4; добавлены интеграционные тесты и документация. `scripts/check.sh` PASS относится к локальному прогону владельца, независимый reviewer должен воспроизвести свой собственный.

**Первичные артефакты H5.6 — внешние, не автоматически находящиеся в Git:** 
- `ANIMA_v0_2_H56_Independent_Reaudit_RU.md`
- `ANIMA_v0_2_H56_Evidence.zip` (исходные independent probes/logs/fixtures/manifest).

**Если они не переданы в твою сессию:** обозначь `H5.6 ORIGINAL EVIDENCE: UNAVAILABLE`; запрашивать их при необходимости можно, но не называй невыполненную проверку original probes успешной. Не заменяй оригинальный repro авторскими R7 тестами. Если архив получен, проверяй `SHA256SUMS.json` и воспроизводи пробы только на новых временных копиях; не исполняй непроверенный архив как доверенный код без инспекции.

## 3. Что изменилось после H5.6

Обязательно сравни exact commits:
```bash
git diff --stat f70d879a88d88f63777646b0a65448765610402d 03ec97448d7e805a1dd34729140a47fd31c53774
git diff --name-status f70d879a88d88f63777646b0a65448765610402d 03ec97448d7e805a1dd34729140a47fd31c53774
git log --oneline --reverse f70d879a88d88f63777646b0a65448765610402d..03ec97448d7e805a1dd34729140a47fd31c53774
```

Изучи реализацию, а не только README:
- `anima/memory/{knowledge,link_store,lifecycle_authority,memory_store,processor,lifecycle,event_processing,event_log,provenance,retrieval,context_builder}.py`;
- `anima/core/assembly.py`, runtime/adapters/trace, `labs/{v02_h5_legacy_diagnostic,v02_h5_compatibility,v02_h5_snapshot}.py`;
- `tests/README_v02_r7_0.md` … `tests/README_v02_r7_4.md`, `tests/test_v02_r7_{0,1,2,3,4}_*.py`;
- `tests/test_v02_r6_{1,2,3,4}_*.py`, H5.5/F/NEW historical tests, `tests/test_knowledge.py`, `tests/test_retrieval.py`, `tests/test_provenance.py`, `tests/test_context_builder.py`, `tests/test_event_processing.py`;
- H5.6 brief `docs/TESTING/ANIMA_v0_2_H5_6_Independent_Reaudit_Brief.md` в `work/v02-h56-independent-audit-prep` (историческая ветка, не target).

Отмечай любое неоговорённое изменение против H5.6 и любые уязвимые инварианты, которые R7 вообще не защищает.

## 4. Обязательная матрица H56-01–H56-06

Для **каждого** H56 finding представь `FIXED_VERIFIED / PARTIAL / REGRESSION / NOT_TESTED` с собственным repro, expected/actual, API и конкретным evidence.

### H56-01 P1 → R7.0 — challenged reconfirm using future supports

Доказательство должно быть **новым и действующим в момент transition**, а не просто существующим в Relations. Повтори H5.6 цепочку: `A` old support → `K confirmed` → `B` contradiction → `K challenged` → `C` source с `supports(C,K)` из 2099 → `confirm(K,C)` сейчас. Требуется атомарный отказ, неизменные Knowledge/History/Relations/Raw, а не успех на существующем `A`.

Обязательно: `confirm` с/без source, active finite support, staged new support after challenge, old active source, expired source, future duplicate, return `created=False`, duplicate relation ID, `timestamp` в различных UTC offsets, границы `[start,end)`, `now` versus transition instant. Проверить, не может ли один старый Memory быть переобъявлен новым без revision.

### H56-02 P2 → R7.0 — finite contradictions

Проверь `challenge(K,B,t5)` и `reject(K, contradiction_memory_id=B,t5)` при существующем `contradicts(B,K)=[t4,t8)`, а также `supports(B,K)=[t8,∞)`. Не должно создаваться бессрочное `contradicts`, изменяться valid_until, появляться overlap или искусственный отказ действующему finite witness. Повтори explicit/implicit reject, `t4` inclusion/`t8` exclusion, future/expired, разные offset. Проверь R3/F-04 opposite polarities. Не принимай целостность на t5 за корректность всей временной истории.

### H56-03 P2 → R7.2 — forged supersedes

Попробуй `LinkStore.create_relation(source_kind="knowledge", relation_type="supersedes", target_kind="knowledge")` на provisional/confirmed/superseded сочетаниях и с реальным/недоступным Raw. Попытайся добиться ложного `describe(old).superseded_by`, `describe(new).supersedes`, `RetrievalEngine` one-hop и score bonus без `KnowledgeLayer.supersede()`.

Восстанови legacy forged relation через SQL **только во временной базе**: raw graph forensic visibility допускается, но authoritative lifecycle projection обязана отказаться. Изучи predicate `is_authorized_supersession`: проверка old/new statuses, evidence owner, `memory_sources`, old/new History, соответствие relation ID и timestamp, finite `valid_until`, поведение при удалённой/дублированной/поддельной History и нескольких supersedes. Убедись, что реальный supersede (включая reopen/retrieval) не регрессировал. H5.0 должен помечать неавторитетный graph `degraded`; H5.4b — при обещанном blocking — `BLOCKED`.

### H56-04 P2 → R7.3 — unknown schema mutates DB before refusal

Создай disposable SQLite со `schema_meta.schema_version=999` и дополнительными user tables/data. Вызов `MemoryStore` обязан отвергать до DDL, не оставляя таблицы/индексы/триггеры; сравни список `sqlite_master`, counters, данные, byte SHA при quiescent snapshot. Проверь версии `2`, `-1`, нецифровые, отсутствующую мета-таблицу, отсутствующий `schema_version`, supported `1`, fresh DB, partially incompatible schema и rollback. Отдельно рассмотри WAL/SHM, URI `mode=ro`, TOCTOU между read-only preflight и `BEGIN IMMEDIATE`, транзакционность DDL с FTS triggers и последствия `sqlite3.complete_statement()`. Не выдавай byte-for-byte гарантию для активной WAL базы.

### H56-05 P2 → R7.3 — malformed dormant temporal Evidence

Подготовь provisional Knowledge с реальным Raw и действующим A + future `supports(C,K)` из t8, у которого через SQL на disposable DB `valid_until=t7`. `confirm` должен быть отклонён даже при effective A. Повтори `challenge/reject/supersede` на повреждённом историческом графе; проверяй fail-closed rollback, неповреждённые Relations/History/Raw и H5.0 `invalid_relation_interval` либо `invalid_relation_timestamp`. Тестируй null, equal, inverted, naive timestamp, malformed ISO, UTC-equivalent offsets, historical expired and future. Убедись, что валидатор срабатывает **до** фильтра по активности, но корректные finite/future intervals не блокируются.

### H56-06 P2 → R7.1 — stale memory_sources with unchanged Memory row

Воссоздай stale `MemoryProcessor._best_candidate` → paused decision → `MemoryLifecycle.merge` переносит Raw sources с conflicting typed Entity claims в target при **побайтово неизменной Memory row** → stale processor возобновляется. Под writer lock должны сверяться *ровно* source IDs, использованные scorer; прямой `process_event` и `connection=...` обязаны отказать до side effects. Проверь `update`, `create_related`, candidate-bearing `create`, composer pause/lock, normal control update, recovery и последующее закрытие/публикацию Memory. Атакуй `candidate=None` и изменения ранжирования/других кандидатов: если свойства не гарантируются контрактом, документируй предел, но не объявляй исправленными.

## 5. Обязательные старые регрессии

Раздельная матрица **NEW-01…NEW-07**, включая:
- NEW-01/02: status-only writers; public Evidence mutation на published Knowledge, Raw/provenance authority;
- NEW-03: direct/coordinator stale writes, memory close/confirm races;
- NEW-04: finite support vs future opposite Evidence;
- NEW-05: `ContextBuilder`, incomplete/truncated adapter stats, selection stats, FAST/DEEP budgets and provenance;
- NEW-06: orphan `memory_sources` после `foreign_keys=OFF`, done/recover/reopen idempotence;
- NEW-07: исторические audit briefs, README/doc hierarchy and check reachability.

И отдельная матрица **F-01…F-08** по исходным H5.5 контрактам. Не своди все F к одному `regression PASS`. Для каждого зафиксируй либо независимую пробу, либо честное `NOT_TESTED`.

## 6. Межкомпонентные атаки, которые нельзя пропустить

1. **Temporal → Knowledge → History → Retrieval.** Смена `confirmed/challenged/reconfirmed/superseded` через реальные CLOSED Memory, finite/expired/future Evidence; History обязан указывать именно на live proof, а не другой источник.
2. **Raw → Memory → Knowledge.** Отсутствие физического Raw при наличии `memory_sources`, corrupted/duplicate/truncated JSONL, Raw binding persisted schema_meta, `source_memory_id` and relation owner, неполные исходные Events, post-transition mutation и rollback.
3. **Memory concurrency → Recovery.** Смешанные source sets, coordinator replay and independent processor, same-row source graph mutation, competing writer, `BEGIN IMMEDIATE` and lock timeouts, physical owner missing при done/skipped/adoption.
4. **Lifecycle → Retrieval → H5.0/H5.4b.** Поддельные/битые supersedes рядом с настоящими, mismatch status and History, reopening, one-hop search, forensic visibility без authoritative presentation.
5. **Schema → Backup → Reopen.** Новый/поддерживаемый/несовместимый bootstrap, WAL/rollback, read-only legacy diagnosis, отсутствие repair, snapshot consistency, negative mutation on copies only.
6. **Context Coverage.** `ContextBuilder` FAST/DEEP, adapters с `stats=None`/missing flags/inconsistent counts, bounded `top_k`, char budget, no false `coverage.complete` and no false proof of complete retrieval.
7. **Public API & delegation.** Поиск обходов через generic `LinkStore`, `MemoryStore`, `KnowledgeLayer`, `MemoryProcessor`, `EventProcessingCoordinator`, `ProvenanceResolver`, `RetrievalEngine`; не принимать underscore-метод как security boundary. Прямой SQL может создать недоверенное legacy состояние — это модель corrupted storage, а не разрешённый API writer.
8. **Operational/perf.** Измерь, если возможно, latency на конечном Evidence graph (1k/10k/50k), дополнительные queries при Retrieval супрессии forged supersedes, bootstrap, concurrent writer wait; не заявляй SLO/безопасность Pi/ARM без тестов.

Расширяй список, если увидишь инвариант вне названных сценариев. Ранее зафиксированные, но не устранённые по контракту ограничения не надо выдавать ни за доказанный дефект, ни за «безопасность».

## 7. Запуски и фактические evidence

Перед исполнением изучи `scripts/check.sh` и его side effects. Если окружение реально доступно:

```bash
git rev-parse HEAD
git status --short
PYTHONPATH="$PWD" python -m pytest -q -rx \
  tests/test_v02_r7_4_integration_release_gate.py \
  tests/test_v02_r7_0_temporal_authority.py \
  tests/test_v02_r7_1_memory_source_integrity.py \
  tests/test_v02_r7_2_lifecycle_write_authority.py \
  tests/test_v02_r7_3_storage_evidence_validation.py \
  tests/test_v02_r6_1_knowledge_write_authority.py \
  tests/test_v02_r6_2_memory_mutation_integrity.py \
  tests/test_v02_r6_3_temporal_context_contracts.py \
  tests/test_v02_r6_4_recovery_owner_integrity.py
bash scripts/check.sh
PYTHONPATH="$PWD" python -m pytest -q -rx
git status --short
```

Записывай exit codes, timestamp, duration, actual pass/xfail/fail, версии Python/SQLite/architecture и SHA. Не предполагается, что локальная среда reviewer точно совпадёт с владельцем. Исходные H5.6 reproduction scripts (при доступном архиве) **адаптируй только в отдельном временном harness**, сохрани оригинальные probe bytes/хэши. Не подменяй negative test ложноположительным зелёным по изменённому expectation.

Исполняй дополнительные concurrency/fault/Raw corruption тесты только в `tmp_path` либо иных disposable окружениях. Отдельно различай `expected fail to mutate` vs `unexpected test failure`. Сохраняй evidence logs, минимальный repro и/или отдельный ZIP с manifest SHA256 без персональных данных. По возможности сверяй unchanged source tree, no GitHub modifications.

Для performance указывай sample sizes, hardware, timing, variance, отличие от H5.6 и издержки R7.2 lookup на forged-edge-heavy graph. При отсутствии окружения или resources — `NOT_TESTED`, не имитируй результаты.

## 8. Обязательный итоговый независимый отчёт

Один подробный отчёт **на русском**:

1. Executive verdict отдельно `PASS / BLOCKED / REVIEW_REQUIRED` и release recommendation `APPROVE_RC / BLOCK_RC / NEEDS_EVIDENCE` (**только рекомендация**).
2. Exact target SHA/branch, clean status, версии ОС/Python/SQLite, diff от H5.6, доступность H5.6 external zip и перечень independently executed tools.
3. Матрица **H56-01–H56-06**: severity, prior repro, new repro, expected/actual, `FIXED_VERIFIED / PARTIAL / REGRESSION / NOT_TESTED`.
4. Матрицы **NEW-01–NEW-07** и **F-01–F-08** с evidence или явным пробелом.
5. **Новые findings** последовательно `H57-01...`, P0–P3, конкретный затронутый публичный API, минимальный воспроизводимый сценарий, failure mode, impact, точная предложенная мера, rollback assertions.
6. Результаты full/targeted pytest/check с exit codes и фактическими цифрами, изолированные negative/fault/cross-module/recovery probes; отдельно NOT_TESTED.
7. Ограничения: `candidate=None`/global ranking, current-vs-historical Knowledge trust, historic Memory revisions, cross-file Raw/SQLite durability, malicious SQL, Raw semantic truth, реальная legacy DB, Pi/ARM64, physical power loss, LLM FAST/DEEP.
8. Таблица **blocking vs nonblocking** и конкретные условия для перехода к RC. Не выпускать release и не менять GitHub.

**Критерий успеха:** независимое опровержение либо подтверждение инвариантов точного snapshot с воспроизводимыми evidence. `2166 PASS` не равняется `APPROVE_RC`. Даже при хорошем H5.7 окончательное решение об ANIMA v0.2 принимает владелец.
