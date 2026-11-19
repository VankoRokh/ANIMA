# ANIMA v0.2 — R8.3 Integration & Acceptance

**Статус:** IMPLEMENTED / LOCAL GATE NOT YET REPORTED.  
**База:** локально проверенный R8.2 `5fc8acb5af478c1cb5b073c32eaeb0e358a2b7fe` —
по отчёту владельца `2298 passed` за 97.25 s и `scripts/check.sh` PASS
на Python 3.14.4; 182 документа, 1334 ссылки, 419 Python файлов.  
**Ветка:** `work/v02-r8-3-integration-acceptance`.  
**Исходный независимый аудит:** H5.7 exact
`03ec97448d7e805a1dd34729140a47fd31c53774`, BLOCKED/BLOCK_RC.
**Независимое evidence:** внешние `ANIMA_v0_2_H57_Evidence.zip` и
`ANIMA_v0_2_H57_Independent_Reaudit_RU.md`.
**Цель:** комплексное принятие трёх **уже исправленных** H57 findings без
расширения функциональности, схемы или полномочий системы.

## 1. Матрица R8

| Finding | Исправление | Проверяемое свойство |
| --- | --- | --- |
| H57-01 P2 | R8.0 | genuinely fresh Raw-backed evidence принимается в `challenged → confirmed` при `confirmed_at == challenged_at`; существовавшие до transition, expired/future supports не становятся «новыми» |
| H57-02 P2 | R8.1 | Retrieval adapter candidate валидируется по kind/ID/record/text/score/reasons **до** coverage и selection; неизвестный kind и испорченные элементы не исчезают с `complete=True` |
| H57-03 P3 | R8.2 | malformed dormant Evidence отвергается `ValueError` до datetime comparisons в `confirm/challenge/reject/supersede`, с сохранением atomic rollback |

Сохранять прежние границы: H56-01–06, NEW-01–07, F-01–08, no
Raw ID without physical Event, Memory source graph/Knowledge lifecycle
authority, finite opposite Evidence, SQLite schema-version fail-closed,
current-namespace Recovery. R8 **не** добавляет automatic aging,
immutable historic Memory revisions, глобальную свежесть ранжирования
`candidate=None`, JSONL/SQLite общий COMMIT или криптографическую
достоверность Raw.

## 2. Интеграционные испытания R8.3

`tests/test_v02_r8_3_integration_acceptance.py` — **17 parametrized cases**,
все в синтетических disposable `pytest tmp_path`, без изменений
настоящих пользователей и аудиторских веток.

- **R8.0 × R7 Raw/History:** после `challenge` записать новый
  canonical Event, создать OPEN Memory, закрыть, подтвердить Knowledge
  в **тот же instant** (включая offset-equivalent timestamp); History
  ссылается на ровно созданную support Relation, Raw не дублируется.
- **R8.2 × R8.0:** искусственно испортить future finite support в той же
  временной БД (naive start или inverted window); same-instant confirm
  обязан отказать `ValueError` до новых эффекта/History/Relation.
  После *явного восстановления синтетической фикстуры* нормальный
  новый support разрешён, malformed не замаскирован TypeError.
- **R8.1 × Raw/Knowledge:** корректный adapter с реальными
  Knowledge/Memory records сохраняет complete coverage и FAST/DEEP
  selection; DEEP извлекает физические Raw источники через настоящий
  ProvenanceResolver и удаляет дубликаты Event IDs.
- **R8.1 invalid adapter:** один дефектный кандидат среди корректных
  (`entity`, wrong record ID, NaN score) должен отвергать весь request
  ещё до любого обращения в provenance (spy запрещает вызов);
  Knowledge/History/Relations/Memory/ledger/Raw unchanged.
- **Context coverage vs budget:** валидный adapter сообщает полное
  Retrieval coverage, но при `max_items=1` Context ставит
  `truncated=True` и `omitted_budget>=1`, для FAST/DEEP.
- **Raw loss × H57-01/H57-02:** физическое удаление нового synthetic
  Raw Event при сохранённом `memory_sources` запрещает Knowledge
  reconfirm и DEEP provenance. После ручного восстановления фикстуры
  подтверждение и DEEP снова корректны; ни один отказ не мутирует DB.
