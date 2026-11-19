# ANIMA v0.2 — H5.8: независимый релизный реаудит R8.0–R8.3

**Роль:** независимый архитектурный, технический, интеграционный и релизный reviewer.  
**Язык:** русский; сохранять оригинальные имена API, идентификаторов, SHA и контрактов.  
**Репозиторий:** `VankoRokh/ANIMA`.  
**Единственный проверяемый snapshot:** `1364e62634669ef553df0b2f2d7a1159d404383f`.  
**Аудиторская ветка:** `audit/v02-h58-r8-post-integration-candidate` (должна указывать точно на SHA выше).  
**Этот документ расположен в ДРУГОЙ ветке:** `work/v02-h58-independent-audit-prep:docs/TESTING/ANIMA_v0_2_H5_8_Independent_Reaudit_Brief.md`.  
**Исходный независимый H5.7:** `audit/v02-h57-r7-post-integration-candidate` @ `03ec97448d7e805a1dd34729140a47fd31c53774`; результат **BLOCKED / BLOCK_RC**.  
**Исторический H5.6:** `audit/v02-h56-r6-post-remediation-candidate` @ `f70d879a88d88f63777646b0a65448765610402d`.

**КРИТИЧНО:** TARGET = SHA `1364e626...`, а не HEAD ветки `work/v02-h58-independent-audit-prep`, куда добавлен этот brief. Не включать файл ТЗ в сравнение production diff или в target fixture.

## 1. Независимость, границы, запреты

Проверяй код и инварианты как независимый reviewer, а не автор R8. **2315 успешных тестов не доказывают отсутствие дефектов**, даже если повторятся. Не доверять названиям тестов, ответам автора и отметкам PASS вместо фактического поведения API и неизменности данных.

**Не менять GitHub:** никаких commit, push, PR, merge, release, tag или исправления target. Не модифицировать пользовательские экземпляры, реальные Raw, модели, конфигурацию, секреты, private backup и рабочий checkout владельца. Все SQL corruption, Raw damage, crash, concurrency, WAL/SHM, backup/restore и fault injection пробы — только на disposable копиях в `tmp_path`, временных checkout/worktree, с явными исходными backup перед повреждением. Нельзя ослаблять оригинальные assertions ради PASS.

В начале зафиксируй `git rev-parse HEAD`, `git status --short`, exact SHA, `python --version`, SQLite version, `platform.machine()`, версии pytest/ОС, источник audit branch; после окончания повтори tree/status/контроль исходников. Если HEAD не target, аудит exact snapshot не засчитывается.

Не публиковать релиз. Аудитор даёт **рекомендацию**, решение о release/RC остаётся у владельца.

## 2. Owner-reported evidence — не independent acceptance

Владелец сообщил последовательные локальные прогоны Python 3.14.4:

| Этап | Full pytest | `scripts/check.sh` |
| --- | ---: | --- |
| H5.7 исходный | 2166 PASS | PASS |
| R8.0 Knowledge Proof Novelty | 2179 PASS | PASS |
| R8.1 Context Adapter Integrity | 2243 PASS | PASS |
| R8.2 Temporal Validation Consistency | 2298 PASS | PASS |
| R8.3 Integration & Acceptance | **2315 PASS / 97.09 s** | PASS: 182 documentation pages, 1334 local links, 420 Python files, 3 VS Code JSON, 3 Bash, CLI extraction, no tracked instance/user settings |

Все результаты выше — **переданы владельцем**, не результаты нового независимого аудита. Самостоятельно запусти доступные проверки и запиши actual outcome, exit codes, versions и ограничения. R8.3 добавил только tests и README, **production в R8.3 не менялся**.

