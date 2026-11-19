# ANIMA v0.2 — R7.4 Integration & Release Gate

**Основа:** R7.3 `d32c48cec344f55a7a4694e141324f9948bdb56c`.
**H5.6 аудит:** `f70d879a88d88f63777646b0a65448765610402d`, BLOCK_RC,
`ANIMA_v0_2_H56_Independent_Reaudit_RU.md`,
`ANIMA_v0_2_H56_Evidence.zip`.
**Локальный результат владельца R7.3:** `2156 passed`,
`scripts/check.sh` PASS, CPython 3.14.4.
**R7.4:** INTEGRATION IMPLEMENTED / LOCAL ACCEPTANCE PENDING.
**Цель:** интеграционные защиты, а не новые функции; новая версия, тег,
PR или release не создаются автоматически.

## 1. Изменения R7 после H5.6

| Finding | Remediation | Проверяемый инвариант |
| --- | --- | --- |
| H56-01 P1 | R7.0 | `challenged → confirmed` требует нового реально действующего Evidence; future duplicate и старый source не подменяют proof |
| H56-02 P2 | R7.0 | Конечные contradicts при `challenge/reject` не превращаются в бессрочные |
| H56-03 P2 | R7.2 | Authoritative `supersedes` только через `KnowledgeLayer.supersede`; reader, Retrieval, diagnostic не доверяют forged Relation |
| H56-04 P2 | R7.3 | Неизвестная версия SQLite отвергается до DDL; transactional bootstrap не оставляет частичной схемы |
| H56-05 P2 | R7.3 | Перед любой Knowledge publication проверяются **все** attached supports/contradicts интервалы, включая future/expired |
| H56-06 P2 | R7.1 | Перед candidate-based write под SQLite lock совпадают Memory row и фактический source-set scorer |

R7.0–R7.3 изменяли `knowledge.py`, `link_store.py`, `processor.py`,
`memory_store.py`, `retrieval.py`,
`lifecycle_authority.py`, read-only H5.0 diagnostic и связанные tests/docs.

## 2. R7.4 integration tests

`tests/test_v02_r7_4_integration_release_gate.py` использует реальные
`EventLog`/Raw-backed CLOSED Memory, настоящий lifecycle и SQLite:
- H56-01 + H56-02: `confirmed` с конечной contradiction →
  `challenged` → неуспешный future-proof reconfirm без изменений →
  успешный reconfirm по новой CLOSED Memory; History указывает
  на **действующую** relation, будущие/конечные интервалы сохраняются;
- H56-02 + R3: implicit/explicit reject в присутствии finite
  contradiction и будущего противоположного support; никакого продления
  finite интервала и никакого opposite-overlap;
- H56-03 + Raw + reopen: авторитетный `supersede` читается после
  повторного открытия БД, Retrieval видит только подтверждённый сосед;
- H56-03 + H5.0: legacy forged `supersedes` рядом с настоящим
  переходом не подменяет authoritative view; read-only gate блокирует
  forged graph, не удаляя raw Relation;
- H56-05 + H56-01: damaged dormant Evidence отказывает при попытке
  `challenged → confirmed`, не меняя Knowledge/History/Relations/Raw;
- H56-04 + Knowledge: на копии существующей DB с History неизвестная
  версия schema отвергается без изменений SHA-256; текущая БД открывается;
- R6.4 + R7: after commit/reopen `recover()`/done replay не
  создают дубли Memory или History после confirmed Knowledge;
- H56-06 + F-01: после source-only merge stale association
  отвергается, затем целевой набор источников можно корректно закрыть
  и использовать как Raw evidence; опубликованная Memory остаётся
  защищённой от изменений.

Временные тесты используют только `pytest tmp_path`. Единственные
ручные SQL изменения намеренно создают disposable legacy-corruption.
Действительные instance data, приватные файлы и GitHub audit-ветки
не используются.

## 3. Обязательный локальный gate

В **новом worktree R7.4 HEAD**:

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python
"$PY" --version
"$PY" -c 'import sqlite3; print(sqlite3.sqlite_version)'

PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r7_4_integration_release_gate.py \
  tests/test_v02_r7_0_temporal_authority.py \
  tests/test_v02_r7_1_memory_source_integrity.py \
  tests/test_v02_r7_2_lifecycle_write_authority.py \
  tests/test_v02_r7_3_storage_evidence_validation.py \
  tests/test_v02_r6_1_knowledge_write_authority.py \
  tests/test_v02_r6_2_memory_mutation_integrity.py \
  tests/test_v02_r6_3_temporal_context_contracts.py \
  tests/test_v02_r6_4_recovery_owner_integrity.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
git status --short
```

**Ориентир:** 2156 ранее пройденных + 10 новых параметризованных integration
cases = **2166 passed**, если tests/plugins/configuration не меняются.
Это **ожидание, не результат исполнения**. Зафиксировать фактические
числа, exit code, версии Python/SQLite, SHA, `git status`, duration.

Отдельно проверить, что `scripts/check.sh` не ослаблен и
`docs/TESTING` остаётся достижимым. Никакой PR/tag/release.

## 4. Независимая H5.7: минимум scope

После подтверждённого R7.4 local gate создать **frozen audit branch**
на точном HEAD R7.4 и отдельную **prep branch** только для H5.7 brief,
не модифицируя audit commit. Независимый reviewer обязан:
1. подтвердить фактический git SHA/tree, diff с H5.6 и пустой status;
2. воспроизвести полный pytest/check, исполнить оригинальные
   `probes/test_h56_findings.py`, `h56_live_reconfirm.py`
   из предоставленного `ANIMA_v0_2_H56_Evidence.zip` на *новых*
   `tmp_path` и отдельно проверить оригинальный H5.6 baseline;
3. проверить H56-01..06 и R7.0–R7.3 **взаимодействия**, не считать
   изменения названий тестов доказательством устранения дефектов;
4. повторить F-01..F-08, NEW-01..NEW-07, Raw authority, source-graph
   races, temporal Evidence, recovery, H5.0/H5.4b, WAL/backup,
   Context Coverage/FAST-DEEP и альтернативные публичные API;
5. проверить, что `supersedes` cannot be forged через generic writer,
   reader/retrieval/history integrity совпадают, а фальсифицированная
   legacy SQLite остаётся видимой как degraded в read-only gate;
6. атаковать две оставшиеся границы: `candidate=None`/ranking TOCTOU
   и post-challenge mutation исторического Memory; классифицировать
   только в рамках реально обещанных свойств;
7. отличать Raw ID existence от semantic/source authority; заявленные
   JSONL/SQLite atomicity, fsync и power-loss **не гарантируются**;
8. выпустить детальный независимый RU report с repro/exit codes,
   severity P0..P3, recommendation `APPROVE_RC/BLOCK_RC/NEEDS_EVIDENCE`.

**Не передавать ревьюеру роль разработчика.**
Нельзя корректировать GitHub, audit snapshot, реальные данные или
исправлять тесты ради PASS. Доступные доказательства первичны,
но локальные 2156/2166 PASS **не заменяют независимый review**.

## 5. Release gates и ограничения

- R7.4 CLOSED только после локальной адресной + полной проверки и
  документационного check на точном commit. При FAIL — остаться в R7.4,
  исправить отдельно и повторить все gates.
- H5.7 frozen только после R7.4 CLOSED; prep branch из того же SHA
  содержит brief, не переносится в target snapshot.
- RC не одобряется автоматически даже при зелёном H5.7:
  окончательное решение владельца после evidence.
- Вне scope новых обещаний: self-aging finite Knowledge, immutable
  historical Memory revisions, semantically true Raw, malicious
  external writers, cross-file crash atomicity, реальные legacy DB,
  ARM64/RPi, physical power loss, FAST/DEEP LLM quality и аппаратные SLO.
- Отсутствие Pi, LLM или питания не является искусственным
  обязательным gate v0.2; обозначать `NOT_TESTED` честно.

Следующий шаг после локального PASS: **freeze target + H5.7 independent
brief**, затем независимый reaudit без релизных действий.