- **Recovery × Knowledge:** `EventProcessingCoordinator` сохраняет
  ledger для нового Event; после повторного `build_core`,
  `recover` не переисполняет effect и `process` возвращает
  `already_done`; History и Raw идентичны.
- **Новый challenge после reconfirm:** предыдущий новый support
  становится *старым* для следующего challenge, повторное
  `confirm` им запрещено и атомарно откатывается.

При всех отрицательных тестах проверяется логический snapshot
`memories, knowledge, relations, history, memory_sources, event_processing`
плюс байты disposable `events.jsonl`. Искажение DB/Raw допускается
**только** на отдельных временных fixtures; не является auto-repair.

**Production-код R8.3 не изменяется.** Это integration/test gate.

## 3. Локальный gate (обязателен до H5.8 freeze)

В **чистом отдельном worktree** точного R8.3 HEAD:

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python
"$PY" --version
"$PY" -c 'import sqlite3, platform; print(sqlite3.sqlite_version, platform.machine())'

PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
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
  tests/test_provenance.py \
  tests/test_retrieval.py \
  tests/test_event_processing.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
git status --short
```

Если число прежних тестов не изменилось, ожидаемый full gate:
**2298 + 17 = 2315 PASS**. Это **ожидание**, не результат запуска.
Записать SHA, фактические exit codes, Python/SQLite, duration, count,
`check.sh` output, clean status.

Если FAIL — исправлять **на R8.3**, не создавать преждевременно audit
candidate и не модифицировать старый H5.7.

## 4. Независимая H5.8: scope и критерии release

После локального PASS заморозить новый `audit/v02-h58-r8-post-integration-candidate`
строго на проверенном **40-char HEAD** и отдельно создать
`work/v02-h58-independent-audit-prep` для H5.8 brief. Prep не
входит в target tree.

Обязательные проверки reviewer:
1. Пристально проверить H57-01/02/03 **на исходных независимых probes
   из H5.7 архива** (при доступности), новые R8 тесты не считать
   достаточной независимой верификацией.
2. Сверить SHA/Tree и diff H5.7→H5.8; production scope R8.0:
   `knowledge.py`, R8.1: `context_builder.py`, R8.2:
   `knowledge.py`, R8.3: tests/docs only.
3. Проверить H56-01–06, NEW-01–07 и F-01–08 без ослабления acceptance.
4. Повторить Raw missing/duplicate/malformed, interval damage,
   same-instant stale source, adapter unknown and mixed candidates,
   FAST/DEEP budgets, provenance, rollback, recovery and reopening,
   supersedes view/diagnostic, Context Coverage.
5. Отдельно исследовать не введённые в scope инварианты: semantic
   truth of Raw, immutable historical Memory revisions, aging finite
   Knowledge, candidate=None/global ranking, SQL admin, WAL durability.
   Не выдавать их ни за реализованные, ни за новые дефекты без
   соответствующего заявленного контракта.
6. Проверить стоимость двойного evidence scan R8.2 и отметить
   nonblocking per-edge SQLite connections на forged-heavy graph
   H5.7; любые SLO/benefit — только с measurements.
7. Отчитаться по `PASS/BLOCKED/REVIEW_REQUIRED` и отдельно по
   `APPROVE_RC/BLOCK_RC/NEEDS_EVIDENCE`, точные repro,
   exit codes, P0–P3, остаточные ограничения, без публикации.

**Отдельно:** оригинальные H5.7 evidence содержит exploratory проверки
automatic aging и immutable historical source, которые намеренно были
`NOT IMPLEMENTED` и давали ожидаемые failed в exploratory.
Не «исправлять» эти unrelated boundary tests ради зелёного числа;
reviewer обязан отделять strict H57 formal probes от scope limitations.

## 5. Release decision

- `R8.3 CLOSED / LOCALLY VERIFIED` возможно только после локального
  адресного + полного PASS и успешного documentation check.
- `H5.8 READY` после freeze и prep brief на разных ветках.
- `v0.2 RC` допускается **только как отдельное решение владельца**
  после независимого H5.8 с оценкой блокирующих дефектов.
- До независимого вердикта `v0.2 BLOCKED`; никаких release/tag.