Обязательные сравнения:
```bash
git diff --stat 03ec97448d7e805a1dd34729140a47fd31c53774 1364e62634669ef553df0b2f2d7a1159d404383f
git diff --name-status 03ec97448d7e805a1dd34729140a47fd31c53774 1364e62634669ef553df0b2f2d7a1159d404383f
git log --oneline --reverse 03ec97448d7e805a1dd34729140a47fd31c53774..1364e62634669ef553df0b2f2d7a1159d404383f
```
Ожидаемый scope по проверенному diff GitHub: **15 коммитов, 10 файлов**; production: только `anima/memory/knowledge.py` и `anima/memory/context_builder.py`; восемь остальных файлов — `tests/test_v02_r8_{0,1,2,3}_*.py` и четыре `tests/README_v02_r8_{0,1,2,3}.md`. Сравни фактические изменения, не предполагай, что заявленный scope гарантирует безопасность.

## 3. Первичные материалы H5.7

При возможности получить отдельно:
- `ANIMA_v0_2_H57_Independent_Reaudit_RU.md` — формальное заключение H5.7.
- `ANIMA_v0_2_H57_Evidence.zip` — original reviewer scripts, logs, manifest, synthetic fixtures и архив H5.6 original probes, в частности:
  - `probes/test_h57_findings.py`;
  - `probes/test_h57_contracts.py`;
  - `probes/test_h57_boundaries.py`;
  - `probes/live_same_second_reconfirm.py`;
  - `original_probes/test_h56_findings.py`, `original_probes/test_h56_contracts.py`, `original_probes/test_h56_boundaries.py`, `original_probes/h56_support.py`.

Проверить архив: `SHA256SUMS.json`, размеры, SHA-256, CRC, path traversal, неизменность original script bytes, читаемость original log/manifest. Затем **инспектировать скрипты** перед запуском: отрицательные probes не считаются доверенным кодом только из-за имени. Фактический target для повторных запусков обязан быть H5.8, а не исходный H5.7.

**Если H5.7 ZIP или оригинальный H5.6 ZIP отсутствует:** отметить `ORIGINAL EVIDENCE NOT AVAILABLE`, не утверждать, что original probes выполнены. Текущие R8 author tests не заменяют независимых сценариев.

Оригинальный H5.7 в full exploratory наборе имел ожидаемые неформальные failed по automatic Knowledge aging и immutable historic source. Эти свойства исторически **не входили в обещанный контракт** и не должны превращаться в новые блокеры лишь из-за старых exploratory assertions. Сохраняй отдельные результаты formal findings, exploratory boundary tests и actual regressions.

## 4. Матрица H57-01–H57-03 — приоритет H5.8

Для **каждой** находки дай статус `FIXED_VERIFIED / PARTIAL / REGRESSION / NOT_TESTED`, конкретные API, expected/actual, воспроизводимый log или unittest, таблицу rollback и точные ограничения.

### H57-01 (P2) — новизна Raw-backed proof при same instant

**Старое поведение:** `KnowledgeLayer.confirm` при `created=True` INSERT support, затем `old_source` query считал собственную новую Relation старой, если `created_at <= challenged_at`. Из-за `_now()` с точностью до секунды корректный `challenge → fresh Raw → new/closed Memory → confirm` падал.

**R8.0 expectation:** исключить **строго ID новой Relation при created=True**, но не старые supports того же Memory; при `created=False` старых исключать нельзя. Проверить, что возможное равенство timestamps не означает тот же объект/доказательство.

**Независимые случаи:**
1. Повтори original H5.7 `live_same_second_reconfirm.py` без подмены системных часов; логируй actual challenge/confirm timestamps, Raw/source IDs, status/History/Relation.
2. Детерминированный equal-instant `confirmed_at==challenged_at`, включая разные UTC offset, genuinely new Raw physically written after challenge, Memory CLOSED перед confirm → **ACCEPT** ровно один новый support и History.
3. `A` previous support при том же/более позднем instant → **DENY** без изменения состояния.
4. Существовавшая до challenge `supports(C,K)`, `created_at==challenged_at` → **DENY**; offset-equivalent timestamps не обходят контроль; `created=False` не считается новым.
5. Pre-staged `supports(C,K)` с `start>challenge` и действительно впервые effective, finite/open-ended → разрешить на границе, не вставлять дубль и не продлевать valid_until.
6. Future-2099 и expired supports не переоткрываются; противоположные finite supports/contradictions соблюдают `[start,end)` и не overlap.
7. Reconfirm → challenge again → тот же C уже старый; нельзя использовать снова.
8. Злой API-путь: duplicate relation IDs, stale evidence owner/missing Raw, source-only merge после scorer, оспаривание при concurrently created Memory; сохранять transactional fail-closed.
9. Проверь, не нарушает ли «исключение created row» инвариант более старой support того же source при corrupted/legacy storage (включая несколько rows, прошлые source IDs, offsets). Отдельно отметь ограничения гарантии Raw semantic truth.

### H57-02 (P2) — ContextBuilder custom-adapter structural integrity

**Старое поведение:** `kind="entity"` с достоверными-looking `stats` исчезал в `_selection_order`, а результат получал `retrieval_coverage.complete=True`, `truncated=False`, нулевые omissions.

**R8.1 expectation:** проверить каждый candidate **до** coverage, budget и provenance; malformed payload отвергается единым `ValueError`, а не тихим drop либо неполным bundle с ложным complete. Native RetrievalEngine продолжает работать.

**Независимые случаи:**
1. Повтори original H5.7 `test_unsupported_candidate_kind_is_not_silently_omitted_as_complete` в FAST и DEEP, с/без `exact_id:+100`.
2. Mixed [valid, unknown, valid] и unknown первым/последним; более дорогие negative cases не должны приводить к частичному результату либо trace, утверждающему successful full coverage.
3. Unknown/missing/non-string/другое написание `kind`; candidate not dict; `id` missing/blank/mismatch с `record["id"]`; `record` отсутствует/не dict, content/statement не строка, `reasons` non-list или содержит неверные элементы, `score` NaN/inf/bool/nonnumeric.
4. Особое внимание **согласованности ID и kind**: допустимость префиксов, существование record, HTML/SQL injection-подобных opaque strings — не смешивать структурную проверку и trust proof; если контракт обещает только representability, явно отметить scope.
5. При корректных custom adapters сохранить FAST/DEEP, exact first, knowledge-first, top-k, relation_hops, budgets, provenance, event ordering/dedup, tri-state coverage при absent/bad stats и distinction `retrieval_coverage.complete` vs Context `truncated`.
6. Проверить противоречивую статистику (`candidates/returned`, bool/integer/string, missing/None flags), nested bad values, duplicates, empty arrays; нет false `complete=True` из unvalidated payload.
7. Испытай hostile record, который формально проходит minimal validation, но ломает downstream provenance/event projection: это потенциальная граница R8.1, если воспроизводится через публичный adapter. Отличать incomplete adapter от Raw damage, когда `ProvenanceResolver` обязан отказать.
8. Ошибка invalid adapter не должна мутировать Knowledge/Memory/Raw или писать ложный successful trace.

### H57-03 (P3) — Temporal Evidence validation order / error taxonomy

**Старое поведение:** при dormant support с `created_at` без UTC offset `confirm` вызывал `_require_effective_memory_evidence` и получал TypeError раньше общего `_validate_evidence_interval`.

**R8.2 expectation:** `_require_valid_evidence_intervals` read-only проходит все Knowledge-attached supports/contradicts внутри той же SQLite-транзакции, до любых сравнения `aware/naive` или INSERT; обе implicit/explicit ветки confirm и `challenge/reject/supersede` должны fail-closed c `ValueError`.

**Независимые случаи:**
1. Повтори исходные H5.7 `test_all_publications_reject_dormant_interval_damage` с оригинальными assertions, без изменения fixture expectations.
2. Повреждения legacy SQLite только в disposable базе: naive/malformed/empty start, naive/malformed end, equal/inverted windows, offset-equivalent equal; future/dormant/expired и active Evidence; corruption как у supports, так и у contradicts.
3. Любой терминальный Knowledge write отказывает до History/Relations/Raw/status mutation; сравнить полноту транзакции (в том числе при newly created Relation, superseding new Knowledge). Необязательно byte-identical SQLite WAL при активном соединении.
4. Valid finite, future и open-ended Evidence не блокируются и не меняют temporal coverage, включая точный end-exclusive boundary и UTC offsets.
5. Verify порядок preflight с R8.0, R7.0 future/support guards, R7.3 Raw validation; специальные тесты на corrupted opposite evidence и без explicit source.
6. Потенциальный overhead: R8.2 выполняет дополнительный scan Evidence перед terminal Raw scan; измерить 1k/10k/50k *корректных* finite/dormant records при возможности, сравнить H5.7 на том же hardware и при одинаковом sample setup. Не выдумывать SLO; фиксировать O(N) стоимость, latency и peak memory.

## 5. Обязательные historical regression gates

Сделай **две отдельные матрицы**, а не один «all green»:

**H56-01–H56-06:**
- H56-01 original future-dated 2099 support & proven old source — P1 old fraud MUST remain denied; R8.0 fresh proof MUST be accepted.
- H56-02 finite contradictions challenge/reject, half-open windows/offsets, no infinite duplication.
- H56-03 generic supersedes forbidden, legacy forged supersedes reader and Retrieval not authoritative, H5.0 diagnostic/compatibility gate; real supersede works.
- H56-04 unsupported `schema_version=999` preflight before DDL, nonmutating, FTS rollback, WAL/SHM limitations.
- H56-05 malformed dormant intervals deny before terminal Knowledge publish; R8.2 now uniform ValueError.
- H56-06 paused MemoryProcessor stale source-only merge refuses all candidate-bearing paths before side effects, ordinary recovery unchanged; `candidate=None` is a documented scope limit.

**NEW-01–NEW-07 and F-01–F-08:** отдельно пройди каждого ID по оригинальным H5.5/H5.6/H5.7 контрактам. Для каждой строки дай независимый test/probe и лог или честное `NOT_TESTED`. Включить public status-only writers, Raw binding, Memory immutable confirmed mutation, historical recovery/done ledger, temporal Evidence opposite overlap, temporal merge clipping, Context coverage, WAL/SHM backup, legacy diagnostic gates и doc hierarchy. Нет одного общего «PASS» для 15 исторических находок.

Не принимать historical `AGING`/immutable text revisions как реализованные, когда это явно не контракт; отсутствие Pi/ARM64, реальных legacy instances, power loss, LLM inference не объявлять доказательством их качества.

## 6. Межкомпонентные и аварийные проверки

Проверить как независимые сценарии:
- Fresh Raw source created/closed после challenge в тот же timestamp → Knowledge confirm → History → Retrieval/Context → provenance physical source; reopen/recover и повторный process не дублируют effects.
- Same-instant confirm при corrupted dormant temporal evidence → `ValueError` и полный rollback; после явного восстановления **только** synthetic fixture нормальный fresh confirm работает; продукт не должен сам исправлять Raw/SQL.
- Bad custom adapter mixed with valid items после успешного Knowledge transition → deny before Context/DEEP provenance; no false complete/no silent omissions.
- Physical Raw loss после сохранения `memory_sources` → Knowledge proof denial и DEEP provenance failure, при этом Context structural validation не скрывает missing Raw.
- Concurrent competing Knowledge transitions, writer lock & `BEGIN IMMEDIATE`, process crash before/after commit и replay, torn/duplicate/malformed Raw; при наличии tools выполнить хотя бы несколько reproducible negative probes.
- Supersedes: публичные альтернативные LinkStore, DAO, KnowledgeLayer, RetrievalEngine, diagnostic gates и legacy SQL-damaged graph; authoritative presentation не должна следовать raw forged edges.
- Cross-file JSONL/SQLite durability и malicious SQL не являются уже доказанной защищённой областью; чётко разделяй security, source authority и кооперативные runtime assumptions.
- Непродуктивная деградация на forged-heavy graph (H5.7 измерил 1k/10k/50k edges → 1004/10004/50004 SQLite connections); это **nonblocking operational concern** без явного SLO, но повторить/сравнить по возможности, и зафиксировать риск.

## 7. Запуски и воспроизводимость

На отдельном чистом checkout точного SHA запусти, если окружение доступно:

```bash
git rev-parse HEAD
git status --short
python --version
python -c 'import sqlite3,platform; print(sqlite3.sqlite_version,platform.machine())'

PYTHONPATH="$PWD" python -m pytest -q -rx \
  tests/test_v02_r8_3_integration_acceptance.py \
  tests/test_v02_r8_2_temporal_validation_consistency.py \
  tests/test_v02_r8_1_context_adapter_integrity.py \
  tests/test_v02_r8_0_challenged_proof_novelty.py \
  tests/test_v02_r7_4_integration_release_gate.py \
  tests/test_v02_r7_3_storage_evidence_validation.py \
  tests/test_v02_r7_2_lifecycle_write_authority.py \
  tests/test_v02_r7_1_memory_source_integrity.py \
  tests/test_v02_r7_0_temporal_authority.py \
  tests/test_v02_r6_3_temporal_context_contracts.py \
  tests/test_knowledge.py \
  tests/test_context_builder.py \
  tests/test_retrieval.py \
  tests/test_provenance.py \
  tests/test_event_processing.py

bash scripts/check.sh
PYTHONPATH="$PWD" python -m pytest -q -rx
git status --short
```

**Не предполагай, что любой список путей уже проверен на этой платформе**: отсутствующий test path нужно отметить в логе/выбрать корректное имя из самого repo, а не править target. При запуске external H5.7 probes добавь их директории к `PYTHONPATH` и работай в новом `tmp_path`; original H5.7 findings intentionally fail на старом H5.7, на R8 ожидается восстановление контракта — определяй PASS по assertions, не меняй expected output.

Запиши фактическое число pass/fail/xfail, exit status, время, версии, hardware, SHA, clean status, журнал отрицательных тестов и exact command. Сохрани воспроизводимые tiny scripts/fixtures и manifest hashes отдельным evidence archive без модели, secrets или пользовательских данных.

При отсутствии возможности исполнять runtime проверки **не делай вывод `FIXED_VERIFIED` только по чтению кода**; укажи `REVIEW_REQUIRED / NEEDS_EVIDENCE` по недоказанным инвариантам.

## 8. Обязательный отчёт

Предоставь подробный независимый отчёт на русском:

1. **Overall:** `PASS / BLOCKED / REVIEW_REQUIRED`; отдельно `APPROVE_RC / BLOCK_RC / NEEDS_EVIDENCE`. RC только рекомендация, никакой публикации.
2. Exact `SHA`, ветка, tree/status, environment, внешняя доступность H5.7 evidence, H5.7→R8 diff и границы.
3. Матрица **H57-01–H57-03** с независимым original repro и новыми attack cases; severity, expected/actual, rollback, `FIXED_VERIFIED / PARTIAL / REGRESSION / NOT_TESTED`.
4. Отдельные матрицы H56-01–H56-06, NEW-01–NEW-07, F-01–F-08, с evidence refs.
5. Новые находки `H58-01...`, P0–P3: точный API, repro, техническая причина, последствия, требуемые меры, блокирующий или nonblocking статус; альтернативные API и возможные обходы.
6. Targeted/full pytest/check (exit codes), независимые исполняемые negative/cross-module/recovery/concurrency cases, исходные H5.7 probes и ограничения.
7. Performance: честные размеры graph/Raw, O(N) scan, latency на H5.7/R8 в одинаковой среде если доступно, оценка пиков, неопределённости.
8. Architecture scope: какие инварианты действительно закрыты, какие остаются сознательно за рамками (aging, historic revisions, candidate=None ranking, uncooperative Raw/SQL, power loss/ARM64/LLM).
9. Таблица blocking/nonblocking и **конкретные условия** допустимости RC либо новой remediation. Не создавать PR/release/tag.

**Успех H5.8** — новое самостоятельное заключение по конкретному замороженному SHA, с минимумом недоказанных деклараций. Даже 2315 PASS не дают автоматическое `APPROVE_RC`.
